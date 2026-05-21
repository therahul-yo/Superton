"""Ingest pipeline tests — file reading, walking, chunking edges."""

from __future__ import annotations

from pathlib import Path

import pytest

from superton.ingest import chunk_text, read_file, walk


def test_chunk_empty_yields_nothing():
    assert list(chunk_text("")) == []
    assert list(chunk_text("   \n  ")) == []


def test_chunk_respects_overlap():
    text = "a" * 2000
    chunks = list(chunk_text(text, size=500, overlap=50))
    assert all(len(c) <= 600 for c in chunks)
    assert len(chunks) >= 3


def test_chunk_prefers_paragraph_breaks():
    text = "abc.\n\n" + ("x" * 400) + "\n\n" + ("y" * 400)
    chunks = list(chunk_text(text, size=300, overlap=20))
    assert len(chunks) >= 2


def test_read_text_file(tmp_path: Path):
    p = tmp_path / "n.txt"
    p.write_text("hello world", encoding="utf-8")
    assert "hello world" in read_file(p)


def test_read_markdown(tmp_path: Path):
    p = tmp_path / "n.md"
    p.write_text("# heading", encoding="utf-8")
    assert "heading" in read_file(p)


def test_read_unknown_suffix_raises(tmp_path: Path):
    p = tmp_path / "n.xyz"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        read_file(p)


def test_walk_single_file(tmp_path: Path):
    p = tmp_path / "f.txt"
    p.write_text("x", encoding="utf-8")
    assert list(walk(p)) == [p]


def test_walk_directory(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b", encoding="utf-8")
    paths = sorted(walk(tmp_path))
    assert len(paths) == 2


def test_walk_skips_vcs_and_build_dirs(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.json").write_text("{}", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    found = list(walk(tmp_path))
    assert len(found) == 1
    assert found[0].name == "keep.txt"
