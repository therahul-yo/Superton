"""Interactive CLI shell for SuperTon."""

from __future__ import annotations

from pathlib import Path

from superton import __version__, chat, errors, ui
from superton.config import Config, write_settings
from superton.logging import get_logger
from superton.memory import Memory
from superton.model import Model, ModelError

log = get_logger("shell")

# Constants re-exported for cli.py and other callers — canonical home is `chat`.
ANSWER_CONTEXT_DRAWERS = chat.ANSWER_CONTEXT_DRAWERS
ANSWER_DRAWER_CHARS = chat.ANSWER_DRAWER_CHARS
CONVERSATION_WINDOW = chat.CONVERSATION_WINDOW

# Back-compat shims: the cli module imports these names from shell. They
# forward to the pure `chat` implementation.
_relevant_hits = chat.relevant_hits
_any_token_match = chat.any_token_match
_expand_hits_for_answer = chat.expand_hits_for_answer
_looks_memory_specific = chat.looks_memory_specific
_wants_source_expansion = chat.wants_source_expansion
_query_tokens = chat.query_tokens
_is_meta_question = chat.is_meta_question
_should_retrieve = chat.should_retrieve
_contextualize_query = chat.contextualize_query
_format_suggestions = chat.format_suggestions
_format_history = chat.format_history
_build_system_prompt = chat.build_system_prompt

console = ui.console()

# Re-exported for any external callers; the canonical sources live in `chat`.
GREETINGS = chat.GREETINGS
META_PHRASES = chat.META_PHRASES
STOPWORDS = chat.STOPWORDS
COMMAND_HELP = {
    "/add": "ingest a file or directory",
    "/doctor": "show runtime health",
    "/forget-source": "remove all drawers from a source",
    "/help": "show shortcuts",
    "/import": "pull conversations from another AI tool",
    "/model": "show model configuration",
    "/quit": "exit SuperTon",
    "/refresh": "reingest a source and remove stale chunks",
    "/reindex": "rebuild semantic index",
    "/search": "search memory",
    "/sources": "list indexed sources",
    "/stats": "show palace stats",
    "/stop": "stop Superton without quitting",
    "/theme": "show/switch CLI theme",
}
ANSWER_CONTEXT_DRAWERS = 10
ANSWER_DRAWER_CHARS = 1200


class _Status:
    """Live state shown in the prompt's bottom toolbar.

    Refreshed after every REPL turn. Cheap to compute — just reads the
    cached config and a small SQLite count. The Ollama probe is cached
    for a few seconds so toolbar refresh doesn't hammer the daemon.
    """

    _BACKEND_TTL = 4.0  # seconds

    def __init__(self, cfg: Config, mem: Memory, model: Model | None = None) -> None:
        self.cfg = cfg
        self.mem = mem
        self.model = model
        self._backend_last_check: float = 0.0
        self._backend_online: bool = False

    def refresh(self, cfg: Config, model: Model | None = None) -> None:
        self.cfg = cfg
        if model is not None:
            self.model = model
        # Force a recheck of backend status on the next toolbar refresh.
        self._backend_last_check = 0.0

    def _backend_status(self) -> str:
        """Cached probe so the toolbar refresh stays under a millisecond."""
        import time as _time

        if self.model is None:
            return "?"
        if _time.time() - self._backend_last_check > self._BACKEND_TTL:
            try:
                self._backend_online = self.model.ping()
            except Exception as e:  # noqa: BLE001
                log.debug("backend ping failed: %s", e)
                self._backend_online = False
            self._backend_last_check = _time.time()
        return "online" if self._backend_online else "offline"

    def toolbar_html(self) -> str:
        try:
            n = self.mem.stats()["drawers"]
        except (RuntimeError, KeyError, OSError) as e:
            log.debug("toolbar stats failed: %s", e)
            n = 0
        t = ui.theme()
        backend = self._backend_status()
        glyph = "●" if backend == "online" else ("○" if backend == "offline" else "·")
        # prompt_toolkit HTML — keep it dim and one-line.
        return (
            f"<bottom-toolbar.text>"
            f"{glyph} {backend} · palace: {n} drawers · model: {self.cfg.model} · "
            f"theme: {t.name}  ·  /help · /quit"
            f"</bottom-toolbar.text>"
        )


def _prompt(status: _Status | None = None) -> str:
    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.lexers import Lexer
        from prompt_toolkit.styles import Style

        class SlashCompleter(Completer):
            def get_completions(self, document, complete_event):
                from prompt_toolkit.formatted_text import FormattedText

                text = document.text_before_cursor
                if not text.startswith("/"):
                    return
                parts = text.split()
                if len(parts) == 2 and parts[0] == "/theme":
                    word = parts[-1]
                    for theme_obj in ui.list_themes():
                        if theme_obj.name.startswith(word) or word in theme_obj.name:
                            yield Completion(
                                theme_obj.name,
                                start_position=-len(word),
                                display_meta=theme_obj.label,
                            )
                    return
                if " " in text:
                    return
                for command, help_text in COMMAND_HELP.items():
                    if command.startswith(text):
                        # Color the leading slash separately so the menu visually
                        # echoes the toolbar/lexer treatment of slash commands.
                        styled = FormattedText([
                            ("class:completion.slash", "/"),
                            ("class:completion.cmd", command[1:]),
                        ])
                        yield Completion(
                            command,
                            start_position=-len(text),
                            display=styled,
                            display_meta=help_text,
                        )

        class SuperTonLexer(Lexer):
            """Color slash commands vs their arguments live as the user types."""

            def lex_document(self, document):
                def get_line(lineno: int):
                    line = document.lines[lineno]
                    if not line.startswith("/"):
                        return [("class:text", line)]
                    parts = line.split(" ", 1)
                    head = parts[0]
                    tail = " " + parts[1] if len(parts) > 1 else ""
                    return [("class:cmd", head), ("class:arg", tail)]
                return get_line

        # Theme-aware styles for the prompt glyph, lexer classes, and the
        # bottom status bar. We route all theme colors through ui.pt_color
        # because prompt_toolkit does not understand Rich's shade-named
        # greys (grey50, grey70, ...). Under mono that would raise ValueError
        # and drop the whole prompt into the plain-input fallback — which
        # was the 'no / menu, no bottom toolbar' bug.
        t = ui.theme()
        primary_pt = ui.pt_color(t.primary)
        secondary_pt = ui.pt_color(t.secondary)
        muted_pt = ui.pt_color(t.muted)
        neutral_pt = ui.pt_color(t.neutral) or "fg:#FFFFFF"
        primary_bg_pt = ui.pt_bg(t.primary)
        if "bold" not in primary_pt.split():
            primary_pt = f"bold {primary_pt}".strip()

        # High-contrast selection style: theme-primary background with a
        # near-black foreground so the highlighted completion stays legible
        # on every theme. `reverse <fg>` looks fine in isolation but on
        # several terminals it collapses the foreground into the terminal's
        # own background colour, which on dark profiles is near-invisible.
        # See https://github.com/prompt-toolkit/python-prompt-toolkit/issues/...
        current_fg = "fg:#0a0a0a"
        current_meta_fg = "fg:#2b2b2b"

        pt_style = Style.from_dict({
            "cmd": primary_pt,
            "arg": secondary_pt,
            "text": neutral_pt,
            "glyph": primary_pt,
            "bottom-toolbar": f"{muted_pt} noreverse",
            "bottom-toolbar.text": muted_pt,
            # Slash-command completion menu: leading slash in primary, the
            # rest of the command in the secondary accent; description (meta)
            # column dim. When a row is the current selection we paint the
            # whole row primary-bg + near-black-fg so it reads cleanly across
            # every theme (no `reverse` fragility).
            "completion.slash": primary_pt,
            "completion.cmd": secondary_pt,
            "completion-menu.completion": muted_pt,
            "completion-menu.completion.current": f"{primary_bg_pt} {current_fg} bold",
            # Nested classes inside the current row inherit the bg but need
            # their own fg overridden so the inner colours don't fight the
            # selection background.
            "completion-menu.completion.current completion.slash": f"{current_fg} bold",
            "completion-menu.completion.current completion.cmd": current_fg,
            "completion-menu.meta.completion": muted_pt,
            "completion-menu.meta.completion.current": f"{primary_bg_pt} {current_meta_fg}",
            "placeholder": muted_pt,
        })

        # Persistent command history across shell sessions.
        cfg = Config.load()
        history_dir = cfg.home / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_dir / "shell"))

        def _bottom_toolbar():
            if status is None:
                return None
            return HTML(status.toolbar_html())

        return prompt(
            HTML("<glyph>&gt;</glyph> "),
            completer=SlashCompleter(),
            complete_while_typing=True,
            history=history,
            lexer=SuperTonLexer(),
            style=pt_style,
            bottom_toolbar=_bottom_toolbar if status is not None else None,
            # Ghost hint shown on the empty prompt; disappears on first
            # keystroke. Quiet onboarding without a persistent banner.
            placeholder=HTML("<placeholder>ask anything · /help</placeholder>"),
        )
    except (ImportError, ValueError):
        return input("> ")


def _print_assistant(answer: str, hits=None) -> None:
    """Print Superton's reply. Tests assert exact body substrings."""
    ui.blank()
    ui.console().print(f"[bold {ui.theme().primary}]Superton[/]")
    ui.console().print(answer)
    if hits:
        ui.citations(hits[:3])
    ui.blank()


def _run_with_spinner(label: str, work):
    if not ui.console().is_terminal:
        return work()
    with ui.spinner(label):
        return work()


def _print_intro(cfg: Config, mem: Memory) -> None:
    s = mem.stats()
    ui.header(cfg, s)
    if not cfg.first_repl_done:
        ui.blank()
        ui.panel(
            "type / to see commands · type your question to chat · ^D to quit\n"
            "press ? any time for the cheatsheet",
            title="quick start",
            anchor=True,
        )
        write_settings(cfg.home, first_repl_done="1")
    # The live bottom toolbar carries the routine hints (/help, /quit, palace
    # state). On a brand-new palace, the user lands here with zero context on
    # what to do next — show a short ordered tutorial instead of the one-line
    # nudge.
    if s["drawers"] == 0:
        t = ui.theme()
        ui.blank()
        ui.panel(
            f"[bold]Your palace is empty.[/bold]  Three ways to fill it:\n\n"
            f"  [{t.primary}]1[/]  [bold]/add ~/Documents[/bold]      "
            f"[{t.muted}]ingest files or a directory[/]\n"
            f"  [{t.primary}]2[/]  [bold]/import claude-code[/bold]   "
            f"[{t.muted}]pull past Claude Code transcripts[/]\n"
            f"  [{t.primary}]3[/]  paste any file path at the prompt\n\n"
            f"[{t.muted}]Once you have drawers, just ask a question.[/]",
            title="getting started",
            anchor=True,
        )
        ui.blank()
    ui.rule()


def _unescape_shell_path(value: str) -> str:
    """Strip shell-style backslash escapes from a raw REPL token.

    macOS Terminal (and most *nix shells) backslash-escape spaces and
    special chars when you drag-and-drop a file into the prompt. Inside
    the REPL we read the line verbatim, so those escapes survive into
    the string and `Path(r"foo\\ bar.txt").exists()` returns False —
    there is no literal file with a backslash in its name.

    Replace every `\\<c>` with `<c>` for any non-newline `c`. Idempotent
    for paths that contain no backslashes.
    """
    if "\\" not in value:
        return value
    out: list[str] = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value) and value[i + 1] != "\n":
            out.append(value[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _resolve_repl_path(value: str) -> Path:
    """Normalize a raw REPL token into a Path (no existence check)."""
    return Path(_unescape_shell_path(value.strip().strip("'\""))).expanduser()


def _path_from_input(text: str) -> Path | None:
    value = text.strip()
    if not value or "\n" in value:
        return None
    path = _resolve_repl_path(value)
    return path if path.exists() else None


def _ingest_path(mem: Memory, path: Path) -> tuple[int, int, int]:
    """Ingest a path. Returns (files, drawers, deduped)."""
    from superton.ingest import chunk_text, read_file, walk

    files = 0
    drawers = 0
    deduped = 0
    for file in walk(path):
        try:
            body = read_file(file)
        except (ValueError, RuntimeError, UnicodeDecodeError) as e:
            ui.warn(f"skipped {file.name}", str(e))
            continue
        files += 1
        for chunk in chunk_text(body):
            mem.add(text=chunk, source=str(file))
            if mem.last_insert_was_new:
                drawers += 1
            else:
                deduped += 1
    return files, drawers, deduped


def _print_search_hits(hits) -> None:
    """Render hits as compact stacked cards.

    Each hit gets a one-line header (cite + score) plus a single-line
    preview, separated by a dim rule. This mirrors Claude Code's tool-
    result presentation: clearly delineated but visually quiet.
    """
    from rich.console import Group
    from rich.text import Text

    ui.blank()
    t = ui.theme()
    cards = []
    for idx, hit in enumerate(hits):
        preview = " ".join(hit.drawer.text.split())[:220]
        score = float(getattr(hit, "score", 0.0) or 0.0)
        score_col = ui.score_color(score)
        header = Text()
        header.append(f"[{idx + 1}]  ", style=t.muted)
        header.append(hit.drawer.id[:8], style=t.secondary)
        header.append("  ", style=t.muted)
        header.append(Path(hit.drawer.source).name, style=t.muted)
        header.append(f"  {score:0.2f} ", style=score_col)
        header.append_text(ui.score_bar(score))
        parts = [header, Text(f"  {preview}", style=t.muted)]
        if idx != len(hits) - 1:
            parts.append(Text("  ·", style=t.rule))
        cards.append(Group(*parts))
    # Staggered cascade: each hit lands ~45 ms after the previous one.
    ui.reveal_cards(cards)
    ui.blank()


def _print_sources(mem: Memory) -> None:
    rows = mem.sources(limit=20)
    ui.blank()
    if not rows:
        ui.hint("no sources indexed yet")
        ui.blank()
        return
    table = ui.make_table("drawers", "source")
    for row in rows:
        table.add_row(str(row["drawers"]), row["source"])
    ui.print_table(table)
    ui.blank()


def _print_model(cfg: Config) -> None:
    ui.blank()
    ui.console().print(
        f"● [bold]{cfg.model}[/bold]  {cfg.base_model}  "
        f"[{ui.theme().muted}]MiniCPM5 · 1B · 128K context[/]"
    )
    ui.blank()


def _print_themes(cfg: Config) -> None:
    ui.blank()
    for t in ui.list_themes():
        marker = "●" if t.name == cfg.theme else "○"
        swatch = (
            f"[{t.primary}]██[/] [{t.secondary}]██[/] "
            f"[{t.success}]✓[/] [{t.warning}]![/] [{t.error}]✗[/]"
        )
        ui.console().print(
            f"{marker} [bold]{t.name}[/bold]  {swatch}  "
            f"[{ui.theme().muted}]{t.label}[/]"
        )
    ui.blank()


def _run_import(mem: Memory, spec: str) -> None:
    """Handle `/import <source> [path]` from inside the shell.

    Thin wrapper around the dedicated importer classes — keeps the CLI's
    `superton import ...` and the shell's `/import` in lockstep without
    shelling out.
    """
    parts = spec.split(None, 1)
    name = parts[0].lower()
    extra = parts[1].strip() if len(parts) > 1 else ""
    ui.blank()
    try:
        if name == "claude-code":
            from superton.importers.claude_code import ClaudeCodeImporter

            with ui.spinner(
                "importing Claude Code sessions",
                phases=["Discovering sessions", "Parsing transcripts", "Indexing turns"],
            ):
                sessions, drawers = ClaudeCodeImporter(mem).import_all(None)
            ui.ok(f"imported {drawers} drawers", f"from {sessions} Claude Code sessions")
        elif name == "chatgpt":
            if not extra:
                ui.warn("chatgpt import needs a path", "e.g. /import chatgpt ~/Downloads/chatgpt-export")
                ui.blank()
                return
            from superton.importers.chatgpt import ChatGPTImporter

            path = Path(extra).expanduser()
            if not path.exists():
                ui.warn(f"not found: {path}")
                ui.blank()
                return
            with ui.spinner(
                "importing ChatGPT conversations",
                phases=["Reading export", "Parsing conversations", "Indexing messages"],
            ):
                conversations, drawers = ChatGPTImporter(mem).import_all(path)
            ui.ok(f"imported {drawers} drawers", f"from {conversations} ChatGPT conversations")
        elif name in {"cursor", "amp"}:
            from superton.importers.generic_threads import GenericThreadImporter

            default_root = Path.home() / f".{name}"
            with ui.spinner(
                f"importing {name} threads",
                phases=["Discovering files", "Parsing", "Indexing"],
            ):
                files, drawers = GenericThreadImporter(
                    mem, name, default_root
                ).import_all(None)
            ui.ok(f"imported {drawers} drawers", f"from {files} {name} files")
        else:
            ui.warn(
                f"unknown source: {name}",
                "choose one of: claude-code, chatgpt <path>, cursor, amp",
            )
    except (FileNotFoundError, PermissionError, ValueError, RuntimeError) as e:
        log.error("import %s failed: %s", name, e)
        errors.render(e)
    except Exception as e:
        log.exception("import %s crashed", name)
        ui.err(f"import failed: {e}")
        ui.hint("re-run with [bold]SUPERTON_LOG=debug[/bold] for the traceback")
    ui.blank()


def _switch_theme(name: str) -> Config:
    if name not in ui.THEMES:
        ui.blank()
        ui.warn(f"unknown theme — choose one of: {', '.join(ui.THEMES)}")
        ui.blank()
        return Config.load()
    cfg = Config.load()
    write_settings(cfg.home, theme=name)
    ui.set_theme(name)
    t = ui.theme()
    swatch = (
        f"[bold {t.primary}]SuperTon[/] → "
        f"[{t.primary}]██[/] [{t.secondary}]██[/] "
        f"[{t.success}]✓[/] [{t.warning}]![/] [{t.error}]✗[/]  "
        f"[{t.muted}]{t.label}[/]"
    )
    ui.flash(swatch)
    ui.blank()
    ui.ok(f"theme → {name}", ui.theme().label)
    ui.blank()
    return Config.load()


def _stop_active_model(model: Model, cfg: Config, *, quiet: bool = False) -> bool:
    """Stop the currently configured SuperTon runner in Ollama."""
    stopped = model.stop(cfg.model)
    if not quiet:
        ui.blank()
        if stopped:
            ui.ok(f"stopped {cfg.model}")
        else:
            ui.step(f"not running: {cfg.model}")
        ui.blank()
    return stopped


def _answer(
    mem: Memory,
    model: Model,
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> str:
    """Render a chat turn through the shell's Rich console.

    The retrieval / refusal / prompt-building logic lives in `superton.chat`.
    This function is the *display* half: it takes the planned answer,
    streams tokens through `ui.stream_answer`, and prints citations.
    """
    # Retrieval can take a few hundred ms on large palaces — show a
    # spinner so the pause between Enter and the Superton header doesn't
    # read as a hang. The thinking spinner inside `ui.stream_answer`
    # covers the gap from then until the first token.
    with ui.spinner("searching palace…"):
        plan = chat.plan_answer(mem, question, history=history)
    if plan.refusal is not None:
        _print_assistant(plan.refusal)
        return plan.refusal

    try:
        answer = ui.stream_answer(chat.stream_answer(model, plan))
    except ModelError as e:
        log.warning("model backend unavailable during answer: %s", e)
        text = chat.fallback_answer(plan)
        _print_assistant(text, hits=plan.hits)
        return text

    if not answer:
        text = "I found related memory, but Superton returned an empty answer."
        _print_assistant(text, hits=plan.hits)
        return text

    if plan.hits:
        ui.citations(plan.hits[:3])
    ui.blank()
    return answer


def run() -> None:
    cfg = Config.load()
    ui.set_theme(cfg.theme)
    mem = Memory(cfg)
    model = Model(cfg)
    status = _Status(cfg, mem, model)
    history: list[tuple[str, str]] = []
    try:
        _print_intro(cfg, mem)
        while True:
            try:
                text = _prompt(status).strip()
            except (EOFError, KeyboardInterrupt):
                ui.blank()
                break
            if not text:
                continue
            if text in {"/quit", "/exit", "quit", "exit"}:
                _stop_active_model(model, cfg, quiet=True)
                break
            if text in {"/help", "?"}:
                ui.console().print(
                    "ingest: /add <path> · /import claude-code|chatgpt|cursor|amp · "
                    "/refresh <path>\n"
                    "search: /search <query> · /sources · /forget-source <name>\n"
                    "config: /model · /theme · /reindex\n"
                    "system: /doctor · /stats · /clear · /stop · /quit"
                )
                continue
            if text == "/stop":
                _stop_active_model(model, cfg)
                continue
            if text == "/import" or text.startswith("/import "):
                source = text.removeprefix("/import").strip()
                if not source:
                    ui.blank()
                    ui.hint("usage: /import claude-code | chatgpt <path> | cursor | amp")
                    ui.blank()
                    continue
                _run_import(mem, source)
                status.refresh(cfg)
                continue
            if text == "/clear":
                history = []
                ui.blank()
                ui.ok("conversation cleared")
                ui.blank()
                continue
            if text == "/model":
                _print_model(cfg)
                continue
            if text == "/theme":
                _print_themes(cfg)
                continue
            if text.startswith("/theme "):
                cfg = _switch_theme(text.removeprefix("/theme ").strip())
                status.refresh(cfg)
                continue
            if text == "/doctor":
                from superton.doctor import render_doctor_report

                ui.blank()
                render_doctor_report(cfg)
                ui.blank()
                continue
            if text == "/sources":
                _print_sources(mem)
                continue
            if text.startswith("/forget-source "):
                source = text.removeprefix("/forget-source ").strip()
                removed = mem.forget_source(source)
                ui.blank()
                if removed:
                    ui.ok(f"forgot {removed} drawer(s)", f"from {source}")
                else:
                    ui.warn(f"no source matched {source}")
                ui.blank()
                continue
            if text.startswith("/refresh "):
                path = _resolve_repl_path(text.removeprefix("/refresh "))
                if not path.exists():
                    ui.blank()
                    ui.warn(f"not found: {path}")
                    ui.blank()
                    continue
                removed = 0
                for file in path.rglob("*") if path.is_dir() else [path]:
                    if file.is_file():
                        removed += mem.forget_source(str(file))
                files, drawers, _deduped = _ingest_path(mem, path)
                ui.blank()
                ui.diff_summary(removed=removed, added=drawers)
                ui.blank()
                ui.ok(f"refreshed {files} file(s)")
                ui.blank()
                continue
            if text == "/reindex":
                with ui.spinner(
                    "rebuilding semantic index",
                    phases=["Reading drawers", "Computing embeddings", "Writing index"],
                ):
                    total = mem.reindex_semantic()
                ui.blank()
                ui.ok(f"reindexed {total} drawers")
                ui.blank()
                continue
            if text == "/stats":
                s = mem.stats()
                ui.blank()
                ui.kv([
                    ("drawers", str(s["drawers"])),
                    ("wings", str(s["wings"])),
                    ("rooms", str(s["rooms"])),
                    ("backend", str(s["backend"])),
                ])
                ui.blank()
                continue
            inline_path = _path_from_input(text)
            if inline_path is not None:
                files, drawers, deduped = _ingest_path(mem, inline_path)
                suffix = f"from {files} file(s)"
                if deduped:
                    suffix += f"  ·  {deduped} deduped"
                ui.ok(f"ingested {drawers} drawers", suffix)
                continue
            if text == "/search":
                ui.blank()
                ui.hint("usage: /search <query>")
                ui.blank()
                continue
            if text.startswith("/search "):
                query = text.removeprefix("/search ").strip()
                with ui.spinner(
                    f"searching for {query!r}",
                    phases=["Embedding query", "Scanning drawers", "Re-ranking hits"],
                ):
                    hits = _relevant_hits(query, mem.search(query, limit=8))
                if not hits:
                    ui.blank()
                    ui.shimmer(f"  scanning palace for {query!r}…")
                    ui.hint("no drawers matched")
                    ui.blank()
                    continue
                _print_search_hits(hits[:5])
                continue
            if text.startswith("/add "):
                path = _resolve_repl_path(text.removeprefix("/add "))
                if not path.exists():
                    ui.blank()
                    ui.warn(f"not found: {path}")
                    ui.blank()
                    continue
                files, drawers, deduped = _ingest_path(mem, path)
                ui.blank()
                suffix = f"from {files} file(s)"
                if deduped:
                    suffix += f"  ·  {deduped} deduped"
                ui.ok(f"ingested {drawers} drawers", suffix)
                ui.blank()
                continue
            _answer_text = _answer(mem, model, text, history=history)
            history.append(("user", text))
            history.append(("assistant", _answer_text))
            # Bound the ring buffer.
            if len(history) > CONVERSATION_WINDOW * 2:
                history = history[-CONVERSATION_WINDOW * 2 :]
    finally:
        mem.close()
        model.close()


# Back-compat: some older tests/scripts looked for __version__ here.
__all__ = [
    "_answer",
    "_expand_hits_for_answer",
    "_ingest_path",
    "_looks_memory_specific",
    "_relevant_hits",
    "_wants_source_expansion",
    "run",
    "__version__",
]
