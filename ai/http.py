"""Small HTTP helper with bounded retry + exponential backoff.

LLM endpoints (Ollama / Azure OpenAI / Kilo) occasionally return transient
errors (network blips, 429 rate limits, 5xx). A single failure should not abort
a whole directory heal, so requests are retried a few times with backoff. Client
errors (4xx other than 408/429) are not retried — they will never succeed.
"""
from __future__ import annotations

import time
from typing import Any

import requests


def post_json(
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 120,
    retries: int = 3,
    backoff: float = 1.0,
) -> dict[str, Any]:
    """POST ``json`` and return the decoded JSON body, retrying transient errors."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.post(url, json=json, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, "status_code", None)
            # Don't retry deterministic client errors (bad key, bad request, ...).
            if status is not None and 400 <= status < 500 and status not in (408, 429):
                raise
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    assert last_exc is not None  # loop always sets it before falling through
    raise last_exc
