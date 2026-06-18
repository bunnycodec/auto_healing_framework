import * as fs from 'fs';
import * as path from 'path';
import { CodePatch, LocatorFix, TraceAction } from '../types';

/**
 * Maps a failed locator back to source code and patches it.
 */
export class CodePatcher {
  constructor(private projectRoot: string) {}

  /**
   * Find the source file/line for a failed action and create a patch.
   */
  createPatch(
    failedAction: TraceAction,
    locatorFix: LocatorFix
  ): CodePatch | null {
    const sourceLocation = this.findSourceLocation(failedAction);
    if (!sourceLocation) {
      return null;
    }

    const { filePath, lineNumber } = sourceLocation;
    const absolutePath = path.resolve(this.projectRoot, filePath);

    if (!fs.existsSync(absolutePath)) {
      return null;
    }

    const fileContent = fs.readFileSync(absolutePath, 'utf-8');
    const lines = fileContent.split('\n');

    if (lineNumber < 1 || lineNumber > lines.length) {
      return null;
    }

    const originalLine = lines[lineNumber - 1];

    // Find and replace the locator in the line
    const patchedLine = this.replaceLocator(originalLine, locatorFix);

    if (patchedLine === originalLine) {
      // Try searching nearby lines (±3) for the locator
      for (let offset = 1; offset <= 3; offset++) {
        for (const dir of [-1, 1]) {
          const nearbyLine = lineNumber - 1 + (offset * dir);
          if (nearbyLine >= 0 && nearbyLine < lines.length) {
            const nearby = lines[nearbyLine];
            const patched = this.replaceLocator(nearby, locatorFix);
            if (patched !== nearby) {
              return {
                filePath: absolutePath,
                lineNumber: nearbyLine + 1,
                originalLine: nearby,
                patchedLine: patched,
                locatorFix,
              };
            }
          }
        }
      }
      return null;
    }

    return {
      filePath: absolutePath,
      lineNumber,
      originalLine,
      patchedLine,
      locatorFix,
    };
  }

  /**
   * Apply a patch to the source file.
   */
  applyPatch(patch: CodePatch): void {
    const content = fs.readFileSync(patch.filePath, 'utf-8');
    const lines = content.split('\n');

    if (lines[patch.lineNumber - 1] !== patch.originalLine) {
      throw new Error(
        `Source file has changed. Expected line ${patch.lineNumber} to be:\n` +
        `  "${patch.originalLine}"\n` +
        `but found:\n` +
        `  "${lines[patch.lineNumber - 1]}"`
      );
    }

    lines[patch.lineNumber - 1] = patch.patchedLine;
    fs.writeFileSync(patch.filePath, lines.join('\n'), 'utf-8');
  }

  /**
   * Revert a previously applied patch.
   */
  revertPatch(patch: CodePatch): void {
    const content = fs.readFileSync(patch.filePath, 'utf-8');
    const lines = content.split('\n');

    if (lines[patch.lineNumber - 1] !== patch.patchedLine) {
      throw new Error('Cannot revert: patched line no longer matches');
    }

    lines[patch.lineNumber - 1] = patch.originalLine;
    fs.writeFileSync(patch.filePath, lines.join('\n'), 'utf-8');
  }

  private findSourceLocation(
    action: TraceAction
  ): { filePath: string; lineNumber: number } | null {
    if (!action.stack) return null;

    // Parse stack trace to find the test file location
    const stackLines = action.stack.split('\n');

    for (const line of stackLines) {
      // Match patterns like: at Function (path/to/file.ts:42:10)
      // or: at path/to/file.spec.ts:42:10
      const match = line.match(
        /at\s+(?:.*?\s+)?\(?(.*?\.(spec|test|e2e)\.(ts|js|mjs|mts)):(\d+):\d+\)?/
      );
      if (match) {
        return {
          filePath: match[1],
          lineNumber: parseInt(match[4], 10),
        };
      }
    }

    // Fallback: match any .ts/.js file in the stack
    for (const line of stackLines) {
      const match = line.match(
        /at\s+(?:.*?\s+)?\(?((?!node_modules).*?\.(ts|js)):(\d+):\d+\)?/
      );
      if (match) {
        return {
          filePath: match[1],
          lineNumber: parseInt(match[3], 10),
        };
      }
    }

    return null;
  }

  private replaceLocator(line: string, fix: LocatorFix): string {
    const oldLocator = fix.oldLocator;

    // Strategy 1: Direct string replacement
    if (line.includes(oldLocator)) {
      return line.replace(oldLocator, fix.newLocator);
    }

    // Strategy 2: Handle escaped quotes in locator strings
    const escapedOld = oldLocator.replace(/'/g, "\\'").replace(/"/g, '\\"');
    if (line.includes(escapedOld)) {
      return line.replace(escapedOld, fix.newLocator);
    }

    // Strategy 3: Match common Playwright locator patterns
    const patterns = [
      // page.locator('selector')
      /page\.locator\(\s*['"`](.*?)['"`]\s*\)/,
      // page.$('selector') or page.$$('selector')
      /page\.\$\$?\(\s*['"`](.*?)['"`]\s*\)/,
      // .locator('selector')
      /\.locator\(\s*['"`](.*?)['"`]\s*\)/,
      // getByRole('role', { name: 'text' })
      /getByRole\(\s*['"`](.*?)['"`]/,
      // getByTestId('id')
      /getByTestId\(\s*['"`](.*?)['"`]\s*\)/,
      // getByText('text')
      /getByText\(\s*['"`](.*?)['"`]\s*\)/,
      // getByLabel('label')
      /getByLabel\(\s*['"`](.*?)['"`]\s*\)/,
      // getByPlaceholder('placeholder')
      /getByPlaceholder\(\s*['"`](.*?)['"`]\s*\)/,
    ];

    for (const pattern of patterns) {
      const match = line.match(pattern);
      if (match && this.isSimilarSelector(match[1], oldLocator)) {
        // Determine the quote style used
        const quoteMatch = line.match(
          new RegExp(pattern.source.replace('(.*?)', '.*?'))
        );
        return line.replace(match[0], this.buildLocatorCall(fix));
      }
    }

    return line; // No replacement found
  }

  private isSimilarSelector(found: string, original: string): boolean {
    // Check if the found selector is similar to the original
    const normalize = (s: string) =>
      s.toLowerCase().replace(/\s+/g, ' ').trim();
    return (
      normalize(found) === normalize(original) ||
      found.includes(original) ||
      original.includes(found)
    );
  }

  private buildLocatorCall(fix: LocatorFix): string {
    const locator = fix.newLocator;

    // If the new locator already uses Playwright API format, return as-is
    if (
      locator.startsWith('getByRole') ||
      locator.startsWith('getByTestId') ||
      locator.startsWith('getByText') ||
      locator.startsWith('getByLabel') ||
      locator.startsWith('getByPlaceholder')
    ) {
      return locator;
    }

    // Wrap in page.locator() if it's a CSS/XPath selector
    switch (fix.strategy) {
      case 'role':
        return locator;
      case 'testId':
        return `getByTestId('${locator}')`;
      case 'text':
        return `getByText('${locator}')`;
      case 'label':
        return `getByLabel('${locator}')`;
      case 'placeholder':
        return `getByPlaceholder('${locator}')`;
      default:
        return `locator('${locator}')`;
    }
  }
}
