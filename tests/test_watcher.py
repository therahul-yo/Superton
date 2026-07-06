"""Tests for the auto-ingest watcher (`superton watch`)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from superton.cli import app
from superton.config import Config
from superton.memory import Memory
from superton.watcher import (
    Watcher,
    add_watch,
    load_watchlist,
    remove_watch,
)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("SUPERTON_HOME", str(home))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return home


def _bump_mtime(path: Path) -> None:
    """Force a visibly newer mtime so signature comparison can't tie."""
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))


# --- watchlist ------------------------------------------------------------


def test_watchlist_round_trip(env: Path, tmp_path: Path):
    cfg = Config.load()
    target = tmp_path / "notes"
    target.mkdir()

    assert load_watchlist(cfg) == []
    assert add_watch(cfg, target) is True
    assert add_watch(cfg, target) is False  # already present
    assert load_watchlist(cfg) == [target]
    assert remove_watch(cfg, target) is True
    assert remove_watch(cfg, target) is False
    assert load_watchlist(cfg) == []


def test_watchlist_ignores_comments_and_blanks(env: Path):
    cfg = Config.load()
    cfg.home.mkdir(parents=True, exist_ok=True)
    (cfg.home / "watchlist").write_text(
        "# my watched dirs\n\n/tmp/somewhere\n", encoding="utf-8"
    )
    assert load_watchlist(cfg) == [Path("/tmp/somewhere")]


def test_cli_watch_add_list_remove(env: Path, tmp_path: Path):
    target = tmp_path / "notes"
    target.mkdir()

    result = CliRunner().invoke(app, ["watch", "add", str(target)])
    assert result.exit_code == 0
    assert "watching" in result.stdout

    listed = CliRunner().invoke(app, ["watch", "list"])
    assert listed.exit_code == 0
    # Long tmp paths fold across lines in an 80-col console, so assert on
    # the basename in output and on the watchlist file as source of truth.
    assert "notes" in listed.stdout
    assert load_watchlist(Config.load()) == [target]

    removed = CliRunner().invoke(app, ["watch", "remove", str(target)])
    assert removed.exit_code == 0
    assert "stopped watching" in removed.stdout


def test_cli_watch_add_missing_path_errors(env: Path):
    result = CliRunner().invoke(app, ["watch", "add", "/nope/never/here"])
    assert result.exit_code == 1


def test_cli_watch_nothing_to_watch_exits_with_hint(env: Path):
    result = CliRunner().invoke(app, ["watch", "--once", "--no-transcripts"])
    assert result.exit_code == 1
    assert "nothing to watch" in result.stdout


# --- scan passes ----------------------------------------------------------


def _watcher(env_home: Path, roots: list[Path], tx: list[tuple[str, Path]] | None = None):
    cfg = Config.load()
    mem = Memory(cfg)
    return cfg, mem, Watcher(cfg, mem, roots=roots, transcript_roots=tx or [])


def test_scan_ingests_new_file_then_goes_quiet(env: Path, tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("alpha decision: use token buckets", encoding="utf-8")

    cfg, mem, watcher = _watcher(env, [notes])
    report = watcher.scan_once()
    assert report.new_files == 1
    assert report.drawers_added >= 1

    # Second pass with no changes: fully quiet.
    second = watcher.scan_once()
    assert second.activity == 0
    mem.close()


def test_scan_refreshes_changed_file_without_duplicates(env: Path, tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    note = notes / "a.md"
    note.write_text("first draft body", encoding="utf-8")

    cfg, mem, watcher = _watcher(env, [notes])
    watcher.scan_once()

    note.write_text("second draft body — completely rewritten", encoding="utf-8")
    _bump_mtime(note)
    report = watcher.scan_once()
    assert report.changed_files == 1

    drawers = [d for d in mem.all(limit=100) if d.source == str(note)]
    texts = " ".join(d.text for d in drawers)
    assert "second draft" in texts
    assert "first draft" not in texts  # stale chunks were dropped
    mem.close()


def test_deleted_file_keeps_its_drawers(env: Path, tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    note = notes / "keep.md"
    note.write_text("memory outlives the file", encoding="utf-8")

    cfg, mem, watcher = _watcher(env, [notes])
    watcher.scan_once()
    note.unlink()
    report = watcher.scan_once()

    assert report.activity == 0
    remaining = [d for d in mem.all(limit=100) if d.source == str(note)]
    assert remaining, "deletion must not forget drawers"
    mem.close()


def test_scan_state_survives_restart(env: Path, tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("persisted state check", encoding="utf-8")

    cfg, mem, watcher = _watcher(env, [notes])
    watcher.scan_once()
    mem.close()

    # New Watcher instance (fresh process semantics) sees the same state.
    cfg2, mem2, watcher2 = _watcher(env, [notes])
    report = watcher2.scan_once()
    assert report.activity == 0
    mem2.close()


def test_unsupported_files_skipped_quietly(env: Path, tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "photo.png").write_bytes(b"\x89PNG not really")
    (notes / "real.md").write_text("supported neighbour", encoding="utf-8")

    cfg, mem, watcher = _watcher(env, [notes])
    report = watcher.scan_once()
    assert report.skipped_files == 1
    assert report.errors == []
    assert report.drawers_added >= 1
    mem.close()


# --- transcript roots -------------------------------------------------------


def _write_session(path: Path, texts: list[str]) -> None:
    lines = [
        json.dumps({"message": {"role": "user", "content": t}}) for t in texts
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_transcript_new_session_imported(env: Path, tmp_path: Path):
    claude_root = tmp_path / "projects" / "myproj"
    claude_root.mkdir(parents=True)
    _write_session(claude_root / "s1.jsonl", ["how do I rate limit?"])

    cfg, mem, watcher = _watcher(
        env, [], tx=[("claude-code", tmp_path / "projects")]
    )
    report = watcher.scan_once()
    assert report.transcript_files == 1
    assert report.transcript_drawers >= 1
    sources = {row["source"] for row in mem.sources(limit=100)}
    assert "claude-code:s1.jsonl" in sources
    mem.close()


def test_transcript_appended_turns_are_picked_up(env: Path, tmp_path: Path):
    claude_root = tmp_path / "projects" / "myproj"
    claude_root.mkdir(parents=True)
    session = claude_root / "s1.jsonl"
    _write_session(session, ["first question about caching"])

    cfg, mem, watcher = _watcher(
        env, [], tx=[("claude-code", tmp_path / "projects")]
    )
    watcher.scan_once()

    _write_session(session, ["first question about caching", "follow-up about eviction"])
    _bump_mtime(session)
    report = watcher.scan_once()
    assert report.transcript_drawers >= 2  # session re-imported with the new turn

    texts = " ".join(d.text for d in mem.all(limit=100))
    assert "eviction" in texts
    mem.close()


def test_cli_watch_once_ingests_watched_dir(env: Path, tmp_path: Path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "n.md").write_text("watch me get ingested", encoding="utf-8")
    assert CliRunner().invoke(app, ["watch", "add", str(notes)]).exit_code == 0

    result = CliRunner().invoke(app, ["watch", "--once", "--no-transcripts"])
    assert result.exit_code == 0
    assert "new file" in result.stdout or "drawers" in result.stdout

    again = CliRunner().invoke(app, ["watch", "--once", "--no-transcripts"])
    assert again.exit_code == 0
    assert "already current" in again.stdout
