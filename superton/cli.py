"""SuperTon command-line interface.

Commands (grouped as in `superton --help`):
  superton init                set up palace + check ollama + build Superton
  superton add <path|url>      ingest file, directory, or web page
  superton ask "..."           query Superton with palace context
  superton list                show recent drawers (--json for scripts)
  superton search "..."        semantic search with SQLite fallback (--json)
  superton forget <id>         remove a drawer
  superton stats               palace statistics (--json)
  superton export              back up every drawer as JSON Lines
  superton import-palace <f>   restore drawers from an export file
  superton theme [name]        show / switch CLI theme
  superton close               stop SuperTon model runners
  superton import <source>     pull conversations from other AI tools
  superton tune                edit Modelfile and rebuild Superton
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.text import Text

from superton import __version__, errors, ui
from superton.blackhole import static_frame
from superton.config import BASE_MODEL_DOWNLOAD_GB, Config, write_settings
from superton.ingest import MAX_FILE_BYTES, chunk_text, file_too_large, read_file, walk
from superton.logging import get_logger
from superton.memory import Memory
from superton.model import Model, ModelError, OllamaError

log = get_logger("cli")

# Help-panel names — every command is grouped so `superton --help` reads
# as a guided tour instead of an alphabetical dump.
PANEL_START = "Start here"
PANEL_INGEST = "Ingest & capture"
PANEL_EXPLORE = "Ask & explore"
PANEL_PALACE = "Palace management"
PANEL_SYSTEM = "Model & system"

app = typer.Typer(
    name="superton",
    help="A local memory palace: ingest notes, docs, and AI chats — ask with citations.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode="rich",
    epilog=(
        "[dim]Examples:[/dim]\n\n"
        "  superton add ~/notes            [dim]# ingest a folder[/dim]\n\n"
        '  superton ask "what did I decide about auth?"\n\n'
        "  superton                        [dim]# interactive shell[/dim]\n\n"
        "  superton export -o palace.jsonl [dim]# back up every drawer[/dim]"
    ),
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
    rendered = build_dir / "Modelfile.superton"
    rendered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rendered


def _pick_theme(*, default: str = "ember") -> str:
    """Interactive theme picker shown during init.

    Stays quiet when the user already accepted a CLI flag — only invoked
    when neither `--theme` nor `--yes` was passed. Re-uses the
    `theme_picker_card` UI helper.
    """
    ui.blank()
    ui.section("choose a theme")
    ui.blank()
    picked = ui.pick_theme_interactive(default)
    if picked is not None:
        ui.set_theme(picked)
        ui.ok(f"theme → {picked}")
        return picked
    # No TTY (CI, piped stdin) — fall back to the typed prompt.
    ui.theme_picker_card(default)
    ui.blank()
    while True:
        choice = typer.prompt(
            f"theme [{'/'.join(ui.THEMES)}]",
            default=default,
        ).strip().lower()
        if choice in ui.THEMES:
            return choice
        ui.warn("pick one of: " + ", ".join(ui.THEMES))


def _detect_preflight(cfg: Config) -> list[tuple[str, str, str]]:
    """Snapshot of what init will and won't have to do, used by the
    pre-flight card so users see the plan before any prompts fire.

    Each row is `(status, name, detail)`. `✓` rows are already-done,
    `→` rows will run, `?` rows we can't tell yet. Kept network-free
    on purpose: the actual ollama probe happens in stage 2 with its own
    spinner. Trying to ping the daemon here would block CI runners
    where the binary is on PATH but the daemon isn't running.
    """
    rows: list[tuple[str, str, str]] = []

    palace_exists = (cfg.palace_dir / "drawers.sqlite").exists()
    rows.append((
        "✓" if palace_exists else "→",
        "palace",
        str(cfg.palace_dir),
    ))

    if shutil.which("ollama") is not None:
        rows.append(("✓", "ollama", "found on PATH"))
        rows.append(("?", "base model", f"{cfg.base_model}  (probed in stage 3)"))
        rows.append(("?", "semantic search", "embedding model  (prepared in stage 4)"))
        rows.append(("?", "Superton", f"{cfg.model}  (built in stage 5)"))
    else:
        rows.append(("→", "ollama", "will offer to install"))
        rows.append(("?", "base model", "needs ollama"))
        rows.append(("?", "Superton", "needs ollama"))

    claude_root = Path.home() / ".claude" / "projects"
    if claude_root.exists() and any(claude_root.rglob("*.jsonl")):
        rows.append(("→", "Claude Code import", f"sessions found at {claude_root}"))
    return rows


def _offer_ollama_install(*, yes: bool) -> bool:
    """Offer to install Ollama via brew (macOS) or the official installer (Linux).

    Returns True if Ollama is on PATH after the attempt (or was already), False
    if the user declined or the install failed.
    """
    if shutil.which("ollama") is not None:
        return True
    import platform
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        cmd = ["brew", "install", "ollama"]
        prompt = "Install Ollama via Homebrew?"
    elif system == "Linux":
        cmd = ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]
        prompt = "Install Ollama via the official installer (curl | sh)?"
    else:
        ui.hint("install Ollama manually: [link]https://ollama.com/download[/link]")
        return False
    ui.blank()
    ui.card(
        "install ollama",
        f"Ollama is missing — needed to run Superton locally.\n\n"
        f"Will run: [bold]{' '.join(cmd)}[/]",
        status=("required", "warning"),
    )
    if not yes and not typer.confirm(prompt, default=True):
        return False
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        ui.warn("ollama install failed")
        return False
    return shutil.which("ollama") is not None


def _confirm_pull(model_name: str, purpose: str, *, yes: bool) -> bool:
    if yes:
        return True
    ui.blank()
    ui.card(
        f"download · {model_name}",
        f"{purpose}\n\n"
        f"[dim]Weights are stored in your local Ollama directory; download once, reuse forever.[/]",
        status=("model pull", "info"),
    )
    return typer.confirm("Pull this model now?", default=True)


DEMO_DRAWERS: tuple[tuple[str, str, str, str], ...] = (
    (
        "demo:notes/launch-plan.md",
        "notes",
        "demo",
        "SuperTon demo launch plan: keep the first run short, ingest notes before asking, "
        "and show citations so users can see which drawers grounded the answer.",
    ),
    (
        "demo:projects/local-memory.md",
        "projects",
        "demo",
        "Project summary: SuperTon is a local memory palace using SQLite for durable "
        "drawers, FTS for exact search, and a semantic sidecar for natural-language recall.",
    ),
    (
        "demo:transcripts/assistant-session.md",
        "transcripts",
        "demo",
        "Assistant transcript: the team decided the product should stay local-first, avoid "
        "telemetry, and make recovery hints visible whenever setup cannot complete a stage.",
    ),
)


def _seed_demo(cfg: Config) -> tuple[int, int]:
    """Seed a tiny demo palace. Returns (added, deduped)."""
    mem = Memory(cfg)
    added = 0
    deduped = 0
    for source, wing, room, text in DEMO_DRAWERS:
        mem.add(text=text, source=source, wing=wing, room=room, metadata={"demo": True})
        if mem.last_insert_was_new:
            added += 1
        else:
            deduped += 1
    mem.close()
    return added, deduped


def _offer_demo_seed(cfg: Config, *, yes: bool) -> None:
    if yes:
        return
    mem = Memory(cfg)
    stats = mem.stats()
    mem.close()
    if stats["drawers"] != 0:
        return
    ui.blank()
    if not typer.confirm("Seed a 3-drawer demo palace so you can ask immediately?", default=False):
        return
    added, deduped = _seed_demo(cfg)
    detail = f"{deduped} already present" if deduped else "try: superton ask \"what is SuperTon?\""
    ui.ok(f"seeded {added} demo drawers", detail)


def _ingest_into_memory(
    mem: Memory, path: Path, *, wing: str, room: str
) -> tuple[int, int, int, int]:
    """Walk `path`, ingest each file. Returns (files, drawers, skipped, deduped)."""
    files = list(walk(path))
    total_drawers = 0
    skipped = 0
    deduped = 0
    if not files:
        return 0, 0, 0, 0
    with ui.progress("ingesting", total=len(files)) as advance:
        for f in files:
            rel = f.relative_to(path) if path.is_dir() else Path(f.name)
            if file_too_large(f):
                ui.warn(
                    f"skip {rel}",
                    f"file is over {MAX_FILE_BYTES // (1024 * 1024)} MB; split it or ingest a smaller export",
                )
                skipped += 1
                advance(description=f"ingesting  [dim]skip {rel}[/]")
                continue
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
                if mem.last_insert_was_new:
                    total_drawers += 1
                else:
                    deduped += 1
            advance(description=f"ingesting  [dim]{rel}[/]")
    return len(files) - skipped, total_drawers, skipped, deduped


def _build_superton(cfg: Config, *, yes: bool) -> bool:
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
            "Required as the Superton base model.",
            yes=yes,
        ):
            model.close()
            return False
        subprocess.run(["ollama", "pull", cfg.base_model], check=False)
        model.invalidate_cache()
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
    version: bool = typer.Option(False, "--version", "-V", help="show version"),
) -> None:
    if version:
        ui.console().print(f"superton {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _launch_shell()
        raise typer.Exit()


@app.command(rich_help_panel=PANEL_START)
def welcome() -> None:
    """Show the SuperTon welcome tour at any time."""
    cfg = _cfg()
    mem = Memory(cfg)
    stats = mem.stats()
    mem.close()
    ui.header(cfg, stats)
    ui.ready_card(cfg, stats)


@app.command(rich_help_panel=PANEL_START)
def init(
    skip_model: bool = typer.Option(False, "--no-model", help="skip ollama model build"),
    yes: bool = typer.Option(False, "--yes", "-y", help="accept setup prompts"),
    theme: str | None = typer.Option(
        None, "--theme", "-t",
        help=f"CLI theme: {', '.join(ui.THEMES)}",
    ),
) -> None:
    """Initialize the palace and build Superton."""
    cfg = _cfg()
    cfg.home.mkdir(parents=True, exist_ok=True)
    cfg.palace_dir.mkdir(parents=True, exist_ok=True)

    is_re_init = cfg.palace_dir.exists() and (cfg.palace_dir / "drawers.sqlite").exists()

    ui.section(
        "superton init",
        "re-checking setup" if is_re_init else "palace + model setup",
    )

    # Pre-flight summary — show the user the full plan before any prompts so
    # they can ^C out if anything looks wrong, and so the prompts that follow
    # feel like steps in a known sequence rather than surprise dialogs.
    summary = (
        "Already set up — re-verifying each stage."
        if is_re_init
        else "First-run setup. Each step asks before downloading anything."
    )
    ui.blank()
    ui.preflight_card("about to do", _detect_preflight(cfg), summary=summary)
    ui.blank()

    # Validate user-provided flags first so a typo fails fast, before we
    # walk through interactive prompts.
    if theme and theme not in ui.THEMES:
        ui.err("unknown theme", "choose one of: " + ", ".join(ui.THEMES))
        raise typer.Exit(1)

    # ---------------------------------------------------------------------
    # Stage 0 — pick theme (interactive when not provided and the user
    # didn't pass --yes, so first-run users see the choices)
    # ---------------------------------------------------------------------
    if theme is None and not yes:
        try:
            theme = _pick_theme(default=cfg.theme)
        except (EOFError, KeyboardInterrupt):
            theme = cfg.theme

    settings_update: dict[str, str] = {}
    if theme and theme != cfg.theme:
        settings_update["theme"] = theme
    if settings_update:
        write_settings(cfg.home, **settings_update)
        cfg = Config.load()
        if "theme" in settings_update:
            ui.set_theme(cfg.theme)

    # Determine how many stages will actually run so the [N/total] indicator
    # in each stage header is meaningful. Stages always present: palace,
    # ollama, base, embed, build. Optional: Claude Code import.
    has_claude_sessions = (Path.home() / ".claude" / "projects").exists() and any(
        (Path.home() / ".claude" / "projects").rglob("*.jsonl")
    )
    total_stages = 1 if skip_model else (6 if has_claude_sessions else 5)
    step = 0

    # ---------------------------------------------------------------------
    # Stage 1 — palace store
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage("creating palace", step=step, total=total_stages):
        Memory(cfg).close()
        ui.stage_ok(f"palace at {cfg.palace_dir}")

    if skip_model:
        ui.blank()
        ui.stage_skip("skipped ollama model build (--no-model)")
        ui.blank()
        _finish_init(cfg, offer_demo=not yes)
        return

    # ---------------------------------------------------------------------
    # Stage 2 — ollama availability
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage("checking ollama", step=step, total=total_stages):
        if shutil.which("ollama") is None:
            ui.stage_warn(
                "ollama not found in PATH",
                hint="install: https://ollama.com/download",
            )
            installed = _offer_ollama_install(yes=yes)
            if not installed:
                if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"):
                    ui.stage_ok("Hugging Face fallback configured via HF_TOKEN")
                else:
                    ui.stage_warn(
                        "no model backend available",
                        hint="set HF_TOKEN and SUPERTON_MODEL_BACKEND=huggingface, "
                        "or rerun after installing ollama",
                    )
                ui.blank()
                _finish_init(cfg, offer_demo=not yes)
                return
            ui.stage_ok("ollama installed")

        model = Model(cfg)
        if not model.ollama_ready() and not model.start_ollama():
            ui.stage_warn(
                "could not start ollama automatically",
                hint="run manually: ollama serve",
            )
            model.close()
            ui.blank()
            _finish_init(cfg, offer_demo=not yes)
            return
        ui.stage_ok(f"ollama running at {cfg.ollama_url}")

    # ---------------------------------------------------------------------
    # Stage 3 — base model
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage(
        f"pulling base model · {cfg.base_model}",
        step=step,
        total=total_stages,
    ):
        if model.has_model(cfg.base_model):
            ui.stage_ok("already present")
        else:
            if not _confirm_pull(
                cfg.base_model,
                f"Required to build Superton, the local answer model. "
                f"~{BASE_MODEL_DOWNLOAD_GB:.1f} GB.",
                yes=yes,
            ):
                ui.stage_warn(
                    "skipped model pull",
                    hint=f"rerun: superton init --yes  (or: ollama pull {cfg.base_model})",
                )
                model.close()
                ui.blank()
                _finish_init(cfg, offer_demo=not yes)
                return
            subprocess.run(["ollama", "pull", cfg.base_model], check=False)
            model.invalidate_cache()
            if not model.has_model(cfg.base_model):
                ui.stage_warn(
                    f"failed to pull {cfg.base_model}",
                    hint="check network and disk space, then rerun: superton init",
                )
                model.close()
                return
            ui.stage_ok("downloaded")

    # ---------------------------------------------------------------------
    # Stage 4 — semantic embedder
    #
    # The semantic store (MemPalace + Chroma) ships its own ONNX embedding
    # model (~80 MB) and lazy-downloads it on first ingest. We warm it here
    # so that download lands in the setup flow instead of interrupting the
    # user's first question. No Ollama embedding model is pulled — the
    # earlier `nomic-embed-text` pull was never used by the search path.
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage("preparing semantic search", step=step, total=total_stages):
        mem = Memory(cfg)
        if mem.warm_embedder():
            ui.stage_ok("embedding model ready")
        else:
            ui.stage_warn(
                "embedding model not prepared",
                hint="it will download on your first ingest instead",
            )
        mem.close()

    # ---------------------------------------------------------------------
    # Stage 5 — build Superton
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage("building Superton", step=step, total=total_stages):
        modelfile = _project_modelfile()
        if modelfile is None:
            ui.stage_warn(
                "Modelfile not found — using base model directly",
                hint="reinstall superton to restore the bundled Modelfile",
            )
        else:
            rendered = _render_modelfile(modelfile, cfg)
            if model.build(rendered):
                ui.stage_ok(f"built as {cfg.model}")
            else:
                ui.stage_warn(
                    "model build failed — base model still usable",
                    hint=f"try `superton tune` or `ollama create {cfg.model} -f Modelfile`",
                )
    model.close()

    # ---------------------------------------------------------------------
    # Stage 6 — offer to import Claude Code sessions
    # ---------------------------------------------------------------------
    if has_claude_sessions:
        claude_root = Path.home() / ".claude" / "projects"
        ui.blank()
        should_import = yes or typer.confirm(
            f"Found Claude Code sessions at {claude_root} — import them now?",
            default=False,
        )
        if should_import:
            step += 1
            with ui.stage(
                "importing Claude Code sessions",
                step=step,
                total=total_stages,
            ):
                from superton.importers.claude_code import ClaudeCodeImporter

                mem = Memory(cfg)
                sessions, drawers = ClaudeCodeImporter(mem).import_all(None)
                mem.close()
                ui.stage_ok(f"{drawers} drawers from {sessions} sessions")

    # ---------------------------------------------------------------------
    # Final — hero ready card
    # ---------------------------------------------------------------------
    _finish_init(cfg, offer_demo=not yes)


def _finish_init(cfg: Config, *, offer_demo: bool = False) -> None:
    """Print the ready card with live palace stats."""
    mem = Memory(cfg)
    stats = mem.stats()
    mem.close()
    ui.blank()
    ui.ready_card(cfg, stats)
    if offer_demo:
        _offer_demo_seed(cfg, yes=False)


@app.command(rich_help_panel=PANEL_START)
def demo() -> None:
    """Seed a tiny local demo palace so new users can ask immediately."""
    cfg = _cfg()
    added, deduped = _seed_demo(cfg)
    ui.section("demo")
    detail = "stable demo drawers"
    if deduped:
        detail += f" · {deduped} already present"
    ui.ok(f"seeded {added} drawer(s)", detail)
    ui.hint('try: [bold]superton ask "what is SuperTon?"[/bold]')


@app.command(rich_help_panel=PANEL_INGEST)
def add(
    target: str = typer.Argument(..., help="file, directory, or http(s) URL to ingest"),
    wing: str = typer.Option("default", "--wing", "-w"),
    room: str = typer.Option("default", "--room", "-r"),
) -> None:
    """Ingest a file, directory, or single URL into the palace."""
    import asyncio

    # URL branch — single-page web ingest.
    if target.startswith(("http://", "https://")):
        cfg = _cfg()
        mem = Memory(cfg)
        ui.section("add", f"{target}  → wing={wing} room={room}")
        with ui.spinner(
            f"fetching {target}",
            phases=["Fetching page", "Extracting body", "Cleaning markdown"],
        ):
            from superton.puller import pull_url

            page = asyncio.run(pull_url(target))
        if page is None:
            ui.warn("could not extract content from URL")
            mem.close()
            return
        from superton.ingest import chunk_text

        drawers = 0
        deduped = 0
        for chunk in chunk_text(page.markdown):
            mem.add(text=chunk, source=target, wing=wing, room=room)
            if mem.last_insert_was_new:
                drawers += 1
            else:
                deduped += 1
        mem.close()
        ui.blank()
        summary = f"from {target}"
        if deduped:
            summary += f"  ·  {deduped} deduped"
        ui.ok(f"ingested {drawers} drawers", summary)
        return

    # File/directory branch — existing behavior.
    path = Path(target).expanduser()
    if not path.exists():
        ui.err(f"not found: {target}")
        raise typer.Exit(1)
    cfg = _cfg()
    mem = Memory(cfg)
    ui.section("add", f"{path}  → wing={wing} room={room}")
    files, total_drawers, _skipped, deduped = _ingest_into_memory(mem, path, wing=wing, room=room)
    mem.close()
    ui.blank()
    summary = f"from {files} file(s)"
    if deduped:
        summary += f"  ·  {deduped} deduped"
    ui.ok(f"ingested {total_drawers} drawers", summary)


@app.command(rich_help_panel=PANEL_INGEST)
def note(
    text: str = typer.Argument(..., help="note text to capture"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="optional note tag"),
) -> None:
    """Capture a quick note without creating a file first."""
    cfg = _cfg()
    mem = Memory(cfg)
    ts = time.time()
    source = f"note:{time.strftime('%Y%m%d-%H%M%S', time.localtime(ts))}"
    metadata = {"kind": "note"}
    if tag:
        metadata["tag"] = tag
    drawer = mem.add(text=text, source=source, wing="notes", room=tag or "daily", metadata=metadata)
    mem.close()
    ui.ok(f"captured note {drawer.id[:8]}", source)


@app.command(rich_help_panel=PANEL_INGEST)
def pull(
    url: str = typer.Argument(..., help="base URL of the site to pull"),
    max_pages: int = typer.Option(100, "--max", "-m", help="max pages to pull"),
    wing: str = typer.Option("default", "--wing", "-w"),
    room: str = typer.Option("default", "--room", "-r"),
    render_js: bool = typer.Option(False, "--render-js", help="use Playwright for JS-rendered sites"),
    concurrency: int = typer.Option(8, "--concurrency", "-c"),
) -> None:
    """Pull an entire website into the palace as markdown drawers.

    Discovers pages via sitemap.xml, navigation links, or BFS crawling,
    then fetches and extracts each page in parallel. Content is converted
    to clean markdown via trafilatura and ingested directly as drawers.

    Equivalent to webpull but native Python, no Bun/Node required.
    """
    import asyncio

    from superton.ingest import chunk_text
    from superton.puller import pull_site

    cfg = _cfg()
    mem = Memory(cfg)
    ui.section("pull", f"{url}  → max={max_pages} wing={wing} room={room}")

    total_pages = 0
    total_drawers = 0
    deduped = 0

    # Live status text is cheap to update; show it from inside the spinner
    # so a long crawl visibly progresses instead of feeling hung.
    with ui.spinner(
        f"pulling {url}",
        phases=["Discovering pages", "Fetching", "Extracting content", "Embedding chunks"],
    ) as set_status:
        async def _run() -> None:
            nonlocal total_pages, total_drawers, deduped
            async for page in pull_site(
                url,
                max_pages=max_pages,
                render_js=render_js,
                concurrency=concurrency,
            ):
                total_pages += 1
                for chunk in chunk_text(page.markdown):
                    mem.add(text=chunk, source=page.url, wing=wing, room=room)
                    if mem.last_insert_was_new:
                        total_drawers += 1
                    else:
                        deduped += 1
                set_status(f"pulling {url}  ·  {total_pages}/{max_pages} pages  ·  {total_drawers} drawers")

        asyncio.run(_run())

    mem.close()
    ui.blank()
    summary = f"pulled {total_pages} pages → {total_drawers} drawers"
    if deduped:
        summary += f"  ·  {deduped} deduped"
    ui.ok(summary)


@app.command(rich_help_panel=PANEL_INGEST)
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
    files, drawers, _skipped, _deduped = _ingest_into_memory(mem, path, wing=wing, room=room)
    mem.close()
    ui.blank()
    ui.diff_summary(removed=removed, added=drawers)
    ui.blank()
    ui.ok(f"refreshed {files} file(s)")


@app.command(rich_help_panel=PANEL_EXPLORE)
def ask(
    question: str = typer.Argument(..., help="your question"),
    k: int = typer.Option(5, "--top-k", "-k"),
    why: bool = typer.Option(False, "--why", help="show retrieval trace"),
) -> None:
    """Ask Superton a question. Answer is grounded in palace drawers."""
    cfg = _cfg()
    mem = Memory(cfg)
    # Empty-palace check before retrieval: skip the search spinner entirely
    # on a brand-new install so the user lands on the recovery hint without
    # waiting for an inevitably empty FTS + semantic round-trip.
    if mem.stats()["drawers"] == 0:
        ui.warn("your palace is empty")
        ui.hint(
            "ingest something first: [bold]superton add ~/notes[/bold] "
            "or try [bold]superton demo[/bold]"
        )
        mem.close()
        raise typer.Exit(0)
    with ui.spinner(
        "retrieving from palace",
        phases=["Searching palace", "Ranking drawers", "Re-scoring sources", "Composing context"],
    ):
        raw_hits = mem.search(question, limit=max(k, 8))
    from superton.shell import (
        ANSWER_CONTEXT_DRAWERS,
        ANSWER_DRAWER_CHARS,
        _any_token_match,
        _expand_hits_for_answer,
        _looks_memory_specific,
        _relevant_hits,
        _wants_source_expansion,
    )

    context_limit = max(k, ANSWER_CONTEXT_DRAWERS) if _wants_source_expansion(question) else k
    hits = _expand_hits_for_answer(
        mem,
        question,
        _relevant_hits(question, raw_hits),
        max_drawers=context_limit,
    )[:context_limit]
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
            score_cell = Text(f"{h.score:.2f} ", style=score_style)
            score_cell.append_text(ui.score_bar(h.score))
            table.add_row(
                ui.style_id(h.drawer.id[:8]),
                score_cell,
                ui.style_path(Path(h.drawer.source).name),
                preview,
            )
        if not hits:
            table.add_row("-", "-", "-", "no memory drawers matched")
        ui.print_table(table)
        ui.blank()

    context = "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} · {Path(h.drawer.source).name}]\n"
        f"{h.drawer.text[:ANSWER_DRAWER_CHARS]}"
        for h in hits[:context_limit]
    )
    from superton.shell import _build_system_prompt

    system = _build_system_prompt(has_drawers=bool(hits))
    if hits:
        prompt = (
            f"FILE EXCERPTS:\n\n{context}\n\n"
            f"QUESTION: {question}\n\n"
            "Answer from the excerpts above."
        )
    else:
        prompt = (
            "No file excerpts were retrieved.\n\n"
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
        log.error("ask failed: %s", e)
        errors.render(e)
    finally:
        model.close()
        mem.close()


def _drawer_dict(d) -> dict:
    """JSON-safe dict for one drawer — shared by `list --json` and `export`."""
    return {
        "id": d.id,
        "text": d.text,
        "source": d.source,
        "wing": d.wing,
        "room": d.room,
        "created_at": d.created_at,
        "metadata": d.metadata,
    }


@app.command("list", rich_help_panel=PANEL_EXPLORE)
def list_drawers(
    limit: int = typer.Option(20, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json", help="emit drawers as JSON"),
) -> None:
    """List recent drawers."""
    mem = Memory(_cfg())
    rows = mem.all(limit=limit)
    mem.close()
    if json_output:
        import json

        print(json.dumps([_drawer_dict(d) for d in rows], indent=2))
        return
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


def _print_recent_sources(*, days: int, limit: int, json_output: bool = False) -> None:
    """Render the 'recent' table. Shared by `recent` and `today` so the
    Typer command bodies don't call each other (Option defaults are
    OptionInfo sentinels at function-call time, which can confuse direct
    Python invocation)."""
    since = time.time() - max(days, 1) * 86400
    mem = Memory(_cfg())
    rows = mem.recent_sources(since=since, limit=limit)
    mem.close()
    if json_output:
        import json

        print(json.dumps(rows, indent=2))
        return
    ui.section("recent", f"last {days} day(s)")
    table = ui.make_table("drawers", "latest", "source")
    for row in rows:
        latest = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(row["latest"])))
        table.add_row(str(row["drawers"]), latest, row["source"])
    if not rows:
        table.add_row("-", "-", "no recent sources")
    ui.print_table(table)


@app.command(rich_help_panel=PANEL_EXPLORE)
def recent(
    days: int = typer.Option(7, "--days", "-d", help="look back this many days"),
    limit: int = typer.Option(30, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json", help="emit sources as JSON"),
) -> None:
    """List sources added recently."""
    _print_recent_sources(days=days, limit=limit, json_output=json_output)


@app.command(rich_help_panel=PANEL_EXPLORE)
def today(
    limit: int = typer.Option(30, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json", help="emit sources as JSON"),
) -> None:
    """List sources added in the last 24 hours."""
    _print_recent_sources(days=1, limit=limit, json_output=json_output)


@app.command(rich_help_panel=PANEL_EXPLORE)
def search(
    query: str,
    limit: int = typer.Option(10, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json", help="emit hits as JSON"),
) -> None:
    """Semantic search across drawers with SQLite fallback."""
    mem = Memory(_cfg())
    with ui.spinner(
        f"searching palace for {query!r}",
        phases=["Embedding query", "Scanning drawers", "Re-ranking hits"],
    ):
        hits = mem.search(query, limit=limit)
    if json_output:
        import json

        mem.close()
        print(json.dumps(
            [{"score": h.score, **_drawer_dict(h.drawer)} for h in hits], indent=2
        ))
        return
    if not hits:
        ui.shimmer(f"  scanning palace for {query!r}…")
        ui.warn("no drawers matched")
        mem.close()
        return
    ui.section("search", f"{len(hits)} matches")
    for h in hits:
        ui.console().print(ui.cite(h.drawer.id, h.drawer.source))
        ui.console().print(f"  {h.drawer.text[:400]}")
        ui.console().print(f"[{ui.theme().rule}]  " + "─" * 50 + "[/]")
    mem.close()


@app.command("open", rich_help_panel=PANEL_EXPLORE)
def open_drawer(
    drawer_id: str = typer.Argument(..., help="drawer id (or the short prefix from a citation)"),
    edit: bool = typer.Option(False, "--edit", "-e", help="open the source file in $EDITOR"),
) -> None:
    """Jump from a citation to the full drawer and its source.

    Accepts the 8-char ids shown in citation footers. With --edit the
    source file opens in $EDITOR (file-backed sources only).
    """
    mem = Memory(_cfg())
    matches = mem.find_by_prefix(drawer_id)
    mem.close()
    if not matches:
        ui.warn(f"no drawer matched {drawer_id}")
        ui.hint("find ids with [bold]superton list[/bold] or in any citation footer")
        raise typer.Exit(1)
    if len(matches) > 1:
        ui.warn(f"{len(matches)} drawers match {drawer_id} — be more specific")
        for d in matches:
            ui.console().print(f"  {ui.style_id(d.id)}  {ui.style_path(Path(d.source).name)}")
        raise typer.Exit(1)

    d = matches[0]
    t = ui.theme()
    created = time.strftime("%Y-%m-%d %H:%M", time.localtime(d.created_at))
    age_days = max(0, int((time.time() - d.created_at) // 86400))
    body = Text()
    body.append(d.id, style=t.secondary)
    body.append(f"  {d.wing}/{d.room}", style=t.muted)
    body.append(f"  ·  {created} ({age_days}d ago)", style=t.muted)
    body.append("\n")
    body.append(d.source, style=t.muted)
    body.append("\n\n")
    body.append(d.text)
    ui.panel(body, title="drawer", anchor=True)

    source_path = Path(d.source).expanduser()
    if not edit:
        if source_path.exists():
            ui.hint(f"open the source with [bold]superton open {d.id[:8]} --edit[/bold]")
        return
    if not source_path.exists():
        ui.warn("source is not a file on disk", d.source)
        ui.hint("notes, imports, and web pulls are virtual sources — the drawer above is the content")
        return
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(source_path)], check=False)


@app.command(rich_help_panel=PANEL_EXPLORE)
def recall(
    limit: int = typer.Option(3, "--limit", "-n", help="how many drawers to resurface"),
    min_age_days: int = typer.Option(
        0, "--older-than", help="only resurface drawers at least this many days old"
    ),
) -> None:
    """Resurface random drawers from the palace — memory you forgot you had.

    With --older-than N the sample skips anything fresher than N days,
    biasing recall toward the almost-forgotten.
    """
    mem = Memory(_cfg())
    older_than = time.time() - min_age_days * 86400 if min_age_days > 0 else None
    drawers = mem.random_drawers(limit=max(limit, 1), older_than=older_than)
    mem.close()
    ui.section("recall", "a walk through the palace")
    if not drawers:
        ui.blank()
        if min_age_days > 0:
            ui.hint(f"nothing older than {min_age_days} day(s) yet — lower --older-than")
        else:
            ui.hint("the palace is empty — ingest something first")
        return

    from rich.console import Group

    t = ui.theme()
    cards = []
    now = time.time()
    for d in drawers:
        age_days = max(0, int((now - d.created_at) // 86400))
        when = "today" if age_days == 0 else (
            "yesterday" if age_days == 1 else f"{age_days} days ago"
        )
        header = Text()
        header.append(f"{t.bullet} ", style=t.primary)
        header.append(when, style=f"bold {t.primary}")
        header.append(f"  {Path(d.source).name}", style=t.muted)
        header.append(f"  {d.id[:8]}", style=t.secondary)
        preview = " ".join(d.text.split())[:300]
        cards.append(Group(header, Text(f"  {preview}", style=t.neutral), Text("")))
    ui.blank()
    ui.reveal_cards(cards)
    ui.hint("read one in full: [bold]superton open <id>[/bold]")


@app.command(rich_help_panel=PANEL_PALACE)
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


@app.command("forget-source", rich_help_panel=PANEL_PALACE)
def forget_source(source: str) -> None:
    """Remove every drawer from a source path or filename."""
    mem = Memory(_cfg())
    removed = mem.forget_source(source)
    mem.close()
    if removed:
        ui.ok(f"forgot {removed} drawer(s)", f"from {source}")
    else:
        ui.warn(f"no source matched {source}")


@app.command(rich_help_panel=PANEL_EXPLORE)
def sources(
    limit: int = typer.Option(30, "--limit", "-n"),
    health: bool = typer.Option(False, "--health", help="show source refresh/index health"),
    json_output: bool = typer.Option(False, "--json", help="emit sources as JSON"),
) -> None:
    """List indexed source files."""
    mem = Memory(_cfg())
    rows = mem.source_health(limit=limit) if health else mem.sources(limit=limit)
    mem.close()
    if json_output:
        import json

        print(json.dumps(rows, indent=2))
        return
    ui.section("sources", f"{len(rows)} indexed")
    if health:
        table = ui.make_table("drawers", "indexed", "pending", "path", "source")
        for row in rows:
            table.add_row(
                str(row["drawers"]),
                str(row["indexed"] or 0),
                str(row["pending"] or 0),
                str(row["path_status"]),
                row["source"],
            )
    else:
        table = ui.make_table("drawers", "source")
        for row in rows:
            table.add_row(str(row["drawers"]), row["source"])
    ui.print_table(table)


@app.command("model", rich_help_panel=PANEL_SYSTEM)
def model_info() -> None:
    """Show the Superton model configuration."""
    cfg = _cfg()
    ui.section("model", cfg.model)
    ui.kv([
        ("model", cfg.model),
        ("base model", cfg.base_model),
        ("hf fallback", cfg.hf_model),
    ])


@app.command("theme", rich_help_panel=PANEL_SYSTEM)
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


@app.command(rich_help_panel=PANEL_PALACE)
def stats(
    json_output: bool = typer.Option(False, "--json", help="emit machine-readable stats"),
) -> None:
    """Palace statistics."""
    mem = Memory(_cfg())
    s = mem.stats()
    mem.close()
    if json_output:
        import json

        print(json.dumps(s, indent=2, sort_keys=True))
        return
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


@app.command(rich_help_panel=PANEL_SYSTEM)
def doctor(
    json_output: bool = typer.Option(False, "--json", help="emit machine-readable diagnostics"),
) -> None:
    """Check local runtime, memory, and model setup."""
    from superton.doctor import render_doctor_report

    render_doctor_report(_cfg(), json_output=json_output)


@app.command(rich_help_panel=PANEL_PALACE)
def reindex() -> None:
    """Rebuild semantic index from the SQLite drawer store."""
    mem = Memory(_cfg())
    with ui.spinner(
        "rebuilding semantic index",
        phases=["Reading drawers", "Computing embeddings", "Writing index"],
    ):
        total = mem.reindex_semantic()
    s = mem.stats()
    mem.close()
    if s.get("semantic_error"):
        ui.warn("semantic reindex incomplete", str(s["semantic_error"]))
        return
    ui.ok(f"reindexed {total} drawers")


@app.command(rich_help_panel=PANEL_PALACE)
def export(
    out: Path | None = typer.Option(
        None, "--out", "-o", help="write to this file (default: stdout)"
    ),
    limit: int = typer.Option(0, "--limit", "-n", help="max drawers to export (0 = all)"),
) -> None:
    """Export every drawer as JSON Lines — for backup, sync, or migration.

    Each line is one self-contained JSON object (id, text, source, wing,
    room, created_at, metadata). Round-trips through
    `superton import-palace <file>` on any machine; drawer ids are
    content-addressed so re-importing is idempotent.
    """
    import json

    mem = Memory(_cfg())
    drawers = mem.all(limit=limit if limit > 0 else 10_000_000)
    mem.close()
    lines = (json.dumps(_drawer_dict(d), ensure_ascii=False) for d in drawers)
    if out is None:
        for line in lines:
            print(line)
        return
    path = out.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    ui.ok(f"exported {len(drawers)} drawers", str(path))


@app.command("import-palace", rich_help_panel=PANEL_PALACE)
def import_palace(
    file: Path = typer.Argument(..., exists=True, help="JSONL file from `superton export`"),
) -> None:
    """Import drawers from a `superton export` JSON Lines file.

    Content-addressed ids make this idempotent: drawers that already
    exist are counted as deduped, not duplicated.
    """
    import json

    mem = Memory(_cfg())
    added = 0
    deduped = 0
    skipped = 0
    with (
        ui.progress("importing palace") as advance,
        file.expanduser().open("r", encoding="utf-8") as fh,
    ):
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                text = row["text"]
                source = row["source"]
            except (json.JSONDecodeError, TypeError, KeyError):
                skipped += 1
                log.warning("import-palace: skipping malformed line %d", lineno)
                continue
            mem.add(
                text=text,
                source=source,
                wing=row.get("wing") or "default",
                room=row.get("room") or "default",
                metadata=row.get("metadata") or {},
            )
            if mem.last_insert_was_new:
                added += 1
            else:
                deduped += 1
            advance(description=f"importing palace  [dim]{added} drawers[/]")
    mem.close()
    detail = f"{deduped} already present" if deduped else None
    ui.ok(f"imported {added} drawers", detail)
    if skipped:
        ui.warn(f"skipped {skipped} malformed line(s)", "see SUPERTON_LOG=warn for line numbers")


@app.command("close", rich_help_panel=PANEL_SYSTEM)
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


def _detect_install_method() -> str:
    """Best-effort sniff of how SuperTon was installed.

    Inspects `sys.prefix` (the venv root) plus the raw `sys.executable`
    string — not `Path(sys.executable).resolve()`. `uv tool install`
    builds tool venvs whose `bin/python` is a *symlink* to the system
    interpreter; `.resolve()` follows that symlink out of the tool dir
    (e.g. to `/opt/homebrew/Cellar/python@3.12/...`) and the detection
    falls through to `"pip"`. That cascade is what left
    `~/.local/bin/superton` orphaned after `superton uninstall`
    "succeeded".

    Returns one of {"uv", "pipx", "pip"}.
    """
    candidates = (sys.prefix, sys.executable)
    for raw in candidates:
        text = str(raw)
        if "/uv/tools/" in text or "uv\\tools\\" in text:
            return "uv"
        if "/pipx/" in text or "pipx\\" in text:
            return "pipx"
    return "pip"


def _tool_uninstall_command() -> list[str]:
    """Best-effort command for removing the installed SuperTon CLI.

    Used both to *show* the user the command (preflight) and to actually
    run it. Detection prefers the interpreter path over `shutil.which`
    because the latter can resolve to a stale shim from a different
    installer.
    """
    method = _detect_install_method()
    if method == "uv" and shutil.which("uv"):
        return ["uv", "tool", "uninstall", "superton"]
    if method == "pipx" and shutil.which("pipx"):
        return ["pipx", "uninstall", "superton"]
    return [sys.executable, "-m", "pip", "uninstall", "-y", "superton"]


def _tool_orphan_paths(method: str) -> list[Path]:
    """Filesystem locations that a successful `<installer> uninstall
    superton` should empty out. Used as a defensive sweep after the
    installer command returns so a partial / silent failure (observed
    on some uv versions where the tool venv directory survived a
    `uv tool uninstall`) doesn't leave the user with an orphan
    install dir nobody knows how to clean."""
    home = Path.home()
    if method == "uv":
        return [
            home / ".local" / "share" / "uv" / "tools" / "superton",
            home / ".local" / "bin" / "superton",
        ]
    if method == "pipx":
        return [
            home / ".local" / "share" / "pipx" / "venvs" / "superton",
            home / ".local" / "bin" / "superton",
        ]
    return []


def _remove_orphan(path: Path) -> bool:
    """Remove a file, symlink (even broken), or directory. Returns True
    when something was actually removed."""
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    return False


def _data_paths(cfg: Config) -> list[Path]:
    """Every directory SuperTon may have written data or caches to.

    Beyond `cfg.home` (palace + config + build dir + shell history) this
    sweeps the default platformdirs location (in case `SUPERTON_HOME`
    points elsewhere), SuperTon's cache dir, and the chromadb cache the
    semantic backend populates with downloaded embedding models.
    """
    from platformdirs import user_cache_dir, user_data_dir

    home = Path.home()
    paths = [
        cfg.home,
        Path(user_data_dir("superton", appauthor=False)),
        Path(user_cache_dir("superton", appauthor=False)),
        # chromadb model/telemetry cache (populated by the semantic backend)
        home / "Library" / "Caches" / "chroma",
        home / ".cache" / "chroma",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _uninstall_model_names(cfg: Config, *, models: bool, all_models: bool) -> list[str]:
    if not models:
        return []
    names = [cfg.model]
    if all_models:
        names.extend([cfg.base_model, cfg.embed_model])
    return list(dict.fromkeys(names))


@app.command(rich_help_panel=PANEL_SYSTEM)
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="confirm removal prompts"),
    data: bool = typer.Option(True, "--data/--keep-data", help="remove the local palace and config"),
    models: bool = typer.Option(True, "--models/--keep-models", help="remove SuperTon Ollama models"),
    all_models: bool = typer.Option(
        True,
        "--all-models/--keep-base-models",
        help="remove the configured base and embedding Ollama models",
    ),
    tool: bool = typer.Option(
        True,
        "--tool/--keep-tool",
        help="also remove the installed `superton` CLI binary (default: yes)",
    ),
) -> None:
    """Remove SuperTon local data, models, and the installed CLI tool.

    By default this removes **everything**: the palace at
    `~/Library/Application Support/superton` (or `$SUPERTON_HOME`), the
    Ollama tags for Superton + base + embed, and the `superton` CLI
    binary itself. Pass `--keep-data`, `--keep-models`, or `--keep-tool`
    to opt out of any stage.

    The CLI removal runs the installer's uninstall command via
    `subprocess.run`, then defensively sweeps the standard tool-venv +
    bin-shim locations. The earlier `os.execvp`-into-uv pattern gave no
    way to verify the cleanup actually finished — some uv versions
    silently left the tool venv directory behind, so a user running
    `superton uninstall` would still see `~/.local/share/uv/tools/superton`
    after the command returned 0.
    """
    cfg = _cfg()
    model_names = _uninstall_model_names(cfg, models=models, all_models=all_models)
    install_method = _detect_install_method()
    tool_cmd = _tool_uninstall_command()

    ui.section("uninstall superton")
    ui.blank()
    rows: list[tuple[str, str, str]] = []
    if data:
        existing = [p for p in _data_paths(cfg) if p.exists()]
        rows.append((
            "→" if existing else "-",
            "palace + caches",
            ", ".join(str(p) for p in existing) or str(cfg.home),
        ))
    else:
        rows.append(("-", "palace + caches", "kept (--keep-data)"))
    if model_names:
        rows.append(("→", "ollama models", ", ".join(model_names)))
    else:
        rows.append(("-", "ollama models", "kept (--keep-models)"))
    if tool:
        rows.append(("→", "superton CLI", " ".join(tool_cmd) + f"  ({install_method})"))
    else:
        rows.append(("-", "superton CLI", "kept (--keep-tool)"))
    ui.preflight_card(
        "about to remove",
        rows,
        summary="This wipes the palace and unlinks the binary so nothing remains in your PATH.",
    )
    ui.blank()

    if not any((data, model_names, tool)):
        ui.warn("nothing selected for removal")
        return

    if not yes and not typer.confirm("Remove selected SuperTon files/models?", default=False):
        ui.warn("uninstall cancelled")
        return

    total_steps = sum(int(bool(x)) for x in (model_names, data, tool))
    step = 0

    if model_names:
        step += 1
        with ui.stage("removing ollama models", step=step, total=total_steps):
            if shutil.which("ollama") is None:
                ui.stage_warn(
                    "ollama not found; skipped model removal",
                    hint="run `ollama rm superton` manually after installing ollama",
                )
            else:
                model = Model(cfg)
                for name in model_names:
                    model.stop(name)
                    result = subprocess.run(["ollama", "rm", name], check=False)
                    if result.returncode == 0:
                        ui.stage_ok(f"removed {name}")
                    else:
                        ui.stage_warn(
                            f"model not removed: {name}",
                            hint=f"try `ollama rm {name}` manually",
                        )
                model.close()

    if data:
        step += 1
        with ui.stage("removing palace + caches", step=step, total=total_steps):
            removed_any = False
            for path in _data_paths(cfg):
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
                    ui.stage_ok(f"removed {path}")
                    removed_any = True
            if not removed_any:
                ui.stage_skip("already gone")

    if tool:
        step += 1
        with ui.stage("removing superton CLI", step=step, total=total_steps):
            ui.hint(" ".join(tool_cmd))
            try:
                # Distinct name from the bytes-returning `result` used in
                # the ollama-rm branch above so mypy can pick the
                # `CompletedProcess[str]` overload here without a clash.
                proc = subprocess.run(
                    tool_cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError as e:
                # Installer binary isn't on PATH — fall through to the
                # defensive sweep so any orphan files still get cleaned.
                log.error("%s not on PATH: %s", tool_cmd[0], e)
                ui.stage_warn(
                    f"{tool_cmd[0]} not on PATH",
                    hint="cleanup will still try to remove orphan files",
                )
            else:
                stderr = (proc.stderr or "").strip()
                if proc.returncode == 0:
                    ui.stage_ok(f"{install_method} reported uninstall")
                else:
                    ui.stage_warn(
                        f"{install_method} exited {proc.returncode}",
                        hint=stderr or "see output above",
                    )

            # Defensive sweep — unlink any leftover tool venv directory
            # and bin shim the installer should have removed but didn't.
            # Even when the command returns 0, observed uv builds have
            # left ~/.local/share/uv/tools/superton on disk; explicit rm
            # makes `superton uninstall` actually idempotent.
            removed_orphans: list[Path] = []
            for orphan in _tool_orphan_paths(install_method):
                if _remove_orphan(orphan):
                    removed_orphans.append(orphan)
            if removed_orphans:
                for p in removed_orphans:
                    ui.stage_ok(f"removed orphan {p}")

    ui.blank()
    ui.ok("uninstall complete")
    if not tool:
        ui.hint(
            "the `superton` binary is still on your PATH (--keep-tool was passed)"
        )


import_app = typer.Typer(help="Import conversations from other AI tools.")
app.add_typer(import_app, name="import", rich_help_panel=PANEL_INGEST)


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
    with ui.spinner(
        "importing Claude Code sessions",
        phases=["Discovering sessions", "Parsing transcripts", "Indexing turns"],
    ):
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
    with ui.spinner(
        "importing ChatGPT conversations",
        phases=["Reading export", "Parsing conversations", "Indexing messages"],
    ):
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
    with ui.spinner(
        "importing Cursor threads",
        phases=["Discovering files", "Parsing JSONL", "Indexing"],
    ):
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
    with ui.spinner(
        "importing Amp threads",
        phases=["Discovering files", "Parsing JSONL", "Indexing"],
    ):
        files, drawers = GenericThreadImporter(
            mem, "amp", Path.home() / ".amp"
        ).import_all(root, replace=replace)
    mem.close()
    ui.ok(f"imported {drawers} drawers", f"from {files} Amp files")


@app.command(rich_help_panel=PANEL_SYSTEM)
def tune() -> None:
    """Open the Modelfile in $EDITOR and rebuild Superton."""
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
app.add_typer(mcp_app, name="mcp", rich_help_panel=PANEL_SYSTEM)


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
    except ImportError as e:
        log.error("mempalace mcp_server import failed: %s", e)
        ui.err("MemPalace MCP server unavailable", str(e))
        ui.hint("install with [bold]uv pip install mempalace[/bold]")
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
        log.exception("mcp server crashed")
        ui.err("mcp server crashed", str(e))
        ui.hint("re-run with [bold]SUPERTON_LOG=debug[/bold] for the full traceback")
        raise typer.Exit(1) from e
    finally:
        _sys.argv = argv_backup


@app.command(rich_help_panel=PANEL_PALACE)
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
    except ImportError as e:
        log.error("mempalace.dedup import failed: %s", e)
        ui.err("MemPalace dedup unavailable", str(e))
        raise typer.Exit(1) from e
    ui.section("dedup", f"threshold {threshold:.2f} · {'dry-run' if dry_run else 'APPLY'}")
    with ui.spinner(
        "scanning palace for duplicates",
        phases=["Loading drawers", "Computing similarities", "Grouping near-duplicates"],
    ):
        try:
            # mempalace's dedup_palace signature varies across versions —
            # the TypeError fallback below handles older positional-only forms.
            result = dedup_palace(  # type: ignore[call-arg]
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
