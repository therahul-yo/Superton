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
import sys
from pathlib import Path

import typer

from superton import __version__, errors, ui
from superton.blackhole import static_frame
from superton.config import MODEL_PROFILES, Config, detect_ram_gb, write_settings
from superton.ingest import chunk_text, read_file, walk
from superton.logging import get_logger
from superton.memory import Memory
from superton.model import Model, ModelError, OllamaError

log = get_logger("cli")

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


def _pick_model_profile(*, default: str = "proton") -> str:
    """Interactive picker showing size + RAM-fit per profile.

    Renders one rounded card per profile (active card border accents in
    primary, others in rule). Each card shows a marker pill, the Ollama
    base tag, the download size, and a visual RAM-fit bar — easier to
    read at a glance than the old `Table` form.
    """
    ram_gb = detect_ram_gb()
    ui.blank()
    ui.section("choose a model profile")
    if ram_gb is not None:
        ui.hint(f"detected RAM · {ram_gb:.1f} GB")
    ui.blank()
    for name, data in MODEL_PROFILES.items():
        ui.profile_card(
            name,
            base_model=str(data["base_model"]),
            download_gb=float(data["download_gb"]),
            min_ram_gb=int(data["min_ram_gb"]),
            label=str(data["label"]),
            ram_gb=ram_gb,
            selected=(name == default),
        )
    ui.blank()
    while True:
        choice = typer.prompt(
            f"profile [{'/'.join(MODEL_PROFILES)}]",
            default=default,
        ).strip().lower()
        if choice in MODEL_PROFILES:
            return choice
        ui.warn("pick one of: " + ", ".join(MODEL_PROFILES))


def _pick_theme(*, default: str = "nebula") -> str:
    """Interactive theme picker shown during init.

    Stays quiet when the user already accepted a CLI flag — only invoked
    when neither `--theme` nor `--yes` was passed. Re-uses the
    `theme_picker_card` UI helper.
    """
    ui.blank()
    ui.section("choose a theme")
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
        rows.append(("?", "embed model", f"{cfg.embed_model}  (probed in stage 4)"))
        rows.append(("?", "Miniton", f"{cfg.model}  (built in stage 5)"))
    else:
        rows.append(("→", "ollama", "will offer to install"))
        rows.append(("?", "base model", "needs ollama"))
        rows.append(("?", "Miniton", "needs ollama"))

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
        f"Ollama is missing — needed to run Miniton locally.\n\n"
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
        "Assistant transcript: Rahul decided the product should stay local-first, avoid "
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
    ui.header(cfg, stats)
    ui.ready_card(cfg, stats)


@app.command()
def init(
    skip_model: bool = typer.Option(False, "--no-model", help="skip ollama model build"),
    yes: bool = typer.Option(False, "--yes", "-y", help="accept setup prompts"),
    model_profile: str | None = typer.Option(
        None, "--model", "-m",
        help=f"model profile to set up: {', '.join(MODEL_PROFILES)}",
    ),
    theme: str | None = typer.Option(
        None, "--theme", "-t",
        help=f"CLI theme: {', '.join(ui.THEMES)}",
    ),
) -> None:
    """Initialize the palace and build Miniton."""
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
    if model_profile and model_profile not in MODEL_PROFILES:
        ui.err("unknown model profile", "choose one of: " + ", ".join(MODEL_PROFILES))
        raise typer.Exit(1)
    if theme and theme not in ui.THEMES:
        ui.err("unknown theme", "choose one of: " + ", ".join(ui.THEMES))
        raise typer.Exit(1)

    # ---------------------------------------------------------------------
    # Stage 0 — pick model profile + theme (interactive when not provided and
    # the user didn't pass --yes, so first-run users see the choices)
    # ---------------------------------------------------------------------
    if model_profile is None and not yes and not skip_model:
        try:
            model_profile = _pick_model_profile(default=cfg.model_profile)
        except (EOFError, KeyboardInterrupt):
            model_profile = cfg.model_profile

    if theme is None and not yes:
        try:
            theme = _pick_theme(default=cfg.theme)
        except (EOFError, KeyboardInterrupt):
            theme = cfg.theme

    settings_update: dict[str, str] = {}
    if model_profile and model_profile != cfg.model_profile:
        selected = MODEL_PROFILES[model_profile]
        settings_update.update(
            model_profile=model_profile,
            base_model=selected["base_model"],
            hf_model=selected["hf_model"],
        )
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
    profile_data = MODEL_PROFILES[cfg.model_profile]
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
                f"Required to build Miniton, the local answer model. "
                f"~{profile_data['download_gb']:.1f} GB.",
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
            if not model.has_model(cfg.base_model):
                ui.stage_warn(
                    f"failed to pull {cfg.base_model}",
                    hint="check network and disk space, then rerun: superton init",
                )
                model.close()
                return
            ui.stage_ok("downloaded")

    # ---------------------------------------------------------------------
    # Stage 4 — embedding model
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage(
        f"pulling embedding model · {cfg.embed_model}",
        step=step,
        total=total_stages,
    ):
        if model.has_model(cfg.embed_model):
            ui.stage_ok("already present")
        else:
            if not _confirm_pull(
                cfg.embed_model,
                "Required for local embeddings and better semantic memory. ~270 MB.",
                yes=yes,
            ):
                ui.stage_warn(
                    "skipped embedding model pull",
                    hint=f"rerun later: ollama pull {cfg.embed_model}",
                )
                model.close()
                ui.blank()
                _finish_init(cfg, offer_demo=not yes)
                return
            subprocess.run(["ollama", "pull", cfg.embed_model], check=False)
            ui.stage_ok("downloaded")

    # ---------------------------------------------------------------------
    # Stage 5 — build Miniton
    # ---------------------------------------------------------------------
    step += 1
    with ui.stage("building Miniton", step=step, total=total_stages):
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


@app.command()
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


@app.command()
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
        for chunk in chunk_text(page.markdown):
            mem.add(text=chunk, source=target, wing=wing, room=room)
            drawers += 1
        mem.close()
        ui.blank()
        ui.ok(f"ingested {drawers} drawers", f"from {target}")
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


@app.command()
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
    files, drawers, _skipped, _deduped = _ingest_into_memory(mem, path, wing=wing, room=room)
    mem.close()
    ui.blank()
    ui.diff_summary(removed=removed, added=drawers)
    ui.blank()
    ui.ok(f"refreshed {files} file(s)")


@app.command()
def ask(
    question: str = typer.Argument(..., help="your question"),
    k: int = typer.Option(5, "--top-k", "-k"),
    why: bool = typer.Option(False, "--why", help="show retrieval trace"),
) -> None:
    """Ask Miniton a question. Answer is grounded in palace drawers."""
    cfg = _cfg()
    mem = Memory(cfg)
    with ui.spinner(
        "retrieving from palace",
        phases=["Searching palace", "Ranking drawers", "Re-scoring sources", "Composing context"],
    ):
        raw_hits = mem.search(question, limit=max(k, 8))
    stats = mem.stats()
    if stats["drawers"] == 0:
        ui.warn("your palace is empty")
        ui.hint("ingest something first: [bold]superton add ~/notes[/bold] or try [bold]superton demo[/bold]")
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
        f"[drawer:{h.drawer.id[:8]} · {Path(h.drawer.source).name}]\n"
        f"{h.drawer.text[:ANSWER_DRAWER_CHARS]}"
        for h in hits[:context_limit]
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
        log.error("ask failed: %s", e)
        errors.render(e)
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
    with ui.spinner(
        f"searching palace for {query!r}",
        phases=["Embedding query", "Scanning drawers", "Re-ranking hits"],
    ):
        hits = mem.search(query, limit=limit)
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
        ui.err("unknown profile", "choose " + " | ".join(MODEL_PROFILES))
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
def doctor(
    json_output: bool = typer.Option(False, "--json", help="emit machine-readable diagnostics"),
) -> None:
    """Check local runtime, memory, and model setup."""
    from superton.doctor import render_doctor_report

    render_doctor_report(_cfg(), json_output=json_output)


@app.command()
def tui() -> None:
    """Launch the Textual TUI (opt-in in 0.2.0).

    Requires the optional `textual` dependency. The install.sh script
    pulls it in by default; pre-existing installs need a one-line
    refresh. See docs/TUI_ARCHITECTURE.md for the design + key bindings.
    """
    try:
        from superton.tui.app import run_tui
    except ImportError as e:
        log.error("textual not installed: %s", e)
        ui.err("textual is not installed", str(e))
        ui.blank()
        # Detect the installer flavour so the hint matches what the user
        # actually used to install SuperTon — keeps the recovery one
        # copy-paste away.
        sys_exec = sys.executable
        if "/uv/tools/" in sys_exec or "/uv-cache/" in sys_exec:
            ui.hint("install with:  [bold]uv tool install --with textual superton --force[/]")
        elif shutil.which("pipx"):
            ui.hint("install with:  [bold]pipx inject superton textual[/]")
        else:
            ui.hint("install with:  [bold]pip install 'superton[tui]'[/]")
        ui.hint("or rerun:      [bold]curl -fsSL https://raw.githubusercontent.com/therahul-yo/Superton/main/install.sh | sh[/]")
        raise typer.Exit(1) from e
    run_tui(_cfg())


@app.command()
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


def _detect_install_method() -> str:
    """Best-effort sniff of how SuperTon was installed.

    Looks at `sys.executable` because the running interpreter lives inside
    the installer's venv — uv puts it under `…/uv/tools/superton/`, pipx
    under `…/pipx/venvs/superton/`, plain pip in the user's site-packages
    or a venv. Returns one of {"uv", "pipx", "pip", "unknown"}.
    """
    exe = Path(sys.executable).resolve()
    text = str(exe)
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


def _uninstall_model_names(cfg: Config, *, models: bool, all_models: bool) -> list[str]:
    if not models:
        return []
    names = [cfg.model]
    if all_models:
        names.extend([cfg.base_model, cfg.embed_model])
    return list(dict.fromkeys(names))


@app.command()
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
    Ollama tags for Miniton + base + embed, and the `superton` CLI
    binary itself. Pass `--keep-data`, `--keep-models`, or `--keep-tool`
    to opt out of any stage.

    The CLI removal uses `os.execvp` so the binary can replace itself —
    a vanilla `subprocess.run` from inside the running process often
    leaves a stale shim in `~/.local/bin/superton`.
    """
    cfg = _cfg()
    model_names = _uninstall_model_names(cfg, models=models, all_models=all_models)
    install_method = _detect_install_method()
    tool_cmd = _tool_uninstall_command()

    ui.section("uninstall superton")
    ui.blank()
    rows: list[tuple[str, str, str]] = []
    if data:
        rows.append((
            "→" if cfg.home.exists() else "-",
            "palace + config",
            str(cfg.home),
        ))
    else:
        rows.append(("-", "palace + config", "kept (--keep-data)"))
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
                    hint="run `ollama rm miniton` manually after installing ollama",
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
        with ui.stage("removing palace", step=step, total=total_steps):
            if cfg.home.exists():
                shutil.rmtree(cfg.home)
                ui.stage_ok(f"removed {cfg.home}")
            else:
                ui.stage_skip(f"already gone: {cfg.home}")

    if tool:
        step += 1
        ui.blank()
        # We close stdout/Rich console gracefully BEFORE swapping process
        # images. After os.execvp our Python process is gone — the
        # installer's uninstall command takes over and can safely
        # unlink the binary that was holding our PID.
        ui.console().print(
            f"[{ui.theme().muted}]→ [{step}/{total_steps}] swapping into:[/]  "
            f"[bold]{' '.join(tool_cmd)}[/]"
        )
        ui.blank()
        try:
            os.execvp(tool_cmd[0], tool_cmd)
        except OSError as e:
            # execvp only fails if the installer command is missing — fall
            # back to subprocess so we at least leave a useful exit code.
            log.error("execvp(%s) failed: %s", tool_cmd[0], e)
            ui.err(f"{tool_cmd[0]} not on PATH", str(e))
            ui.hint("run manually:  " + " ".join(tool_cmd))
            raise typer.Exit(1) from e

    # We only reach here when --keep-tool was set.
    ui.blank()
    ui.ok("uninstall complete")
    ui.hint("the `superton` binary is still on your PATH (--keep-tool was passed)")


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
