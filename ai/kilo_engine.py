from __future__ import annotations

from .base import AIEngine, LocatorSuggestion
from .http import post_json
from .ollama_engine import build_locator_prompt, parse_locator_response


class KiloEngine(AIEngine):
    def __init__(self, *, api_key: str, model: str, url: str) -> None:
        self.api_key = api_key
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
        payload = post_json(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return parse_locator_response(content, failed_locator)