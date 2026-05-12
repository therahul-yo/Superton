"""Smoke tests — make sure imports work and the basic store roundtrips."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from superton.config import Config
from superton.ingest import chunk_text
from superton.memory import Memory


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    os.environ["SUPERTON_HOME"] = str(tmp_path)
    return Config.load()


def test_imports():
    import superton  # noqa: F401
    from superton import blackhole, cli, ingest, memory, model  # noqa: F401


def test_chunk_short_text():
    chunks = list(chunk_text("hello world"))
    assert chunks == ["hello world"]


def test_chunk_long_text():
    text = ("para one. " * 200) + "\n\n" + ("para two. " * 200)
    chunks = list(chunk_text(text, size=500, overlap=50))
    assert len(chunks) > 1
    assert all(len(c) <= 600 for c in chunks)


def test_memory_add_and_search(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="rate limiting via token bucket", source="notes.md")
    mem.add(text="auth uses jwt with refresh", source="notes.md")
    hits = mem.search("rate")
    assert len(hits) == 1
    assert "token bucket" in hits[0].drawer.text
    mem.close()


def test_memory_dedup(cfg: Config):
    mem = Memory(cfg)
    d1 = mem.add(text="same content", source="a.md")
    d2 = mem.add(text="same content", source="a.md")
    assert d1.id == d2.id
    assert mem.stats()["drawers"] == 1
    mem.close()


def test_memory_forget(cfg: Config):
    mem = Memory(cfg)
    d = mem.add(text="ephemeral note", source="x.md")
    assert mem.forget(d.id) is True
    assert mem.forget(d.id) is False
    mem.close()


def test_blackhole_renders():
    from superton.blackhole import render_frame, static_frame
    frame = render_frame(0.0)
    assert len(str(frame)) > 100
    assert static_frame() is not None
