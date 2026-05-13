"""SuperTon command-line interface.

Commands:
  superton init                set up palace + check ollama + build Miniton
  superton add <path>          ingest file or directory
  superton ask "..."           query Miniton with palace context
  superton list                show recent drawers
  superton search "..."        semantic search with SQLite fallback
  superton forget <id>         remove a drawer
  superton stats               palace statistics
  superton theme [name]        show / switch CLI theme
  superton close               stop SuperTon model runners
  superton import <source>     pull conversations from other AI tools
  superton tune                edit Modelfile and rebuild Miniton
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

from superton import __version__, ui
from superton.blackhole import static_frame
from superton.config import MODEL_PROFILES, Config, write_settings
from superton.ingest import chunk_text, read_file, walk
from superton.memory import Memory
from superton.model import Model, ModelError, OllamaError

app = typer.Typer(
    name="superton",
    help="A tiny local LLM with infinite memory.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
)


def _cfg() -> Config:
    return Config.load()


def _print_header() -> None:
    cfg = _cfg()
    mem = Memory(cfg)
    s = mem.stats()
    mem.close()
    ui.console().print(static_frame(), justify="center")
    ui.console().print(
        f"  [{ui.theme().muted}]palace · {s['drawers']} drawers · {s['wings']} wings · "
        f"{s['rooms']} rooms[/]",
        justify="center",
    )
    ui.blank()


def _launch_shell() -> None:
    from superton.shell import run

    run()


def _project_modelfile() -> Path | None:
    package_modelfile = Path(__file__).resolve().parent / "Modelfile"
    if package_modelfile.exists():
        return package_modelfile
    modelfile = Path(__file__).resolve().parent.parent / "Modelfile"
    if modelfile.exists():
        return modelfile
    modelfile = Path.cwd() / "Modelfile"
    return modelfile if modelfile.exists() else None


def _render_modelfile(template: Path, cfg: Config) -> Path:
    """Render a runtime Modelfile with the configured hidden base model."""
    text = template.read_text(encoding="utf-8")
    lines = text.splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith("FROM "):
            lines[i] = f"FROM {cfg.base_model}"
            replaced = True
            break
    if not replaced:
        lines.insert(0, f"FROM {cfg.base_model}")

    build_dir = cfg.home / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    rendered = build_dir / "Modelfile.miniton"
    rendered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rendered


def _confirm_pull(model_name: str, purpose: str, *, yes: bool) -> bool:
    if yes:
        return True
    ui.blank()
    ui.panel(
        f"[bold]{model_name}[/bold]\n\n"
        f"{purpose}\n\n"
        f"[{ui.theme().muted}]This downloads model weights to your local Ollama store.[/]",
        title="Model Download",
        anchor=True,
    )
    return typer.confirm("Pull this model now?", default=True)


def _ingest_into_memory(mem: Memory, path: Path, *, wing: str, room: str) -> tuple[int, int, int]:
    files = list(walk(path))
    total_drawers = 0
    skipped = 0
    if not files:
        return 0, 0, 0
    with ui.progress("ingesting", total=len(files)) as advance:
        for f in files:
            rel = f.relative_to(path) if path.is_dir() else Path(f.name)
            try:
                text = read_file(f)
            except (ValueError, RuntimeError, UnicodeDecodeError) as e:
                ui.warn(f"skip {rel}", str(e))
                skipped += 1
                advance(description=f"ingesting  [dim]skip {rel}[/]")
                continue
            if not text.strip():
                advance(description=f"ingesting  [dim]empty {rel}[/]")
                continue
            for chunk in chunk_text(text):
                mem.add(text=chunk, source=str(f), wing=wing, room=room)
                total_drawers += 1
            advance(description=f"ingesting  [dim]{rel}[/]")
    return len(files) - skipped, total_drawers, skipped


def _build_miniton(cfg: Config, *, yes: bool) -> bool:
    if shutil.which("ollama") is None:
        ui.warn("ollama not found in PATH")
        ui.hint("install: [link]https://ollama.com/download[/link]")
        return False
    model = Model(cfg)
    if not model.ollama_ready():
        ui.step("starting ollama service")
        if not model.start_ollama():
            ui.warn("could not start ollama automatically")
            model.close()
            return False
    if not model.has_model(cfg.base_model):
        if not _confirm_pull(
            cfg.base_model,
            f"Required for {cfg.model_profile} profile.",
            yes=yes,
        ):
            model.close()
            return False
        subprocess.run(["ollama", "pull", cfg.base_model], check=False)
    modelfile = _project_modelfile()
    if modelfile is None:
        ui.err("Modelfile not found")
        model.close()
        return False
    rendered = _render_modelfile(modelfile, cfg)
    ok = model.build(rendered)
    model.close()
    return ok


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="show version"),
) -> None:
    if version:
        ui.console().print(f"superton {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _launch_shell()
        raise typer.Exit()


@app.command()
def welcome() -> None:
    """Show the SuperTon welcome tour at any time."""
    cfg = _cfg()
    mem = Memory(cfg)
    stats = mem.stats()
    mem.close()
    ui.welcome_tour(cfg, stats)


@app.command()
def init(
    skip_model: bool = typer.Option(False, "--no-model", help="skip ollama model build"),
    yes: bool = typer.Option(False, "--yes", "-y", help="accept setup prompts"),
) -> None:
    """Initialize the palace and build Miniton."""
    cfg = _cfg()
    cfg.home.mkdir(parents=True, exist_ok=True)
    cfg.palace_dir.mkdir(parents=True, exist_ok=True)

    ui.section("superton init", "palace + model setup")

    # ---------------------------------------------------------------------
    # Stage 1 — palace store
    # ---------------------------------------------------------------------
    with ui.stage("creating palace"):
        Memory(cfg).close()
        ui.stage_ok(f"palace at {cfg.palace_dir}")

    if skip_model:
        ui.stage_skip("skipped ollama model build (--no-model)")
        ui.blank()
        ui.next_steps_card(cfg)
        return

    # ---------------------------------------------------------------------
    # Stage 2 — ollama availability
    # ---------------------------------------------------------------------
    with ui.stage("checking ollama"):
        if shutil.which("ollama") is None:
            ui.stage_warn("ollama not found in PATH")
            ui.hint("install: [link]https://ollama.com/download[/link]")
            if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"):
                ui.stage_ok("Hugging Face fallback configured via HF_TOKEN")
            else:
                ui.hint(
                    "fallback: set [bold]HF_TOKEN[/bold] and "
                    "[bold]SUPERTON_MODEL_BACKEND=huggingface[/bold]"
                )
            ui.blank()
            ui.next_steps_card(cfg)
            return

        model = Model(cfg)
        if not model.ollama_ready() and not model.start_ollama():
            ui.stage_warn("could not start ollama automatically")
            ui.hint("run manually: [bold]ollama serve[/bold]")
            model.close()
            ui.blank()
            ui.next_steps_card(cfg)
            return
        ui.stage_ok(f"ollama running at {cfg.ollama_url}")

    # ---------------------------------------------------------------------
    # Stage 3 — base model
    # ---------------------------------------------------------------------
    with ui.stage(f"pulling base model · {cfg.base_model}"):
        if model.has_model(cfg.base_model):
            ui.stage_ok("already present")
        else:
            if not _confirm_pull(
                cfg.base_model,
                "Required to build Miniton, the local answer model.",
                yes=yes,
            ):
                ui.stage_warn("skipped model pull")
                model.close()
                ui.blank()
                ui.next_steps_card(cfg)
                return
            subprocess.run(["ollama", "pull", cfg.base_model], check=False)
            if not model.has_model(cfg.base_model):
                ui.stage_warn(f"failed to pull {cfg.base_model}")
                model.close()
                return
            ui.stage_ok("downloaded")

    # ---------------------------------------------------------------------
    # Stage 4 — embedding model
    # ---------------------------------------------------------------------
    with ui.stage(f"pulling embedding model · {cfg.embed_model}"):
        if model.has_model(cfg.embed_model):
            ui.stage_ok("already present")
        else:
            if not _confirm_pull(
                cfg.embed_model,
                "Required for local embeddings and better semantic memory.",
                yes=yes,
            ):
                ui.stage_warn("skipped embedding model pull")
                model.close()
                ui.blank()
                ui.next_steps_card(cfg)
                return
            subprocess.run(["ollama", "pull", cfg.embed_model], check=False)
            ui.stage_ok("downloaded")

    # ---------------------------------------------------------------------
    # Stage 5 — build Miniton
    # ---------------------------------------------------------------------
    with ui.stage("building Miniton"):
        modelfile = _project_modelfile()
        if modelfile is None:
            ui.stage_warn("Modelfile not found — using base model directly")
        else:
            rendered = _render_modelfile(modelfile, cfg)
            if model.build(rendered):
                ui.stage_ok(f"built as {cfg.model}")
            else:
                ui.stage_warn("model build failed — base model still usable")
    model.close()

    # ---------------------------------------------------------------------
    # Stage 6 — offer to import Claude Code sessions
    # ---------------------------------------------------------------------
    claude_root = Path.home() / ".claude" / "projects"
    if claude_root.exists() and any(claude_root.rglob("*.jsonl")):
        ui.blank()
        should_import = yes or typer.confirm(
            f"Found Claude Code sessions at {claude_root} — import them now?",
            default=False,
        )
        if should_import:
            with ui.stage("importing Claude Code sessions"):
                from superton.importers.claude_code import ClaudeCodeImporter

                mem = Memory(cfg)
                sessions, drawers = ClaudeCodeImporter(mem).import_all(None)
                mem.close()
                ui.stage_ok(f"{drawers} drawers from {sessions} sessions")

    # ---------------------------------------------------------------------
    # Final — next steps card
    # ---------------------------------------------------------------------
    ui.blank()
    ui.next_steps_card(cfg)


@app.command()
def add(
    path: Path = typer.Argument(..., exists=True, help="file or directory to ingest"),
    wing: str = typer.Option("default", "--wing", "-w"),
    room: str = typer.Option("default", "--room", "-r"),
) -> None:
    """Ingest a file or directory into the palace."""
    cfg = _cfg()
    mem = Memory(cfg)
    ui.section("add", f"{path}  → wing={wing} room={room}")
    files, total_drawers, _skipped = _ingest_into_memory(mem, path, wing=wing, room=room)
    mem.close()
    ui.blank()
    ui.ok(f"ingested {total_drawers} drawers", f"from {files} file(s)")


@app.command()
def refresh(
    path: Path = typer.Argument(..., exists=True, help="file or directory to replace in memory"),
    wing: str = typer.Option("default", "--wing", "-w"),
    room: str = typer.Option("default", "--room", "-r"),
) -> None:
    """Forget existing drawers from a source path, then ingest it again."""
    mem = Memory(_cfg())
    ui.section("refresh", str(path))
    removed = 0
    for f in walk(path):
        removed += mem.forget_source(str(f))
    files, drawers, _skipped = _ingest_into_memory(mem, path, wing=wing, room=room)
    mem.close()
    ui.ok(
        f"refreshed {files} file(s)",
        f"removed {removed} stale drawers, added {drawers}",
    )


@app.command()
def ask(
    question: str = typer.Argument(..., help="your question"),
    k: int = typer.Option(5, "--top-k", "-k"),
    why: bool = typer.Option(False, "--why", help="show retrieval trace"),
) -> None:
    """Ask Miniton a question. Answer is grounded in palace drawers."""
    cfg = _cfg()
    mem = Memory(cfg)
    with ui.spinner("retrieving from palace"):
        raw_hits = mem.search(question, limit=max(k, 8))
    from superton.shell import _any_token_match, _looks_memory_specific, _relevant_hits

    hits = _relevant_hits(question, raw_hits)[:k]
    if _looks_memory_specific(question) and not _any_token_match(question, hits):
        ui.warn("no matching memory found")
        ui.hint("add the source first with [bold]superton add <path>[/bold]")
        mem.close()
        return

    if why:
        ui.section("retrieval", f"top {len(hits)}")
        table = ui.make_table("drawer", "score", "source", "preview")
        for h in hits:
            preview = h.drawer.text.replace("\n", " ")[:80]
            score_style = ui.score_color(h.score)
            table.add_row(
                ui.style_id(h.drawer.id[:8]),
                f"[{score_style}]{h.score:.2f}[/]",
                ui.style_path(Path(h.drawer.source).name),
                preview,
            )
        if not hits:
            table.add_row("-", "-", "-", "no memory drawers matched")
        ui.print_table(table)
        ui.blank()

    context = "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} · {Path(h.drawer.source).name}]\n{h.drawer.text[:700]}"
        for h in hits
    )
    from superton.shell import _build_system_prompt

    system = _build_system_prompt(has_drawers=bool(hits))
    if hits:
        prompt = (
            f"MEMORY DRAWERS:\n\n{context}\n\n"
            f"User question: {question}\n\n"
            "Answer using only the drawers above."
        )
    else:
        prompt = (
            "No memory drawers were retrieved.\n\n"
            f"User question: {question}\n\n"
            "Answer briefly as a local model."
        )

    model = Model(cfg)
    if model.backend() is None:
        model.start_ollama(timeout=5.0)
    if model.backend() is None:
        ui.warn("no model backend available")
        ui.hint("run: [bold]superton init[/bold]")
        model.close()
        mem.close()
        return

    ui.console().print(f"  {ui.prompt_glyph()} ", end="")
    try:
        for tok in model.generate(prompt, system=system):
            ui.console().print(tok, end="")
        ui.blank()
        if hits:
            ui.citations(hits[:3])
    except (OllamaError, ModelError) as e:
        ui.err(f"{e}")
    finally:
        model.close()
        mem.close()


@app.command("list")
def list_drawers(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List recent drawers."""
    mem = Memory(_cfg())
    rows = mem.all(limit=limit)
    mem.close()
    ui.section("drawers", f"last {len(rows)}")
    table = ui.make_table("id", "wing/room", "source", "preview")
    for d in rows:
        preview = d.text.replace("\n", " ")[:70]
        table.add_row(
            ui.style_id(d.id[:8]),
            f"{d.wing}/{d.room}",
            ui.style_path(Path(d.source).name),
            preview,
        )
    ui.print_table(table)


@app.command()
def search(query: str, limit: int = typer.Option(10, "--limit", "-n")) -> None:
    """Semantic search across drawers with SQLite fallback."""
    mem = Memory(_cfg())
    with ui.spinner(f"searching palace for {query!r}"):
        hits = mem.search(query, limit=limit)
    if not hits:
        ui.warn("no drawers matched")
        mem.close()
        return
    ui.section("search", f"{len(hits)} matches")
    for h in hits:
        ui.console().print(ui.cite(h.drawer.id, h.drawer.source))
        ui.console().print(f"  {h.drawer.text[:400]}")
        ui.console().print(f"[{ui.theme().rule}]  " + "─" * 50 + "[/]")
    mem.close()


@app.command()
def forget(drawer_id: str) -> None:
    """Remove a drawer by ID."""
    mem = Memory(_cfg())
    if len(drawer_id) < 16:
        for d in mem.all(limit=10000):
            if d.id.startswith(drawer_id):
                drawer_id = d.id
                break
    removed = mem.forget(drawer_id)
    mem.close()
    if removed:
        ui.ok(f"forgot {drawer_id[:8]}")
    else:
        ui.warn(f"no drawer matched {drawer_id}")


@app.command("forget-source")
def forget_source(source: str) -> None:
    """Remove every drawer from a source path or filename."""
    mem = Memory(_cfg())
    removed = mem.forget_source(source)
    mem.close()
    if removed:
        ui.ok(f"forgot {removed} drawer(s)", f"from {source}")
    else:
        ui.warn(f"no source matched {source}")


@app.command()
def sources(limit: int = typer.Option(30, "--limit", "-n")) -> None:
    """List indexed source files."""
    mem = Memory(_cfg())
    rows = mem.sources(limit=limit)
    mem.close()
    ui.section("sources", f"{len(rows)} indexed")
    table = ui.make_table("drawers", "source")
    for row in rows:
        table.add_row(str(row["drawers"]), row["source"])
    ui.print_table(table)


@app.command("model")
def model_profile(
    profile: str | None = typer.Argument(None, help="fast, better, or strong"),
    yes: bool = typer.Option(False, "--yes", "-y", help="accept model download prompts"),
    build: bool = typer.Option(True, "--build/--no-build", help="rebuild Miniton after switching"),
) -> None:
    """Show or switch Miniton's model profile."""
    cfg = _cfg()
    if profile is None:
        ui.section("model profile", f"active: {cfg.model_profile}")
        table = ui.make_table("profile", "model", "notes")
        for name, data in MODEL_PROFILES.items():
            marker = "●" if name == cfg.model_profile else "○"
            table.add_row(f"{marker} {name}", data["base_model"], data["label"])
        ui.print_table(table)
        return
    if profile not in MODEL_PROFILES:
        ui.err("unknown profile", "choose fast, better, or strong")
        raise typer.Exit(1)
    selected = MODEL_PROFILES[profile]
    write_settings(
        cfg.home,
        model_profile=profile,
        base_model=selected["base_model"],
        hf_model=selected["hf_model"],
    )
    cfg = Config.load()
    ui.flash(
        f"[bold {ui.theme().primary}]model[/] → "
        f"[bold]{profile}[/]  [{ui.theme().muted}]{cfg.base_model}[/]"
    )
    ui.ok(f"model profile → {profile}", cfg.base_model)
    if build:
        if _build_miniton(cfg, yes=yes):
            ui.ok(f"rebuilt {cfg.model}")
        else:
            ui.warn("profile saved, but model was not rebuilt")


@app.command("theme")
def theme_cmd(
    name: str | None = typer.Argument(None, help=f"one of: {', '.join(ui.THEMES)}"),
) -> None:
    """Show or switch the CLI theme."""
    cfg = _cfg()
    if name is None:
        ui.section("themes", f"active: {cfg.theme}")
        table = ui.make_table("theme", "description", "preview")
        for t in ui.list_themes():
            marker = "●" if t.name == cfg.theme else "○"
            # Render a tiny color swatch so users can see the palette.
            swatch = (
                f"[{t.primary}]██[/] "
                f"[{t.secondary}]██[/] "
                f"[{t.success}]✓[/] "
                f"[{t.warning}]![/] "
                f"[{t.error}]✗[/]"
            )
            table.add_row(f"{marker} {t.name}", t.label, swatch)
        ui.print_table(table)
        ui.blank()
        ui.hint("switch with [bold]superton theme <name>[/bold]")
        return
    if name not in ui.THEMES:
        ui.err("unknown theme", f"choose one of: {', '.join(ui.THEMES)}")
        raise typer.Exit(1)
    write_settings(cfg.home, theme=name)
    ui.set_theme(name)
    # 200ms transition flash showing the new theme's swatch.
    t = ui.theme()
    swatch = (
        f"[bold {t.primary}]SuperTon[/] → "
        f"[{t.primary}]██[/] [{t.secondary}]██[/] "
        f"[{t.success}]✓[/] [{t.warning}]![/] [{t.error}]✗[/]  "
        f"[{t.muted}]{t.label}[/]"
    )
    ui.flash(swatch)
    ui.ok(f"theme → {name}", ui.theme().label)


@app.command()
def stats() -> None:
    """Palace statistics."""
    mem = Memory(_cfg())
    s = mem.stats()
    mem.close()
    ui.section("palace")
    ui.kv([
        ("drawers", str(s["drawers"])),
        ("wings", str(s["wings"])),
        ("rooms", str(s["rooms"])),
        ("backend", str(s["backend"])),
        ("disk", f"{s['bytes'] / 1024:.1f} KB"),
    ])
    if s.get("semantic_error"):
        ui.warn("semantic fallback active", str(s["semantic_error"]))


@app.command()
def doctor() -> None:
    """Check local runtime, memory, and model setup."""
    from superton.doctor import render_doctor_report

    render_doctor_report(_cfg())


@app.command()
def reindex() -> None:
    """Rebuild semantic index from the SQLite drawer store."""
    mem = Memory(_cfg())
    with ui.spinner("rebuilding semantic index"):
        total = mem.reindex_semantic()
    s = mem.stats()
    mem.close()
    if s.get("semantic_error"):
        ui.warn("semantic reindex incomplete", str(s["semantic_error"]))
        return
    ui.ok(f"reindexed {total} drawers")


@app.command("close")
def close_models(
    all_models: bool = typer.Option(
        False,
        "--all",
        help="also stop SuperTon base and embedding models",
    ),
    force_daemon: bool = typer.Option(
        False,
        "--force-daemon",
        help="also kill the ollama daemon process after stopping models",
    ),
) -> None:
    """Stop running SuperTon model runners."""
    cfg = _cfg()
    if shutil.which("ollama") is None:
        ui.warn("ollama not found")
        return

    names = [cfg.model]
    if all_models:
        names.extend([cfg.base_model, cfg.embed_model])

    model = Model(cfg)
    for name in dict.fromkeys(names):
        if model.stop(name):
            ui.ok(f"stopped {name}")
        else:
            ui.step(f"not running: {name}")
    model.close()

    if force_daemon:
        ui.warn("force-stopping ollama daemon")
        subprocess.run(["pkill", "-f", "ollama serve"], check=False)


import_app = typer.Typer(help="Import conversations from other AI tools.")
app.add_typer(import_app, name="import")


_REPLACE_HELP = (
    "re-import sources that are already in the palace (drops them first)"
)


@import_app.command("claude-code")
def import_claude_code(
    root: Path | None = typer.Option(None, "--root", help="defaults to ~/.claude/projects"),
    replace: bool = typer.Option(False, "--replace", help=_REPLACE_HELP),
) -> None:
    """Import Claude Code session transcripts."""
    from superton.importers.claude_code import ClaudeCodeImporter

    mem = Memory(_cfg())
    with ui.spinner("importing Claude Code sessions"):
        sessions, drawers = ClaudeCodeImporter(mem).import_all(root, replace=replace)
    mem.close()
    ui.ok(f"imported {drawers} drawers", f"from {sessions} Claude Code sessions")


@import_app.command("chatgpt")
def import_chatgpt(
    root: Path = typer.Argument(..., exists=True, help="ChatGPT export directory or conversations.json"),
    replace: bool = typer.Option(False, "--replace", help=_REPLACE_HELP),
) -> None:
    """Import ChatGPT data export conversations."""
    from superton.importers.chatgpt import ChatGPTImporter

    mem = Memory(_cfg())
    with ui.spinner("importing ChatGPT conversations"):
        conversations, drawers = ChatGPTImporter(mem).import_all(root, replace=replace)
    mem.close()
    ui.ok(f"imported {drawers} drawers", f"from {conversations} ChatGPT conversations")


@import_app.command("cursor")
def import_cursor(
    root: Path | None = typer.Option(None, "--root", help="defaults to ~/.cursor"),
    replace: bool = typer.Option(False, "--replace", help=_REPLACE_HELP),
) -> None:
    """Import readable Cursor conversation/log files."""
    from superton.importers.generic_threads import GenericThreadImporter

    mem = Memory(_cfg())
    with ui.spinner("importing Cursor threads"):
        files, drawers = GenericThreadImporter(
            mem, "cursor", Path.home() / ".cursor"
        ).import_all(root, replace=replace)
    mem.close()
    ui.ok(f"imported {drawers} drawers", f"from {files} Cursor files")


@import_app.command("amp")
def import_amp(
    root: Path | None = typer.Option(None, "--root", help="defaults to ~/.amp"),
    replace: bool = typer.Option(False, "--replace", help=_REPLACE_HELP),
) -> None:
    """Import readable Amp conversation/log files."""
    from superton.importers.generic_threads import GenericThreadImporter

    mem = Memory(_cfg())
    with ui.spinner("importing Amp threads"):
        files, drawers = GenericThreadImporter(
            mem, "amp", Path.home() / ".amp"
        ).import_all(root, replace=replace)
    mem.close()
    ui.ok(f"imported {drawers} drawers", f"from {files} Amp files")


@app.command()
def tune() -> None:
    """Open the Modelfile in $EDITOR and rebuild Miniton."""
    cfg = _cfg()
    modelfile = _project_modelfile()
    if modelfile is None:
        ui.err("Modelfile not found")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(modelfile)], check=False)
    if shutil.which("ollama"):
        rendered = _render_modelfile(modelfile, cfg)
        model = Model(cfg)
        if model.build(rendered):
            ui.ok(f"{cfg.model} rebuilt")
        model.close()


# --- MemPalace power-user commands --------------------------------------------

mcp_app = typer.Typer(help="Expose the palace over MCP for Claude / Cursor / Gemini.")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve(
    collection: str | None = typer.Option(
        None, "--collection", "-c", help="override the semantic collection name"
    ),
) -> None:
    """Run the MemPalace MCP server against the SuperTon palace.

    This is a delegating wrapper. Other AI tools (Claude Code, Cursor,
    Gemini CLI) can connect to it over stdio and get 29 tools for reading
    and writing drawers, querying the knowledge graph, and navigating the
    palace — backed by your SuperTon store.
    """
    cfg = _cfg()
    try:
        from mempalace.mcp_server import main as mcp_main
    except Exception as e:
        ui.err("MemPalace MCP server unavailable", str(e))
        raise typer.Exit(1) from e
    ui.section("mcp serve", f"palace: {cfg.semantic_dir}")
    ui.hint("stdio transport · Ctrl+C to stop")
    # The server reads argv directly, so we rebuild a stable argv.
    import sys as _sys
    argv_backup = _sys.argv[:]
    _sys.argv = [
        "mempalace-mcp",
        "--palace-path", str(cfg.semantic_dir),
        "--collection-name", collection or cfg.semantic_collection,
    ]
    try:
        mcp_main()
    except KeyboardInterrupt:
        ui.blank()
        ui.ok("mcp server stopped")
    except SystemExit:
        raise
    except Exception as e:
        ui.err("mcp server crashed", str(e))
        raise typer.Exit(1) from e
    finally:
        _sys.argv = argv_backup


@app.command()
def dedup(
    threshold: float = typer.Option(
        0.92, "--threshold", "-t", help="similarity threshold (0-1, higher = stricter)"
    ),
    dry_run: bool = typer.Option(
        True, "--dry-run/--apply", help="preview by default; pass --apply to actually remove"
    ),
) -> None:
    """Find near-duplicate drawers across sources (uses MemPalace dedup)."""
    cfg = _cfg()
    try:
        from mempalace.dedup import dedup_palace
    except Exception as e:
        ui.err("MemPalace dedup unavailable", str(e))
        raise typer.Exit(1) from e
    ui.section("dedup", f"threshold {threshold:.2f} · {'dry-run' if dry_run else 'APPLY'}")
    with ui.spinner("scanning palace for duplicates"):
        try:
            result = dedup_palace(
                palace_path=str(cfg.semantic_dir),
                collection_name=cfg.semantic_collection,
                threshold=threshold,
                dry_run=dry_run,
            )
        except TypeError:
            # Older mempalace signatures: positional-only
            result = dedup_palace(str(cfg.semantic_dir))
    if isinstance(result, dict):
        ui.kv([(k, str(v)) for k, v in result.items() if not k.startswith("_")])
    else:
        ui.info("dedup complete", str(result))
    if dry_run:
        ui.hint("re-run with [bold]--apply[/bold] to actually remove duplicates")


# Back-compat shim for tools that looked up `console` on this module.
console = ui.console()
err_console = ui.err_console()


if __name__ == "__main__":
    app()
