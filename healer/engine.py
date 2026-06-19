from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ai import AIEngine, create_ai_engine
from config import Settings, settings

from .analyser import FailureAnalyser
from .classifier import locator_signature
from .detector import FailureDetector
from .git_pr import GitPrManager
from .models import CodePatch, FailureCategory, FailureContext, HealingReport
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
        batch_validate: bool = False,
    ) -> None:
        self.settings = app_settings
        self.dry_run = dry_run
        self.auto_commit = auto_commit
        self.auto_pr = auto_pr
        # batch_validate: apply every patch first, then validate with a SINGLE
        # re-run instead of one re-run per locator. Much faster when many
        # distinct locators are broken; the trade-off is coarser failure
        # attribution (see heal_directory).
        self.batch_validate = batch_validate
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
        prepared: list[tuple[HealingReport, CodePatch]] = []

        # Read every trace's failure context up front. A validation re-run during
        # healing wipes the framework's results dir (Playwright clears
        # test-results on each run), so traces must be extracted before the first
        # re-run. Any trace that has vanished or is corrupt is skipped, not fatal.
        detected: list[tuple[Path, FailureContext]] = []
        for trace_zip in traces:
            try:
                failure = self.detector.from_trace(trace_zip, self.settings.temp_dir)
            except (OSError, zipfile.BadZipFile):
                continue
            detected.append((trace_zip, failure))

        for trace_zip, failure in detected:
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

            if self.batch_validate and not self.dry_run:
                # Defer validation: prepare the patch and apply it, but don't
                # re-run yet — a single re-run validates the whole batch below.
                report, patch = self._prepare(trace_zip, precomputed_failure=failure)
                if signature:
                    seen[signature] = report
                if patch is not None:
                    prepared.append((report, patch))
                    reports.append(report)
                else:
                    reports.append(self._save_report(report))
                continue

            report = self._heal_single(trace_zip, precomputed_failure=failure)
            reports.append(self._save_report(report))
            if signature:
                seen[signature] = report
            if report.patch and report.status == "healed":
                patches.append(report.patch)

        if prepared:
            patches.extend(self._validate_batch(prepared))

        if patches and not self.dry_run and (self.auto_commit or self.auto_pr):
            self._commit(patches, reports)

        return reports

    # ── Core single-trace flow ──────────────────────────────────────────────

    def _prepare(self, trace_zip: Path, *, precomputed_failure=None) -> tuple[HealingReport, CodePatch | None]:
        """Detect, classify, analyse and build a patch — no file writes, no re-run.

        Returns the report plus a ready-to-apply patch (or ``None`` when the
        failure is not healable, the AI returned nothing, or it could not be
        mapped to a source line). Validation is the caller's responsibility.
        """
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
            return report, None

        suggestion = self.analyser.analyse(failure)
        report.suggestion = suggestion
        if not suggestion:
            report.messages.append("AI did not return a locator suggestion")
            return report, None

        patch = self.modifier.build_patch(
            project_root=self.settings.playwright_project_root,
            test_file=failure.test_file,
            line_number=failure.line_number,
            suggestion=suggestion,
        )
        if not patch:
            report.messages.append("Could not map failure to a source code location")
            return report, None

        report.patch = patch
        report.patched_file = patch.file_path

        if self.dry_run:
            report.status = "skipped"
            report.messages.append(
                f"[DRY RUN] Would patch {patch.file_path}:{patch.line_number}"
            )
            return report, None

        return report, patch

    def _heal_single(self, trace_zip: Path, *, precomputed_failure=None) -> HealingReport:
        report, patch = self._prepare(trace_zip, precomputed_failure=precomputed_failure)
        if patch is None:
            return report

        original_content = self.modifier.snapshot(Path(patch.file_path))
        self.modifier.apply(patch)

        rerun = self.rerunner.rerun(
            project_root=self.settings.project_root,
            command=self.settings.test_command,
        )
        report.rerun_output = rerun.output

        if rerun.passed:
            report.status = "healed"
            return report

        self.modifier.restore(Path(patch.file_path), original_content)
        report.status = "restored"
        report.messages.append("Rerun failed; restored original file from backup")
        return report

    def _validate_batch(self, prepared: list[tuple[HealingReport, CodePatch]]) -> list[CodePatch]:
        """Apply all prepared patches, then validate with a SINGLE re-run.

        Fast path for many distinct broken locators: one re-run instead of N.
        Each unique file is snapshotted once (pristine) so multiple patches to
        the same file restore cleanly. If the single re-run fails, every file is
        restored and all reports are marked ``restored`` — re-run without batch
        mode to validate (and salvage) each locator individually.
        """
        snapshots: dict[str, str] = {}
        for _, patch in prepared:
            if patch.file_path not in snapshots:
                snapshots[patch.file_path] = self.modifier.snapshot(Path(patch.file_path))
            self.modifier.apply(patch)

        rerun = self.rerunner.rerun(
            project_root=self.settings.project_root,
            command=self.settings.test_command,
        )

        healed: list[CodePatch] = []
        if rerun.passed:
            for report, patch in prepared:
                report.status = "healed"
                report.rerun_output = rerun.output
                healed.append(patch)
        else:
            for file_path, content in snapshots.items():
                self.modifier.restore(Path(file_path), content)
            for report, _ in prepared:
                report.status = "restored"
                report.rerun_output = rerun.output
                report.messages.append(
                    "Batch validation re-run failed; restored all files. "
                    "Re-run without batch mode to validate each locator individually."
                )

        for report, _ in prepared:
            self._save_report(report)
        return healed

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
