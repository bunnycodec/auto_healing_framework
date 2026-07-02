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

Optionally install as a package to get the `auto-healer` console command:

```powershell
.venv\Scripts\python -m pip install -e .
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

## Run it inside any test repo (framework-independent)

The tool is decoupled from any specific project via a `healer.yml` config file. From
inside the test repository you want to heal:

```powershell
auto-healer init        # generate a healer.yml
# edit healer.yml: set framework, test_command, results_dir
auto-healer run         # run tests -> collect traces -> heal, all config-driven
```

Example `healer.yml`:

```yaml
framework: playwright          # playwright | cypress | selenium
language: typescript           # typescript | javascript | python
project_root: .                # project under test (relative to this file)
test_command: "npx playwright test --trace on"
results_dir: test-results      # where trace.zip files are written
workers: 4
ai:
  mode: azure-openai           # rule | azure-openai | ollama | kilo
```

Resolution precedence: **environment variables > `healer.yml` > defaults**. Secrets
(API keys) always come from the environment / `.env`, never `healer.yml` — so CI can
inject them safely.

## Usage

### Full pipeline (run tests -> collect traces -> heal)

After `pip install -e .` you can use the `auto-healer` console command:

```powershell
auto-healer run                # heal
auto-healer run --dry-run      # preview only
auto-healer heal "C:\path\to\test-results" --auto-pr
auto-healer heal "path\to\trace.zip"
```

Or call the module directly (no install needed):

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

### FastAPI service & live dashboard

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open **http://localhost:8000** for a real-time healing dashboard (heal rate, status &
category breakdowns, activity timeline, recent events) that updates live via SSE.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET`  | `/` | Live telemetry dashboard |
| `GET`  | `/metrics` | Aggregated healing metrics (JSON) |
| `GET`  | `/metrics/stream` | Server-Sent Events live metrics feed |
| `POST` | `/run` | Heal a single `trace.zip` |
| `POST` | `/heal-directory` | Heal a results folder (dedup) |
| `POST` | `/orchestrate` | Run tests, collect traces, then heal |
| `GET`  | `/reports` | List generated JSON reports |
| `GET`  | `/health` | Health check |

## Docker

Run anywhere with zero local Python setup.

```bash
# Build
docker build -t ai-auto-healer .

# Serve the dashboard + API (http://localhost:8000)
docker run -p 8000:8000 --env-file .env ai-auto-healer

# Or with compose (persists reports/ for dashboard history)
docker compose up

# Use the CLI inside the container against a mounted project
docker run --rm -v ${PWD}:/work -w /work --env-file .env \
  ai-auto-healer heal test-results --auto-pr
```

The container's entrypoint runs the dashboard by default (`serve`); any other argument
is passed to the `auto-healer` CLI (`init`, `run`, `heal`).

## CI integration (nightly jobs)

Trigger auto-healing whenever a scheduled test run fails — same 3-step pattern in any
CI system: **run tests (traces on) → on failure, heal → open a PR**.

```yaml
- run: npx playwright test --trace on        # allow it to fail
  continue-on-error: true
- run: pip install git+https://github.com/bunnycodec/auto_healing_framework.git
  if: failure()
- run: auto-healer heal test-results --auto-pr
  if: failure()
```

Ready-to-use templates for **GitHub Actions**, **Azure DevOps**, and **Jenkins** are in
[ci/](ci/) — see [ci/README.md](ci/README.md).

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
