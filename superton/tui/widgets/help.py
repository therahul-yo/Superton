"""Help modal — shown via `?` or F1."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_TEXT = """\
[b]SuperTon TUI · key bindings[/]

[b]Global[/]
  ?, F1          show this help
  Ctrl+K         command palette
  Ctrl+B         toggle sidebar
  Ctrl+L         clear conversation
  Tab            cycle focus
  Esc            close modal / return to chat
  Ctrl+C × 2     quit

[b]Sidebar[/]
  ↑ / ↓          navigate sources
  Enter          open source
  /              filter sources

[b]Chat input[/]
  Enter          send message
  ↑ / ↓          history
  /cmd args      run slash command (same as classic shell)

[dim]Press Esc to close.[/]
"""


class HelpModal(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", "close"),
        ("q", "dismiss", "close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help"):
            yield Static(HELP_TEXT)
