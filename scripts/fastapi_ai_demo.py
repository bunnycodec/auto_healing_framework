from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    work_dir = Path(tempfile.mkdtemp(prefix="auto-healer-fastapi-ai-demo-"))
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

        os.environ["AI_MODE"] = "azure-openai"
        os.environ["PLAYWRIGHT_PROJECT_ROOT"] = str(project_root)
        os.environ["TEST_COMMAND"] = f'"{sys.executable}" validate.py'
        os.environ["REPORTS_DIR"] = str(reports_dir)
        os.environ["HEALER_TEMP_DIR"] = str(temp_dir)

        from fastapi.testclient import TestClient
        from app.main import app

        response = TestClient(app).post("/run", json={"trace_zip": str(trace_zip)})
        print(f"status_code={response.status_code}")
        print(json.dumps(response.json(), indent=2))
        patched = test_file.read_text(encoding="utf-8")
        print("patched_locator_line=" + next(line.strip() for line in patched.splitlines() if "getByRole" in line))

        if response.status_code != 200:
            return 1
        body = response.json()
        if body.get("status") != "healed":
            return 1
        if "/Start now/i" not in patched:
            return 1
        print(f"work_dir={work_dir}")
        return 0
    finally:
        if "--keep" not in sys.argv:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())