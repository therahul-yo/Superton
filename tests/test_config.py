"""Config validation tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from superton.config import (
    DEFAULT_BASE_MODEL,
    DEFAULT_HF_MODEL,
    VALID_BACKENDS,
    VALID_MEMORY_BACKENDS,
    Config,
    detect_ram_gb,
    write_settings,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    return tmp_path


def test_default_model_is_minicpm5(home: Path):
    cfg = Config.load()
    assert cfg.base_model == DEFAULT_BASE_MODEL == "openbmb/minicpm5"
    assert cfg.hf_model == DEFAULT_HF_MODEL == "openbmb/MiniCPM5-1B"
    assert cfg.model == "superton"


def test_invalid_model_backend_falls_back_to_auto(home: Path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERTON_MODEL_BACKEND", "openai")
    with caplog.at_level(logging.WARNING, logger="superton.config"):
        cfg = Config.load()
    assert cfg.model_backend == "auto"


def test_invalid_memory_backend_falls_back_to_hybrid(home: Path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "elasticsearch")
    with caplog.at_level(logging.WARNING, logger="superton.config"):
        cfg = Config.load()
    assert cfg.memory_backend == "hybrid"


def test_invalid_theme_falls_back_to_ember(home: Path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERTON_THEME", "neopunk")
    with caplog.at_level(logging.WARNING, logger="superton.config"):
        cfg = Config.load()
    assert cfg.theme == "ember"


def test_all_valid_themes_load(home: Path, monkeypatch):
    for name in ("ember", "crimson", "void", "ash"):
        monkeypatch.setenv("SUPERTON_THEME", name)
        cfg = Config.load()
        assert cfg.theme == name


def test_all_valid_backends_load(home: Path, monkeypatch):
    for name in VALID_BACKENDS:
        monkeypatch.setenv("SUPERTON_MODEL_BACKEND", name)
        cfg = Config.load()
        assert cfg.model_backend == name


def test_all_valid_memory_backends_load(home: Path, monkeypatch):
    for name in VALID_MEMORY_BACKENDS:
        monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", name)
        cfg = Config.load()
        assert cfg.memory_backend == name


def test_write_settings_roundtrips(home: Path, monkeypatch):
    write_settings(home, theme="void", base_model="openbmb/minicpm5:q8_0")
    monkeypatch.delenv("SUPERTON_THEME", raising=False)
    monkeypatch.delenv("SUPERTON_BASE_MODEL", raising=False)
    cfg = Config.load()
    assert cfg.theme == "void"
    assert cfg.base_model == "openbmb/minicpm5:q8_0"


def test_write_settings_overwrites_existing(home: Path, monkeypatch):
    write_settings(home, theme="void")
    write_settings(home, theme="crimson")
    monkeypatch.delenv("SUPERTON_THEME", raising=False)
    cfg = Config.load()
    assert cfg.theme == "crimson"


def test_detect_ram_returns_float_or_none():
    # Not asserting an exact value — just that the function never explodes.
    ram = detect_ram_gb()
    assert ram is None or isinstance(ram, float)
