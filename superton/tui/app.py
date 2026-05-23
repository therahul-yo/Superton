"""SupertonApp — full-screen Textual TUI."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from superton import chat, errors, ui
from superton.config import Config, write_settings
from superton.logging import get_logger
from superton.memory import Memory
from superton.model import Model
from superton.tui.state import AppState
from superton.tui.theme import theme_to_css
from superton.tui.widgets.chat import ChatTranscript
from superton.tui.widgets.drawer_view import DrawerView
from superton.tui.widgets.header import StatusHeader
from superton.tui.widgets.help import HelpModal
from superton.tui.widgets.input import MessageInput, MessageSubmitted
from superton.tui.widgets.palette import CommandPalette, PaletteAction
from superton.tui.widgets.sidebar import SearchRequested, Sidebar, SourceSelected

log = get_logger("tui")


class SupertonApp(App[None]):
    """Default interactive mode for SuperTon (opt-in via `superton tui` in 0.2.0)."""

    CSS = ""  # set dynamically in on_mount via theme_to_css

    BINDINGS = [
        Binding("ctrl+k", "open_palette", "palette", priority=True),
        Binding("ctrl+b", "toggle_sidebar", "sidebar"),
        Binding("ctrl+l", "clear_chat", "clear"),
        Binding("question_mark", "help", "help"),
        Binding("f1", "help", "help"),
        Binding("ctrl+c", "quit", "quit", priority=True),
    ]

    def __init__(self, cfg: Config | None = None) -> None:
        super().__init__()
        self.cfg = cfg or Config.load()
        # Memory and Model are created lazily on mount so test fixtures can
        # inject fakes (see tests/test_tui.py).
        self.mem: Memory | None = None
        self.model: Model | None = None
        self.state = AppState(cfg=self.cfg)

    # -- lifecycle -----------------------------------------------------------

    def on_mount(self) -> None:
        self.stylesheet.add_source(theme_to_css(ui.theme()))
        self.stylesheet.parse()
        self.refresh_css()

        # Lazy-init the heavy collaborators so tests can patch them.
        if self.mem is None:
            self.mem = Memory(self.cfg)
        if self.model is None:
            self.model = Model(self.cfg)

        self._refresh_state()
        self._set_focus_to_input()

    def compose(self) -> ComposeResult:
        yield StatusHeader(id="header")
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            with Vertical(id="chat-container"):
                yield ChatTranscript(id="chat")
                yield MessageInput(id="input-row")
        yield ModeFooter(id="footer")

    # -- actions -------------------------------------------------------------

    def action_open_palette(self) -> None:
        self.push_screen(CommandPalette())

    def action_help(self) -> None:
        self.push_screen(HelpModal())

    def action_toggle_sidebar(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", Sidebar)
            sidebar.display = not sidebar.display
        except Exception:  # noqa: BLE001
            pass

    def action_clear_chat(self) -> None:
        self.state.chat.clear()
        self.state.history.clear()
        chat_widget = self.query_one("#chat", ChatTranscript)
        chat_widget.clear()
        self._toast("conversation cleared")

    # -- message handlers ----------------------------------------------------

    def on_message_submitted(self, event: MessageSubmitted) -> None:
        text = event.text
        if text in {"/quit", "/exit", "quit", "exit"}:
            self._stop_model(quiet=True)
            self.exit()
            return
        if text.startswith("/"):
            self._dispatch_slash(text)
            return
        self._handle_chat(text)

    def on_palette_action(self, event: PaletteAction) -> None:
        self._dispatch_slash(event.command)

    def on_source_selected(self, event: SourceSelected) -> None:
        if self.mem is None:
            return
        drawers = self.mem.drawers_for_source(event.source, limit=10)
        if drawers:
            self.push_screen(DrawerView(drawers[0], total_in_source=len(drawers)))

    def on_search_requested(self, event: SearchRequested) -> None:
        # Sidebar filter Enter falls through to a real search query.
        self._handle_chat(event.query)

    # -- core flows ----------------------------------------------------------

    def _handle_chat(self, question: str) -> None:
        if self.mem is None or self.model is None:
            return

        transcript = self.query_one("#chat", ChatTranscript)
        transcript.write_question(question)

        plan = chat.plan_answer(self.mem, question, history=self.state.history)

        transcript.begin_assistant()
        self.state.pending_op = "thinking"
        self._refresh_state()

        if plan.refusal is not None:
            from superton.chat import ChatTurn

            turn = ChatTurn(question=question, answer=plan.refusal, refused=True)
            transcript.finish_assistant(turn)
            self.state.push_turn(turn)
            self.state.pending_op = None
            self._refresh_state()
            return

        # Run the generation in a worker so streaming doesn't block the UI.
        self.run_worker(self._stream_in_worker(plan, question), exclusive=True)

    async def _stream_in_worker(self, plan, question: str) -> None:
        transcript = self.query_one("#chat", ChatTranscript)
        buf: list[str] = []
        if self.model is None:
            return
        try:
            # Textual's worker model expects async; we wrap the sync generator.
            for tok in chat.stream_answer(self.model, plan):
                buf.append(tok)
                # Batch into ~50ms flushes by checking every token. Cheap.
                transcript.stream_token(tok)
            text = "".join(buf).strip()
        except Exception as e:  # noqa: BLE001
            log.exception("model stream failed")
            text = chat.fallback_answer(plan)
            from superton.chat import ChatTurn

            turn = ChatTurn(question=question, answer=text, hits=plan.hits, error=str(e))
            transcript.finish_assistant(turn)
            self.state.push_turn(turn)
            self.state.pending_op = None
            self._refresh_state()
            return

        if not text:
            text = "I found related memory, but Miniton returned an empty answer."

        from superton.chat import ChatTurn

        turn = ChatTurn(question=question, answer=text, hits=plan.hits)
        transcript.finish_assistant(turn)
        self.state.push_turn(turn)
        self.state.pending_op = None
        self._refresh_state()

    def _dispatch_slash(self, command: str) -> None:
        """Run a slash command. Mirrors the shell's command map so muscle
        memory carries across.
        """
        cmd = command.strip()
        if cmd in {"/quit", "/exit"}:
            self._stop_model(quiet=True)
            self.exit()
            return
        if cmd in {"/help", "?"}:
            self.action_help()
            return
        if cmd == "/clear":
            self.action_clear_chat()
            return
        if cmd == "/stop":
            self._stop_model()
            return
        if cmd == "/stats":
            if self.mem is not None:
                s = self.mem.stats()
                self._toast(
                    f"palace · {s['drawers']} drawers · {s['wings']} wings · {s['rooms']} rooms"
                )
            return
        if cmd == "/sources":
            self._refresh_sidebar()
            self._toast("sidebar refreshed")
            return
        if cmd == "/doctor":
            self._toast("run `superton doctor` from a shell — full report is CLI-only")
            return
        if cmd == "/reindex":
            self._toast("reindexing…", kind="info")
            if self.mem is not None:
                total = self.mem.reindex_semantic()
                self._toast(f"reindexed {total} drawers")
            return
        if cmd.startswith("/theme"):
            parts = cmd.split(None, 1)
            if len(parts) == 2:
                self._switch_theme(parts[1].strip())
            else:
                themes = ", ".join(ui.THEMES)
                self._toast(f"themes: {themes}")
            return
        if cmd.startswith("/model"):
            parts = cmd.split(None, 1)
            if len(parts) == 2:
                self._switch_model(parts[1].strip())
            else:
                self._toast(f"model profile: {self.cfg.model_profile}")
            return
        if cmd.startswith("/import"):
            self._toast(
                "imports run via `superton import …` from a shell (TUI 0.2 is opt-in for chat)",
                kind="warning",
            )
            return
        self._toast(f"unknown command: {cmd}", kind="warning")

    def _switch_theme(self, name: str) -> None:
        if name not in ui.THEMES:
            self._toast(f"unknown theme · choose one of: {', '.join(ui.THEMES)}", kind="warning")
            return
        write_settings(self.cfg.home, theme=name)
        self.cfg = Config.load()
        ui.set_theme(name)
        # Re-render CSS from the new theme.
        self.stylesheet.add_source(theme_to_css(ui.theme()))
        self.stylesheet.parse()
        self.refresh_css()
        self._refresh_state()
        self._toast(f"theme → {name}")

    def _switch_model(self, profile: str) -> None:
        from superton.config import MODEL_PROFILES

        if profile not in MODEL_PROFILES:
            self._toast(
                f"unknown profile · choose: {', '.join(MODEL_PROFILES)}", kind="warning"
            )
            return
        selected = MODEL_PROFILES[profile]
        write_settings(
            self.cfg.home,
            model_profile=profile,
            base_model=selected["base_model"],
            hf_model=selected["hf_model"],
        )
        self.cfg = Config.load()
        if self.model is not None:
            self.model.close()
        self.model = Model(self.cfg)
        self._refresh_state()
        self._toast(f"model → {profile} · {self.cfg.base_model}")

    # -- helpers -------------------------------------------------------------

    def _set_focus_to_input(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self.query_one("#input-row", MessageInput).focus_input()

    def _refresh_state(self) -> None:
        try:
            header = self.query_one("#header", StatusHeader)
            header.theme_name = ui.theme().name
            header.model_profile = self.cfg.model_profile
            header.pending_op = self.state.pending_op
            if self.mem is not None:
                header.drawers = self.mem.stats()["drawers"]
            if self.model is not None:
                try:
                    header.backend_online = self.model.ping()
                except Exception:  # noqa: BLE001
                    header.backend_online = False
            footer = self.query_one("#footer", ModeFooter)
            footer.set_context(
                theme=ui.theme().name,
                model=self.cfg.model_profile,
                drawers=header.drawers,
            )
            self._refresh_sidebar()
        except Exception as e:  # noqa: BLE001
            log.debug("state refresh skipped: %s", e)

    def _refresh_sidebar(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", Sidebar)
            if self.mem is not None:
                sidebar.sources = self.mem.sources(limit=200)
        except Exception:  # noqa: BLE001
            pass

    def _toast(self, msg: str, *, kind: str = "info") -> None:
        # Lightweight toast: replace the footer right-side text for 2.5s.
        try:
            footer = self.query_one("#footer", ModeFooter)
            footer.toast(msg, kind=kind)
        except Exception:  # noqa: BLE001
            log.info("toast: %s", msg)

    def _stop_model(self, *, quiet: bool = False) -> bool:
        if self.model is None:
            if not quiet:
                self._toast("model not running")
            return False
        stopped = self.model.stop(self.cfg.model)
        if not quiet:
            self._toast(
                f"stopped {self.cfg.model}" if stopped else f"not running: {self.cfg.model}",
                kind="success" if stopped else "info",
            )
        return stopped

    # -- shutdown ------------------------------------------------------------

    def on_unmount(self) -> None:
        if self.mem is not None:
            self.mem.close()
        if self.model is not None:
            self.model.close()


class ModeFooter(Static):
    """Footer with mode breadcrumb + key bindings. Toast-able right side."""

    DEFAULT_CSS = ""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.theme_name = "nebula"
        self.model_profile = "proton"
        self.drawers = 0

    def on_mount(self) -> None:
        self._render_default()

    def set_context(self, *, theme: str, model: str, drawers: int) -> None:
        self.theme_name = theme
        self.model_profile = model
        self.drawers = drawers
        self._render_default()

    def _render_default(self) -> None:
        self.update(
            f"[bold]chatting[/]  ·  {self.theme_name}  ·  {self.model_profile}  ·  "
            f"{self.drawers} drawers  ·  ? help  ·  Ctrl+K palette  ·  Ctrl+B sidebar"
        )

    def toast(self, msg: str, *, kind: str = "info") -> None:
        color = {"info": "white", "warning": "yellow", "error": "red", "success": "green"}.get(
            kind, "white"
        )
        self.update(f"[bold]chatting[/]  ·  [{color}]{msg}[/]")
        self.set_timer(2.5, self._render_default)


def run_tui(cfg: Config | None = None) -> None:
    """Entry point used by `superton tui`."""
    try:
        SupertonApp(cfg).run()
    except KeyboardInterrupt:
        # Textual already handled cleanup; suppress the noisy traceback.
        pass
    except Exception as e:  # noqa: BLE001
        log.exception("TUI crashed")
        errors.render(e)
        raise
