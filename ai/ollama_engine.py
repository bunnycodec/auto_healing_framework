from __future__ import annotations

import json
import re

import requests

from .base import AIEngine, LocatorSuggestion


class OllamaEngine(AIEngine):
    def __init__(self, *, model: str, url: str) -> None:
        self.model = model
        self.url = url

    def suggest_locator(
        self,
        *,
        error_message: str,
        failed_locator: str,
        dom_chunk: str,
    ) -> LocatorSuggestion:
        prompt = build_locator_prompt(error_message, failed_locator, dom_chunk)
        response = requests.post(
            self.url,
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        content = response.json().get("response", "")
        return parse_locator_response(content, failed_locator)


def build_locator_prompt(error_message: str, failed_locator: str, dom_chunk: str) -> str:
    return f"""
You are fixing a Playwright locator failure. Return only JSON.

Failed locator:
{failed_locator}

Error message:
{error_message}

Relevant DOM chunk:
{dom_chunk}

Rules for "new_locator":
- It MUST be a single Playwright locator expression ONLY.
- Examples: getByRole('button', {{ name: /Start now/i }}) or getByTestId('submit') or locator('#submit').
- Do NOT include "await", "this.page.", variable assignments, comments, code blocks, or explanations.
- Keep it on a single line with no newlines.

Respond with ONLY valid JSON, no markdown fences:
{{"new_locator":"<single locator expression>", "confidence":0.0, "reasoning":"<short explanation>"}}
""".strip()


def sanitize_locator(raw: str, old_locator: str) -> str:
    """Extract a single clean Playwright locator expression from a model answer.

    Models sometimes wrap the locator in code, comments, or prose. This pulls
    out the first valid locator-builder expression and strips noise.
    """
    text = raw.strip()
    # Strip code fences if present.
    text = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "").strip()

    # Prefer a getByRole/getByTestId/getByText/getByLabel/locator(...) call.
    builders = r"(getBy[A-Za-z]+|locator)"
    match = re.search(rf"{builders}\([^\n]*", text)
    if match:
        candidate = match.group(0).strip().rstrip(";").strip()
        candidate = _balance_parens(candidate)
        # Drop a leading "page." / "this.page." if the model added it.
        candidate = re.sub(r"^(?:this\.)?page\.", "", candidate)
        return candidate

    # Fall back to first non-empty single line.
    for line in text.splitlines():
        line = line.strip().rstrip(";").strip()
        if line:
            return line
    return old_locator


def _balance_parens(expr: str) -> str:
    """Trim the expression to the point where parentheses are balanced."""
    depth = 0
    for index, char in enumerate(expr):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return expr[: index + 1]
    return expr


def parse_locator_response(content: str, failed_locator: str) -> LocatorSuggestion:
    cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(cleaned)
    return LocatorSuggestion(
        old_locator=failed_locator,
        new_locator=sanitize_locator(str(data["new_locator"]), failed_locator),
        confidence=float(data.get("confidence", 0.5)),
        reasoning=str(data.get("reasoning", "AI-generated locator suggestion")),
    )