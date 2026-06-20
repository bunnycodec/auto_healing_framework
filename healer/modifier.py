from __future__ import annotations

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
    def snapshot(self, file_path: Path) -> str:
        """Capture a file's current content in memory for rollback.

        Used as the pre-patch safety net during validation: if the re-run
        fails, ``restore`` rewrites this content. No sidecar backup file is
        written — git is the durable audit trail once a PR is raised.
        """
        return file_path.read_text(encoding="utf-8")

    def restore(self, file_path: Path, content: str) -> None:
        file_path.write_text(content, encoding="utf-8")

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
        Strategy 2: search the *same* failing file for the locator expression.
        Strategy 3 (last resort): grep the project, only when no failing file is
        known. Scoping to the failing file first avoids patching an identical
        locator string that legitimately lives in a different test.
        """
        if test_file and line_number:
            patch = self._patch_from_line(test_file, line_number, suggestion)
            if patch:
                return patch
        if test_file and test_file.exists():
            patch = self._patch_in_file(test_file, suggestion)
            if patch:
                return patch
            return None
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
            patch = self._patch_in_file(source_file, suggestion)
            if patch:
                return patch
        return None

    def _patch_in_file(self, source_file: Path, suggestion: LocatorSuggestion) -> CodePatch | None:
        """Replace the first occurrence of the broken locator within one file."""
        old = suggestion.old_locator
        if not old or len(old) <= 8 or old.startswith("internal:"):
            return None
        try:
            lines = source_file.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return None
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
