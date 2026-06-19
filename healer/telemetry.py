"""Telemetry: aggregate healing reports into dashboard metrics."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HEAL_STATUSES = {"healed", "restored", "skipped", "duplicate", "failed"}


def load_reports(reports_dir: Path) -> list[dict[str, Any]]:
    """Read all report JSON files, newest first."""
    if not reports_dir.exists():
        return []
    reports: list[dict[str, Any]] = []
    for report_file in reports_dir.glob("*.json"):
        try:
            reports.append(json.loads(report_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    reports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return reports


def compute_metrics(reports_dir: Path) -> dict[str, Any]:
    """Aggregate reports into headline metrics for the dashboard."""
    reports = load_reports(reports_dir)
    total = len(reports)

    status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    confidences: list[float] = []
    committed = 0
    prs = 0
    file_counts: Counter[str] = Counter()
    timeline: dict[str, Counter[str]] = defaultdict(Counter)

    for report in reports:
        status = report.get("status", "unknown")
        status_counts[status] += 1
        category_counts[report.get("category", "unknown")] += 1

        if report.get("status") == "healed":
            suggestion = report.get("suggestion") or {}
            if isinstance(suggestion, dict) and suggestion.get("confidence") is not None:
                confidences.append(float(suggestion["confidence"]))
            if report.get("patched_file"):
                file_counts[Path(str(report["patched_file"])).name] += 1

        if report.get("committed"):
            committed += 1
        if report.get("pr_url"):
            prs += 1

        day = str(report.get("created_at", ""))[:10] or "unknown"
        timeline[day][status] += 1

    healed = status_counts.get("healed", 0)
    failed = status_counts.get("failed", 0) + status_counts.get("restored", 0)
    # Heal rate = healed / (genuine locator attempts) = healed / (healed + failed)
    attempts = healed + failed
    heal_rate = round(healed / attempts, 3) if attempts else 0.0
    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

    return {
        "total_reports": total,
        "healed": healed,
        "failed": failed,
        "skipped": status_counts.get("skipped", 0),
        "duplicate": status_counts.get("duplicate", 0),
        "heal_rate": heal_rate,
        "avg_confidence": avg_confidence,
        "committed": committed,
        "prs_opened": prs,
        "status_breakdown": dict(status_counts),
        "category_breakdown": dict(category_counts),
        "top_files": file_counts.most_common(5),
        "timeline": {
            day: dict(counts) for day, counts in sorted(timeline.items())
        },
        "recent": [_summarize(r) for r in reports[:15]],
    }


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    suggestion = report.get("suggestion") or {}
    return {
        "created_at": report.get("created_at", ""),
        "test_name": report.get("test_name", ""),
        "status": report.get("status", ""),
        "category": report.get("category", ""),
        "old_locator": suggestion.get("old_locator") if isinstance(suggestion, dict) else None,
        "new_locator": suggestion.get("new_locator") if isinstance(suggestion, dict) else None,
        "confidence": suggestion.get("confidence") if isinstance(suggestion, dict) else None,
        "patched_file": report.get("patched_file"),
        "pr_url": report.get("pr_url"),
    }
