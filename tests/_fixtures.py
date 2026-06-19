from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from config import Settings


def make_settings(work_dir: Path) -> Settings:
    """Build a self-contained Settings object pointing at a temp project."""
    project_root = work_dir / "playwright-tests"
    project_root.mkdir(parents=True, exist_ok=True)

    validate_script = project_root / "validate.py"
    validate_script.write_text(
        "from pathlib import Path\n"
        "content = Path('tests/landing.page.ts').read_text()\n"
        "raise SystemExit(0 if '/Start now/i' in content else 1)\n",
        encoding="utf-8",
    )

    return Settings(
        ai_mode="rule",
        ollama_model="qwen3:8b",
        ollama_url="http://localhost:11434/api/generate",
        azure_openai_api_key=None,
        azure_openai_endpoint=None,
        azure_openai_deployment=None,
        azure_openai_api_version="2025-04-01-preview",
        kilo_api_key=None,
        kilo_api_url="https://api.kilo.ai/v1/messages",
        kilo_model="claude-sonnet",
        project_root=project_root,
        test_command=f'"{sys.executable}" validate.py',
        reports_dir=work_dir / "reports",
        temp_dir=work_dir / "trace-output",
    )


def make_second_broken_trace(work_dir: Path, *, folder: str = "broken-submit-button") -> Path:
    """A second, DISTINCT broken locator in its own page object + trace.

    Used to exercise multi-locator healing (the batch-validate path needs two
    different locators so they aren't deduplicated into one).
    """
    project_root = work_dir / "playwright-tests"
    tests_dir = project_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    test_file = tests_dir / "contact.page.ts"
    test_file.write_text(
        "export class ContactPage {\n"
        "  get submitButton() {\n"
        "    return this.page.getByRole('button', { name: /Sumbit/i });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    trace_dir = work_dir / "test-results" / folder
    trace_dir.mkdir(parents=True, exist_ok=True)

    error_context = trace_dir / "error-context.md"
    error_context.write_text(
        "TimeoutError: locator.click: Timeout 10000ms exceeded.\n"
        "Call log:\n"
        "  - waiting for getByRole('button', { name: /Sumbit/i })\n\n"
        f"    at Object.<anonymous> ({test_file}:3:36)\n",
        encoding="utf-8",
    )

    trace_zip = trace_dir / "trace.zip"
    with zipfile.ZipFile(trace_zip, "w") as archive:
        archive.writestr(
            "resources/snapshot.html",
            "<html><body><main><button>Submit</button></main></body></html>",
        )
    return trace_zip


def make_broken_trace(work_dir: Path, *, folder: str = "broken-start-button") -> Path:
    """Create a broken page object + a matching trace.zip and error context."""
    project_root = work_dir / "playwright-tests"
    tests_dir = project_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    test_file = tests_dir / "landing.page.ts"
    test_file.write_text(
        "export class LandingPage {\n"
        "  get startNowButton() {\n"
        "    return this.page.getByRole('button', { name: /Start new/i });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    trace_dir = work_dir / "test-results" / folder
    trace_dir.mkdir(parents=True, exist_ok=True)

    error_context = trace_dir / "error-context.md"
    error_context.write_text(
        "TimeoutError: locator.click: Timeout 10000ms exceeded.\n"
        "Call log:\n"
        "  - waiting for getByRole('button', { name: /Start new/i })\n\n"
        f"    at Object.<anonymous> ({test_file}:3:36)\n",
        encoding="utf-8",
    )

    trace_zip = trace_dir / "trace.zip"
    with zipfile.ZipFile(trace_zip, "w") as archive:
        archive.writestr(
            "resources/snapshot.html",
            "<html><body><main><button>Start now</button></main></body></html>",
        )
    return trace_zip


def make_corrupted_trace(work_dir: Path, *, folder: str = "corrupted-trace") -> Path:
    """Create a failure where error-context.md is corrupted (ENOENT) but the
    trace.zip action log still holds the real locator failure + stack.

    This reproduces the high-parallelism trace race where the sidecar
    error-context.md is unusable.
    """
    import json

    project_root = work_dir / "playwright-tests"
    tests_dir = project_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    test_file = tests_dir / "landing.page.ts"
    test_file.write_text(
        "export class LandingPage {\n"
        "  get startNowButton() {\n"
        "    return this.page.getByRole('button', { name: /Start new/i });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    trace_dir = work_dir / "test-results" / folder
    trace_dir.mkdir(parents=True, exist_ok=True)

    # Corrupted sidecar — no usable locator info (mimics the ENOENT race).
    error_context = trace_dir / "error-context.md"
    error_context.write_text(
        "# Error details\n"
        "Error: apiRequestContext._wrapApiCall: ENOENT: no such file or "
        f"directory, open '{test_file}'\n",
        encoding="utf-8",
    )

    # Valid trace action log with the real failed 'after' event.
    after_event = {
        "type": "after",
        "callId": "pw:api@58",
        "error": {
            "name": "",
            "message": (
                "TimeoutError: locator.click: Timeout 10000ms exceeded.\n"
                "Call log:\n"
                "\u001b[2m  - waiting for getByRole('button', { name: /Start new/i })\u001b[22m\n"
            ),
            "stack": (
                "TimeoutError: locator.click: Timeout 10000ms exceeded.\n"
                "  - waiting for getByRole('button', { name: /Start new/i })\n\n"
                f"    at LandingPage.start ({test_file}:3:36)\n"
                "    at Object.<anonymous> (C:\\proj\\tests\\steps\\common.steps.ts:26:36)\n"
            ),
        },
    }

    trace_zip = trace_dir / "trace.zip"
    with zipfile.ZipFile(trace_zip, "w") as archive:
        archive.writestr("0-trace.trace", json.dumps(after_event) + "\n")
        archive.writestr(
            "resources/snapshot.html",
            "<html><body><main><button>Start now</button></main></body></html>",
        )
    return trace_zip
