from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from healer import HealingEngine, HealingOrchestrator


router = APIRouter(tags=["runner"])


class RunRequest(BaseModel):
    trace_zip: str
    dry_run: bool = False
    auto_commit: bool = False
    auto_pr: bool = False


class HealDirectoryRequest(BaseModel):
    trace_dir: str
    dry_run: bool = False
    auto_commit: bool = False
    auto_pr: bool = False


class OrchestrateRequest(BaseModel):
    dry_run: bool = False
    auto_commit: bool = False
    auto_pr: bool = False


@router.post("/run")
def run_healer(request: RunRequest) -> dict:
    trace_zip = Path(request.trace_zip).resolve()
    if not trace_zip.exists():
        raise HTTPException(status_code=404, detail=f"Trace zip not found: {trace_zip}")
    engine = HealingEngine(
        dry_run=request.dry_run,
        auto_commit=request.auto_commit,
        auto_pr=request.auto_pr,
    )
    report = engine.heal_trace(trace_zip)
    return {
        "status": report.status,
        "trace_zip": report.trace_zip,
        "test_name": report.test_name,
        "category": report.category,
        "messages": report.messages,
        "suggestion": asdict(report.suggestion) if report.suggestion else None,
        "patched_file": report.patched_file,
    }


@router.post("/heal-directory")
def heal_directory(request: HealDirectoryRequest) -> dict:
    trace_dir = Path(request.trace_dir).resolve()
    if not trace_dir.exists():
        raise HTTPException(status_code=404, detail=f"Trace directory not found: {trace_dir}")
    engine = HealingEngine(
        dry_run=request.dry_run,
        auto_commit=request.auto_commit,
        auto_pr=request.auto_pr,
    )
    reports = engine.heal_directory(trace_dir)
    return {
        "total": len(reports),
        "healed": sum(1 for r in reports if r.status == "healed"),
        "duplicate": sum(1 for r in reports if r.status == "duplicate"),
        "skipped": sum(1 for r in reports if r.status == "skipped"),
        "reports": [
            {
                "status": r.status,
                "test_name": r.test_name,
                "category": r.category,
                "patched_file": r.patched_file,
            }
            for r in reports
        ],
    }


@router.post("/orchestrate")
def orchestrate(request: OrchestrateRequest) -> dict:
    orchestrator = HealingOrchestrator(
        dry_run=request.dry_run,
        auto_commit=request.auto_commit,
        auto_pr=request.auto_pr,
    )
    result = orchestrator.run()
    return {
        "tests_passed": result.tests_passed,
        "traces_found": result.traces_found,
        "healed": sum(1 for r in result.reports if r.status == "healed"),
        "reports": [
            {"status": r.status, "test_name": r.test_name, "patched_file": r.patched_file}
            for r in result.reports
        ],
    }