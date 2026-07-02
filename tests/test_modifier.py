from __future__ import annotations

from pathlib import Path

from ai.base import LocatorSuggestion
from healer.modifier import TestFileModifier


def _suggestion() -> LocatorSuggestion:
    return LocatorSuggestion(
        old_locator="getByRole('button', { name: /Start new/i })",
        new_locator="getByRole('button', { name: /Start now/i })",
        confidence=0.8,
        reasoning="test",
    )


def test_patch_from_line(tmp_path: Path) -> None:
    source = tmp_path / "landing.page.ts"
    source.write_text(
        "class P {\n"
        "  get b() {\n"
        "    return this.page.getByRole('button', { name: /Start new/i });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    modifier = TestFileModifier()
    patch = modifier.build_patch(
        project_root=tmp_path,
        test_file=source,
        line_number=3,
        suggestion=_suggestion(),
    )
    assert patch is not None
    assert patch.line_number == 3
    modifier.apply(patch)
    assert "/Start now/i" in source.read_text(encoding="utf-8")


def test_patch_by_grep_when_line_unknown(tmp_path: Path) -> None:
    nested = tmp_path / "pages"
    nested.mkdir()
    source = nested / "landing.page.ts"
    source.write_text(
        "return this.page.getByRole('button', { name: /Start new/i });\n",
        encoding="utf-8",
    )
    modifier = TestFileModifier()
    patch = modifier.build_patch(
        project_root=tmp_path,
        test_file=None,
        line_number=None,
        suggestion=_suggestion(),
    )
    assert patch is not None
    assert patch.file_path.endswith("landing.page.ts")
    modifier.apply(patch)
    assert "/Start now/i" in source.read_text(encoding="utf-8")


def test_snapshot_and_restore(tmp_path: Path) -> None:
    source = tmp_path / "x.ts"
    source.write_text("original\n", encoding="utf-8")
    modifier = TestFileModifier()
    snapshot = modifier.snapshot(source)
    source.write_text("changed\n", encoding="utf-8")
    modifier.restore(source, snapshot)
    assert source.read_text(encoding="utf-8") == "original\n"
    # No sidecar backup file is left on disk.
    assert not list(tmp_path.glob("*.backup_*"))
