from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ai.rule_engine import RuleEngine
from config import Settings
from healer.engine import HealingEngine


def main() -> int:
    work_dir = Path(tempfile.mkdtemp(prefix="auto-healer-self-test-"))
    try:
        project_root = work_dir / "playwright-tests"
        tests_dir = project_root / "tests"
        trace_dir = work_dir / "test-results" / "broken-start-button"
        reports_dir = work_dir / "reports"
        temp_dir = work_dir / "trace-output"

        tests_dir.mkdir(parents=True)
        trace_dir.mkdir(parents=True)

        test_file = tests_dir / "landing.page.ts"
        test_file.write_text(
            "export class LandingPage {\n"
            "  get startNowButton() {\n"
            "    return this.page.getByRole('button', { name: /Start new/i });\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )

        validate_script = project_root / "validate.py"
        validate_script.write_text(
            "from pathlib import Path\n"
            "content = Path('tests/landing.page.ts').read_text()\n"
            "raise SystemExit(0 if '/Start now/i' in content else 1)\n",
            encoding="utf-8",
        )

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

        settings = Settings(
            ai_mode="rule",
            ollama_model="qwen3:8b",
            ollama_url="http://localhost:11434/api/generate",
            kilo_api_key=None,
            kilo_api_url="https://api.kilo.ai/v1/messages",
            kilo_model="claude-sonnet",
            project_root=project_root,
            test_command=f'"{sys.executable}" validate.py',
            reports_dir=reports_dir,
            temp_dir=temp_dir,
        )

        report = HealingEngine(app_settings=settings, ai_engine=RuleEngine()).heal_trace(trace_zip)
        patched = test_file.read_text(encoding="utf-8")
        report_files = list(reports_dir.glob("*.json"))

        assert report.status == "healed", report
        assert "/Start now/i" in patched, patched
        assert report.suggestion is not None
        assert report.suggestion.old_locator == "getByRole('button', { name: /Start new/i })"
        assert report_files, "expected a JSON report"
        json.loads(report_files[0].read_text(encoding="utf-8"))

        print("self-test passed")
        print(f"work_dir={work_dir}")
        return 0
    finally:
        if "--keep" not in sys.argv:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())