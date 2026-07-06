"""Tests for `superton open` and `superton recall`."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from superton.cli import app
from superton.config import Config
from superton.memory import Memory


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("SUPERTON_HOME", str(home))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return home


def _seed_note(text: str) -> str:
    """Capture a note and return its full drawer id."""
    CliRunner().invoke(app, ["note", text])
    listed = CliRunner().invoke(app, ["list", "--json"])
    rows = json.loads(listed.stdout)
    for row in rows:
        if text in row["text"]:
            return str(row["id"])
    raise AssertionError("seeded note not found")


# --- memory helpers ---------------------------------------------------------


def test_find_by_prefix_resolves_short_ids(env: Path):
    mem = Memory(Config.load())
    drawer = mem.add(text="prefix lookup body", source="/x/a.md")
    assert [d.id for d in mem.find_by_prefix(drawer.id)] == [drawer.id]
    assert [d.id for d in mem.find_by_prefix(drawer.id[:8])] == [drawer.id]
    assert mem.find_by_prefix("") == []
    assert mem.find_by_prefix("zzzzzzzz") == []
    mem.close()


def test_random_drawers_limit_and_age_filter(env: Path):
    mem = Memory(Config.load())
    for i in range(5):
        mem.add(text=f"sample drawer {i}", source="/x/a.md")
    assert len(mem.random_drawers(limit=3)) == 3
    # Everything was created just now — an age floor in the past excludes all.
    assert mem.random_drawers(limit=3, older_than=time.time() - 3600) == []
    mem.close()


# --- superton open ------------------------------------------------------------


def test_open_shows_full_drawer(env: Path):
    drawer_id = _seed_note("the full body of the opened drawer")
    result = CliRunner().invoke(app, ["open", drawer_id[:8]])
    assert result.exit_code == 0
    assert "the full body of the opened drawer" in result.stdout
    assert "notes/" in result.stdout  # wing/room line


def test_open_unknown_id_exits_1(env: Path):
    result = CliRunner().invoke(app, ["open", "deadbeef"])
    assert result.exit_code == 1
    assert "no drawer matched" in result.stdout + result.output


def test_open_edit_virtual_source_warns(env: Path):
    drawer_id = _seed_note("note drawers have no file behind them")
    result = CliRunner().invoke(app, ["open", drawer_id[:8], "--edit"])
    assert result.exit_code == 0
    assert "not a file on disk" in result.stdout


def test_open_edit_launches_editor_for_real_file(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    note = tmp_path / "real.md"
    note.write_text("a real file on disk", encoding="utf-8")
    CliRunner().invoke(app, ["add", str(note)])
    listed = CliRunner().invoke(app, ["list", "--json"])
    drawer_id = json.loads(listed.stdout)[0]["id"]

    monkeypatch.setenv("EDITOR", "true")  # /usr/bin/true — exits 0 instantly
    result = CliRunner().invoke(app, ["open", drawer_id, "--edit"])
    assert result.exit_code == 0


# --- superton recall ------------------------------------------------------------


def test_recall_resurfaces_drawers(env: Path):
    _seed_note("recall me from the depths of the palace")
    result = CliRunner().invoke(app, ["recall"])
    assert result.exit_code == 0
    assert "recall" in result.stdout
    assert "today" in result.stdout  # freshly created → age label 'today'
    assert "superton open" in result.stdout  # follow-up hint


def test_recall_empty_palace_hints(env: Path):
    result = CliRunner().invoke(app, ["recall"])
    assert result.exit_code == 0
    assert "palace is empty" in result.stdout


def test_recall_older_than_filters_fresh_drawers(env: Path):
    _seed_note("too fresh to recall")
    result = CliRunner().invoke(app, ["recall", "--older-than", "5"])
    assert result.exit_code == 0
    assert "nothing older than 5" in result.stdout
