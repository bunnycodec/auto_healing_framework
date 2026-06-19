from __future__ import annotations

import json
from pathlib import Path

from healer.telemetry import compute_metrics, load_reports


def _write_report(reports_dir: Path, name: str, data: dict) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_empty_metrics(tmp_path: Path) -> None:
    metrics = compute_metrics(tmp_path / "reports")
    assert metrics["total_reports"] == 0
    assert metrics["heal_rate"] == 0.0
    assert metrics["recent"] == []


def test_metrics_aggregation(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write_report(reports, "a", {
        "status": "healed", "category": "locator", "test_name": "t1",
        "created_at": "2026-06-19T10:00:00+00:00", "patched_file": "pages/login.ts",
        "suggestion": {"old_locator": "x", "new_locator": "y", "confidence": 0.9},
        "committed": True, "pr_url": "http://pr/1",
    })
    _write_report(reports, "b", {
        "status": "healed", "category": "locator", "test_name": "t2",
        "created_at": "2026-06-19T11:00:00+00:00", "patched_file": "pages/login.ts",
        "suggestion": {"old_locator": "x", "new_locator": "z", "confidence": 0.8},
    })
    _write_report(reports, "c", {
        "status": "restored", "category": "locator", "test_name": "t3",
        "created_at": "2026-06-19T12:00:00+00:00",
        "suggestion": {"old_locator": "x", "new_locator": "bad", "confidence": 0.4},
    })
    _write_report(reports, "d", {
        "status": "skipped", "category": "network", "test_name": "t4",
        "created_at": "2026-06-19T13:00:00+00:00",
    })

    m = compute_metrics(reports)

    # Skipped reports are ignored — metrics focus on genuine healing outcomes.
    assert m["total_reports"] == 3
    assert m["healed"] == 2
    assert m["failed"] == 1          # the 'restored'
    assert "skipped" not in m
    assert m["heal_rate"] == round(2 / 3, 3)
    assert m["avg_confidence"] == round((0.9 + 0.8) / 2, 3)
    assert m["committed"] == 1
    assert m["prs_opened"] == 1
    assert m["category_breakdown"]["locator"] == 3
    assert ("login.ts", 2) in m["top_files"]
    # recent is newest-first, skipped excluded — so 'restored' t3 leads
    assert m["recent"][0]["test_name"] == "t3"


def test_load_reports_sorted_newest_first(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write_report(reports, "old", {"status": "healed", "created_at": "2026-06-18T00:00:00+00:00"})
    _write_report(reports, "new", {"status": "healed", "created_at": "2026-06-19T00:00:00+00:00"})
    loaded = load_reports(reports)
    assert loaded[0]["created_at"] > loaded[1]["created_at"]


def test_reports_grouped_per_run(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    # Two separate run folders, each kept independently.
    _write_report(reports / "20260619-100000-000001", "trace-a", {
        "status": "healed", "category": "locator", "test_name": "t1",
        "created_at": "2026-06-19T10:00:00+00:00",
        "suggestion": {"old_locator": "x", "new_locator": "y", "confidence": 0.9},
    })
    _write_report(reports / "20260619-110000-000002", "trace-a", {
        "status": "healed", "category": "locator", "test_name": "t1",
        "created_at": "2026-06-19T11:00:00+00:00",
        "suggestion": {"old_locator": "x", "new_locator": "y", "confidence": 0.8},
    })
    _write_report(reports / "20260619-110000-000002", "trace-b", {
        "status": "failed", "category": "locator", "test_name": "t2",
        "created_at": "2026-06-19T11:00:01+00:00",
    })

    m = compute_metrics(reports)

    assert m["total_runs"] == 2
    # Newest run first; it has 1 healed + 1 failed.
    latest = m["runs"][0]
    assert latest["run_id"] == "20260619-110000-000002"
    assert latest["healed"] == 1
    assert latest["failed"] == 1
    assert latest["total"] == 2
