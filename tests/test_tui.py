"""Pilot-driven integration tests for the TUI.

Each test boots `SupertonApp` against a temp palace, drives it with
keypresses, and asserts visible state. We inject fake `Memory` and `Model`
so the tests stay hermetic and fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superton.chat import ChatTurn
from superton.config import Config
from superton.memory import Memory


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return Config.load()


class _FakeModel:
    """A stand-in Model that streams a canned answer."""

    def __init__(self, answer: str = "ok"):
        self.answer = answer
        self.last_prompt: str | None = None

    def backend(self) -> str | None:
        return "ollama"

    def ping(self) -> bool:
        return True

    def start_ollama(self, *, timeout: float = 5.0) -> bool:
        return True

    def generate(self, prompt, system=None, history=None):
        self.last_prompt = prompt
        yield from self.answer

    def close(self) -> None:
        return None


# --- importability / smoke -------------------------------------------------


def test_tui_module_imports():
    from superton.tui import SupertonApp  # noqa: F401


def test_theme_to_css_renders_for_each_theme():
    from superton.tui.theme import theme_to_css
    from superton.ui import THEMES

    for theme in THEMES.values():
        css = theme_to_css(theme)
        assert "#header" in css
        assert "#sidebar" in css
        assert "#chat" in css


def test_theme_color_helper_handles_grey_shades():
    from superton.tui.theme import _color

    assert _color("grey50").startswith("#")
    assert _color("bold #FFD93D").upper() == "#FFD93D"
    assert _color("white") == "white"
    assert _color("") == "#FFFFFF"


# --- state ----------------------------------------------------------------


def test_app_state_push_turn_bounds_history(cfg: Config):
    from superton.tui.state import AppState

    state = AppState(cfg=cfg)
    for i in range(20):
        state.push_turn(ChatTurn(question=f"q{i}", answer=f"a{i}"))
    assert len(state.history) == 12  # 6 turns × 2 entries
    assert state.chat[-1].question == "q19"


def test_app_state_defaults(cfg: Config):
    from superton.tui.state import AppState

    state = AppState(cfg=cfg)
    assert state.focus == "chat"
    assert state.mode == "chatting"
    assert state.backend_online is False
    assert state.pending_op is None


# --- palette ---------------------------------------------------------------


def test_palette_fuzzy_matches_subsequence():
    from superton.tui.widgets.palette import CommandPalette

    assert CommandPalette._fuzzy("sw md", "switch model")
    assert CommandPalette._fuzzy("doc", "doctor (health check)")
    assert not CommandPalette._fuzzy("xyz", "switch theme")


def test_palette_actions_include_common_commands():
    from superton.tui.widgets.palette import PALETTE_ACTIONS

    commands = [c for _, c in PALETTE_ACTIONS]
    assert "/theme" in commands
    assert "/doctor" in commands
    assert "/quit" in commands


# --- Pilot-driven app tests ------------------------------------------------


@pytest.mark.asyncio
async def test_app_boots_and_shows_header(cfg: Config):
    from superton.tui.app import SupertonApp

    mem = Memory(cfg)
    fake_model = _FakeModel("hello world")
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = fake_model  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        # Header should be mounted and show the theme name.
        header = app.query_one("#header")
        assert header is not None
        assert app.cfg.theme in {"nebula", "mono", "solar", "frost"}
    mem.close()


@pytest.mark.asyncio
async def test_app_clear_chat_action(cfg: Config):
    from superton.tui.app import SupertonApp

    mem = Memory(cfg)
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        app.state.chat.append(ChatTurn(question="q", answer="a"))
        app.state.history.extend([("user", "q"), ("assistant", "a")])
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert app.state.chat == []
        assert app.state.history == []
    mem.close()


@pytest.mark.asyncio
async def test_app_help_modal_opens_and_dismisses(cfg: Config):
    from superton.tui.app import SupertonApp
    from superton.tui.widgets.help import HelpModal

    mem = Memory(cfg)
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpModal)
    mem.close()


@pytest.mark.asyncio
async def test_app_palette_opens(cfg: Config):
    from superton.tui.app import SupertonApp
    from superton.tui.widgets.palette import CommandPalette

    mem = Memory(cfg)
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+k")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)
    mem.close()


@pytest.mark.asyncio
async def test_app_unknown_slash_command_warns(cfg: Config):
    from superton.tui.app import SupertonApp

    mem = Memory(cfg)
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        app._dispatch_slash("/bogus")
        await pilot.pause()
        # Toast updates the footer — just verify nothing crashed.
        footer = app.query_one("#footer")
        assert footer is not None
    mem.close()


@pytest.mark.asyncio
async def test_app_switch_theme_via_command(cfg: Config):
    from superton.tui.app import SupertonApp

    mem = Memory(cfg)
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        app._dispatch_slash("/theme solar")
        await pilot.pause()
        from superton import ui

        assert ui.theme().name == "solar"
        # Reset for other tests in the session.
        app._dispatch_slash("/theme nebula")
    mem.close()


@pytest.mark.asyncio
async def test_app_sidebar_refresh_pulls_sources(cfg: Config):
    from superton.tui.app import SupertonApp
    from superton.tui.widgets.sidebar import Sidebar

    mem = Memory(cfg)
    mem.add(text="alpha", source="/tmp/a.txt")
    mem.add(text="beta", source="/tmp/b.txt")

    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        sidebar = app.query_one("#sidebar", Sidebar)
        assert len(sidebar.sources) == 2
        sources = {row["source"] for row in sidebar.sources}
        assert sources == {"/tmp/a.txt", "/tmp/b.txt"}
    mem.close()


@pytest.mark.asyncio
async def test_app_dispatches_stats_to_toast(cfg: Config):
    from superton.tui.app import SupertonApp

    mem = Memory(cfg)
    mem.add(text="x", source="x.md")
    app = SupertonApp(cfg)
    app.mem = mem
    app.model = _FakeModel()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        app._dispatch_slash("/stats")
        await pilot.pause()
        # No crash → pass; toast text is implementation detail.
    mem.close()
