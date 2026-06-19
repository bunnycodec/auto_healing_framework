from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ai import AIEngine, create_ai_engine
from config import Settings, settings

from .analyser import FailureAnalyser
from .classifier import locator_signature
from .detector import FailureDetector
from .git_pr import GitPrManager
from .models import CodePatch, FailureCategory, HealingReport
from .modifier import TestFileModifier
from .rerunner import TestRerunner


def _new_run_id() -> str:
    """A unique id for one healing run, used to keep reports per run."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


class HealingEngine:
    def __init__(
        self,
        *,
        app_settings: Settings = settings,
        ai_engine: AIEngine | None = None,
        dry_run: bool = False,
        auto_commit: bool = False,
        auto_pr: bool = False,
    ) -> None:
        self.settings = app_settings
        self.dry_run = dry_run
        self.auto_commit = auto_commit
        self.auto_pr = auto_pr
        self.run_id = _new_run_id()
        ai_engine = ai_engine or create_ai_engine()
        self.detector = FailureDetector()
        self.analyser = FailureAnalyser(ai_engine)
        self.modifier = TestFileModifier()
        self.rerunner = TestRerunner()

    # ── Public API ──────────────────────────────────────────────────────────

    def heal_trace(self, trace_zip: Path) -> HealingReport:
        report = self._heal_single(trace_zip)
        return self._save_report(report)

    def heal_directory(self, trace_dir: Path) -> list[HealingReport]:
        """Heal every trace.zip under a directory, de-duplicating by locator."""
        traces = self._find_traces(trace_dir)
        reports: list[HealingReport] = []
        seen: dict[str, HealingReport] = {}
        patches: list[CodePatch] = []

        for trace_zip in traces:
            failure = self.detector.from_trace(trace_zip, self.settings.temp_dir)
            classification = failure.classification
            signature = (
                locator_signature(failure.failed_locator, failure.error_message)
                if classification and classification.is_healable
                else None
            )

            if signature and signature in seen:
                rep = seen[signature]
                duplicate = HealingReport(
                    trace_zip=str(trace_zip),
                    status="duplicate" if rep.status == "healed" else "failed",
                    test_name=failure.test_name,
                    category=FailureCategory.LOCATOR.value,
                    confidence=classification.confidence if classification else 0.0,
                    failure=failure,
                    messages=[f"Duplicate locator already handled by '{rep.test_name}'"],
                )
                reports.append(self._save_report(duplicate))
                continue

            report = self._heal_single(trace_zip, precomputed_failure=failure)
            reports.append(self._save_report(report))
            if signature:
                seen[signature] = report
            if report.patch and report.status == "healed":
                patches.append(report.patch)

        if patches and not self.dry_run and (self.auto_commit or self.auto_pr):
            self._commit(patches, reports)

        return reports

    # ── Core single-trace flow ──────────────────────────────────────────────

    def _heal_single(self, trace_zip: Path, *, precomputed_failure=None) -> HealingReport:
        failure = precomputed_failure or self.detector.from_trace(trace_zip, self.settings.temp_dir)
        classification = failure.classification
        report = HealingReport(
            trace_zip=str(trace_zip),
            status="failed",
            test_name=failure.test_name,
            category=classification.category.value if classification else FailureCategory.UNKNOWN.value,
            confidence=classification.confidence if classification else 0.0,
            failure=failure,
        )

        if not classification or not classification.is_healable:
            report.status = "skipped"
            report.messages.append(
                f"Skipping non-locator failure: {classification.reason if classification else 'unknown'}"
            )
            return report

        suggestion = self.analyser.analyse(failure)
        report.suggestion = suggestion
        if not suggestion:
            report.messages.append("AI did not return a locator suggestion")
            return report

        patch = self.modifier.build_patch(
            project_root=self.settings.playwright_project_root,
            test_file=failure.test_file,
            line_number=failure.line_number,
            suggestion=suggestion,
        )
        if not patch:
            report.messages.append("Could not map failure to a source code location")
            return report

        report.patch = patch
        report.patched_file = patch.file_path

        if self.dry_run:
            report.status = "skipped"
            report.messages.append(
                f"[DRY RUN] Would patch {patch.file_path}:{patch.line_number}"
            )
            return report

        backup_path = self.modifier.backup(Path(patch.file_path))
        self.modifier.apply(patch)

        rerun = self.rerunner.rerun(
            project_root=self.settings.project_root,
            command=self.settings.test_command,
        )
        report.rerun_output = rerun.output

        if rerun.passed:
            report.status = "healed"
            return report

        self.modifier.restore(Path(patch.file_path), backup_path)
        report.status = "restored"
        report.messages.append("Rerun failed; restored original file from backup")
        return report

    # ── Git/PR ──────────────────────────────────────────────────────────────

    def _commit(self, patches: list[CodePatch], reports: list[HealingReport]) -> None:
        manager = GitPrManager(self.settings.project_root)
        if self.auto_pr:
            result = manager.commit_and_pr(patches)
            for report in reports:
                if report.patch in patches:
                    report.committed = True
                    report.pr_url = result.url
        else:
            manager.commit_only(patches)
            for report in reports:
                if report.patch in patches:
                    report.committed = True

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _find_traces(self, trace_dir: Path) -> list[Path]:
        if trace_dir.is_file() and trace_dir.name.endswith(".zip"):
            return [trace_dir]
        return sorted(trace_dir.rglob("trace.zip"))

    def _save_report(self, report: HealingReport) -> HealingReport:
        # Focus on healed/failed outcomes — skipped (non-locator / passing)
        # traces are noise and are intentionally not persisted.
        if report.status == "skipped":
            return report
        run_dir = self.settings.reports_dir / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(report.trace_zip).parent.name or Path(report.trace_zip).stem
        report_path = run_dir / f"{stem}.json"
        report_path.write_text(json.dumps(asdict(report), indent=2, default=str), encoding="utf-8")
        return report
