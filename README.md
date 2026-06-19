# AI Auto-Healing Framework

AI-powered self-healing for **Playwright** test suites. When a test fails because a
locator changed, this tool automatically:

1. **Detects** the failure from the Playwright `trace.zip`
2. **Classifies** it (locator / timeout / network / assertion / environment)
3. **Extracts** the failed locator, source location, and an accessibility (aria) DOM snapshot
4. **Asks an LLM** for the corrected locator
5. **Patches** the source file (line-precise, with a project-wide grep fallback)
6. **Re-runs** the affected test and **auto-restores** on failure
7. **Reports** the result as JSON (and can open a PR)

```
Test fails → trace collected → DOM analyzed → locator fixed → test passes → report/PR
```

## Architecture

```
app/                  # FastAPI service + dashboard
├── main.py
└── routes/           # /run, /heal-directory, /orchestrate, /reports, /health

ai/                   # Pluggable AI engines
├── base.py
├── factory.py        # AI_MODE -> engine
├── rule_engine.py    # deterministic, offline (no API needed)
├── azure_openai_engine.py
├── ollama_engine.py
└── kilo_engine.py

healer/               # Core healing engine
├── detector.py       # trace + error + aria-DOM extraction (with trace-log fallback)
├── classifier.py     # failure classification + locator dedup signature
├── analyser.py       # calls the AI engine
├── modifier.py       # line-precise patch + grep fallback + backup/restore
├── rerunner.py       # targeted re-run validation
├── git_pr.py         # branch / commit / PR
├── engine.py         # single-trace + directory healing (deduplicated)
└── orchestrator.py   # run tests -> collect traces -> heal

config.py             # settings from environment / .env
scripts/              # heal_gds.py, self_test.py, fastapi_ai_demo.py
tests/                # pytest suite
```

## Setup

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Configure the AI provider in `.env` (see `.env.example`):

```ini
AI_MODE=azure-openai          # rule | azure-openai | ollama | kilo
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_DEPLOYMENT=...
AZURE_OPENAI_API_VERSION=2025-04-01-preview
```

> `AI_MODE=rule` is deterministic and needs no API — handy for offline smoke tests.

## Usage

### Full pipeline (run tests -> collect traces -> heal)

```powershell
.venv\Scripts\python -m healer.cli run            # heal
.venv\Scripts\python -m healer.cli run --dry-run  # preview only
```

Point it at a project with environment variables:

```powershell
$env:PLAYWRIGHT_PROJECT_ROOT = "C:\path\to\playwright-project"
$env:TEST_COMMAND = "npm run test:smoke -- --trace on --workers 15"
.venv\Scripts\python -m healer.cli run
```

### Heal existing traces

```powershell
# A whole results folder (locator de-duplicated)
.venv\Scripts\python -m healer.cli heal "C:\path\to\test-results" --auto-pr

# A single trace
.venv\Scripts\python -m healer.cli heal "path\to\trace.zip"
```

### Demo against the bundled GDS framework

```powershell
.venv\Scripts\python scripts\heal_gds.py
```

### FastAPI service

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/run` | Heal a single `trace.zip` |
| `POST` | `/heal-directory` | Heal a results folder (dedup) |
| `POST` | `/orchestrate` | Run tests, collect traces, then heal |
| `GET`  | `/reports` | List generated JSON reports |
| `GET`  | `/health` | Health check |

## Validation

```powershell
.venv\Scripts\python -m pytest                    # unit + integration tests
.venv\Scripts\python scripts\self_test.py         # deterministic end-to-end (no AI)
```

## How it stays reliable

- **Trace action-log fallback** — if `error-context.md` is missing/corrupted (a known
  high-parallelism race), the detector recovers the locator + source line from the
  trace's `.trace` action log.
- **Aria-snapshot DOM context** — the AI is fed the accessibility tree (role + accessible
  name), which is what locators actually target.
- **Locator de-duplication** — many tests fail on one broken locator; only one trace is
  sent to the LLM, the rest are reported as duplicates.
- **Safe patching** — line-precise edits with timestamped backups; if the re-run fails,
  the original file is automatically restored.
