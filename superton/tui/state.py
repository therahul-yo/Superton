"""Shared state types for the SuperTon TUI.

The TUI keeps a single `AppState` on the app instance; widgets read from
it via Textual's reactive system. Mutations are funnelled through message
handlers so widgets stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from superton.chat import ChatTurn
from superton.config import Config
from superton.memory import Drawer

Mode = Literal["chatting", "searching", "viewing", "help", "palette"]
Focus = Literal["chat", "sidebar", "palette"]


@dataclass
class SidebarState:
    sources: list[dict] = field(default_factory=list)
    cursor: int = 0
    filter: str = ""
    selected_drawer: Drawer | None = None


@dataclass
class AppState:
    cfg: Config
    chat: list[ChatTurn] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)
    sidebar: SidebarState = field(default_factory=SidebarState)
    focus: Focus = "chat"
    mode: Mode = "chatting"
    backend_online: bool = False
    pending_op: str | None = None

    def push_turn(self, turn: ChatTurn) -> None:
        self.chat.append(turn)
        self.history.append(("user", turn.question))
        self.history.append(("assistant", turn.answer))
        # Bound the history ring buffer.
        if len(self.history) > 12:
            self.history = self.history[-12:]
