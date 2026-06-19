from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from config import load_settings
from healer.telemetry import compute_metrics


router = APIRouter(tags=["telemetry"])


@router.get("/metrics")
def metrics() -> dict:
    """Aggregated healing metrics for the dashboard."""
    settings = load_settings()
    return compute_metrics(settings.reports_dir)


@router.get("/metrics/stream")
async def metrics_stream() -> StreamingResponse:
    """Server-Sent Events stream that pushes metrics whenever reports change.

    Lightweight near-real-time monitoring: it polls the reports directory and
    emits a new event only when the report set changes (count or newest file).
    """

    async def event_generator():
        settings = load_settings()
        last_signature: tuple[int, float] | None = None
        while True:
            reports_dir = settings.reports_dir
            signature = _reports_signature(reports_dir)
            if signature != last_signature:
                last_signature = signature
                payload = compute_metrics(reports_dir)
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _reports_signature(reports_dir) -> tuple[int, float]:
    if not reports_dir.exists():
        return (0, 0.0)
    files = list(reports_dir.glob("*.json"))
    latest = max((f.stat().st_mtime for f in files), default=0.0)
    return (len(files), latest)
