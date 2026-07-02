"""Cross-run heal ledger — idempotency / loop protection.

Without this, a persistently-wrong locator could be re-analysed and re-PR'd on
every nightly run. The ledger records the outcome per locator *signature* and
lets the engine skip signatures that have already failed ``max_attempts`` times,
so the healer stops banging on a fix it cannot make.

Stored as a small JSON file at the project root (``.healer-ledger.json``).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_FILENAME = ".healer-ledger.json"


class HealLedger:
    def __init__(self, project_root: Path, *, max_attempts: int = 3) -> None:
        self.path = project_root / LEDGER_FILENAME
        self.max_attempts = max_attempts
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def should_skip(self, signature: str | None) -> bool:
        """True when this signature has failed too many times to keep retrying."""
        if not signature:
            return False
        entry = self._data.get(signature)
        if not entry:
            return False
        return (
            entry.get("last_status") in {"restored", "failed"}
            and int(entry.get("attempts", 0)) >= self.max_attempts
        )

    def record(self, signature: str | None, status: str) -> None:
        if not signature:
            return
        entry = self._data.setdefault(signature, {"attempts": 0})
        # A success resets the counter; a failure increments it.
        entry["attempts"] = 0 if status == "healed" else int(entry.get("attempts", 0)) + 1
        entry["last_status"] = status
        entry["last_at"] = datetime.now(timezone.utc).isoformat()

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            pass  # ledger is best-effort; never block healing on a write failure
