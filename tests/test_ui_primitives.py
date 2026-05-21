"""Tests for the polished UI primitives added in the aesthetics pass."""

from __future__ import annotations

from rich.text import Text

from superton import ui


def test_pill_returns_styled_text():
    p = ui.pill("nebula", kind="primary")
    assert isinstance(p, Text)
    assert "nebula" in p.plain


def test_pill_unknown_kind_falls_back_to_neutral():
    p = ui.pill("x", kind="bogus")
    assert "x" in p.plain


def test_status_pills_includes_drawer_count():
    class _Cfg:
        model_profile = "proton"

    pills = ui.status_pills(_Cfg(), {"drawers": 42})
    plain = pills.plain
    assert "nebula" in plain or ui.theme().name in plain
    assert "miniton:proton" in plain
    assert "42" in plain


def test_status_pills_shows_semantic_warning():
    class _Cfg:
        model_profile = "proton"

    pills = ui.status_pills(_Cfg(), {"drawers": 1, "semantic_error": "boom"})
    assert "semantic offline" in pills.plain


def test_numbered_chip_renders_id_and_filename():
    chip = ui.numbered_chip(1, "abcdef1234567890", "/tmp/notes.md")
    plain = chip.plain
    assert " 1 " in plain
    assert "abcdef12" in plain
    assert "notes.md" in plain


def test_numbered_chip_handles_none_values():
    chip = ui.numbered_chip(2, None, None)
    assert " 2 " in chip.plain


def test_diff_summary_runs_without_error(capsys):
    ui.diff_summary(removed=3, added=5)
    out = capsys.readouterr().out
    assert "3" in out and "5" in out


def test_card_renders_title_glyph(capsys):
    ui.card("search", "body text here")
    out = capsys.readouterr().out
    assert "search" in out
    assert "body text here" in out


def test_card_with_status_pill(capsys):
    ui.card("ingest", "47 drawers", status=("ok", "success"))
    out = capsys.readouterr().out
    assert "ingest" in out
    assert "ok" in out


def test_shimmer_is_noop_in_non_terminal():
    # Console.is_terminal is False under pytest capture — should not raise.
    ui.shimmer("scanning")


def test_section_with_sweep_disabled_prints_once(capsys):
    ui.section("test-section", sweep=False)
    out = capsys.readouterr().out
    # Subtitle absent — just title.
    assert "test-section" in out
    assert out.count("test-section") == 1


def test_maybe_pager_short_text_prints_directly(capsys):
    ui.maybe_pager("short answer")
    out = capsys.readouterr().out
    assert "short answer" in out


def test_maybe_pager_empty_is_noop(capsys):
    ui.maybe_pager("")
    out = capsys.readouterr().out
    assert out == ""


def test_spinner_phases_accepts_iterable():
    # Just verifies the context manager opens and closes without raising
    # — the phase cycler thread is a daemon and exits on stop.
    with ui.spinner("test", phases=["one", "two"]):
        pass


def test_spinner_yields_set_status_callable():
    with ui.spinner("test") as set_status:
        assert callable(set_status)
        set_status("updated")
