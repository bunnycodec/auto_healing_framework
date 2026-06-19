from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import Settings, settings

from .engine import HealingEngine
from .models import HealingReport


@dataclass
class OrchestrationResult:
    tests_passed: bool
    traces_found: int
    reports: list[HealingReport]


class HealingOrchestrator:
    """Runs the test suite, collects fresh traces, and heals failures.

    Mirrors the TypeScript `run-and-heal` flow: always clears stale results
    first so only fresh traces are analysed (no caching).
    """

    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        dry_run: bool = False,
        auto_commit: bool = False,
        auto_pr: bool = False,
        batch_validate: bool = False,
    ) -> None:
        self.settings = app_settings
        self.dry_run = dry_run
        self.auto_commit = auto_commit
        self.auto_pr = auto_pr
        self.batch_validate = batch_validate

    def run(self) -> OrchestrationResult:
        results_dir = self.settings.results_dir
        self._clear(results_dir)

        passed = self._run_tests()
        if passed:
            return OrchestrationResult(tests_passed=True, traces_found=0, reports=[])

        traces = sorted(results_dir.rglob("trace.zip")) if results_dir.exists() else []
        if not traces:
            return OrchestrationResult(tests_passed=False, traces_found=0, reports=[])

        engine = HealingEngine(
            app_settings=self.settings,
            dry_run=self.dry_run,
            auto_commit=self.auto_commit,
            auto_pr=self.auto_pr,
            batch_validate=self.batch_validate,
        )
        reports = engine.heal_directory(results_dir)
        return OrchestrationResult(tests_passed=False, traces_found=len(traces), reports=reports)

    def _run_tests(self) -> bool:
        completed = subprocess.run(
            self.settings.test_command,
            cwd=self.settings.project_root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return completed.returncode == 0

    @staticmethod
    def _clear(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
