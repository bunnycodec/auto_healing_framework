from __future__ import annotations

import argparse
from pathlib import Path

from .engine import HealingEngine
from .models import HealingReport
from .orchestrator import HealingOrchestrator


def _print_report(report: HealingReport) -> None:
    icon = {
        "healed": "[healed]",
        "restored": "[restored]",
        "skipped": "[skipped]",
        "duplicate": "[duplicate]",
        "failed": "[failed]",
    }.get(report.status, "[?]")
    print(f"{icon} {report.test_name or report.trace_zip} ({report.category}, {report.confidence:.0%})")
    for message in report.messages:
        print(f"    {message}")
    if report.suggestion:
        print(f"    {report.suggestion.old_locator} -> {report.suggestion.new_locator}")
    if report.patched_file:
        print(f"    patched: {report.patched_file}:{report.patch.line_number if report.patch else '?'}")
    if report.pr_url:
        print(f"    PR: {report.pr_url}")


def _summary(reports: list[HealingReport]) -> int:
    healed = sum(1 for r in reports if r.status == "healed")
    skipped = sum(1 for r in reports if r.status == "skipped")
    duplicate = sum(1 for r in reports if r.status == "duplicate")
    failed = sum(1 for r in reports if r.status in {"failed", "restored"})
    print("\nHealing Summary")
    print(f"  healed:     {healed}")
    print(f"  duplicate:  {duplicate}")
    print(f"  skipped:    {skipped}")
    print(f"  failed:     {failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Auto-Healing Framework CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    heal = sub.add_parser("heal", help="Heal a single trace.zip or a directory of traces")
    heal.add_argument("trace", type=Path, help="Path to trace.zip or a results directory")
    heal.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    heal.add_argument("--auto-commit", action="store_true", help="Commit fixes on a branch")
    heal.add_argument("--auto-pr", action="store_true", help="Open a PR with the fixes")

    run = sub.add_parser("run", help="Run tests, collect traces, then heal failures")
    run.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    run.add_argument("--auto-commit", action="store_true", help="Commit fixes on a branch")
    run.add_argument("--auto-pr", action="store_true", help="Open a PR with the fixes")

    args = parser.parse_args()

    if args.command == "heal":
        target = args.trace.resolve()
        engine = HealingEngine(
            dry_run=args.dry_run,
            auto_commit=args.auto_commit,
            auto_pr=args.auto_pr,
        )
        if target.is_dir():
            reports = engine.heal_directory(target)
        else:
            reports = [engine.heal_trace(target)]
        for report in reports:
            _print_report(report)
        return _summary(reports)

    if args.command == "run":
        orchestrator = HealingOrchestrator(
            dry_run=args.dry_run,
            auto_commit=args.auto_commit,
            auto_pr=args.auto_pr,
        )
        result = orchestrator.run()
        if result.tests_passed:
            print("All tests passed - no healing needed.")
            return 0
        if result.traces_found == 0:
            print("Tests failed but no traces were found.")
            return 1
        for report in result.reports:
            _print_report(report)
        return _summary(result.reports)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())