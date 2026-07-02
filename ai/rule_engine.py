from __future__ import annotations

import re

from .base import AIEngine, LocatorSuggestion


class RuleEngine(AIEngine):
    """Deterministic local engine used for smoke tests and offline demos.

    This is intentionally conservative: it only proposes a replacement when it
    can infer an accessible name from the DOM chunk.
    """

    def suggest_locator(
        self,
        *,
        error_message: str,
        failed_locator: str,
        dom_chunk: str,
    ) -> LocatorSuggestion:
        role = extract_role(failed_locator) or "button"
        name = extract_button_name(dom_chunk) or extract_name_from_locator(failed_locator)
        if not name:
            raise ValueError("RuleEngine could not infer a replacement locator")

        return LocatorSuggestion(
            old_locator=failed_locator,
            new_locator=f"getByRole('{role}', {{ name: /{escape_js_regex(name)}/i }})",
            confidence=0.8,
            reasoning="Inferred replacement from the pruned DOM chunk",
        )


def extract_role(locator: str) -> str | None:
    match = re.search(r"getByRole\(['\"]([^'\"]+)", locator)
    return match.group(1) if match else None


def extract_name_from_locator(locator: str) -> str | None:
    match = re.search(r"name:\s*/([^/]+)/", locator)
    if match:
        return match.group(1)
    match = re.search(r"name:\s*['\"]([^'\"]+)['\"]", locator)
    return match.group(1) if match else None


def extract_button_name(dom_chunk: str) -> str | None:
    match = re.search(r"<button[^>]*>(.*?)</button>", dom_chunk, re.I | re.S)
    if not match:
        match = re.search(r"role=['\"]button['\"][^>]*aria-label=['\"]([^'\"]+)['\"]", dom_chunk, re.I)
        return clean_text(match.group(1)) if match else None
    return clean_text(re.sub(r"<[^>]+>", "", match.group(1)))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def escape_js_regex(value: str) -> str:
    escaped = re.escape(value)
    return escaped.replace(r"\ ", " ")