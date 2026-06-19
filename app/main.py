from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.routes.report import router as report_router
from app.routes.runner import router as runner_router


app = FastAPI(title="AI Auto-Healing Framework")
app.include_router(runner_router)
app.include_router(report_router)

_TEMPLATE = Path(__file__).resolve().parent / "templates" / "dashboard.html"


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    if _TEMPLATE.exists():
        return _TEMPLATE.read_text(encoding="utf-8")
    return "<h1>AI Auto-Healing Framework</h1>"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}