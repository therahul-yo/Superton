"""Ctrl+K command palette — fuzzy match across slash commands + actions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView

PALETTE_ACTIONS: list[tuple[str, str]] = [
    ("switch theme", "/theme"),
    ("switch model · fast",  "/model fast"),
    ("switch model · better", "/model better"),
    ("switch model · strong", "/model strong"),
    ("doctor (health check)", "/doctor"),
    ("show palace stats",     "/stats"),
    ("list sources",          "/sources"),
    ("rebuild semantic index", "/reindex"),
    ("clear conversation",    "/clear"),
    ("import claude-code",    "/import claude-code"),
    ("import chatgpt …",      "/import chatgpt "),
    ("import cursor",         "/import cursor"),
    ("import amp",            "/import amp"),
    ("show help",             "?"),
    ("quit",                  "/quit"),
]


class PaletteAction(Message):
    """User picked an entry in the palette — the app should dispatch its slash."""

    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__()


class CommandPalette(ModalScreen[None]):
    """Centred modal with a filter input and a fuzzy-matched action list."""

    BINDINGS = [("escape", "dismiss", "close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            yield Input(placeholder="type to filter…", id="palette-input")
            yield ListView(id="palette-list")

    def on_mount(self) -> None:
        self._refresh("")
        self.query_one("#palette-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "palette-input":
            self._refresh(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "palette-input":
            return
        lv = self.query_one("#palette-list", ListView)
        # Submit the first visible match if Enter is pressed in the filter.
        if lv.children:
            first = lv.children[0]
            if isinstance(first, ListItem) and first.name:
                self.post_message(PaletteAction(first.name))
                self.dismiss()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item is not None and item.name:
            self.post_message(PaletteAction(item.name))
            self.dismiss()

    def _refresh(self, q: str) -> None:
        lv = self.query_one("#palette-list", ListView)
        lv.clear()
        f = q.lower().strip()
        for label, command in PALETTE_ACTIONS:
            if f and not self._fuzzy(f, label.lower()):
                continue
            lv.append(ListItem(Label(f"{label:30}  {command}"), name=command))

    @staticmethod
    def _fuzzy(needle: str, hay: str) -> bool:
        """Lightweight subsequence matcher — 'sw md' matches 'switch model'."""
        i = 0
        for ch in hay:
            if i < len(needle) and needle[i] == ch:
                i += 1
        return i == len(needle)
