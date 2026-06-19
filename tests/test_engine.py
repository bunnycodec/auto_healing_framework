from __future__ import annotations

from pathlib import Path

from ai.rule_engine import RuleEngine
from healer.engine import HealingEngine

from ._fixtures import make_broken_trace, make_settings


def test_heal_single_trace_rule_mode(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    engine = HealingEngine(app_settings=settings, ai_engine=RuleEngine())
    report = engine.heal_trace(trace_zip)

    assert report.status == "healed"
    assert report.suggestion is not None
    assert report.suggestion.old_locator == "getByRole('button', { name: /Start new/i })"
    page_object = settings.playwright_project_root / "tests" / "landing.page.ts"
    assert "/Start now/i" in page_object.read_text(encoding="utf-8")
    # Reports are kept per run, in a run-id subfolder.
    saved = list(settings.reports_dir.rglob("*.json"))
    assert saved
    assert saved[0].parent.parent == settings.reports_dir


def test_heal_directory_deduplicates(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    make_broken_trace(tmp_path, folder="trace-a")
    make_broken_trace(tmp_path, folder="trace-b")
    make_broken_trace(tmp_path, folder="trace-c")

    engine = HealingEngine(app_settings=settings, ai_engine=RuleEngine())
    reports = engine.heal_directory(tmp_path / "test-results")

    assert len(reports) == 3
    healed = [r for r in reports if r.status == "healed"]
    duplicate = [r for r in reports if r.status == "duplicate"]
    assert len(healed) == 1
    assert len(duplicate) == 2


def test_heal_directory_skips_vanished_trace(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    make_broken_trace(tmp_path, folder="trace-a")
    # A second trace that disappears before healing runs — mimics a Playwright
    # retry folder wiped by a validation re-run. It must be skipped, not fatal.
    ghost = make_broken_trace(tmp_path, folder="trace-b")
    ghost.unlink()

    engine = HealingEngine(app_settings=settings, ai_engine=RuleEngine())
    reports = engine.heal_directory(tmp_path / "test-results")

    assert any(r.status == "healed" for r in reports)


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    engine = HealingEngine(app_settings=settings, ai_engine=RuleEngine(), dry_run=True)
    report = engine.heal_trace(trace_zip)

    assert report.status == "skipped"
    assert report.patch is not None
    page_object = settings.playwright_project_root / "tests" / "landing.page.ts"
    assert "/Start new/i" in page_object.read_text(encoding="utf-8")
    # Skipped reports are not persisted.
    assert not list(settings.reports_dir.rglob("*.json"))
