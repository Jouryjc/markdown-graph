"""Unit tests for the safe markdown archive extractor.

Offline + deterministic: crafted in-memory zips via stdlib zipfile, no network,
no real models.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from webapp.backend.archive import extract_markdown_archive


def _make_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_mixed_case_md_suffix_normalized_to_lowercase(tmp_path):
    """`.MD` / `.Markdown` are written as lowercase `.md` so the engine's
    case-sensitive `*.md` glob discovers every counted file (regression: an
    uppercase `FOO.MD` was counted but never indexed on case-sensitive FSes)."""
    archive = tmp_path / "bundle.zip"
    _make_zip(
        archive,
        {
            "docs/Upper.MD": b"# upper",
            "docs/Mixed.Markdown": b"# mixed",
            "docs/lower.md": b"# lower",
            "docs/notes.txt": b"ignored non-markdown",
        },
    )
    dest = tmp_path / "out"
    dest.mkdir()

    count = extract_markdown_archive(archive, dest)

    written = sorted(
        p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()
    )
    assert count == 3
    assert written == ["docs/Mixed.md", "docs/Upper.md", "docs/lower.md"]
    # Every written markdown file ends in lowercase .md (engine-discoverable).
    assert all(p.suffix == ".md" for p in dest.rglob("*") if p.is_file())


def test_non_markdown_files_are_skipped(tmp_path):
    archive = tmp_path / "bundle.zip"
    _make_zip(archive, {"a.md": b"# a", "b.png": b"\x89PNG", "c.json": b"{}"})
    dest = tmp_path / "out"
    dest.mkdir()

    count = extract_markdown_archive(archive, dest)

    assert count == 1
    assert [p.name for p in dest.rglob("*") if p.is_file()] == ["a.md"]
