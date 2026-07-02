from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from ai.base import LocatorSuggestion


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FailureCategory(str, Enum):
    """Root-cause category of a test failure."""

    LOCATOR = "locator"
    TIMEOUT = "timeout"
    NETWORK = "network"
    ASSERTION = "assertion"
    ENVIRONMENT = "environment"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureClassification:
    category: FailureCategory
    confidence: float
    reason: str

    @property
    def is_healable(self) -> bool:
        return self.category == FailureCategory.LOCATOR


@dataclass
class FailureContext:
    trace_zip: Path
    test_file: Path | None
    line_number: int | None
    failed_locator: str | None
    error_message: str
    dom_chunk: str = ""
    test_name: str = ""
    classification: FailureClassification | None = None
    # BDD context recovered from the Playwright trace (empty for non-BDD suites).
    feature: str = ""
    scenario: str = ""
    step: str = ""
    step_keyword: str = ""


@dataclass
class CodePatch:
    file_path: str
    line_number: int
    original_line: str
    patched_line: str
    suggestion: LocatorSuggestion


@dataclass
class HealingReport:
    trace_zip: str
    status: str  # healed | restored | low_confidence | skipped | duplicate | failed
    test_name: str = ""
    category: str = FailureCategory.UNKNOWN.value
    confidence: float = 0.0
    failure: FailureContext | None = None
    suggestion: LocatorSuggestion | None = None
    patch: CodePatch | None = None
    patched_file: str | None = None
    rerun_output: str = ""
    committed: bool = False
    pr_url: str | None = None
    messages: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)