"""Tests for `superton timeline` and `superton digest`."""

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


class FakeModel:
    """Streams a canned digest; stands in for superton.cli.Model."""

    online = True

    def __init__(self, cfg):
        self.cfg = cfg

    def backend(self):
        return "fake" if self.online else None

    def start_ollama(self, timeout: float = 5.0) -> bool:
        return self.online

    def generate(self, prompt, system=None, history=None):
        yield "Worked on\n- the digest feature [abcd1234]"

    def close(self) -> None:
        return None


class OfflineModel(FakeModel):
    online = False


# --- memory queries ---------------------------------------------------------


def test_activity_groups_by_day_and_source(env: Path):
    mem = Memory(Config.load())
    mem.add(text="alpha work", source="/x/alpha.md")
    mem.add(text="alpha more work", source="/x/alpha.md")
    mem.add(text="beta work", source="/x/beta.md")
    rows = mem.activity(since=time.time() - 60)
    mem.close()

    by_source = {r["source"]: r for r in rows}
    assert by_source["/x/alpha.md"]["drawers"] == 2
    assert by_source["/x/beta.md"]["drawers"] == 1
    assert all(len(str(r["day"])) == 10 for r in rows)  # YYYY-MM-DD


def test_drawers_since_respects_window(env: Path):
    mem = Memory(Config.load())
    mem.add(text="inside the window", source="/x/a.md")
    assert mem.drawers_since(since=time.time() - 60)
    assert mem.drawers_since(since=time.time() + 60) == []
    mem.close()


# --- timeline ---------------------------------------------------------------


def test_timeline_renders_today_activity(env: Path):
    CliRunner().invoke(app, ["note", "timeline check note"])
    result = CliRunner().invoke(app, ["timeline"])
    assert result.exit_code == 0
    assert "timeline" in result.stdout
    assert "today" in result.stdout
    assert "drawer(s)" in result.stdout


def test_timeline_json(env: Path):
    CliRunner().invoke(app, ["note", "timeline json note"])
    result = CliRunner().invoke(app, ["timeline", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows and {"day", "source", "drawers"} <= set(rows[0])


def test_timeline_empty_window(env: Path):
    result = CliRunner().invoke(app, ["timeline"])
    assert result.exit_code == 0
    assert "nothing ingested" in result.stdout


# --- digest -------------------------------------------------------------------


def test_digest_empty_palace_hints(env: Path):
    result = CliRunner().invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "nothing ingested" in result.stdout


def test_digest_streams_model_brief(env: Path, monkeypatch: pytest.MonkeyPatch):
    CliRunner().invoke(app, ["note", "decided to ship the watcher first"])
    monkeypatch.setattr("superton.cli.Model", FakeModel)
    result = CliRunner().invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "Worked on" in result.stdout
    assert "sources" in result.stdout  # citations footer


def test_digest_offline_falls_back_to_activity_table(
    env: Path, monkeypatch: pytest.MonkeyPatch
):
    CliRunner().invoke(app, ["note", "offline digest note"])
    monkeypatch.setattr("superton.cli.Model", OfflineModel)
    result = CliRunner().invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "model backend offline" in result.stdout
    assert "note:" in result.stdout  # activity summary shows the source


def test_digest_spreads_context_across_sources(env: Path, monkeypatch: pytest.MonkeyPatch):
    """One bulk source must not monopolize the digest context."""
    mem = Memory(Config.load())
    for i in range(60):
        mem.add(text=f"bulk import chunk {i}", source="/x/bulk.md")
    mem.add(text="tiny but important note", source="/x/tiny.md")
    mem.close()

    captured: dict[str, str] = {}

    class CapturingModel(FakeModel):
        def generate(self, prompt, system=None, history=None):
            captured["prompt"] = prompt
            yield "ok"

    monkeypatch.setattr("superton.cli.Model", CapturingModel)
    result = CliRunner().invoke(app, ["digest"])
    assert result.exit_code == 0
    assert "tiny.md" in captured["prompt"]
