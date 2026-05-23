"""Tests for the logging module and error-to-hint mapping."""

from __future__ import annotations

import json
import logging

import pytest

from superton import errors
from superton import logging as slog
from superton.errors import (
    ConfigError,
    IngestError,
    SupertonError,
    hint_for,
)
from superton.model import HuggingFaceError, ModelError, OllamaError


def _reconfigure(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    slog.configure(force=True)


def test_get_logger_under_package_namespace():
    logger = slog.get_logger("memory")
    assert logger.name == "superton.memory"


def test_get_logger_passthrough_for_dotted_name():
    logger = slog.get_logger("superton.custom")
    assert logger.name == "superton.custom"


def test_log_level_warn_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SUPERTON_LOG", raising=False)
    slog.configure(force=True)
    assert logging.getLogger("superton").level == logging.WARNING


def test_log_level_debug_from_env(monkeypatch: pytest.MonkeyPatch):
    _reconfigure(monkeypatch, SUPERTON_LOG="debug")
    assert logging.getLogger("superton").level == logging.DEBUG


def test_log_level_off_silences(monkeypatch: pytest.MonkeyPatch):
    _reconfigure(monkeypatch, SUPERTON_LOG="off")
    assert logging.getLogger("superton").level > logging.CRITICAL


def test_log_level_unknown_falls_back_to_warn(monkeypatch: pytest.MonkeyPatch):
    _reconfigure(monkeypatch, SUPERTON_LOG="bogus")
    assert logging.getLogger("superton").level == logging.WARNING


def test_json_formatter_emits_one_line_dict(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    _reconfigure(monkeypatch, SUPERTON_LOG="info", SUPERTON_LOG_JSON="1")
    slog.get_logger("memory").info("hello", extra={"source": "x.md"})
    captured = capsys.readouterr().err.strip().splitlines()
    record = json.loads(captured[-1])
    assert record["msg"] == "hello"
    assert record["level"] == "info"
    assert record["source"] == "x.md"


def test_configure_is_idempotent(monkeypatch: pytest.MonkeyPatch):
    _reconfigure(monkeypatch, SUPERTON_LOG="info")
    before = list(logging.getLogger("superton").handlers)
    slog.configure()
    assert list(logging.getLogger("superton").handlers) == before


def test_configure_force_replaces_handlers(monkeypatch: pytest.MonkeyPatch):
    _reconfigure(monkeypatch, SUPERTON_LOG="info")
    slog.configure(force=True)
    handlers = logging.getLogger("superton").handlers
    assert all(getattr(h, "_extra_marker", None) is None for h in handlers)


# --- error hints ------------------------------------------------------------


def test_hint_for_ollama_error_mentions_serve(monkeypatch: pytest.MonkeyPatch):
    # Pretend Ollama is on PATH so we exercise the "installed but daemon
    # down" branch — the new install-detection logic returns a different
    # hint when shutil.which returns None (covered by the test below).
    monkeypatch.setattr(errors.shutil, "which", lambda _name: "/usr/local/bin/ollama")
    h = hint_for(OllamaError("connection refused"))
    assert "ollama serve" in h.hint


def test_hint_for_ollama_error_when_not_installed_points_at_download(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(errors.shutil, "which", lambda _name: None)
    h = hint_for(OllamaError("connection refused"))
    assert "not installed" in h.summary
    assert "ollama.com/download" in h.hint or "superton init" in h.hint


def test_hint_for_huggingface_error_mentions_token():
    h = hint_for(HuggingFaceError("401"))
    assert "HF_TOKEN" in h.hint


def test_hint_for_model_error_mentions_init(monkeypatch: pytest.MonkeyPatch):
    # `hint_for(ModelError)` also branches on shutil.which now. Pretend
    # Ollama is present so we exercise the original "no backend" path.
    monkeypatch.setattr(errors.shutil, "which", lambda _name: "/usr/local/bin/ollama")
    h = hint_for(ModelError("no backend"))
    assert "superton init" in h.hint


def test_hint_for_ingest_error_summarizes():
    h = hint_for(IngestError("bad pdf"))
    assert "bad pdf" in h.summary


def test_hint_for_config_error_points_at_settings():
    h = hint_for(ConfigError("bad theme"))
    assert "config.toml" in h.hint or "env var" in h.hint


def test_hint_for_file_not_found():
    h = hint_for(FileNotFoundError(2, "no such file", "/tmp/missing"))
    assert "/tmp/missing" in h.summary or "not found" in h.summary


def test_hint_for_unknown_falls_back_to_debug():
    h = hint_for(RuntimeError("weird"))
    assert "SUPERTON_LOG=debug" in h.hint


def test_render_writes_two_lines(capsys: pytest.CaptureFixture):
    errors.render(OllamaError("nope"))
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "ollama" in combined.lower()


def test_superton_error_is_exception_subclass():
    assert issubclass(SupertonError, Exception)
