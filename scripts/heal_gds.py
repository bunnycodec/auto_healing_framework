"""Run the Python AI-healing orchestrator against the real GDS Playwright framework.

Usage:
    .venv\\Scripts\\python scripts\\heal_gds.py

Environment overrides (all optional):
    GDS_PROJECT   Path to the Playwright project (default: C:\\MyWork\\Playwright-framework-for-GDS-App)
    AI_MODE       AI provider: azure-openai | ollama | kilo | rule (default: azure-openai)
    TEST_COMMAND  Test command to run (default: npm run test:smoke -- --trace on --workers 15)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

GDS_PROJECT = Path(os.getenv("GDS_PROJECT", r"C:\MyWork\Playwright-framework-for-GDS-App"))


def main() -> int:
    if not GDS_PROJECT.exists():
        print(f"GDS project not found: {GDS_PROJECT}")
        return 2

    # Point the healer at the real Playwright project.
    # AI_MODE and TEST_COMMAND can be overridden from the environment.
    os.environ.setdefault("AI_MODE", "azure-openai")
    os.environ["PLAYWRIGHT_PROJECT_ROOT"] = str(GDS_PROJECT)
    os.environ.setdefault(
        "TEST_COMMAND", "npm run test:smoke -- --trace on --workers 15"
    )
    os.environ["REPORTS_DIR"] = str(REPO_ROOT / "reports")
    os.environ["HEALER_TEMP_DIR"] = str(REPO_ROOT / "trace-output")

    print(f"Project   : {GDS_PROJECT}")
    print(f"AI mode   : {os.environ['AI_MODE']}")
    print(f"Test cmd  : {os.environ['TEST_COMMAND']}\n")

    from config import settings
    from healer import HealingOrchestrator

    orchestrator = HealingOrchestrator(app_settings=settings)
    result = orchestrator.run()

    print("\n================ ORCHESTRATION RESULT ================")
    print(f"tests_passed : {result.tests_passed}")
    print(f"traces_found : {result.traces_found}")
    healed = sum(1 for r in result.reports if r.status == "healed")
    duplicate = sum(1 for r in result.reports if r.status == "duplicate")
    skipped = sum(1 for r in result.reports if r.status == "skipped")
    failed = sum(1 for r in result.reports if r.status in {"failed", "restored"})
    print(f"healed       : {healed}")
    print(f"duplicate    : {duplicate}")
    print(f"skipped      : {skipped}")
    print(f"failed       : {failed}")

    for report in result.reports:
        if report.suggestion:
            print(
                f"\n[{report.status}] {report.test_name}\n"
                f"  {report.suggestion.old_locator}\n"
                f"  -> {report.suggestion.new_locator} "
                f"({report.suggestion.confidence:.0%})"
            )
            if report.patched_file:
                print(f"  patched: {report.patched_file}")

    if result.tests_passed:
        return 0
    return 0 if healed > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
