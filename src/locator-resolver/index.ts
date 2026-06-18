import {
  FailureClassification,
  LocatorFix,
  LlmProvider,
  DomSnapshot,
  TraceAction,
} from '../types';

/**
 * Uses LLM to analyze DOM snapshots and suggest correct locators
 * for elements that failed to be found.
 */
export class LocatorResolver {
  constructor(private llm: LlmProvider) {}

  /**
   * Analyze the failure and suggest a corrected locator.
   */
  async resolve(classification: FailureClassification): Promise<LocatorFix | null> {
    if (classification.category !== 'locator') {
      return null;
    }

    const failedAction = classification.failedAction;
    if (!failedAction?.selector) {
      return null;
    }

    const snapshot = classification.relevantSnapshot;
    if (!snapshot) {
      return null;
    }

    // Trim large DOM to stay within token limits
    const trimmedHtml = this.trimDom(snapshot.html, failedAction.selector);

    const prompt = this.buildPrompt(failedAction, trimmedHtml);
    const response = await this.llm.analyze(prompt);

    return this.parseResponse(response, failedAction.selector);
  }

  private buildPrompt(action: TraceAction, domHtml: string): string {
    return `A Playwright test failed because the following locator could not find a matching element in the DOM.

## Failed Locator
\`\`\`
${action.selector}
\`\`\`

## Error Message
\`\`\`
${action.error}
\`\`\`

## Action Type
${action.type}

## Page URL
${action.pageUrl || 'Unknown'}

## Current DOM Snapshot (trimmed)
\`\`\`html
${domHtml}
\`\`\`

## Instructions
1. Analyze the DOM to find the element that the original locator was likely targeting.
2. Consider what the test was trying to do (action type: ${action.type}).
3. Suggest the BEST replacement locator using Playwright's locator API.
4. Prefer locator strategies in this order: getByRole > getByTestId > getByText > getByLabel > getByPlaceholder > CSS selector > XPath.

## Response Format
Respond ONLY with valid JSON (no markdown fences):
{
  "newLocator": "the corrected Playwright locator string",
  "strategy": "role|testId|text|css|xpath|label|placeholder",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation of why this locator is correct",
  "alternatives": ["alternative locator 1", "alternative locator 2"]
}`;
  }

  private trimDom(html: string, selector: string): string {
    const maxLength = 15000; // ~4K tokens
    if (html.length <= maxLength) return html;

    // Try to extract relevant parts of the DOM
    // Look for elements that might match parts of the selector
    const selectorParts = selector
      .replace(/[[\](){}]/g, ' ')
      .split(/\s+/)
      .filter(p => p.length > 2);

    // Find sections of HTML that contain selector-related text
    const relevantSections: string[] = [];
    const lines = html.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].toLowerCase();
      if (selectorParts.some(p => line.includes(p.toLowerCase()))) {
        // Include surrounding context (5 lines before/after)
        const start = Math.max(0, i - 5);
        const end = Math.min(lines.length, i + 6);
        relevantSections.push(lines.slice(start, end).join('\n'));
      }
    }

    if (relevantSections.length > 0) {
      const result = relevantSections.join('\n\n<!-- ... -->\n\n');
      if (result.length <= maxLength) return result;
      return result.substring(0, maxLength) + '\n<!-- truncated -->';
    }

    // Fallback: take the first chunk
    return html.substring(0, maxLength) + '\n<!-- truncated -->';
  }

  private parseResponse(response: string, originalSelector: string): LocatorFix | null {
    try {
      // Strip markdown code fences if present
      let cleaned = response.trim();
      if (cleaned.startsWith('```')) {
        cleaned = cleaned.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
      }

      const parsed = JSON.parse(cleaned);

      if (!parsed.newLocator) {
        return null;
      }

      return {
        oldLocator: originalSelector,
        newLocator: parsed.newLocator,
        strategy: parsed.strategy || 'css',
        confidence: parsed.confidence || 0.5,
        reasoning: parsed.reasoning || 'LLM suggestion',
        alternatives: parsed.alternatives || [],
      };
    } catch {
      // Try to extract locator from free-text response
      const locatorMatch = response.match(/(?:locator|selector)[:\s]*[`"']([^`"']+)[`"']/i);
      if (locatorMatch) {
        return {
          oldLocator: originalSelector,
          newLocator: locatorMatch[1],
          strategy: 'css',
          confidence: 0.4,
          reasoning: 'Extracted from LLM free-text response',
          alternatives: [],
        };
      }
      return null;
    }
  }
}
