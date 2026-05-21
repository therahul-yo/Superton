"""Tests for the install-flow UI primitives added to ui.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from superton import ui
from superton.config import Config


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return Config.load()


# --- ram_bar ---------------------------------------------------------------


def test_ram_bar_unknown_shows_question_marks():
    out = ui.ram_bar(None, 8.0)
    assert "??" in out.plain
    assert "8 GB" in out.plain


def test_ram_bar_fits_shows_filled_segments():
    out = ui.ram_bar(used_gb=16.0, recommended_gb=8.0, width=4)
    plain = out.plain
    assert "■" in plain
    assert "fits" in plain


def test_ram_bar_tight_marks_warning():
    out = ui.ram_bar(used_gb=4.0, recommended_gb=16.0, width=4)
    assert "tight" in out.plain


def test_ram_bar_width_respected():
    out = ui.ram_bar(used_gb=8.0, recommended_gb=8.0, width=6)
    bar_chars = sum(out.plain.count(c) for c in "■□")
    assert bar_chars == 6


# --- preflight_card --------------------------------------------------------


def test_preflight_card_renders_each_row(capsys):
    rows = [
        ("✓", "palace", "exists"),
        ("→", "ollama", "will install"),
        ("?", "model", "needs ollama"),
        ("-", "claude code", "no sessions found"),
    ]
    ui.preflight_card("about to do", rows, summary="first run")
    out = capsys.readouterr().out
    assert "about to do" in out
    assert "first run" in out
    assert "palace" in out
    assert "ollama" in out
    assert "needs ollama" in out


def test_preflight_card_works_without_summary(capsys):
    ui.preflight_card("re-init", [("✓", "palace", "exists")])
    out = capsys.readouterr().out
    assert "re-init" in out


# --- ready_card ------------------------------------------------------------


def test_ready_card_includes_palace_path_and_commands(cfg: Config, capsys):
    ui.ready_card(cfg, {"drawers": 0, "wings": 0, "rooms": 0})
    out = capsys.readouterr().out
    assert "ready" in out
    assert "superton add" in out
    assert "superton tui" in out
    assert str(cfg.palace_dir) in out


# --- profile_card ----------------------------------------------------------


def test_profile_card_renders_selected_state(capsys):
    ui.profile_card(
        "fast",
        base_model="qwen2.5:1.5b-instruct",
        download_gb=1.0,
        min_ram_gb=4,
        label="lowest memory",
        ram_gb=8.0,
        selected=True,
    )
    out = capsys.readouterr().out
    assert "fast" in out
    assert "qwen2.5:1.5b-instruct" in out
    assert "~1.0 GB" in out


def test_profile_card_unselected_uses_circle(capsys):
    ui.profile_card(
        "strong",
        base_model="qwen2.5:7b-instruct",
        download_gb=4.7,
        min_ram_gb=16,
        label="best local quality",
        ram_gb=8.0,
        selected=False,
    )
    out = capsys.readouterr().out
    assert "strong" in out
    assert "○" in out
    # 8 GB < 16 GB recommended → tight pill
    assert "tight" in out


# --- theme_picker_card -----------------------------------------------------


def test_theme_picker_card_shows_all_themes(capsys):
    ui.theme_picker_card("nebula")
    out = capsys.readouterr().out
    for name in ui.THEMES:
        assert name in out


# --- stage(step, total) ----------------------------------------------------


def test_stage_renders_progress_indicator(capsys):
    with ui.stage("checking ollama", step=2, total=5):
        pass
    out = capsys.readouterr().out
    assert "[2/5]" in out
    assert "checking ollama" in out


def test_stage_without_step_falls_back(capsys):
    with ui.stage("creating palace"):
        pass
    out = capsys.readouterr().out
    assert "creating palace" in out
    assert "/" not in out.split("creating palace")[0]


def test_stage_warn_with_hint_prints_recovery_line(capsys):
    ui.stage_warn("ollama not found", hint="install: https://ollama.com/download")
    out = capsys.readouterr().out
    assert "ollama not found" in out
    assert "↳" in out
    assert "ollama.com" in out


def test_stage_warn_without_hint_omits_arrow(capsys):
    ui.stage_warn("something happened")
    out = capsys.readouterr().out
    assert "something happened" in out
    assert "↳" not in out
