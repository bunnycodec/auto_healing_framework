from __future__ import annotations

from ai.base import AIEngine, LocatorSuggestion

from .models import FailureContext


class FailureAnalyser:
    def __init__(self, ai_engine: AIEngine) -> None:
        self.ai_engine = ai_engine

    def analyse(self, failure: FailureContext) -> LocatorSuggestion | None:
        if not failure.failed_locator:
            return None
        return self.ai_engine.suggest_locator(
            error_message=failure.error_message,
            failed_locator=failure.failed_locator,
            dom_chunk=failure.dom_chunk,
        )