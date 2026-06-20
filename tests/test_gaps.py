from __future__ import annotations

import json
from pathlib import Path

from ai.base import AIEngine, LocatorSuggestion
from ai.ollama_engine import is_generic_locator, is_valid_locator_expression
from ai.rule_engine import RuleEngine
from config import Settings
from healer.classifier import FailureClassifier
from healer.engine import HealingEngine
from healer.git_pr import _clean
from healer.ledger import HealLedger
from healer.models import FailureCategory

from ._fixtures import make_broken_trace, make_settings


class _StubEngine(AIEngine):
    """Returns a fixed locator + confidence so gate behaviour is deterministic."""

    def __init__(self, *, new_locator: str, confidence: float) -> None:
        self.new_locator = new_locator
        self.confidence = confidence

    def suggest_locator(self, *, error_message: str, failed_locator: str, dom_chunk: str) -> LocatorSuggestion:
        return LocatorSuggestion(
            old_locator=failed_locator,
            new_locator=self.new_locator,
            confidence=self.confidence,
            reasoning="stub",
        )


# ── P0-1 confidence gate ──────────────────────────────────────────────────────


def test_low_confidence_suggestion_is_report_only(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    engine = HealingEngine(
        app_settings=settings,
        ai_engine=_StubEngine(new_locator="getByRole('button', { name: /Start now/i })", confidence=0.2),
    )
    report = engine.heal_trace(trace_zip)

    assert report.status == "low_confidence"
    # The file must be untouched — report-only never applies the change.
    page_object = settings.playwright_project_root / "tests" / "landing.page.ts"
    assert "/Start new/i" in page_object.read_text(encoding="utf-8")


def test_high_confidence_suggestion_heals(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    engine = HealingEngine(
        app_settings=settings,
        ai_engine=_StubEngine(new_locator="getByRole('button', { name: /Start now/i })", confidence=0.95),
    )
    report = engine.heal_trace(trace_zip)

    assert report.status == "healed"
    page_object = settings.playwright_project_root / "tests" / "landing.page.ts"
    assert "/Start now/i" in page_object.read_text(encoding="utf-8")


def test_generic_locator_is_penalised_to_report_only(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    # High self-reported confidence, but a too-broad locator -> penalised below gate.
    engine = HealingEngine(
        app_settings=settings,
        ai_engine=_StubEngine(new_locator="getByRole('button')", confidence=0.95),
    )
    report = engine.heal_trace(trace_zip)

    assert report.status == "low_confidence"
    assert any("Generic" in m for m in report.messages)


def test_invalid_locator_expression_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    engine = HealingEngine(
        app_settings=settings,
        ai_engine=_StubEngine(new_locator="just click the start button", confidence=0.95),
    )
    report = engine.heal_trace(trace_zip)

    assert report.status == "failed"
    assert any("invalid locator" in m.lower() for m in report.messages)


# ── P2-8 locator validity / strictness ────────────────────────────────────────


def test_is_valid_locator_expression() -> None:
    assert is_valid_locator_expression("getByRole('button', { name: /Go/i })")
    assert is_valid_locator_expression("locator('#submit')")
    assert not is_valid_locator_expression("await page.getByRole('button')")
    assert not is_valid_locator_expression("getByRole('button'")  # unbalanced
    assert not is_valid_locator_expression("click the button")
    assert not is_valid_locator_expression("getByRole('a'); getByRole('b')")


def test_is_generic_locator() -> None:
    assert is_generic_locator("getByRole('button')")
    assert is_generic_locator("locator('div')")
    assert not is_generic_locator("getByRole('button', { name: /Go/i })")
    assert not is_generic_locator("locator('#submit')")


# ── P0-2 targeted validation command ──────────────────────────────────────────


def _settings_with(root: Path, **kw) -> Settings:
    base = dict(
        project_root=root,
        test_command="npx playwright test --trace on",
    )
    base.update(kw)
    return Settings(**base)


def test_targeted_command_targets_spec_file(tmp_path: Path) -> None:
    settings = _settings_with(tmp_path)
    spec = tmp_path / "tests" / "login.spec.ts"
    cmd = settings.targeted_command([(spec, 42)])
    assert cmd == "npx playwright test --trace on tests/login.spec.ts:42"


def test_targeted_command_falls_back_for_page_object(tmp_path: Path) -> None:
    settings = _settings_with(tmp_path)
    pom = tmp_path / "tests" / "login.page.ts"
    # A page object isn't a runnable spec -> never target it, run the full suite.
    assert settings.targeted_command([(pom, 10)]) == "npx playwright test --trace on"


def test_targeted_command_disabled_returns_full_command(tmp_path: Path) -> None:
    settings = _settings_with(tmp_path, targeted_validation=False)
    spec = tmp_path / "tests" / "login.spec.ts"
    assert settings.targeted_command([(spec, 1)]) == "npx playwright test --trace on"


# ── P1-4 classifier strong vs weak ────────────────────────────────────────────


def test_strong_locator_failure_high_confidence() -> None:
    result = FailureClassifier().classify("Error: locator.click: element not found", "locator('#x')")
    assert result.category == FailureCategory.LOCATOR
    assert result.confidence >= 0.9


def test_weak_visibility_failure_low_confidence() -> None:
    result = FailureClassifier().classify(
        "TimeoutError: element is not visible", "getByRole('button', { name: /Go/i })"
    )
    assert result.category == FailureCategory.LOCATOR
    assert result.confidence <= 0.6  # held as report-only by the gate


# ── P2-9 ledger idempotency ───────────────────────────────────────────────────


def test_ledger_skips_after_max_attempts(tmp_path: Path) -> None:
    ledger = HealLedger(tmp_path, max_attempts=2)
    sig = "getByRole('button', { name: /Go/i })"
    assert not ledger.should_skip(sig)
    ledger.record(sig, "restored")
    assert not ledger.should_skip(sig)  # 1 failure, under the cap
    ledger.record(sig, "restored")
    assert ledger.should_skip(sig)  # 2 failures, at the cap


def test_ledger_success_resets_counter(tmp_path: Path) -> None:
    ledger = HealLedger(tmp_path, max_attempts=1)
    sig = "locator('#submit')"
    ledger.record(sig, "restored")
    assert ledger.should_skip(sig)
    ledger.record(sig, "healed")
    assert not ledger.should_skip(sig)


def test_ledger_persists_and_reloads(tmp_path: Path) -> None:
    sig = "locator('#submit')"
    first = HealLedger(tmp_path, max_attempts=1)
    first.record(sig, "restored")
    first.save()
    reloaded = HealLedger(tmp_path, max_attempts=1)
    assert reloaded.should_skip(sig)


# ── P2-6 report redaction + PR/commit sanitisation ────────────────────────────


def test_saved_report_redacts_dom_chunk_by_default(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    trace_zip = make_broken_trace(tmp_path)

    engine = HealingEngine(app_settings=settings, ai_engine=RuleEngine())
    engine.heal_trace(trace_zip)

    saved = list(settings.reports_dir.rglob("*.json"))
    assert saved
    data = json.loads(saved[0].read_text(encoding="utf-8"))
    assert data["failure"]["dom_chunk"] == ""


def test_clean_flattens_and_strips_backticks() -> None:
    assert _clean("line1\nline2`code`") == "line1 line2 code"
    assert _clean("x" * 500, limit=10) == "x" * 10
