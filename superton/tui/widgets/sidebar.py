"""Sidebar: scrollable source list + fuzzy filter input.

Sources come from `Memory.sources()`. Selecting one yields a
`SourceSelected` message the app handles by opening drawer-view mode.
"""

from __future__ import annotations

from pathlib import Path

from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static


class SourceSelected(Message):
    """Fired when the user presses Enter on a sidebar row."""

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__()


class SearchRequested(Message):
    """Fired when the user types into the sidebar's filter and presses Enter."""

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__()


class Sidebar(Widget):
    """Recent sources with a fuzzy filter on top."""

    can_focus = True

    sources: reactive[list[dict]] = reactive(list, recompose=False)
    filter_text: reactive[str] = reactive("")

    def compose(self):
        with Vertical():
            yield Static("recent sources", id="sidebar-title")
            yield Input(placeholder="filter…", id="sidebar-filter")
            yield ListView(id="sidebar-list")

    def watch_sources(self, sources: list[dict]) -> None:
        self._populate()

    def watch_filter_text(self, _: str) -> None:
        self._populate()

    def _populate(self) -> None:
        try:
            lv = self.query_one("#sidebar-list", ListView)
        except Exception:  # noqa: BLE001
            return
        lv.clear()
        f = self.filter_text.lower().strip()
        for row in self.sources:
            label = self._format_row(row)
            if f and f not in label.lower():
                continue
            lv.append(ListItem(Label(label), name=row["source"]))

    @staticmethod
    def _format_row(row: dict) -> str:
        source = row.get("source", "")
        n = row.get("drawers", 0)
        # Show basename so the sidebar stays narrow; full path lives in metadata.
        name = source.split(":", 1)[-1]
        name = Path(name).name if "/" in name else name
        return f"{name[:24]:24}  {n:>3}"

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "sidebar-filter":
            self.filter_text = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sidebar-filter" and event.value.strip():
            self.post_message(SearchRequested(event.value.strip()))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item is not None and item.name:
            self.post_message(SourceSelected(item.name))
