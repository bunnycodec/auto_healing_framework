# Hand-off: AI Auto-Healing Framework

> Pick-up document for continuing work on the Python/FastAPI auto-healer.
> Last updated: 2026-06-19

## TL;DR

A **Python/FastAPI** tool that auto-heals broken Playwright locators: it runs a test
suite, reads the failure `trace.zip`, asks an LLM for the corrected locator, patches the
source file (line-precise), re-runs to validate, and reports the result. It replaced an
earlier TypeScript version (now removed).

- **Repo:** `bunnycodec/auto_healing_framework`
- **Working branch:** `feat/python-auto-healer` (open PR **#2** → `main`)
- **This dir:** `C:\Users\Lokesh-PC\copilot-worktrees\auto_healing_framework\376805-cgcp-didactic-robot`
- **Demo target (Playwright suite under test):** `C:\MyWork\Playwright-framework-for-GDS-App`

## Status: working

- `pytest` → 13 passed
- Deterministic `self_test.py` → passes (no AI needed)
- FastAPI `/health`, `/reports` → ok
- End-to-end Azure OpenAI healing verified on the GDS framework for **landing,
  personal-details (Step 1), and contact-information (Step 2)** pages.

## Setup

```powershell
cd "C:\Users\Lokesh-PC\copilot-worktrees\auto_healing_framework\376805-cgcp-didactic-robot"
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .   # registers the `auto-healer` command
```

Configure the AI provider in `.env` (a real `.env` already exists locally; it is
git-ignored and must NOT be committed). Template is `.env.example`.

```ini
AI_MODE=azure-openai          # rule | azure-openai | ollama | kilo
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_DEPLOYMENT=...
AZURE_OPENAI_API_VERSION=2025-04-01-preview
```

`AI_MODE=rule` is deterministic and offline — use it for tests/CI where no API is wanted.

## How to invoke

### Console command (after `pip install -e .`)

```powershell
auto-healer run                                  # run tests -> collect traces -> heal
auto-healer run --dry-run                        # preview, no writes
auto-healer heal "C:\path\to\test-results"       # heal a results folder (dedup)
auto-healer heal "path\to\trace.zip"             # heal one trace
auto-healer heal "...\test-results" --auto-commit
auto-healer heal "...\test-results" --auto-pr
```

### Module form (no install needed)

```powershell
.venv\Scripts\python -m healer.cli run
.venv\Scripts\python -m healer.cli heal "<path>"
```

### Pre-wired GDS demo

```powershell
.venv\Scripts\python scripts\heal_gds.py
```

### Target another project (env overrides)

```powershell
$env:PLAYWRIGHT_PROJECT_ROOT = "C:\path\to\playwright-project"
$env:TEST_COMMAND = "npm run test:smoke -- --trace on --workers 15"
.venv\Scripts\python -m healer.cli run
```

### FastAPI service

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
# POST /run {"trace_zip": "..."}
# POST /heal-directory {"trace_dir": "..."}
# POST /orchestrate {}
# GET  /reports
# GET  /health
```

### Tests

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts\self_test.py
```

## Architecture

```
app/        FastAPI service + dashboard (routes: /run, /heal-directory, /orchestrate, /reports, /health)
ai/         Pluggable engines: rule, azure-openai, ollama, kilo (factory.py picks via AI_MODE)
healer/     detector, classifier, analyser, modifier, rerunner, git_pr, engine, orchestrator
config.py   Settings from environment / .env
scripts/    heal_gds.py, self_test.py, fastapi_ai_demo.py
tests/      pytest suite (classifier, modifier, engine, detector)
```

Pipeline: `orchestrator.run()` → run tests → collect fresh `trace.zip` files →
`engine.heal_directory()` → per trace: `detector` → `classifier` → (dedup) →
`analyser` (LLM) → `modifier` (patch + backup) → `rerunner` (validate) →
restore-on-fail → JSON report → optional git/PR.

## Important design decisions / gotchas

1. **Trace action-log fallback** (`healer/detector.py`): under high parallelism
   (`--workers 15`), Playwright sometimes writes a corrupted `error-context.md`
   (an `ENOENT ... landing.page.ts` message). The detector falls back to parsing the
   trace's `.trace` JSONL `after` events to recover the real locator + source line.
   This is why deeper-page failures are caught, not just landing-page ones.

2. **Aria-snapshot DOM context**: Playwright does NOT store usable live HTML in the
   trace. The detector feeds the LLM the **accessibility tree** (role + accessible name)
   from the "Page snapshot" section / `ariaSnapshot` events. This is what makes the AI
   suggestions accurate.

3. **Locator de-duplication** (`healer/classifier.locator_signature` + `engine`):
   many tests fail on one broken locator; only ONE trace goes to the LLM, the rest are
   reported as `duplicate`. Expect `healed: 1, duplicate/skipped: N` for a single break.

4. **Safe patching** (`healer/modifier.py`): line-precise edit with a project-wide grep
   fallback, timestamped backup, and automatic restore if the re-run fails. A `restored`
   status means the AI's suggestion didn't pass validation (not a crash).

5. **AI response sanitising** (`ai/ollama_engine.sanitize_locator`): models sometimes
   return prose/code around the locator. The sanitizer extracts a single clean
   `getByRole(...)` / `locator(...)` expression. Shared by the Azure engine.

6. **Secrets**: `.env` is git-ignored. Only `.env.example` (empty placeholders) is
   committed. Never stage `.env`.

## Suggested next steps (open ideas)

- **CI integration**: add a GitHub Actions job that runs Playwright with traces, then
  `auto-healer heal test-results --auto-pr` on failure.
- **Confidence gating**: skip patching (or require review) when AI confidence < threshold.
- **Multi-locator-per-test**: current dedup keys on the first failed locator; extend to
  heal multiple distinct locators in one run.
- **Provider hardening**: retries/backoff for Azure/Ollama/Kilo HTTP calls.
- **Report UI**: render `/reports` JSON in the FastAPI dashboard instead of raw JSON.
- **Packaging**: optionally publish to an internal index so `pip install ai-auto-healer`
  works without `-e .`.

## Reproduce a heal (smoke check)

```powershell
# 1. Break a locator in the GDS project, e.g. tests/pages/contact-information.page.ts:
#    'Postcode' -> 'Posstcode'
# 2. Heal it:
cd "C:\Users\Lokesh-PC\copilot-worktrees\auto_healing_framework\376805-cgcp-didactic-robot"
.venv\Scripts\python scripts\heal_gds.py
# 3. Confirm:
cd "C:\MyWork\Playwright-framework-for-GDS-App"; npm run test:smoke   # 15 passed
```
