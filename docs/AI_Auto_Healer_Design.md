**AI Auto-Healing Framework**

Project Design & Architecture Document

*Version 1.0 | June 2026 | Confidential*

# **1. Project Overview**

This document outlines the design and architecture of the AI Auto-Healing Framework — a solution that automatically detects, analyses, fixes, and validates broken Playwright test scenarios caused by UI changes in the application codebase.

The goal is a fully autonomous healing loop: when a regression test fails due to a locator change, the system identifies the failure, uses AI to find the correct locator, modifies the test file, re-runs the test, and reports the outcome — without human intervention.

# **2. Tech Stack**

| **Layer** | **Tool / Technology** | **Purpose** |
| --- | --- | --- |
| Orchestrator | Python | Drives the full healing loop |
| AI Engine (Local) | Ollama — qwen3:8b | Free, runs locally on M4 MacBook |
| AI Engine (API) | Kilo API — Claude Sonnet | Fallback / portfolio demo mode |
| Test Runner | Playwright + TypeScript | Existing 20-scenario framework |
| DOM Capture | Playwright trace.zip | DOM snapshot at exact failure point |
| File Modifier | Python (fs operations) | Surgical .ts file modification |
| Web Dashboard | FastAPI + HTML/JS | Entry point, live progress, reports |
| Reporting | JSON → Dashboard render | Clean, shareable healing report |

AI mode is configurable via environment variable:

AI\_MODE=ollama # or: kilo

OLLAMA\_MODEL=qwen3:8b

KILO\_API\_KEY=your\_key\_here

# **3. Project Folder Structure**

ai-auto-healer/

│

├── app/ # FastAPI web dashboard

│ ├── main.py # FastAPI entry point

│ ├── routes/

│ │ ├── runner.py # Trigger test runs

│ │ └── report.py # Serve healing reports

│ └── templates/

│ └── dashboard.html # UI

│

├── healer/ # Core healing engine

│ ├── detector.py # Intercepts failures, extracts context

│ ├── analyser.py # Sends to AI, gets new locator

│ ├── modifier.py # Modifies the .ts test file

│ └── rerunner.py # Re-runs the specific failed test

│

├── ai/ # AI engine abstraction

│ ├── base.py # Abstract interface

│ ├── ollama\_engine.py # Ollama implementation

│ └── kilo\_engine.py # Kilo API implementation

│

├── playwright-tests/ # Existing Playwright TS framework

│ ├── tests/ # 20 test scenarios

│ └── playwright.config.ts

│

├── reports/ # Generated healing reports (JSON)

│

├── config.py # AI\_MODE, model, API keys

├── .env # Secrets

└── requirements.txt

**Key Design Decisions**

| **Decision** | **Reasoning** |
| --- | --- |
| healer/ is separate from ai/ | AI engine is swappable without touching healing logic |
| playwright-tests/ stays isolated | Healer only touches it via modifier.py — clean boundary |
| reports/ uses flat JSON | Easy to render in dashboard, easy to export or share |
| config.py + .env | One place to switch between Ollama and Kilo API |

# **4. The Full Healing Loop**

User opens Dashboard (FastAPI)

↓

Clicks 'Run Regression'

↓

Python triggers Playwright test run

↓

Test Fails → Failure Intercepted

↓

AI Engine Analyses:

→ Error message + failed locator

→ DOM snapshot from trace.zip

→ App codebase (component structure)

↓

AI Suggests New Locator

↓

modifier.py patches the .ts file (line-precise)

↓

Re-run that specific test scenario

↓

Pass → Healed ✅ | Fail → Restore backup ❌

↓

Report rendered in Dashboard

# **5. Problem Statement 1 — DOM Size vs AI Context Window**

## **The Problem**

A real-world DOM can be 50,000–200,000 characters. Feeding the entire page HTML to the AI engine will:

* Exceed the context window of local models (qwen3:8b)
* Dramatically slow down response time
* Confuse the model with irrelevant noise

## **The Solution — DOM Pruning Pipeline**

We do not send the full DOM. We send only the targeted region relevant to the failed locator, cleaned of all noise.

**Step 1 — Use Playwright trace.zip (not page.content())**

When Playwright runs a test, it generates a trace.zip file containing DOM snapshots at every action. This gives us the DOM at the exact moment of failure — without needing to re-run the browser.

import zipfile, os

def extract\_dom\_from\_trace(trace\_zip\_path: str, output\_dir: str) -> str:

with zipfile.ZipFile(trace\_zip\_path, 'r') as z:

z.extractall(output\_dir)

snapshot\_dir = os.path.join(output\_dir, 'snapshots')

snapshots = sorted(os.listdir(snapshot\_dir))

last\_snapshot = snapshots[-1] # closest to failure

with open(os.path.join(snapshot\_dir, last\_snapshot)) as f:

return f.read()

**Step 2 — Isolate the Failure Zone**

Using the failed locator (from the Playwright error), walk up the DOM tree N levels to extract just the surrounding region.

from bs4 import BeautifulSoup

def extract\_dom\_chunk(full\_html: str, failed\_locator: str, depth: int = 3):

soup = BeautifulSoup(full\_html, 'html.parser')

candidate = soup.find(attrs={'id': failed\_locator.strip('#')})

node = candidate

for \_ in range(depth):

if node.parent:

node = node.parent

return str(node)

**Step 3 — Prune and Clean**

Strip all attributes and tags that are irrelevant to locator identification.

def prune\_dom(html\_chunk: str) -> str:

soup = BeautifulSoup(html\_chunk, 'html.parser')

for tag in soup(['script', 'style', 'svg', 'img', 'meta', 'link']):

tag.decompose()

allowed = {'id','class','name','type','aria-label',

'placeholder','href','role','data-testid'}

for tag in soup.find\_all(True):

tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed}

return str(soup)

## **Result**

80,000+ character DOM → ~300–800 character targeted chunk sent to AI. Well within context window for both Ollama and Kilo API.

| **Stage** | **What Happens** |
| --- | --- |
| Trace captured | Playwright saves trace.zip on test failure |
| DOM extracted | Python unzips and reads the last snapshot |
| Zone isolated | Failure locator used to find surrounding region |
| Noise pruned | Scripts, styles, SVGs, useless attributes removed |
| Lean chunk sent | ~300–800 chars delivered to AI engine |

# **6. Problem Statement 2 — Safe Modification of .ts Test Files**

## **The Problem**

Blindly replacing a locator string across a TypeScript file is dangerous:

* The same locator string may appear in multiple places — not all of which failed
* The locator string may appear inside comments — which should never be changed
* A wrong-line replacement can silently corrupt test logic

## **The Solution — Line-Precise Targeting**

Playwright error output always includes the exact file, line number, and column of the failure. We use this to perform a surgical, single-line replacement — never a global string search.

**Extracting the Failure Location**

A Playwright failure message looks like this:

Error: locator('#submit-btn') — element not found

at LoginTest.ts:87:23

From this we extract: file = LoginTest.ts, line = 87, column = 23.

**Backup Before Touch**

Before any modification, the original file is backed up with a timestamp. If the re-run fails after healing, the backup is automatically restored.

import shutil

from datetime import datetime

def backup\_test\_file(file\_path: str) -> str:

ts = datetime.now().strftime('%Y%m%d\_%H%M%S')

backup\_path = f'{file\_path}.backup\_{ts}'

shutil.copy2(file\_path, backup\_path)

return backup\_path

def restore\_if\_failed(file\_path: str, backup\_path: str, passed: bool):

if not passed:

shutil.copy2(backup\_path, file\_path)

print('Healing failed — original file restored')

**Line-Precise Replacement**

def modify\_locator(file\_path: str, line\_number: int,

old\_locator: str, new\_locator: str) -> bool:

with open(file\_path, 'r') as f:

lines = f.readlines()

target\_line = lines[line\_number - 1]

if old\_locator not in target\_line:

return False # safety abort — mismatch detected

lines[line\_number - 1] = target\_line.replace(old\_locator, new\_locator, 1)

with open(file\_path, 'w') as f:

f.writelines(lines)

return True

## **Full Safe Modification Flow**

Extract line number from Playwright error

↓

Backup the .ts file

↓

Confirm old locator exists on that exact line

↓

AI suggests new locator

↓

Replace on that line only (no global search)

↓

Re-run the specific test

↓

Pass → keep change, log heal ✅

Fail → restore backup, flag for manual review ❌

| **Risk** | **Mitigation** |
| --- | --- |
| Same locator in multiple places | Line-number targeting — only that line is touched |
| Locator appears in comments | Line-precise replace never touches other lines |
| Wrong line targeted | Safety check: confirm old locator exists on line before writing |
| Healing makes things worse | Auto-restore from timestamped backup if re-run fails |

# **7. Summary — Both Problems Solved**

| **Problem** | **Solution** |
| --- | --- |
| DOM too large for AI | trace.zip extraction → failure zone isolation → noise pruning → lean chunk |
| Unsafe .ts modification | Line-precise targeting + pre-modification backup + auto-restore on failure |

*These two foundations are resolved before any code is written. All other components of the framework build on top of these guarantees.*

*AI Auto-Healing Framework | Internal Design Document | June 2026*
