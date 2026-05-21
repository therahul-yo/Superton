"""Drawer-view modal: full text + metadata for a selected drawer/source."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from superton.memory import Drawer


class DrawerView(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", "close"),
        ("q", "dismiss", "close"),
    ]

    def __init__(self, drawer: Drawer, *, total_in_source: int = 1) -> None:
        super().__init__()
        self.drawer = drawer
        self.total = total_in_source

    def compose(self) -> ComposeResult:
        with Vertical(id="help"):  # reuse the help modal styling
            yield Static(
                f"[b]drawer[/] [dim]{self.drawer.id[:8]}[/]  ·  "
                f"[dim]{self.drawer.source}[/]  ·  "
                f"[dim]{self.drawer.wing}/{self.drawer.room}[/]  ·  "
                f"[dim]{self.total} drawer(s) in source[/]"
            )
            with VerticalScroll():
                # Render as markdown so code fences in drawer text light up.
                yield Markdown(self.drawer.text)
