from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ai.base import LocatorSuggestion

from .models import CodePatch


EXCLUDED_DIRS = {
    "node_modules",
    "dist",
    ".features-gen",
    "playwright-report",
    "test-results",
    ".git",
    ".venv",
    "__pycache__",
}
SOURCE_SUFFIXES = {".ts", ".js", ".mts", ".mjs"}


class TestFileModifier:
    def backup(self, file_path: Path) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = file_path.with_suffix(file_path.suffix + f".backup_{timestamp}")
        shutil.copy2(file_path, backup_path)
        return backup_path

    def restore(self, file_path: Path, backup_path: Path) -> None:
        shutil.copy2(backup_path, file_path)

    def build_patch(
        self,
        *,
        project_root: Path,
        test_file: Path | None,
        line_number: int | None,
        suggestion: LocatorSuggestion,
    ) -> CodePatch | None:
        """Resolve the exact source location of the broken locator.

        Strategy 1: use the line number extracted from the stack trace.
        Strategy 2: grep the project for the full locator expression.
        """
        if test_file and line_number:
            patch = self._patch_from_line(test_file, line_number, suggestion)
            if patch:
                return patch
        return self._patch_by_grep(project_root, suggestion)

    def apply(self, patch: CodePatch) -> None:
        path = Path(patch.file_path)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        index = patch.line_number - 1
        # Preserve the original line ending.
        ending = "\n" if lines[index].endswith("\n") else ""
        lines[index] = patch.patched_line + ending
        path.write_text("".join(lines), encoding="utf-8")

    def _patch_from_line(
        self,
        test_file: Path,
        line_number: int,
        suggestion: LocatorSuggestion,
    ) -> CodePatch | None:
        if not test_file.exists():
            return None
        lines = test_file.read_text(encoding="utf-8").splitlines()
        if line_number < 1 or line_number > len(lines):
            return None

        candidates = (line_number - 1, *range(max(0, line_number - 4), min(len(lines), line_number + 3)))
        for idx in candidates:
            original = lines[idx]
            if suggestion.old_locator and suggestion.old_locator in original:
                patched = original.replace(suggestion.old_locator, suggestion.new_locator, 1)
                if patched != original:
                    return CodePatch(
                        file_path=str(test_file),
                        line_number=idx + 1,
                        original_line=original,
                        patched_line=patched,
                        suggestion=suggestion,
                    )
        return None

    def _patch_by_grep(self, project_root: Path, suggestion: LocatorSuggestion) -> CodePatch | None:
        old = suggestion.old_locator
        if not old or len(old) <= 8 or old.startswith("internal:"):
            return None

        for source_file in self._collect_sources(project_root):
            try:
                lines = source_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for idx, original in enumerate(lines):
                if old in original:
                    patched = original.replace(old, suggestion.new_locator, 1)
                    if patched != original:
                        return CodePatch(
                            file_path=str(source_file),
                            line_number=idx + 1,
                            original_line=original,
                            patched_line=patched,
                            suggestion=suggestion,
                        )
        return None

    def _collect_sources(self, directory: Path):
        if not directory.exists():
            return
        for entry in directory.iterdir():
            if entry.name in EXCLUDED_DIRS:
                continue
            if entry.is_dir():
                yield from self._collect_sources(entry)
            elif entry.is_file() and entry.suffix in SOURCE_SUFFIXES:
                yield entry
