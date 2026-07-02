from __future__ import annotations

from healer.classifier import FailureClassifier, locator_signature
from healer.models import FailureCategory


def test_locator_failure_is_classified_and_healable() -> None:
    classifier = FailureClassifier()
    result = classifier.classify(
        "TimeoutError: locator.click: Timeout 10000ms exceeded.\n"
        "  - waiting for getByRole('button', { name: /Start now/i })",
        "getByRole('button', { name: /Start now/i })",
    )
    assert result.category == FailureCategory.LOCATOR
    assert result.is_healable
    assert result.confidence >= 0.75


def test_network_failure_is_not_healable() -> None:
    classifier = FailureClassifier()
    result = classifier.classify("Error: net::ERR_CONNECTION_REFUSED at api call", None)
    assert result.category == FailureCategory.NETWORK
    assert not result.is_healable


def test_assertion_failure_is_not_healable() -> None:
    classifier = FailureClassifier()
    result = classifier.classify("expect(received).toEqual(expected) assertion failed", None)
    assert result.category == FailureCategory.ASSERTION
    assert not result.is_healable


def test_unknown_for_empty_error() -> None:
    classifier = FailureClassifier()
    result = classifier.classify("", None)
    assert result.category == FailureCategory.UNKNOWN


def test_locator_signature_strips_ansi() -> None:
    sig = locator_signature("getByRole('button', { name: /Start now/i })\x1b[22m", "")
    assert sig == "getByRole('button', { name: /Start now/i })"
