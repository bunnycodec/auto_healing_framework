from __future__ import annotations

import argparse
from pathlib import Path

from config import find_config_file, load_settings

from .engine import HealingEngine
from .models import HealingReport
from .orchestrator import HealingOrchestrator


HEALER_YML_TEMPLATE = """\
# AI Auto-Healer configuration
# Run `auto-healer run` from this directory to use it.
# Environment variables override these values (ideal for CI secrets).

framework: {framework}        # playwright | cypress | selenium
language: {language}      # typescript | javascript | python
project_root: .              # path to the project under test (relative to this file)
test_command: "{test_command}"
results_dir: test-results    # where the framework writes trace.zip files
workers: 4

ai:
  mode: rule                 # rule | azure-openai | ollama | kilo

reports_dir: reports
temp_dir: trace-output

# Secrets stay in the environment / .env, never here. For example:
#   AI_MODE=azure-openai
#   AZURE_OPENAI_API_KEY=...
#   AZURE_OPENAI_ENDPOINT=...
#   AZURE_OPENAI_DEPLOYMENT=...
"""


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


def _init_config(target_dir: Path, *, framework: str, language: str, force: bool) -> int:
    target = (target_dir / "healer.yml").resolve()
    if target.exists() and not force:
        print(f"healer.yml already exists at {target} (use --force to overwrite)")
        return 1

    test_commands = {
        "playwright": "npx playwright test --trace on",
        "cypress": "npx cypress run",
        "selenium": "pytest",
    }
    content = HEALER_YML_TEMPLATE.format(
        framework=framework,
        language=language,
        test_command=test_commands.get(framework, "npx playwright test --trace on"),
    )
    target.write_text(content, encoding="utf-8")
    print(f"Created {target}")
    print("Next: set your AI provider (e.g. AI_MODE=azure-openai) in the environment / .env,")
    print("      then run: auto-healer run")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Auto-Healing Framework CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a healer.yml in the current project")
    init.add_argument("--framework", default="playwright", help="playwright | cypress | selenium")
    init.add_argument("--language", default="typescript", help="typescript | javascript | python")
    init.add_argument("--force", action="store_true", help="Overwrite an existing healer.yml")

    heal = sub.add_parser("heal", help="Heal a single trace.zip or a directory of traces")
    heal.add_argument("trace", type=Path, help="Path to trace.zip or a results directory")
    heal.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    heal.add_argument("--auto-commit", action="store_true", help="Commit fixes on a branch")
    heal.add_argument("--auto-pr", action="store_true", help="Open a PR with the fixes")
    heal.add_argument(
        "--validate-once",
        action="store_true",
        help="Apply all locator fixes, then validate with a single re-run "
        "(faster for many distinct broken locators)",
    )

    run = sub.add_parser("run", help="Run tests, collect traces, then heal failures")
    run.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    run.add_argument("--auto-commit", action="store_true", help="Commit fixes on a branch")
    run.add_argument("--auto-pr", action="store_true", help="Open a PR with the fixes")
    run.add_argument(
        "--validate-once",
        action="store_true",
        help="Apply all locator fixes, then validate with a single re-run "
        "(faster for many distinct broken locators)",
    )

    args = parser.parse_args()

    if args.command == "init":
        return _init_config(
            Path.cwd(),
            framework=args.framework,
            language=args.language,
            force=args.force,
        )

    # Resolve project-specific settings from healer.yml (if present) + env.
    settings = load_settings()
    config_path = find_config_file()
    if config_path is not None:
        print(f"config    : {config_path}")
    print(f"project   : {settings.project_root}")
    print(f"framework : {settings.framework}")
    print(f"ai mode   : {settings.ai_mode}\n")

    if args.command == "heal":
        target = args.trace.resolve()
        engine = HealingEngine(
            app_settings=settings,
            dry_run=args.dry_run,
            auto_commit=args.auto_commit,
            auto_pr=args.auto_pr,
            batch_validate=args.validate_once,
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
            app_settings=settings,
            dry_run=args.dry_run,
            auto_commit=args.auto_commit,
            auto_pr=args.auto_pr,
            batch_validate=args.validate_once,
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