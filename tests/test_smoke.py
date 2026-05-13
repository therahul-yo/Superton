"""Smoke tests — make sure imports work and the basic store roundtrips."""

from __future__ import annotations

from pathlib import Path

import pytest

from superton.config import Config
from superton.ingest import chunk_text
from superton.memory import Memory
from superton.model import Model


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
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


def test_model_defaults_are_miniton(cfg: Config):
    assert cfg.model == "miniton"
    assert cfg.base_model == "qwen2.5:1.5b-instruct"
    assert cfg.model_profile == "fast"
    assert cfg.memory_backend == "sqlite"


def test_model_profile_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from superton.config import Config, write_settings

    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    write_settings(
        tmp_path,
        model_profile="better",
        base_model="qwen2.5:3b-instruct",
        hf_model="Qwen/Qwen2.5-3B-Instruct",
    )
    cfg = Config.load()
    assert cfg.model_profile == "better"
    assert cfg.base_model == "qwen2.5:3b-instruct"
    assert cfg.hf_model == "Qwen/Qwen2.5-3B-Instruct"


def test_modelfile_render_uses_configured_base(cfg: Config, tmp_path: Path):
    from superton.cli import _render_modelfile

    template = tmp_path / "Modelfile"
    template.write_text("FROM placeholder\nSYSTEM \"\"\"hello\"\"\"\n", encoding="utf-8")
    rendered = _render_modelfile(template, cfg)
    assert rendered.read_text(encoding="utf-8").startswith("FROM qwen2.5:1.5b-instruct\n")


def test_confirm_pull_yes_skips_prompt():
    from superton.cli import _confirm_pull

    assert _confirm_pull("model", "purpose", yes=True) is True


def test_hugging_face_backend_detection(cfg: Config, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPERTON_MODEL_BACKEND", "huggingface")
    monkeypatch.setenv("HF_TOKEN", "test-token")
    model = Model(Config.load())
    assert model.backend() == "huggingface"
    model.close()


def test_start_ollama_returns_true_when_already_ready(cfg: Config, monkeypatch: pytest.MonkeyPatch):
    model = Model(cfg)
    monkeypatch.setattr(model, "_ollama_ping", lambda: True)
    assert model.start_ollama() is True
    model.close()


def test_model_stop_calls_ollama(cfg: Config, monkeypatch: pytest.MonkeyPatch):
    calls = []

    class Result:
        returncode = 0

    def fake_run(cmd, check):
        calls.append((cmd, check))
        return Result()

    monkeypatch.setattr("superton.model.subprocess.run", fake_run)
    model = Model(cfg)
    assert model.stop("miniton") is True
    assert calls == [(["ollama", "stop", "miniton"], False)]
    model.close()


def test_shell_greeting_does_not_dump_memory(cfg: Config, capsys: pytest.CaptureFixture):
    from superton.shell import _answer

    class FakeModel:
        def generate(self, prompt, system=None, history=None):
            assert "raw readme chunk" not in prompt
            yield "model-generated hello"

    mem = Memory(cfg)
    mem.add(text="raw readme chunk should not appear", source="README.md")
    _answer(mem, FakeModel(), "hey")
    out = capsys.readouterr().out
    assert "model-generated hello" in out
    assert "raw readme chunk" not in out
    mem.close()


def test_shell_model_error_fallback_is_summary(cfg: Config, capsys: pytest.CaptureFixture):
    from superton.model import ModelError
    from superton.shell import _answer

    class BrokenModel:
        def generate(self, prompt, system=None, history=None):
            raise ModelError("no backend")

    mem = Memory(cfg)
    mem.add(text="rate limiting via token bucket", source="notes.md")
    _answer(mem, BrokenModel(), "rate limiting")
    out = capsys.readouterr().out
    assert "Top match" in out
    assert "rate limiting via token bucket" not in out
    mem.close()


def test_shell_personal_query_refuses_weak_matches(cfg: Config, capsys: pytest.CaptureFixture):
    from superton.shell import _answer

    class FakeModel:
        def generate(self, prompt, system=None, history=None):
            yield "should not be used"

    mem = Memory(cfg)
    mem.add(text="SuperTon project roadmap and release notes", source="README.md")
    _answer(mem, FakeModel(), "gimme rahul T projects from his resume")
    out = capsys.readouterr().out
    assert "do not have matching memory" in out
    assert "should not be used" not in out
    mem.close()


def test_shell_path_input_ingests_file(cfg: Config, tmp_path: Path):
    from superton.shell import _ingest_path

    note = tmp_path / "resume.txt"
    note.write_text("Rahul T projects include SuperTon and MemPalace.", encoding="utf-8")
    mem = Memory(cfg)
    files, drawers = _ingest_path(mem, note)
    assert files == 1
    assert drawers == 1
    assert mem.search("Rahul projects")
    mem.close()


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


def test_memory_sources_and_forget_source(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="alpha", source="/tmp/a.txt")
    mem.add(text="beta", source="/tmp/a.txt")
    mem.add(text="gamma", source="/tmp/b.txt")
    sources = mem.sources()
    assert any(row["source"] == "/tmp/a.txt" and row["drawers"] == 2 for row in sources)
    assert mem.source_matches("a.txt") == ["/tmp/a.txt"]
    assert mem.forget_source("a.txt") == 2
    assert not mem.search("alpha")
    assert mem.search("gamma")
    mem.close()


def test_blackhole_renders():
    from superton.blackhole import render_frame, static_frame
    frame = render_frame(0.0)
    assert len(str(frame)) > 100
    assert static_frame() is not None


def test_chatgpt_importer(cfg: Config, tmp_path: Path):
    from superton.importers.chatgpt import ChatGPTImporter

    export = tmp_path / "conversations.json"
    export.write_text(
        """
        [
          {
            "title": "Memory Plan",
            "mapping": {
              "1": {"message": {"author": {"role": "user"}, "content": {"parts": ["remember this"]}}},
              "2": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["stored"]}}}
            }
          }
        ]
        """,
        encoding="utf-8",
    )
    mem = Memory(cfg)
    conversations, drawers = ChatGPTImporter(mem).import_all(export)
    assert conversations == 1
    assert drawers == 2
    assert mem.stats()["drawers"] == 2
    mem.close()


def test_generic_thread_importer(cfg: Config, tmp_path: Path):
    from superton.importers.generic_threads import GenericThreadImporter

    thread = tmp_path / "thread.jsonl"
    thread.write_text('{"role":"user","content":"cursor decision"}\n', encoding="utf-8")
    mem = Memory(cfg)
    files, drawers = GenericThreadImporter(mem, "cursor", tmp_path).import_all(tmp_path)
    assert files == 1
    assert drawers == 1
    mem.close()
