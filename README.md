# 🩹 Playwright Self-Heal

A **framework-agnostic, self-healing tool** for Playwright test suites. When tests fail due to broken locators, this tool automatically:

1. **Parses** Playwright trace files (`.zip`)
2. **Extracts** DOM snapshots, network traffic, and action logs
3. **Classifies** failures (locator vs. network vs. assertion vs. environment)
4. **Resolves** the correct locator using LLM-powered DOM analysis
5. **Patches** the source code with the fixed locator
6. **Re-runs** the failed test to validate the fix
7. **Commits** the change and **raises a PR**

```
Test Fails → Trace Collected → DOM Analyzed → Locator Fixed → Test Passes → PR Raised ✅
```

## Quick Start

```bash
# Install
npm install playwright-self-heal

# Set your LLM provider key
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...

# Heal broken locators from trace files
npx self-heal heal --trace ./test-results --auto-pr
```

## Architecture

```
src/
├── cli/                  # CLI interface (commander)
├── trace-parser/         # Extracts data from Playwright trace .zip files
├── failure-classifier/   # Classifies failure root cause
├── llm/                  # Pluggable LLM providers (OpenAI, Azure, Anthropic, Gemini)
├── locator-resolver/     # LLM-powered locator suggestion from DOM snapshots
├── code-patcher/         # Maps failures to source files and patches locators
├── test-runner/          # Re-runs tests to validate fixes
├── git-pr/               # Git commit, push, and PR creation
└── types/                # TypeScript type definitions
```

## CLI Usage

### `self-heal heal` — Full healing pipeline

```bash
npx self-heal heal \
  --trace ./test-results \           # Trace file (.zip) or directory
  --project ./my-test-project \      # Test project root (default: cwd)
  --test-command "npx playwright test" \  # Test runner command
  --provider openai \                # LLM provider
  --auto-commit \                    # Commit fixes automatically
  --auto-pr \                        # Create a PR
  --dry-run                          # Preview changes without modifying files
```

### `self-heal analyze` — Classify failures only

```bash
npx self-heal analyze --trace ./test-results/trace.zip
```

Output:
```
📋 Test: should display user profile
   File: tests/profile.spec.ts
   Category:   locator
   Confidence: 95%
   Reason:     Locator failure: Selector "#user-name" could not find a matching element.
   Selector:   #user-name
```

## Programmatic API

```typescript
import { SelfHealEngine, SelfHealConfig } from 'playwright-self-heal';

const config: SelfHealConfig = {
  tracePath: './test-results',
  projectRoot: './my-test-project',
  llm: {
    provider: 'openai',
    apiKey: process.env.OPENAI_API_KEY!,
    model: 'gpt-4o',
  },
  git: {
    remote: 'origin',
    baseBranch: 'main',
    branchPrefix: 'self-heal',
  },
  testCommand: 'npx playwright test',
  autoCommit: true,
  autoPr: true,
  maxRetries: 1,
  dryRun: false,
};

const engine = new SelfHealEngine(config);

// Optional: progress logging
engine.setProgressCallback((message, phase) => {
  console.log(`[${phase}] ${message}`);
});

const results = await engine.heal();

for (const result of results) {
  console.log(`${result.testName}: ${result.rerunPassed ? 'HEALED ✅' : 'FAILED ❌'}`);
  if (result.prUrl) console.log(`  PR: ${result.prUrl}`);
}
```

## LLM Provider Configuration

Configure via environment variables or CLI flags. Copy `.env.example` to `.env` and set your provider:

| Provider | Env Vars |
|---|---|
| **OpenAI** | `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL` |
| **Azure OpenAI** | `LLM_PROVIDER=azure-openai`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` |
| **Anthropic** | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| **Google Gemini** | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL` |

## Failure Classification

The classifier distinguishes between failure types:

| Category | Healable | Description |
|---|---|---|
| `locator` | ✅ Yes | Element not found, selector mismatch |
| `timeout` | ❌ No | Generic timeout (not locator-related) |
| `network` | ❌ No | API/network failure |
| `assertion` | ❌ No | Value assertion mismatch |
| `environment` | ❌ No | Browser crash, page error |
| `unknown` | ❌ No | Unclassified failure |

## CI/CD Integration

### GitHub Actions

```yaml
- name: Run Playwright tests
  run: npx playwright test --trace on
  continue-on-error: true

- name: Self-heal broken locators
  run: npx self-heal heal --trace ./test-results --auto-pr
  env:
    LLM_PROVIDER: openai
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## How It Works

1. **Trace Parsing**: Extracts newline-delimited JSON events from Playwright trace `.zip` files, including action logs, DOM snapshots, and network requests.

2. **Failure Classification**: Pattern-matches error messages against known locator failure signatures (e.g., "waiting for selector", "element not found") to classify the root cause.

3. **LLM-Powered Resolution**: Sends the broken selector and relevant DOM snapshot to an LLM, which analyzes the HTML structure and suggests the correct Playwright locator using the most robust strategy available (role > testId > text > CSS).

4. **Code Patching**: Parses the stack trace from the failed action to find the exact source file and line number, then surgically replaces the old locator with the new one.

5. **Validation**: Re-runs only the failed test. If it passes, the fix is accepted; if it still fails, the patch is reverted.

6. **PR Creation**: Commits the validated fix on a new branch and creates a PR with a detailed description of what was changed and why.

## License

MIT