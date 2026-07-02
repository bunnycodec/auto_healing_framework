# Hand-off: AI Auto-Healing Framework

> Pick-up document for continuing work on the Python/FastAPI auto-healer.
> Last updated: 2026-06-20

## TL;DR

A **Python/FastAPI** tool that auto-heals broken Playwright locators: it runs a test
suite, reads the failure `trace.zip`, asks an LLM for the corrected locator, patches the
source file (line-precise), re-runs to validate, and reports the result. It replaced an
earlier TypeScript version (now removed).

The heal loop is now **governance-gated** (confidence threshold, locator validity,
generic-locator penalty, cross-run idempotency ledger), validates fixes by re-running
**only the failing spec** where possible, and the dashboard surfaces the failing
**Gherkin feature → scenario → step** alongside the before/after locator.

- **Repo:** `bunnycodec/auto_healing_framework`
- **Working branch:** `feat/python-auto-healer` (open PR **#2** → `main`)
- **This dir:** `C:\Users\Lokesh-PC\copilot-worktrees\auto_healing_framework\376805-cgcp-didactic-robot`
- **Demo target (Playwright suite under test):** `C:\MyWork\Playwright-framework-for-GDS-App`

## Status: working

- `pytest` → **41 passed** (added `tests/test_gaps.py`, BDD detector test)
- Deterministic `self_test.py` → passes (no AI needed)
- FastAPI `/health`, `/reports`, `/metrics`, `/metrics/stream` → ok
- End-to-end Azure OpenAI healing re-verified on the GDS framework: broke the
  landing **Start now** button, healed `name: 'Begin application'` → `name: /Start now/i`
  at 98% confidence; dashboard showed the full scenario/step chain.

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
app/        FastAPI service + dashboard (routes: /run, /heal-directory, /orchestrate, /reports, /metrics, /health)
ai/         Pluggable engines: rule, azure-openai, ollama, kilo (factory.py picks via AI_MODE); http.py = retry/backoff
healer/     detector, classifier, analyser, modifier, rerunner, git_pr, engine, orchestrator, ledger, telemetry
config.py   Settings from environment / .env (incl. min_confidence, targeted_validation, max_heal_attempts)
scripts/    heal_gds.py, self_test.py, fastapi_ai_demo.py
tests/      pytest suite (classifier, modifier, engine, detector, config, telemetry, gaps)
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

4. **Safe patching** (`healer/modifier.py`): line-precise edit; if the stack line
   doesn't match, it searches **only the failing file** for the locator (the
   project-wide grep is a last resort used only when no failing file is known).
   In-memory snapshot + automatic restore if the re-run fails. A `restored`
   status means the AI's suggestion didn't pass validation (not a crash).

5. **AI response sanitising** (`ai/ollama_engine.sanitize_locator`): models sometimes
   return prose/code around the locator. The sanitizer extracts a single clean
   `getByRole(...)` / `locator(...)` expression. Shared by the Azure engine.

6. **Secrets**: `.env` is git-ignored. Only `.env.example` (empty placeholders) is
   committed. Never stage `.env`.

7. **Confidence gate** (`healer/engine._prepare` + `config.min_confidence`, default
   `0.7`): the engine gates on the **effective** confidence = `min(classification,
   suggestion)`. Below the bar the suggestion is recorded but never applied
   (status `low_confidence`, report-only) so a human can review with zero file change.

8. **Locator validity + generic penalty** (`ai/ollama_engine.is_valid_locator_expression`,
   `is_generic_locator`): structurally invalid AI output is rejected before any write;
   over-broad locators (e.g. `getByRole('button')` with no name) are penalised to
   report-only so they can't pass validation by coincidence.

9. **Targeted validation** (`config.targeted_command` + `_is_spec_file`): a heal is
   validated by re-running only the failing spec (`file:line`), not the whole suite.
   When the failing file isn't a recognisable spec (e.g. a page object) it safely
   falls back to the full command, so it never hands the runner a non-test path.

10. **Resilience** (`ai/http.py`, `engine.heal_directory`): LLM calls retry with
    exponential backoff (skipping deterministic 4xx); a single trace's failure is
    caught and reported, never aborting the rest of the batch.

11. **Classifier strong/weak split** (`healer/classifier.py`): definite
    element-not-found patterns score `0.95`; transient visibility/state patterns
    (likely timing flakes, not drift) score `0.55` so the confidence gate holds them
    as report-only rather than rewriting a good locator.

12. **Idempotency ledger** (`healer/ledger.py`, `.healer-ledger.json` at project root):
    stops re-attempting a locator signature after `max_heal_attempts` (default 3)
    failures, preventing repeated identical PRs. Git-ignore this file in target repos.

13. **BDD scenario/step capture** (`healer/detector._extract_bdd_context`): recovers the
    Gherkin **feature + scenario** from the trace `context-options.title`
    (`spec:line › Feature › Scenario`) and the failing **step** from the nearest
    `test.step` ancestor of the errored action. Surfaced via `telemetry._summarize`
    and rendered on the dashboard (keyword badge + before→after locator).

14. **Report redaction** (`engine._serialize` + `config.save_dom_in_reports`): persisted
    reports drop the DOM chunk and cap `error_message` by default to avoid leaking page
    data; `git_pr._clean` flattens LLM `reasoning`/locators before they enter commits/PRs.

## Suggested next steps (open ideas)

- **CI integration**: wire `ci/github-actions-nightly.yml` to run Playwright with traces,
  then `auto-healer heal test-results --auto-pr` on failure.
- **Per-test re-run for page objects**: targeted validation currently falls back to a
  full run when the failing frame is a page object; map POM → owning spec to narrow it.
- **Provider expansion**: add OpenAI/Anthropic/Gemini engines (factory already pluggable).
- **Dashboard filters**: filter the run/event list by status (healed/report-only/failed)
  and by feature.
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
