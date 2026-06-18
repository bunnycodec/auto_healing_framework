/**
 * Core type definitions for the self-healing framework.
 */

// --- Trace Types ---

export interface TraceAction {
  /** Action type: click, fill, navigate, etc. */
  type: string;
  /** Selector used in the action */
  selector?: string;
  /** URL navigated to */
  url?: string;
  /** Value filled into an input */
  value?: string;
  /** Timestamp of the action */
  timestamp: number;
  /** Whether the action succeeded */
  success: boolean;
  /** Error message if action failed */
  error?: string;
  /** Stack trace pointing to source file/line */
  stack?: string;
  /** Page URL at time of action */
  pageUrl?: string;
}

export interface DomSnapshot {
  /** Full HTML of the page at snapshot time */
  html: string;
  /** URL of the page */
  url: string;
  /** Timestamp of snapshot */
  timestamp: number;
  /** Extracted accessible tree (if available) */
  accessibilityTree?: AccessibilityNode[];
}

export interface AccessibilityNode {
  role: string;
  name: string;
  selector?: string;
  children?: AccessibilityNode[];
  attributes?: Record<string, string>;
}

export interface NetworkEntry {
  url: string;
  method: string;
  status: number;
  requestHeaders?: Record<string, string>;
  responseHeaders?: Record<string, string>;
  requestBody?: string;
  responseBody?: string;
  timestamp: number;
  duration: number;
  resourceType: string;
  failed: boolean;
  failureText?: string;
}

export interface TraceData {
  /** All actions performed during the test */
  actions: TraceAction[];
  /** DOM snapshots captured (before/after actions) */
  snapshots: DomSnapshot[];
  /** Network requests made during the test */
  network: NetworkEntry[];
  /** Test metadata */
  metadata: TraceMetadata;
}

export interface TraceMetadata {
  testName: string;
  testFile: string;
  browser: string;
  startTime: number;
  endTime: number;
  status: 'passed' | 'failed' | 'timedOut';
  error?: string;
}

// --- Failure Classification ---

export type FailureCategory =
  | 'locator'       // Element not found, selector mismatch
  | 'timeout'       // Action timed out but not clearly a locator issue
  | 'network'       // API/network failure
  | 'assertion'     // Assertion failed (value mismatch)
  | 'environment'   // Browser crash, page error, etc.
  | 'unknown';

export interface FailureClassification {
  category: FailureCategory;
  confidence: number; // 0-1
  reason: string;
  failedAction?: TraceAction;
  /** The DOM snapshot closest to the failure */
  relevantSnapshot?: DomSnapshot;
  /** Network entries relevant to the failure */
  relevantNetwork?: NetworkEntry[];
  /** Suggested fix details (populated for locator failures) */
  suggestedFix?: LocatorFix;
}

// --- Locator Resolution ---

export interface LocatorFix {
  /** The broken selector from the test */
  oldLocator: string;
  /** The suggested new selector */
  newLocator: string;
  /** Locator strategy used */
  strategy: 'role' | 'testId' | 'text' | 'css' | 'xpath' | 'label' | 'placeholder';
  /** Confidence of the suggestion (0-1) */
  confidence: number;
  /** Explanation of why this locator was chosen */
  reasoning: string;
  /** Alternative locators ranked by reliability */
  alternatives?: string[];
}

// --- Code Patching ---

export interface CodePatch {
  filePath: string;
  lineNumber: number;
  originalLine: string;
  patchedLine: string;
  locatorFix: LocatorFix;
}

// --- Healing Result ---

export interface HealingResult {
  testName: string;
  testFile: string;
  classification: FailureClassification;
  patch?: CodePatch;
  rerunPassed: boolean;
  committed: boolean;
  prUrl?: string;
  error?: string;
}

// --- Configuration ---

export interface SelfHealConfig {
  /** Path to trace files or directory */
  tracePath: string;
  /** Path to the test project root */
  projectRoot: string;
  /** LLM provider configuration */
  llm: LlmConfig;
  /** Git configuration */
  git: GitConfig;
  /** Test runner command */
  testCommand: string;
  /** Whether to auto-commit fixes */
  autoCommit: boolean;
  /** Whether to auto-create PR */
  autoPr: boolean;
  /** Maximum number of healing attempts */
  maxRetries: number;
  /** Whether to run in dry-run mode */
  dryRun: boolean;
}

export interface LlmConfig {
  provider: 'openai' | 'azure-openai' | 'anthropic' | 'gemini';
  apiKey: string;
  model?: string;
  endpoint?: string;       // For Azure OpenAI
  deployment?: string;     // For Azure OpenAI
  apiVersion?: string;     // For Azure OpenAI
  temperature?: number;
  maxTokens?: number;
}

export interface GitConfig {
  remote: string;
  baseBranch: string;
  branchPrefix: string;
  commitMessage?: string;
  prTitle?: string;
  prBody?: string;
}

// --- LLM Provider Interface ---

export interface LlmProvider {
  analyze(prompt: string, context?: Record<string, string>): Promise<string>;
  name: string;
}

export interface LlmMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}
