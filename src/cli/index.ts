#!/usr/bin/env node

import { Command } from 'commander';
import chalk from 'chalk';
import ora from 'ora';
import * as path from 'path';
import * as fs from 'fs';
import * as dotenv from 'dotenv';
import { SelfHealEngine } from '../index';
import { SelfHealConfig, LlmConfig, GitConfig } from '../types';

dotenv.config();

const program = new Command();

program
  .name('self-heal')
  .description(
    'Framework-agnostic self-healing tool for Playwright test suites.\n' +
    'Analyzes trace files, classifies failures, auto-fixes broken locators, and raises PRs.'
  )
  .version('1.0.0');

// --- Main heal command ---
program
  .command('heal')
  .description('Analyze traces and heal broken locators')
  .requiredOption('-t, --trace <path>', 'Path to trace file (.zip) or directory containing traces')
  .option('-p, --project <path>', 'Path to the test project root', process.cwd())
  .option('-c, --test-command <cmd>', 'Test runner command', 'npx playwright test')
  .option('--provider <name>', 'LLM provider (openai, azure-openai, anthropic, gemini)', getEnvProvider())
  .option('--model <name>', 'LLM model name')
  .option('--api-key <key>', 'LLM API key (prefer env vars)')
  .option('--auto-commit', 'Automatically commit fixes', false)
  .option('--auto-pr', 'Automatically create a PR', false)
  .option('--dry-run', 'Show what would be changed without modifying files', false)
  .option('--max-retries <n>', 'Maximum healing attempts per failure', '1')
  .option('--base-branch <branch>', 'Base branch for PR', 'main')
  .option('--remote <name>', 'Git remote name', 'origin')
  .action(async (options) => {
    const spinner = ora();

    try {
      const config = buildConfig(options);
      const engine = new SelfHealEngine(config);

      // Wire up progress to spinner
      engine.setProgressCallback((message, phase) => {
        const icon = phaseIcons[phase] || 'ℹ️';
        if (phase === 'error') {
          spinner.fail(chalk.red(message));
        } else {
          spinner.text = `${icon} ${message}`;
          if (!spinner.isSpinning) spinner.start();
        }
      });

      console.log(chalk.bold('\n🩹 Playwright Self-Heal\n'));
      console.log(chalk.gray(`Trace:    ${options.trace}`));
      console.log(chalk.gray(`Project:  ${options.project}`));
      console.log(chalk.gray(`Provider: ${config.llm.provider}`));
      console.log(chalk.gray(`Dry run:  ${options.dryRun ? 'yes' : 'no'}`));
      console.log();

      spinner.start('Starting healing pipeline...');
      const results = await engine.heal();
      spinner.stop();

      // Print summary
      printSummary(results);
    } catch (error: unknown) {
      spinner.fail(chalk.red(`Error: ${error instanceof Error ? error.message : String(error)}`));
      process.exit(1);
    }
  });

// --- Analyze command (classify only, no patching) ---
program
  .command('analyze')
  .description('Analyze and classify trace failures without making changes')
  .requiredOption('-t, --trace <path>', 'Path to trace file (.zip) or directory')
  .action(async (options) => {
    const { TraceParser } = await import('../trace-parser');
    const { FailureClassifier } = await import('../failure-classifier');

    const parser = new TraceParser();
    const classifier = new FailureClassifier();

    console.log(chalk.bold('\n🔍 Trace Analysis\n'));

    try {
      const tracePath = path.resolve(options.trace);
      let traces;

      if (tracePath.endsWith('.zip')) {
        traces = [await parser.parse(tracePath)];
      } else {
        traces = await parser.parseDirectory(tracePath);
      }

      for (const trace of traces) {
        console.log(chalk.cyan(`\n📋 Test: ${trace.metadata.testName}`));
        console.log(chalk.gray(`   File: ${trace.metadata.testFile}`));
        console.log(chalk.gray(`   Status: ${trace.metadata.status}`));
        console.log(chalk.gray(`   Actions: ${trace.actions.length}`));
        console.log(chalk.gray(`   Snapshots: ${trace.snapshots.length}`));
        console.log(chalk.gray(`   Network: ${trace.network.length} request(s)`));

        const classification = classifier.classify(trace);
        const color = classification.category === 'locator' ? chalk.yellow : chalk.gray;
        console.log(color(`\n   Category:   ${classification.category}`));
        console.log(color(`   Confidence: ${(classification.confidence * 100).toFixed(0)}%`));
        console.log(color(`   Reason:     ${classification.reason}`));

        if (classification.failedAction?.selector) {
          console.log(chalk.red(`   Selector:   ${classification.failedAction.selector}`));
        }
      }
    } catch (error: unknown) {
      console.error(chalk.red(`Error: ${error instanceof Error ? error.message : String(error)}`));
      process.exit(1);
    }
  });

// --- Helpers ---

const phaseIcons: Record<string, string> = {
  parse: '📦',
  classify: '🔍',
  resolve: '🎯',
  patch: '🔧',
  rerun: '🔄',
  git: '📝',
  skip: '⏭️',
  error: '❌',
};

function getEnvProvider(): string {
  return process.env.LLM_PROVIDER || 'openai';
}

function buildConfig(options: Record<string, string | boolean>): SelfHealConfig {
  const provider = (options.provider as string) || getEnvProvider();

  const llm: LlmConfig = {
    provider: provider as LlmConfig['provider'],
    apiKey: resolveApiKey(provider, options.apiKey as string),
    model: options.model as string | undefined,
    endpoint: process.env.AZURE_OPENAI_ENDPOINT,
    deployment: process.env.AZURE_OPENAI_DEPLOYMENT,
    apiVersion: process.env.AZURE_OPENAI_API_VERSION,
  };

  const git: GitConfig = {
    remote: (options.remote as string) || 'origin',
    baseBranch: (options.baseBranch as string) || 'main',
    branchPrefix: 'self-heal',
  };

  return {
    tracePath: path.resolve(options.trace as string),
    projectRoot: path.resolve((options.project as string) || process.cwd()),
    llm,
    git,
    testCommand: (options.testCommand as string) || 'npx playwright test',
    autoCommit: options.autoCommit as boolean,
    autoPr: options.autoPr as boolean,
    maxRetries: parseInt((options.maxRetries as string) || '1', 10),
    dryRun: options.dryRun as boolean,
  };
}

function resolveApiKey(provider: string, explicitKey?: string): string {
  if (explicitKey) return explicitKey;

  const envKeys: Record<string, string> = {
    openai: 'OPENAI_API_KEY',
    'azure-openai': 'AZURE_OPENAI_API_KEY',
    anthropic: 'ANTHROPIC_API_KEY',
    gemini: 'GEMINI_API_KEY',
  };

  const envKey = envKeys[provider];
  const value = envKey ? process.env[envKey] : undefined;

  if (!value) {
    throw new Error(
      `No API key found for provider "${provider}". ` +
      `Set ${envKey || 'the appropriate env var'} or use --api-key.`
    );
  }

  return value;
}

function printSummary(results: Array<{ testName: string; classification: { category: string; confidence: number; reason: string }; patch?: unknown; rerunPassed: boolean; committed: boolean; prUrl?: string; error?: string }>): void {
  console.log(chalk.bold('\n📊 Healing Summary\n'));

  const healed = results.filter(r => r.rerunPassed);
  const skipped = results.filter(r => r.classification.category !== 'locator');
  const failed = results.filter(r => r.classification.category === 'locator' && !r.rerunPassed);

  console.log(chalk.green(`  ✅ Healed:  ${healed.length}`));
  console.log(chalk.yellow(`  ⏭️  Skipped: ${skipped.length} (non-locator failures)`));
  console.log(chalk.red(`  ❌ Failed:  ${failed.length}`));
  console.log();

  for (const result of results) {
    const icon = result.rerunPassed ? '✅' : result.classification.category !== 'locator' ? '⏭️' : '❌';
    console.log(`  ${icon} ${result.testName}`);
    console.log(chalk.gray(`     ${result.classification.category} — ${result.classification.reason.slice(0, 80)}`));

    if (result.prUrl) {
      console.log(chalk.blue(`     PR: ${result.prUrl}`));
    }
    if (result.error) {
      console.log(chalk.red(`     Error: ${result.error}`));
    }
    console.log();
  }
}

program.parse();
