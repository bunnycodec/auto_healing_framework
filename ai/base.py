from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LocatorSuggestion:
    old_locator: str
    new_locator: str
    confidence: float
    reasoning: str


class AIEngine(ABC):
    @abstractmethod
    def suggest_locator(
        self,
        *,
        error_message: str,
        failed_locator: str,
        dom_chunk: str,
    ) -> LocatorSuggestion:
        """Return the best replacement locator for a locator-related failure."""