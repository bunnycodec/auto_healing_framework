from __future__ import annotations

from pathlib import Path

from ai.rule_engine import RuleEngine
from healer.detector import FailureDetector
from healer.engine import HealingEngine
from healer.models import FailureCategory

from ._fixtures import make_corrupted_trace, make_settings


def test_detector_extracts_bdd_scenario_and_step(tmp_path: Path) -> None:
    """Scenario, feature and the failing Gherkin step come from the trace."""
    from ._fixtures import make_bdd_trace

    make_settings(tmp_path)
    trace_zip = make_bdd_trace(tmp_path)

    context = FailureDetector().from_trace(trace_zip, tmp_path / "trace-output")

    assert context.feature == "Landing Page — Benefit Selection"
    assert context.scenario == (
        "Starting a Universal Credit application navigates to personal details"
    )
    assert context.step_keyword == "When"
    assert context.step == "I click start now"


def test_detector_falls_back_to_trace_action_log(tmp_path: Path) -> None:
    """When error-context.md is corrupted, the detector must recover the real
    locator + source location from the trace action log."""
    make_settings(tmp_path)
    trace_zip = make_corrupted_trace(tmp_path)

    detector = FailureDetector()
    context = detector.from_trace(trace_zip, tmp_path / "trace-output")

    assert context.classification is not None
    assert context.classification.category == FailureCategory.LOCATOR
    assert context.failed_locator == "getByRole('button', { name: /Start new/i })"
    assert context.test_file is not None
    assert context.test_file.name == "landing.page.ts"
    assert context.line_number == 3


def test_corrupted_trace_still_heals_end_to_end(tmp_path: Path) -> None:
    """The full pipeline should heal even when error-context.md is unusable."""
    settings = make_settings(tmp_path)
    trace_zip = make_corrupted_trace(tmp_path)

    engine = HealingEngine(app_settings=settings, ai_engine=RuleEngine())
    report = engine.heal_trace(trace_zip)

    assert report.status == "healed"
    page_object = settings.playwright_project_root / "tests" / "landing.page.ts"
    assert "/Start now/i" in page_object.read_text(encoding="utf-8")
