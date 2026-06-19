from __future__ import annotations

import json

from fastapi import APIRouter

from config import settings


router = APIRouter(tags=["reports"])


@router.get("/reports")
def list_reports() -> list[dict]:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    for report_file in sorted(settings.reports_dir.glob("*.json")):
        reports.append(json.loads(report_file.read_text(encoding="utf-8")))
    return reports