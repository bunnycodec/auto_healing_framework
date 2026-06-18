import {
  SelfHealConfig,
  HealingResult,
  TraceData,
  FailureClassification,
  LocatorFix,
  CodePatch,
} from './types';
import { TraceParser } from './trace-parser';
import { FailureClassifier } from './failure-classifier';
import { createLlmProvider } from './llm';
import { LocatorResolver } from './locator-resolver';
import { CodePatcher } from './code-patcher';
import { TestRunner } from './test-runner';
import { GitPrManager } from './git-pr';

export { TraceParser } from './trace-parser';
export { FailureClassifier } from './failure-classifier';
export { createLlmProvider } from './llm';
export { LocatorResolver } from './locator-resolver';
export { CodePatcher } from './code-patcher';
export { TestRunner } from './test-runner';
export { GitPrManager } from './git-pr';
export * from './types';

/**
 * Main orchestrator for the self-healing pipeline.
 *
 * Usage:
 * ```ts
 * import { SelfHealEngine } from 'playwright-self-heal';
 *
 * const engine = new SelfHealEngine(config);
 * const results = await engine.heal();
 * ```
 */
export class SelfHealEngine {
  private parser: TraceParser;
  private classifier: FailureClassifier;
  private resolver: LocatorResolver;
  private patcher: CodePatcher;
  private runner: TestRunner;
  private gitManager: GitPrManager;

  private onProgress?: (message: string, phase: string) => void;

  constructor(private config: SelfHealConfig) {
    this.parser = new TraceParser();
    this.classifier = new FailureClassifier();

    const llmProvider = createLlmProvider(config.llm);
    this.resolver = new LocatorResolver(llmProvider);
    this.patcher = new CodePatcher(config.projectRoot);
    this.runner = new TestRunner(config.projectRoot, config.testCommand);
    this.gitManager = new GitPrManager(config.projectRoot, config.git);
  }

  /**
   * Set a progress callback for CLI/UI updates.
   */
  setProgressCallback(cb: (message: string, phase: string) => void): void {
    this.onProgress = cb;
  }

  /**
   * Run the full self-healing pipeline.
   */
  async heal(): Promise<HealingResult[]> {
    const results: HealingResult[] = [];
    const allPatches: CodePatch[] = [];

    // Phase 1: Parse traces
    this.progress('Parsing trace files...', 'parse');
    const traces = await this.parseTraces();
    this.progress(`Found ${traces.length} trace(s)`, 'parse');

    for (const trace of traces) {
      const result = await this.healSingleTrace(trace);
      results.push(result);

      if (result.patch) {
        allPatches.push(result.patch);
      }
    }

    // Phase 6: Git commit & PR (if patches were applied and validated)
    const validPatches = allPatches.filter((_, i) => results[i]?.rerunPassed);

    if (validPatches.length > 0 && !this.config.dryRun) {
      await this.commitAndPr(validPatches, results);
    }

    return results;
  }

  /**
   * Heal a single trace file through the full pipeline.
   */
  private async healSingleTrace(trace: TraceData): Promise<HealingResult> {
    const result: HealingResult = {
      testName: trace.metadata.testName,
      testFile: trace.metadata.testFile,
      classification: { category: 'unknown', confidence: 0, reason: '' },
      rerunPassed: false,
      committed: false,
    };

    try {
      // Phase 2: Classify failure
      this.progress(`Classifying failure for: ${trace.metadata.testName}`, 'classify');
      const classification = this.classifier.classify(trace);
      result.classification = classification;

      this.progress(
        `Classification: ${classification.category} (confidence: ${(classification.confidence * 100).toFixed(0)}%)`,
        'classify'
      );

      if (classification.category !== 'locator') {
        this.progress(
          `Skipping non-locator failure: ${classification.reason}`,
          'skip'
        );
        return result;
      }

      // Phase 3: Resolve correct locator
      this.progress('Resolving correct locator via LLM...', 'resolve');
      const locatorFix = await this.resolver.resolve(classification);

      if (!locatorFix) {
        result.error = 'Could not determine correct locator from DOM snapshot';
        this.progress(result.error, 'error');
        return result;
      }

      this.progress(
        `Suggested fix: "${locatorFix.oldLocator}" → "${locatorFix.newLocator}" (${locatorFix.strategy}, ${(locatorFix.confidence * 100).toFixed(0)}%)`,
        'resolve'
      );

      classification.suggestedFix = locatorFix;

      // Phase 4: Patch source code
      this.progress('Patching source code...', 'patch');
      const patch = this.patcher.createPatch(
        classification.failedAction!,
        locatorFix
      );

      if (!patch) {
        result.error = 'Could not map failure to source code location';
        this.progress(result.error, 'error');
        return result;
      }

      result.patch = patch;

      if (this.config.dryRun) {
        this.progress(
          `[DRY RUN] Would patch ${patch.filePath}:${patch.lineNumber}`,
          'patch'
        );
        return result;
      }

      this.patcher.applyPatch(patch);
      this.progress(
        `Patched ${patch.filePath}:${patch.lineNumber}`,
        'patch'
      );

      // Phase 5: Re-run test
      this.progress('Re-running test to validate fix...', 'rerun');
      const testResult = this.runner.run(
        trace.metadata.testFile,
        trace.metadata.testName
      );

      result.rerunPassed = testResult.passed;

      if (testResult.passed) {
        this.progress('✅ Test passed after healing!', 'rerun');
      } else {
        this.progress('❌ Test still failing — reverting patch', 'rerun');
        this.patcher.revertPatch(patch);
        result.error = `Test still failed after patch: ${testResult.output.slice(0, 200)}`;
      }
    } catch (error: unknown) {
      result.error = `Healing error: ${error instanceof Error ? error.message : String(error)}`;
      this.progress(result.error, 'error');
    }

    return result;
  }

  private async parseTraces(): Promise<TraceData[]> {
    const tracePath = this.config.tracePath;

    if (tracePath.endsWith('.zip')) {
      return [await this.parser.parse(tracePath)];
    }

    return this.parser.parseDirectory(tracePath);
  }

  private async commitAndPr(
    patches: CodePatch[],
    results: HealingResult[]
  ): Promise<void> {
    if (this.config.autoCommit || this.config.autoPr) {
      this.progress('Committing changes...', 'git');

      if (this.config.autoPr) {
        const pr = await this.gitManager.commitAndPr(patches);
        this.progress(`PR created: ${pr.url}`, 'git');

        for (const result of results) {
          if (result.patch && result.rerunPassed) {
            result.committed = true;
            result.prUrl = pr.url;
          }
        }
      } else {
        const commitHash = await this.gitManager.commitOnly(patches);
        this.progress(`Committed: ${commitHash}`, 'git');

        for (const result of results) {
          if (result.patch && result.rerunPassed) {
            result.committed = true;
          }
        }
      }
    }
  }

  private progress(message: string, phase: string): void {
    if (this.onProgress) {
      this.onProgress(message, phase);
    }
  }
}
