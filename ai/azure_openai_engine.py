from __future__ import annotations

import json
import re

from .base import AIEngine, LocatorSuggestion
from .http import post_json
from .ollama_engine import build_locator_prompt, sanitize_locator


class AzureOpenAIEngine(AIEngine):
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        deployment: str,
        api_version: str,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.deployment = deployment
        self.api_version = api_version

    def suggest_locator(
        self,
        *,
        error_message: str,
        failed_locator: str,
        dom_chunk: str,
    ) -> LocatorSuggestion:
        prompt = build_locator_prompt(error_message, failed_locator, dom_chunk)
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )
        payload = post_json(
            url,
            headers={"api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": "You fix Playwright locators. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_completion_tokens": 4096,
            },
            timeout=120,
        )
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return parse_locator_response(content, failed_locator)


def parse_locator_response(content: str, failed_locator: str) -> LocatorSuggestion:
    data = parse_json_object(content)
    new_locator = data.get("new_locator") or data.get("newLocator")
    if not new_locator:
        raise ValueError(f"Azure OpenAI response did not include new_locator: {content!r}")
    return LocatorSuggestion(
        old_locator=failed_locator,
        new_locator=sanitize_locator(str(new_locator), failed_locator),
        confidence=float(data.get("confidence", 0.5)),
        reasoning=str(data.get("reasoning", "Azure OpenAI locator suggestion")),
    )


def parse_json_object(content: str) -> dict:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if match:
            return json.loads(match.group(0))
        raise