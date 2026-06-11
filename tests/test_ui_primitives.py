"""Tests for the polished UI primitives added in the aesthetics pass."""

from __future__ import annotations

import pytest
from rich.text import Text

from superton import ui


def test_pill_returns_styled_text():
    p = ui.pill("ember", kind="primary")
    assert isinstance(p, Text)
    assert "ember" in p.plain


def test_pill_unknown_kind_falls_back_to_neutral():
    p = ui.pill("x", kind="bogus")
    assert "x" in p.plain


def test_status_pills_includes_drawer_count():
    class _Cfg:
        model = "superton"

    pills = ui.status_pills(_Cfg(), {"drawers": 42})
    plain = pills.plain
    assert "ember" in plain or ui.theme().name in plain
    assert "superton" in plain
    assert "42" in plain


def test_status_pills_shows_semantic_warning():
    class _Cfg:
        model = "superton"

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


# --- ui polish pass: theme cursors, tempo, score bars, reveal cascade ---------


@pytest.mark.parametrize("name", list(ui.THEMES))
def test_theme_has_cursor_and_tempo(name):
    t = ui.THEMES[name]
    assert t.cursor, f"{name} theme is missing a cursor glyph"
    assert t.tempo > 0, f"{name} theme tempo must be positive"


def test_theme_cursors_are_distinct_enough():
    cursors = {t.cursor for t in ui.THEMES.values()}
    assert len(cursors) >= 3  # per-theme identity, not one shared glyph


def test_typing_cursor_uses_theme_glyph():
    assert ui.theme().cursor in ui.typing_cursor()


def test_typing_cursor_explicit_char_override():
    assert "|" in ui.typing_cursor("|")


def test_score_bar_full_and_empty():
    full = ui.score_bar(1.0)
    empty = ui.score_bar(0.0)
    assert "▰" in full.plain and "▱" not in full.plain
    assert "▱" in empty.plain and "▰" not in empty.plain


def test_score_bar_clamps_out_of_range():
    assert ui.score_bar(7.5).plain == ui.score_bar(1.0).plain
    assert ui.score_bar(-2.0).plain == ui.score_bar(0.0).plain


def test_reveal_cards_prints_everything(capsys):
    ui.reveal_cards([Text("alpha"), Text("beta"), Text("gamma")])
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out and "gamma" in out


def test_reveal_cards_no_sleep_when_not_terminal(monkeypatch):
    import time as _time

    called = []
    monkeypatch.setattr(_time, "sleep", lambda *_: called.append(1))
    ui.reveal_cards([Text("a"), Text("b")])
    assert not called  # non-TTY path must not stagger


def test_rule_titled_carries_theme_glyph(capsys):
    ui.rule("memory")
    out = capsys.readouterr().out
    assert ui.theme().prompt_glyph in out
    assert "memory" in out


def test_rule_untitled_has_no_glyph(capsys):
    ui.rule()
    out = capsys.readouterr().out
    assert ui.theme().prompt_glyph not in out


def test_flash_is_noop_when_not_terminal(capsys):
    ui.flash(Text("switched"))
    assert capsys.readouterr().out == ""


def test_stream_answer_non_tty_has_no_cursor(capsys):
    answer = ui.stream_answer(iter(["hello ", "world"]))
    assert answer == "hello world"
    assert ui.theme().cursor not in capsys.readouterr().out
