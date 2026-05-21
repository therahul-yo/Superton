"""Config validation tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from superton.config import (
    MODEL_PROFILES,
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


def test_invalid_model_profile_falls_back_to_fast(home: Path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERTON_MODEL_PROFILE", "ultra")
    with caplog.at_level(logging.WARNING, logger="superton.config"):
        cfg = Config.load()
    assert cfg.model_profile == "fast"
    assert any("ultra" in r.message for r in caplog.records)


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


def test_invalid_theme_falls_back_to_nebula(home: Path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERTON_THEME", "neopunk")
    with caplog.at_level(logging.WARNING, logger="superton.config"):
        cfg = Config.load()
    assert cfg.theme == "nebula"


def test_all_valid_themes_load(home: Path, monkeypatch):
    for name in ("nebula", "mono", "solar", "frost"):
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
    write_settings(home, theme="solar", model_profile="better")
    monkeypatch.delenv("SUPERTON_THEME", raising=False)
    monkeypatch.delenv("SUPERTON_MODEL_PROFILE", raising=False)
    cfg = Config.load()
    assert cfg.theme == "solar"
    assert cfg.model_profile == "better"


def test_write_settings_overwrites_existing(home: Path, monkeypatch):
    write_settings(home, theme="solar")
    write_settings(home, theme="frost")
    monkeypatch.delenv("SUPERTON_THEME", raising=False)
    cfg = Config.load()
    assert cfg.theme == "frost"


def test_detect_ram_returns_float_or_none():
    # Not asserting an exact value — just that the function never explodes.
    ram = detect_ram_gb()
    assert ram is None or isinstance(ram, float)


def test_model_profiles_has_three_tiers():
    assert set(MODEL_PROFILES) == {"fast", "better", "strong"}
    for data in MODEL_PROFILES.values():
        assert "base_model" in data
        assert "min_ram_gb" in data
