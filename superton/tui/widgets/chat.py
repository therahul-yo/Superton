"""Chat transcript: scrollable list of user/assistant turns plus citations.

Uses Textual's `RichLog` so streaming token batches just `write()` without
re-rendering the whole transcript. Citation chips are appended after the
answer finishes streaming so the order matches the shell.
"""

from __future__ import annotations

from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog

from superton.chat import ChatTurn
from superton.memory import SearchHit
from superton.ui import theme as ui_theme


class ChatTranscript(RichLog):
    """Scrollable chat history.

    Each turn is rendered as:
        ▎ you
          <question>
        ▎ Miniton
          <answer markdown>
        sources  [ 1 ] abcd1234 file.md  …
    """

    DEFAULT_CSS = "ChatTranscript { padding: 0 0; }"

    def __init__(self, **kwargs):
        super().__init__(wrap=True, markup=True, **kwargs)
        # Anchor styles to the active theme so theme switches re-render
        # the next turn (existing scrollback keeps its colors — accepted
        # tradeoff to avoid full re-render on theme change).
        self._t = ui_theme()

    # -- writers -------------------------------------------------------------

    def write_question(self, question: str) -> None:
        t = ui_theme()
        head = Text()
        head.append("▎ ", style=t.secondary)
        head.append("you", style=f"bold {t.secondary}")
        self.write(head)
        self.write(Text("  " + question, style=t.neutral))
        self.write("")  # spacer

    def begin_assistant(self) -> None:
        """Print the `▎ Miniton` header. Subsequent `stream_token` calls add body."""
        t = ui_theme()
        head = Text()
        head.append("▎ ", style=t.primary)
        head.append("Miniton", style=f"bold {t.primary}")
        self.write(head)

    def stream_token(self, batch: str) -> None:
        """Append a batch of tokens to the in-progress assistant turn."""
        if not batch:
            return
        self.write(batch)

    def finish_assistant(self, turn: ChatTurn) -> None:
        """Re-render the final answer as markdown and append citation chips."""
        # We can't easily edit prior lines in RichLog; instead we add a
        # spacer + the markdown render so the streamed plain text and the
        # final formatted version sit together. Acceptable cost — the
        # streamed plaintext is visible and the formatted version is the
        # authoritative read.
        if turn.answer:
            self.write("")
            self.write(Markdown(turn.answer, code_theme="ansi_dark"))
        if turn.refused:
            self.write(Text("(refused)", style="italic"))
        elif turn.error:
            self.write(Text(f"(model error: {turn.error})", style="italic"))
        if turn.hits:
            self.write(self._citations_row(turn.hits[:3]))
        self.write("")

    def _citations_row(self, hits: list[SearchHit]) -> Text:
        t = ui_theme()
        row = Text("sources  ", style=t.muted)
        for i, h in enumerate(hits, 1):
            row.append(f" {i} ", style=f"bold {t.neutral} on {t.muted}")
            row.append(" ")
            row.append(h.drawer.id[:8], style=t.secondary)
            row.append(" ")
            row.append(Path(h.drawer.source).name, style=t.muted)
            if i != len(hits):
                row.append("  ")
        return row
