"""Header widget — status pills row at the top of the TUI.

Mirrors the design doc: theme · model · backend · palace size.
"""

from __future__ import annotations

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusHeader(Widget):
    """Single-row header showing the current SuperTon session at a glance."""

    DEFAULT_CSS = ""

    backend_online: reactive[bool] = reactive(False)
    drawers: reactive[int] = reactive(0)
    theme_name: reactive[str] = reactive("nebula")
    model_profile: reactive[str] = reactive("fast")
    pending_op: reactive[str | None] = reactive(None)

    def compose(self):
        with Horizontal():
            yield Static("❍ SuperTon", classes="header-title", id="header-title")
            yield Static("·", id="header-sep-1")
            yield Static("", id="header-theme", classes="header-pill primary")
            yield Static("·", id="header-sep-2")
            yield Static("", id="header-model", classes="header-pill")
            yield Static("·", id="header-sep-3")
            yield Static("", id="header-backend", classes="header-pill")
            yield Static("", id="header-spacer")
            yield Static("", id="header-palace", classes="header-pill")

    def on_mount(self) -> None:
        self._refresh_pills()

    def watch_backend_online(self, _online: bool) -> None:
        self._refresh_pills()

    def watch_drawers(self, _n: int) -> None:
        self._refresh_pills()

    def watch_theme_name(self, _name: str) -> None:
        self._refresh_pills()

    def watch_model_profile(self, _p: str) -> None:
        self._refresh_pills()

    def watch_pending_op(self, _op: str | None) -> None:
        self._refresh_pills()

    def _refresh_pills(self) -> None:
        try:
            self.query_one("#header-theme", Static).update(f" {self.theme_name} ")
            self.query_one("#header-model", Static).update(f" miniton:{self.model_profile} ")

            backend = self.query_one("#header-backend", Static)
            if self.pending_op:
                backend.update(f" ⟳ {self.pending_op} ")
                backend.set_classes("header-pill")
            elif self.backend_online:
                backend.update(" ● online ")
                backend.set_classes("header-pill online")
            else:
                backend.update(" ○ offline ")
                backend.set_classes("header-pill offline")

            self.query_one("#header-palace", Static).update(f" palace · {self.drawers} ")
        except Exception:  # noqa: BLE001 — widget not mounted yet
            pass
