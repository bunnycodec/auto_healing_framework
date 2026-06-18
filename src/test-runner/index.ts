import { execSync, ExecSyncOptionsWithStringEncoding } from 'child_process';
import * as path from 'path';

export interface TestRunResult {
  passed: boolean;
  output: string;
  exitCode: number;
  duration: number;
}

/**
 * Re-runs a specific failed test to validate the healing patch.
 */
export class TestRunner {
  constructor(
    private projectRoot: string,
    private testCommand: string
  ) {}

  /**
   * Run a specific test file (optionally a specific test by name).
   */
  run(testFile: string, testName?: string): TestRunResult {
    const relativeFile = path.relative(this.projectRoot, testFile);
    let command = this.testCommand;

    // Build the command with test file filter
    if (command.includes('npx playwright test')) {
      command = `${command} "${relativeFile}"`;
      if (testName) {
        command += ` --grep "${this.escapeShell(testName)}"`;
      }
      // Generate traces on re-run for verification
      command += ' --reporter=list';
    } else if (command.includes('jest') || command.includes('vitest')) {
      command += ` --testPathPattern="${relativeFile}"`;
      if (testName) {
        command += ` --testNamePattern="${this.escapeShell(testName)}"`;
      }
    } else {
      // Generic: just append the file
      command += ` "${relativeFile}"`;
    }

    const startTime = Date.now();
    const execOptions: ExecSyncOptionsWithStringEncoding = {
      cwd: this.projectRoot,
      encoding: 'utf-8',
      timeout: 120_000, // 2 minute timeout
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, FORCE_COLOR: '0' },
    };

    try {
      const output = execSync(command, execOptions);
      return {
        passed: true,
        output: output.toString(),
        exitCode: 0,
        duration: Date.now() - startTime,
      };
    } catch (error: unknown) {
      const execError = error as { status?: number; stdout?: string; stderr?: string };
      return {
        passed: false,
        output: `${execError.stdout || ''}\n${execError.stderr || ''}`.trim(),
        exitCode: execError.status || 1,
        duration: Date.now() - startTime,
      };
    }
  }

  private escapeShell(str: string): string {
    return str.replace(/['"\\]/g, '\\$&');
  }
}
