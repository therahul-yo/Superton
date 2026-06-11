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
    # Tight RAM is a warning, not a hard failure — yellow, not red.
    assert out.spans[0].style == ui.INSTALL_YELLOW


def test_ram_bar_fits_uses_orange():
    """Fits RAM renders the bar in INSTALL_ORANGE — the forward/progress
    signal in the install palette."""
    out = ui.ram_bar(used_gb=16.0, recommended_gb=8.0, width=4)
    assert "fits" in out.plain
    assert out.spans[0].style == ui.INSTALL_ORANGE


def test_ram_bar_fits_pill_uses_install_purple():
    """The `fits` chip uses INSTALL_PURPLE (the affirmative tone) rather
    than the active theme's success green, so the install flow keeps a
    self-contained four-color vocabulary that doesn't shift with the
    user's chosen theme."""
    out = ui.ram_bar(used_gb=16.0, recommended_gb=8.0, width=4)
    # Find the span containing the " fits " label — its style should name
    # INSTALL_PURPLE as the background.
    fits_spans = [s for s in out.spans if "fits" in out.plain[s.start:s.end]]
    assert fits_spans, "no styled span carries the fits label"
    assert ui.INSTALL_PURPLE in fits_spans[0].style


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
    assert str(cfg.palace_dir) in out



# --- theme_picker_card -----------------------------------------------------


def test_theme_picker_card_shows_all_themes(capsys):
    ui.theme_picker_card("ember")
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
