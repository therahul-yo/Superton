"""Importer test coverage: Claude Code, ChatGPT, generic threads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superton.config import Config
from superton.importers.chatgpt import ChatGPTImporter
from superton.importers.claude_code import ClaudeCodeImporter, _extract_text
from superton.importers.generic_threads import GenericThreadImporter
from superton.memory import Memory


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return Config.load()


# --- Claude Code -------------------------------------------------------------


def test_claude_code_extract_text_string():
    assert _extract_text("hello") == "hello"


def test_claude_code_extract_text_blocks():
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "tool_use", "name": "Bash"},
        {"type": "tool_result", "content": "output"},
    ]
    out = _extract_text(blocks)
    assert "first" in out
    assert "[tool_use: Bash]" in out
    assert "[tool_result] output" in out


def test_claude_code_extract_text_unknown_returns_empty():
    assert _extract_text(42) == ""


def test_claude_code_import_session(cfg: Config, tmp_path: Path):
    session = tmp_path / "abc123.jsonl"
    session.write_text(
        '{"message": {"role": "user", "content": "what about X?"}}\n'
        '{"message": {"role": "assistant", "content": "X is fine."}}\n'
        '{"message": {"role": "system", "content": "ignored"}}\n',
        encoding="utf-8",
    )
    mem = Memory(cfg)
    n = ClaudeCodeImporter(mem).import_session(session)
    assert n == 2
    sources = {row["source"] for row in mem.sources()}
    assert "claude-code:abc123.jsonl" in sources
    mem.close()


def test_claude_code_import_skips_existing_source(cfg: Config, tmp_path: Path):
    session = tmp_path / "abc.jsonl"
    session.write_text(
        '{"message": {"role": "user", "content": "hello"}}\n',
        encoding="utf-8",
    )
    mem = Memory(cfg)
    importer = ClaudeCodeImporter(mem)
    n1 = importer.import_session(session)
    n2 = importer.import_session(session)
    assert n1 == 1
    assert n2 == 0
    mem.close()


def test_claude_code_import_replace_reimports(cfg: Config, tmp_path: Path):
    session = tmp_path / "abc.jsonl"
    session.write_text(
        '{"message": {"role": "user", "content": "hello"}}\n',
        encoding="utf-8",
    )
    mem = Memory(cfg)
    importer = ClaudeCodeImporter(mem)
    importer.import_session(session)
    n = importer.import_session(session, replace=True)
    assert n == 1
    mem.close()


def test_claude_code_import_skips_malformed_lines(cfg: Config, tmp_path: Path):
    session = tmp_path / "broken.jsonl"
    session.write_text(
        '{"message": {"role": "user", "content": "good"}}\n'
        "not valid json\n"
        '{"message": {"role": "assistant", "content": "ok"}}\n',
        encoding="utf-8",
    )
    mem = Memory(cfg)
    n = ClaudeCodeImporter(mem).import_session(session)
    assert n == 2
    mem.close()


def test_claude_code_discover_missing_root(cfg: Config, tmp_path: Path):
    mem = Memory(cfg)
    importer = ClaudeCodeImporter(mem)
    assert list(importer.discover(tmp_path / "nope")) == []
    mem.close()


# --- ChatGPT ----------------------------------------------------------------


def test_chatgpt_skips_re_import(cfg: Config, tmp_path: Path):
    export = tmp_path / "conversations.json"
    payload = [
        {
            "title": "Plan",
            "mapping": {
                "1": {"message": {"author": {"role": "user"}, "content": {"parts": ["hi"]}}},
            },
        }
    ]
    export.write_text(json.dumps(payload), encoding="utf-8")
    mem = Memory(cfg)
    importer = ChatGPTImporter(mem)
    c1, d1 = importer.import_all(export)
    c2, d2 = importer.import_all(export)
    assert c1 == 1 and d1 == 1
    assert c2 == 0 and d2 == 0
    mem.close()


def test_chatgpt_replace_reimports(cfg: Config, tmp_path: Path):
    export = tmp_path / "conversations.json"
    payload = [
        {
            "title": "Plan",
            "mapping": {
                "1": {"message": {"author": {"role": "user"}, "content": {"parts": ["hi"]}}},
            },
        }
    ]
    export.write_text(json.dumps(payload), encoding="utf-8")
    mem = Memory(cfg)
    importer = ChatGPTImporter(mem)
    importer.import_all(export)
    c2, d2 = importer.import_all(export, replace=True)
    assert c2 == 1 and d2 == 1
    mem.close()


def test_chatgpt_skips_empty_messages(cfg: Config, tmp_path: Path):
    export = tmp_path / "conversations.json"
    payload = [
        {
            "title": "Mixed",
            "mapping": {
                "1": {"message": {"author": {"role": "user"}, "content": {"parts": [""]}}},
                "2": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["real"]}}},
                "3": {"message": {"author": {"role": "system"}, "content": {"parts": ["skip"]}}},
            },
        }
    ]
    export.write_text(json.dumps(payload), encoding="utf-8")
    mem = Memory(cfg)
    _, drawers = ChatGPTImporter(mem).import_all(export)
    assert drawers == 1
    mem.close()


# --- Generic threads (Cursor, Amp) ------------------------------------------


def test_generic_thread_importer_json(cfg: Config, tmp_path: Path):
    thread = tmp_path / "convo.json"
    thread.write_text(
        json.dumps({"text": "hello world", "content": "more body"}),
        encoding="utf-8",
    )
    mem = Memory(cfg)
    files, drawers = GenericThreadImporter(mem, "cursor", tmp_path).import_all(tmp_path)
    assert files == 1
    assert drawers == 1
    mem.close()


def test_generic_thread_importer_jsonl_malformed_lines_skipped(cfg: Config, tmp_path: Path):
    thread = tmp_path / "convo.jsonl"
    thread.write_text(
        '{"content": "good"}\n'
        "not json\n"
        '{"content": "also good"}\n',
        encoding="utf-8",
    )
    mem = Memory(cfg)
    files, drawers = GenericThreadImporter(mem, "amp", tmp_path).import_all(tmp_path)
    assert files == 1
    assert drawers >= 1
    mem.close()


def test_generic_thread_importer_missing_root_is_empty(cfg: Config, tmp_path: Path):
    mem = Memory(cfg)
    importer = GenericThreadImporter(mem, "cursor", tmp_path / "missing")
    files, drawers = importer.import_all()
    assert files == 0 and drawers == 0
    mem.close()


def test_generic_thread_importer_plain_text(cfg: Config, tmp_path: Path):
    thread = tmp_path / "notes.txt"
    thread.write_text("plain text content here", encoding="utf-8")
    mem = Memory(cfg)
    files, drawers = GenericThreadImporter(mem, "cursor", tmp_path).import_all(tmp_path)
    assert files == 1
    assert drawers >= 1
    mem.close()
