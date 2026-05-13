"""Interactive CLI shell for SuperTon."""

from __future__ import annotations

from pathlib import Path

from superton import __version__, ui
from superton.config import MODEL_PROFILES, Config, write_settings
from superton.memory import Memory
from superton.model import Model, ModelError

console = ui.console()

GREETINGS = {"hi", "hey", "hello", "yo", "sup"}

# Questions about the assistant itself. Matching one of these means we should
# NOT retrieve (random drawers only add noise) and should NOT include
# conversation history (the 1.5B model otherwise pattern-matches on the
# previous reply and repeats it verbatim).
META_PHRASES = (
    "what are you", "what r u", "what are u",
    "who are you", "who r u", "who are u",
    "what can you do", "what do you do",
    "what is your use", "what is ur use", "whats your use", "whats ur use",
    "tell me about yourself", "introduce yourself",
    "what is this", "whats this", "wats this",
    "how do you work", "how does this work",
    "what r u for", "what are u for",
)
STOPWORDS = {
    "a", "about", "an", "and", "are", "from", "give", "gimme", "how", "i",
    "in", "is", "it", "me", "my", "of", "on", "the", "this", "to", "u",
    "use", "what", "you",
}
COMMAND_HELP = {
    "/add": "ingest a file or directory",
    "/doctor": "show runtime health",
    "/forget-source": "remove all drawers from a source",
    "/help": "show shortcuts",
    "/model": "show/switch model profile",
    "/quit": "exit SuperTon",
    "/refresh": "reingest a source and remove stale chunks",
    "/reindex": "rebuild semantic index",
    "/search": "search memory",
    "/sources": "list indexed sources",
    "/stats": "show palace stats",
    "/theme": "show/switch CLI theme",
}


class _Status:
    """Live state shown in the prompt's bottom toolbar.

    Refreshed after every REPL turn. Cheap to compute — just reads the
    cached config and a small SQLite count.
    """

    def __init__(self, cfg: Config, mem: Memory) -> None:
        self.cfg = cfg
        self.mem = mem

    def refresh(self, cfg: Config) -> None:
        self.cfg = cfg

    def toolbar_html(self) -> str:
        try:
            n = self.mem.stats()["drawers"]
        except Exception:
            n = 0
        t = ui.theme()
        # prompt_toolkit HTML — keep it dim and one-line.
        return (
            f"<bottom-toolbar.text>"
            f"palace: {n} drawers · model: {self.cfg.model_profile} · "
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
                text = document.text_before_cursor
                if not text.startswith("/"):
                    return
                parts = text.split()
                if len(parts) == 2 and parts[0] == "/model":
                    word = parts[-1]
                    for profile in MODEL_PROFILES:
                        if profile.startswith(word) or word in profile:
                            yield Completion(profile, start_position=-len(word))
                    return
                if len(parts) == 2 and parts[0] == "/theme":
                    word = parts[-1]
                    for name in ui.THEMES:
                        if name.startswith(word) or word in name:
                            yield Completion(name, start_position=-len(word))
                    return
                if " " in text:
                    return
                for command, help_text in COMMAND_HELP.items():
                    if command.startswith(text):
                        yield Completion(
                            command,
                            start_position=-len(text),
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
        # bottom status bar. The status bar holds the live palace summary so
        # the user always sees where they are — same role as Claude Code's
        # persistent footer.
        t = ui.theme()
        pt_style = Style.from_dict({
            "cmd": f"bold {t.primary}",
            "arg": t.secondary if t.secondary.startswith("#") else "",
            "text": "",
            "glyph": f"bold {t.primary}" if t.primary.startswith("#") or t.primary.startswith("bold") else t.primary,
            "bottom-toolbar": f"{t.muted} noreverse",
            "bottom-toolbar.text": f"{t.muted}",
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
        )
    except (ImportError, ValueError):
        return input("> ")


def _print_assistant(answer: str, hits=None) -> None:
    """Print Miniton's reply. Tests assert exact body substrings."""
    ui.blank()
    ui.console().print(f"[bold {ui.theme().primary}]Miniton[/]")
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
    # The live bottom toolbar carries the routine hints (/help, /quit, palace
    # state). Here we only surface the empty-palace nudge, since it's the one
    # hint that demands action before the user can do anything useful.
    if s["drawers"] == 0:
        ui.footer_hints(["⚠  no drawers yet — add a file with /add <path>"])
    ui.rule()


def _path_from_input(text: str) -> Path | None:
    value = text.strip().strip("'\"")
    if not value or "\n" in value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() else None


def _ingest_path(mem: Memory, path: Path) -> tuple[int, int]:
    from superton.ingest import chunk_text, read_file, walk

    files = 0
    drawers = 0
    for file in walk(path):
        try:
            body = read_file(file)
        except (ValueError, RuntimeError, UnicodeDecodeError) as e:
            ui.warn(f"skipped {file.name}", str(e))
            continue
        files += 1
        for chunk in chunk_text(body):
            mem.add(text=chunk, source=str(file))
            drawers += 1
    return files, drawers


def _query_tokens(query: str) -> set[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in query)
    return {token for token in cleaned.split() if len(token) > 1 and token not in STOPWORDS}


def _looks_memory_specific(query: str) -> bool:
    normalized = query.lower()
    personal_markers = (
        "resume", "resue", "cv", "pdf", "document", "file",
        "from my", "from his", "fromhis", "rahul",
    )
    if any(marker in normalized for marker in personal_markers):
        return True
    return "project" in normalized and ("my" in normalized or "rahul" in normalized)


def _relevant_hits(question: str, hits):
    """Re-rank retrieval hits to prefer keyword-overlap, but never throw away
    semantically strong matches.

    Before Phase A (when retrieval was SQLite FTS + naive semantic), this was
    a hard filter. With the MemPalace hybrid retriever it would reject
    otherwise-correct hits just because the user's word isn't literally in
    the drawer. We now treat keyword overlap as a bonus, not a gate.
    """
    if not hits:
        return []
    tokens = _query_tokens(question)
    if not tokens:
        return list(hits)
    scored: list[tuple[float, int, object]] = []
    for idx, hit in enumerate(hits):
        haystack = f"{Path(hit.drawer.source).name} {hit.drawer.text[:2500]}".lower()
        matches = sum(1 for token in tokens if token in haystack)
        # Keep the original retrieval score as the base; overlap nudges the
        # order but cannot drop a drawer.
        base = float(getattr(hit, "score", 0.0) or 0.0)
        boost = 0.15 * matches
        scored.append((base + boost, -idx, hit))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [h for _, _, h in scored]


def _print_search_hits(hits) -> None:
    """Render hits as compact stacked cards.

    Each hit gets a one-line header (cite + score) plus a single-line
    preview, separated by a dim rule. This mirrors Claude Code's tool-
    result presentation: clearly delineated but visually quiet.
    """
    from rich.text import Text

    ui.blank()
    t = ui.theme()
    for idx, hit in enumerate(hits):
        preview = " ".join(hit.drawer.text.split())[:220]
        score = float(getattr(hit, "score", 0.0) or 0.0)
        score_col = ui.score_color(score)
        header = Text()
        header.append(f"[{idx + 1}]  ", style=t.muted)
        header.append(hit.drawer.id[:8], style=t.secondary)
        header.append("  ", style=t.muted)
        header.append(Path(hit.drawer.source).name, style=t.muted)
        header.append(f"  {score:0.2f}", style=score_col)
        ui.console().print(header)
        ui.console().print(f"  [{t.muted}]{preview}[/]")
        if idx != len(hits) - 1:
            ui.console().print(f"  [{t.rule}]·[/]")
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
    for name, data in MODEL_PROFILES.items():
        marker = "●" if name == cfg.model_profile else "○"
        ui.console().print(
            f"{marker} [bold]{name}[/bold]  {data['base_model']}  "
            f"[{ui.theme().muted}]{data['label']}[/]"
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


def _switch_model(profile: str) -> Config:
    if profile not in MODEL_PROFILES:
        ui.blank()
        ui.warn("choose one of: fast, better, strong")
        ui.blank()
        return Config.load()
    selected = MODEL_PROFILES[profile]
    cfg = Config.load()
    write_settings(
        cfg.home,
        model_profile=profile,
        base_model=selected["base_model"],
        hf_model=selected["hf_model"],
    )
    ui.flash(
        f"[bold {ui.theme().primary}]model[/] → "
        f"[bold]{profile}[/]  [{ui.theme().muted}]{selected['base_model']}[/]"
    )
    ui.blank()
    ui.ok(f"model profile → {profile}", selected["base_model"])
    ui.hint("run [bold]superton init --yes[/bold] to pull/rebuild if needed")
    ui.blank()
    return Config.load()


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


def _any_token_match(question: str, hits) -> bool:
    """True if at least one hit shares any meaningful token with the query.

    Used to decide whether to refuse a memory-specific question. We only look
    at token *presence* — the ranking of hits is handled by `_relevant_hits`.
    """
    tokens = _query_tokens(question)
    if not tokens:
        return False
    for hit in hits:
        haystack = f"{Path(hit.drawer.source).name} {hit.drawer.text[:2500]}".lower()
        if any(token in haystack for token in tokens):
            return True
    return False


def _format_suggestions(raw_hits, limit: int = 2) -> str:
    """Render a 'did you mean' list from raw retrieval hits.

    Dedupes by source filename so the user sees distinct candidate documents,
    not three chunks from the same file.
    """
    if not raw_hits:
        return ""
    seen: set[str] = set()
    lines: list[str] = []
    for hit in raw_hits:
        src = Path(hit.drawer.source).name
        if src in seen:
            continue
        seen.add(src)
        lines.append(f"  • {src}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _is_meta_question(question: str) -> bool:
    """True if the message is a greeting or a question about the assistant
    itself (not about the user's stored memory)."""
    normalized = question.lower().strip(" !?.")
    if normalized in GREETINGS:
        return True
    return any(phrase in normalized for phrase in META_PHRASES)


def _should_retrieve(question: str) -> bool:
    # Skip retrieval for greetings and meta-questions. Random drawers only
    # confuse the small model on these.
    return not _is_meta_question(question)


def _build_system_prompt(*, has_drawers: bool) -> str:
    """Two distinct prompts — one for grounded answers, one for free-form.

    Branching on the presence of drawers makes the instruction unambiguous
    for small (1.5B) models. When drawers exist, we forbid the refuse path.
    When they don't, the model answers as a normal local assistant.
    """
    if has_drawers:
        return (
            "You are Miniton, a local assistant in the SuperTon CLI. "
            "MEMORY DRAWERS from the user's palace are supplied below — the "
            "user has already given you access to them.\n\n"
            "Your job:\n"
            "- Use ONLY the drawers to answer. Quote specific facts from them.\n"
            "- For vague questions like 'X details', 'tell me about X', or "
            "'summary', produce 3-6 concise bullet points that summarize what "
            "the drawers say about the subject.\n"
            "- Cite drawer ids inline like [abcd1234] when quoting.\n"
            "- Never ask for a file, link, or path — the user has already "
            "ingested it.\n"
            "- Never say 'I do not have that in memory'. The drawers are "
            "right here. Read them and answer.\n"
            "- Keep answers under 8 lines unless the user asks for detail."
        )
    return (
        "You are Miniton — a small local AI assistant built into the "
        "SuperTon CLI. You run entirely on the user's machine via Ollama "
        "and answer questions grounded in their personal palace of memories "
        "(notes, documents, past AI-tool conversations). No memory drawers "
        "were retrieved for this message, so answer briefly and "
        "conversationally as a normal assistant. If asked who you are or "
        "what you do, give a short one-paragraph self-introduction. Keep "
        "answers under 6 lines."
    )


# --- conversation memory ------------------------------------------------------

CONVERSATION_WINDOW = 6  # keep last N (user, assistant) turns


def _format_history(history: list[tuple[str, str]]) -> str:
    """Render recent turns for the prompt — compact, role-tagged."""
    if not history:
        return ""
    lines: list[str] = []
    for role, text in history[-CONVERSATION_WINDOW:]:
        lines.append(f"{role}: {text.strip()}")
    return "\n".join(lines)


def _contextualize_query(question: str, history: list[tuple[str, str]] | None) -> str:
    """For short follow-up questions, prepend the most recent user turn so
    retrieval stays on the current conversation topic.

    Without this, 'check pdf source' after 'rahul resume memory' re-runs
    semantic search against only 'check pdf source' and typically pulls
    unrelated Claude Code file-listing drawers.
    """
    if not history:
        return question
    # A 'short follow-up' is anything with fewer than 5 whitespace-separated
    # words. Covers cases like 'check pdf source', 'and the projects?',
    # 'what about python', etc.
    if len(question.split()) >= 5:
        return question
    last_user = None
    for role, text in reversed(history):
        if role == "user":
            last_user = text
            break
    if not last_user:
        return question
    return f"{last_user} {question}"


def _answer(
    mem: Memory,
    model: Model,
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> str:
    """Answer a single user message. Returns the assistant text so callers
    can append it to conversation history."""
    search_query = _contextualize_query(question, history)
    raw_hits = mem.search(search_query, limit=8) if _should_retrieve(question) else []
    hits = _relevant_hits(question, raw_hits)
    # For memory-specific queries (resume, "rahul", document, etc.) we refuse
    # when no retrieved drawer shares even a single meaningful token with the
    # query. This keeps Miniton from confabulating an answer from drawers
    # that were semantically nearby but talk about something unrelated.
    if _looks_memory_specific(question) and not _any_token_match(question, hits):
        base = "I do not have matching memory for that."
        suggestions = _format_suggestions(raw_hits)
        if suggestions:
            refusal = (
                f"{base}\n\n"
                "Did you mean one of these?\n"
                f"{suggestions}\n\n"
                "Ask about one of those, or add the source with `/add <path>`."
            )
        else:
            refusal = (
                f"{base} Add the resume or document first with "
                "`/add <path>` or paste the file path directly."
            )
        _print_assistant(refusal)
        return refusal
    context = "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} source:{Path(h.drawer.source).name}]\n{h.drawer.text[:700]}"
        for h in hits[:3]
    )
    system = _build_system_prompt(has_drawers=bool(hits))
    if _is_meta_question(question):
        # For greetings and 'what are you' style questions, hand the model a
        # clean slate: no drawers (already empty), no history. Otherwise the
        # small model pattern-matches on its previous reply and repeats it.
        chat_history: list[dict[str, str]] = []
    else:
        chat_history = [
            {"role": "user" if role == "user" else "assistant", "content": text}
            for role, text in (history or [])[-CONVERSATION_WINDOW * 2:]
        ]
    if hits:
        parts = [f"Memory drawers:\n\n{context}", f"User message: {question}"]
        parts.append("Write a concise answer, not a dump of the context.")
        prompt = "\n\n".join(parts)
    else:
        prompt = question
    try:
        def generate_answer():
            if hasattr(model, "backend") and model.backend() is None and hasattr(model, "start_ollama"):
                model.start_ollama(timeout=5.0)
            yield from model.generate(prompt, system=system, history=chat_history)

        answer = ui.stream_answer(generate_answer())
    except ModelError:
        if hits:
            answer = (
                "I found related memory, but the model backend is unavailable. "
                f"Top match: [{hits[0].drawer.id[:8]}] {Path(hits[0].drawer.source).name}"
            )
        else:
            answer = "Miniton is not available. Run `superton init` to start/build the local model."
        _print_assistant(answer, hits=hits)
        return answer
    if not answer:
        answer = "I found related memory, but Miniton returned an empty answer."
        _print_assistant(answer, hits=hits)
        return answer
    if hits:
        ui.citations(hits[:3])
    ui.blank()
    return answer


def run() -> None:
    cfg = Config.load()
    ui.set_theme(cfg.theme)
    mem = Memory(cfg)
    model = Model(cfg)
    status = _Status(cfg, mem)
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
                break
            if text in {"/help", "?"}:
                ui.console().print(
                    "/add <path> · /search <query> · /sources · /forget-source <name> · "
                    "/refresh <path> · /model [fast|better|strong] · /theme · /clear · "
                    "/doctor · /reindex · /quit"
                )
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
            if text.startswith("/model "):
                cfg = _switch_model(text.removeprefix("/model ").strip())
                model.close()
                model = Model(cfg)
                status.refresh(cfg)
                continue
            if text == "/theme":
                _print_themes(cfg)
                continue
            if text.startswith("/theme "):
                cfg = _switch_theme(text.removeprefix("/theme ").strip())
                status.refresh(cfg)
                continue
            if text == "/doctor":
                s = mem.stats()
                ui.blank()
                ui.kv([
                    ("home", str(cfg.home)),
                    ("model", f"{cfg.model_profile} · {cfg.base_model}"),
                    ("memory", f"{s['backend']} · {s['drawers']} drawers"),
                    ("semantic", "on" if s["semantic_enabled"] else "off"),
                    ("theme", f"{cfg.theme} · {ui.theme().label}"),
                ])
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
                path = Path(text.removeprefix("/refresh ").strip()).expanduser()
                if not path.exists():
                    ui.blank()
                    ui.warn(f"not found: {path}")
                    ui.blank()
                    continue
                removed = 0
                for file in path.rglob("*") if path.is_dir() else [path]:
                    if file.is_file():
                        removed += mem.forget_source(str(file))
                files, drawers = _ingest_path(mem, path)
                ui.blank()
                ui.ok(
                    f"refreshed {files} file(s)",
                    f"removed {removed}, added {drawers}",
                )
                ui.blank()
                continue
            if text == "/reindex":
                with ui.spinner("rebuilding semantic index"):
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
            path = _path_from_input(text)
            if path is not None:
                files, drawers = _ingest_path(mem, path)
                ui.ok(f"ingested {drawers} drawers", f"from {files} file(s)")
                continue
            if text == "/search":
                ui.blank()
                ui.hint("usage: /search <query>")
                ui.blank()
                continue
            if text.startswith("/search "):
                query = text.removeprefix("/search ").strip()
                with ui.spinner(f"searching for {query!r}"):
                    hits = _relevant_hits(query, mem.search(query, limit=8))
                if not hits:
                    ui.blank()
                    ui.hint("no drawers matched")
                    ui.blank()
                    continue
                _print_search_hits(hits[:5])
                continue
            if text.startswith("/add "):
                path = Path(text.removeprefix("/add ").strip()).expanduser()
                if not path.exists():
                    ui.blank()
                    ui.warn(f"not found: {path}")
                    ui.blank()
                    continue
                files, drawers = _ingest_path(mem, path)
                ui.blank()
                ui.ok(f"ingested {drawers} drawers", f"from {files} file(s)")
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
    "_ingest_path",
    "_looks_memory_specific",
    "_relevant_hits",
    "run",
    "__version__",
]
