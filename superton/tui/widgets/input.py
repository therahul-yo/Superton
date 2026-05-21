"""Message input row: themed prompt glyph + Input widget.

Submitted text is dispatched to the app via `MessageSubmitted`. History
navigation (↑/↓) is handled here using a small ring buffer.
"""

from __future__ import annotations

from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static


class MessageSubmitted(Message):
    """Fired when the user presses Enter on a non-empty input."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class MessageInput(Widget):
    """Single-line themed input with persistent history navigation."""

    DEFAULT_CSS = "MessageInput { height: 3; }"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._cursor: int | None = None

    def compose(self):
        with Horizontal():
            yield Static("›", id="input-glyph")
            yield Input(placeholder="Ask Miniton, or /help", id="message-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "message-input":
            return
        text = event.value.strip()
        if not text:
            return
        self._history.append(text)
        self._cursor = None
        event.input.value = ""
        self.post_message(MessageSubmitted(text))

    def focus_input(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self.query_one("#message-input", Input).focus()

    def on_key(self, event) -> None:
        if not self._history:
            return
        if event.key == "up":
            self._cursor = (
                len(self._history) - 1 if self._cursor is None else max(0, self._cursor - 1)
            )
            self._apply_history()
            event.stop()
        elif event.key == "down":
            if self._cursor is None:
                return
            if self._cursor >= len(self._history) - 1:
                self._cursor = None
                self.query_one("#message-input", Input).value = ""
            else:
                self._cursor += 1
                self._apply_history()
            event.stop()

    def _apply_history(self) -> None:
        if self._cursor is None:
            return
        self.query_one("#message-input", Input).value = self._history[self._cursor]
