from __future__ import annotations

import re

from .models import FailureCategory, FailureClassification


# Patterns that strongly indicate a locator / element-resolution failure.
LOCATOR_PATTERNS = (
    "waiting for selector",
    "waiting for locator",
    "no element matches selector",
    "element not found",
    "locator resolved to",
    "strict mode violation",
    "element is not visible",
    "element is not enabled",
    "element is not stable",
    "element is outside of the viewport",
    "frame was detached",
    "element is detached",
    "selector resolved to hidden",
    "error: locator",
    "timeouterror: locator",
    "locator.click",
    "locator.fill",
    "locator.waitfor",
    "waiting for get",
    "element does not have",
)

NETWORK_PATTERNS = (
    "net::err",
    "network error",
    "econnrefused",
    "enotfound",
    "socket hang up",
    "request failed",
    "fetch failed",
)

ASSERTION_PATTERNS = (
    "expect(",
    "to equal",
    "to be visible",
    "to have text",
    "tobe(",
    "toequal(",
    "assertion",
    "expected",
)

ENVIRONMENT_PATTERNS = (
    "browser has been closed",
    "target page, context or browser has been closed",
    "page crashed",
    "browser closed",
    "session closed",
)


class FailureClassifier:
    """Classifies the root cause of a Playwright failure from its error text."""

    def classify(self, error_message: str, failed_locator: str | None) -> FailureClassification:
        error = (error_message or "").lower()

        if not error:
            return FailureClassification(
                category=FailureCategory.UNKNOWN,
                confidence=0.3,
                reason="No error message available in trace data",
            )

        if self._matches(error, LOCATOR_PATTERNS):
            return FailureClassification(
                category=FailureCategory.LOCATOR,
                confidence=0.95,
                reason=f"Locator failure detected for selector: {failed_locator or 'unknown'}",
            )

        has_selector_timeout = bool(failed_locator) and (
            "timeout" in error or "timed out" in error
        ) and "navigation" not in error
        if has_selector_timeout:
            return FailureClassification(
                category=FailureCategory.LOCATOR,
                confidence=0.75,
                reason=f"Selector timeout suggests a locator failure: {failed_locator}",
            )

        if self._matches(error, NETWORK_PATTERNS):
            return FailureClassification(
                category=FailureCategory.NETWORK,
                confidence=0.85,
                reason="Network-related failure",
            )

        if self._matches(error, ENVIRONMENT_PATTERNS):
            return FailureClassification(
                category=FailureCategory.ENVIRONMENT,
                confidence=0.8,
                reason="Browser/page environment failure",
            )

        if self._matches(error, ASSERTION_PATTERNS):
            return FailureClassification(
                category=FailureCategory.ASSERTION,
                confidence=0.7,
                reason="Assertion / expectation mismatch",
            )

        if "timeout" in error or "timed out" in error:
            return FailureClassification(
                category=FailureCategory.TIMEOUT,
                confidence=0.6,
                reason="Generic timeout not tied to a locator",
            )

        return FailureClassification(
            category=FailureCategory.UNKNOWN,
            confidence=0.2,
            reason="Unclassified failure",
        )

    @staticmethod
    def _matches(error: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern in error for pattern in patterns)


def locator_signature(failed_locator: str | None, error_message: str) -> str | None:
    """Build a stable dedup key for a locator failure.

    Multiple tests failing on the same broken locator share a signature, so the
    engine only needs to analyse and patch one representative trace.
    """
    if failed_locator:
        return _strip_ansi(failed_locator).strip()

    match = re.search(r"waiting for (.+?)(?:\n|$)", _strip_ansi(error_message))
    if match:
        return match.group(1).strip()
    return None


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", value)
