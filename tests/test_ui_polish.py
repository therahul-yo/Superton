"""Tests for UI-polish additions: dedup counting, doctor masking, status bar."""

from __future__ import annotations

from pathlib import Path

import pytest

from superton.config import Config
from superton.doctor import _mask_token
from superton.memory import Memory


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return Config.load()


# --- dedup tracking ---------------------------------------------------------


def test_last_insert_was_new_true_on_first_insert(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="hello", source="a.md")
    assert mem.last_insert_was_new is True
    mem.close()


def test_last_insert_was_new_false_on_duplicate(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="hello", source="a.md")
    mem.add(text="hello", source="a.md")
    assert mem.last_insert_was_new is False
    mem.close()


def test_last_insert_was_new_alternates(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="alpha", source="a.md")
    assert mem.last_insert_was_new
    mem.add(text="alpha", source="a.md")  # dup
    assert not mem.last_insert_was_new
    mem.add(text="beta", source="a.md")
    assert mem.last_insert_was_new
    mem.close()


def test_source_health_tracks_semantic_status(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="alpha", source="note:alpha")
    rows = mem.source_health()
    assert rows[0]["source"] == "note:alpha"
    assert rows[0]["path_status"] == "virtual"
    assert rows[0]["pending"] == 0
    mem.close()


def test_source_matches_uses_filename_terms(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="rate limiting", source="/tmp/project-roadmap.md")
    assert mem.source_matches("roadmap") == ["/tmp/project-roadmap.md"]
    mem.close()


def test_ingest_path_returns_deduped_count(cfg: Config, tmp_path: Path):
    from superton.shell import _ingest_path

    note = tmp_path / "n.txt"
    note.write_text("same content for dedup test", encoding="utf-8")
    mem = Memory(cfg)
    files1, drawers1, dedup1 = _ingest_path(mem, note)
    files2, drawers2, dedup2 = _ingest_path(mem, note)
    assert dedup1 == 0
    assert drawers1 == 1
    assert drawers2 == 0
    assert dedup2 == 1
    mem.close()


# --- doctor token masking ---------------------------------------------------


def test_mask_token_long():
    assert _mask_token("hf_abcdefghijklmnop") == "hf_a…mnop"


def test_mask_token_short_is_all_dots():
    out = _mask_token("short")
    assert out == "•" * 5


def test_mask_token_empty():
    assert _mask_token("") == ""


def test_mask_token_exactly_eight_is_all_dots():
    assert _mask_token("12345678") == "•" * 8


# --- shell status backend probe --------------------------------------------


def test_status_backend_caches_pings(cfg: Config):
    from superton.shell import _Status

    class FakeModel:
        def __init__(self) -> None:
            self.calls = 0

        def ping(self) -> bool:
            self.calls += 1
            return True

    mem = Memory(cfg)
    model = FakeModel()
    status = _Status(cfg, mem, model)  # type: ignore[arg-type]
    _ = status.toolbar_html()
    _ = status.toolbar_html()
    _ = status.toolbar_html()
    # Three toolbar refreshes share one ping thanks to the TTL cache.
    assert model.calls == 1
    mem.close()


def test_status_backend_offline_renders_open_circle(cfg: Config):
    from superton.shell import _Status

    class DownModel:
        def ping(self) -> bool:
            return False

    mem = Memory(cfg)
    status = _Status(cfg, mem, DownModel())  # type: ignore[arg-type]
    html = status.toolbar_html()
    assert "offline" in html
    assert "○" in html
    mem.close()


def test_status_backend_online_renders_filled_dot(cfg: Config):
    from superton.shell import _Status

    class UpModel:
        def ping(self) -> bool:
            return True

    mem = Memory(cfg)
    status = _Status(cfg, mem, UpModel())  # type: ignore[arg-type]
    html = status.toolbar_html()
    assert "online" in html
    assert "●" in html
    mem.close()
