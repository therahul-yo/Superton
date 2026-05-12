"""SuperTon CLI — entry point.

Commands:
  superton init                set up palace + check ollama + build Miniton
  superton add <path>          ingest file or directory
  superton ask "..."           query Miniton with palace context
  superton list                show recent drawers
  superton search "..."        semantic search with SQLite fallback
  superton forget <id>         remove a drawer
  superton stats               palace statistics
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
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from superton import __version__
from superton.blackhole import play_boot, static_frame
from superton.config import Config
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

console = Console()
err_console = Console(stderr=True)

PROMPT_GLYPH = "[#FFD93D]❍[/]"


def _cfg() -> Config:
    return Config.load()


def _print_header() -> None:
    cfg = _cfg()
    mem = Memory(cfg)
    s = mem.stats()
    mem.close()
    console.print(static_frame(), justify="center")
    console.print(
        f"  [dim]palace · {s['drawers']} drawers · {s['wings']} wings · "
        f"{s['rooms']} rooms[/dim]",
        justify="center",
    )
    console.print()


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
    console.print()
    console.print(Panel(
        f"[bold]{model_name}[/bold]\n\n"
        f"{purpose}\n\n"
        "This downloads model weights to your local Ollama store.",
        title="Model Download",
        border_style="yellow",
    ))
    return typer.confirm("Pull this model now?", default=True)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="show version"),
) -> None:
    if version:
        console.print(f"superton {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _launch_shell()
        raise typer.Exit()


@app.command()
def init(
    skip_animation: bool = typer.Option(False, "--no-animation"),
    skip_model: bool = typer.Option(False, "--no-model", help="skip ollama model build"),
    yes: bool = typer.Option(False, "--yes", "-y", help="accept setup prompts"),
) -> None:
    """Initialize the palace and build Miniton."""
    if not skip_animation:
        play_boot(console, duration=1.4)

    cfg = _cfg()
    cfg.home.mkdir(parents=True, exist_ok=True)
    cfg.palace_dir.mkdir(parents=True, exist_ok=True)

    # Touch the memory store so the schema is created.
    Memory(cfg).close()
    console.print(f"[green]✓[/green] palace at [bold]{cfg.palace_dir}[/bold]")

    if skip_model:
        console.print("[dim]skipped ollama model build[/dim]")
        return

    if shutil.which("ollama") is None:
        console.print("[yellow]![/yellow] ollama not found in PATH")
        console.print("  install: [link]https://ollama.com/download[/link]")
        if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"):
            console.print("[green]✓[/green] Hugging Face fallback is configured via token")
        else:
            console.print(
                "  fallback: set [bold]HF_TOKEN[/bold] and "
                "[bold]SUPERTON_MODEL_BACKEND=huggingface[/bold]"
            )
        return

    model = Model(cfg)
    if not model.ollama_ready():
        console.print("[dim]starting ollama service...[/dim]")
        if not model.start_ollama():
            console.print("[yellow]![/yellow] could not start ollama automatically")
            console.print("  run manually: [bold]ollama serve[/bold]")
            console.print(
                "  or use Hugging Face: [bold]SUPERTON_MODEL_BACKEND=huggingface HF_TOKEN=...[/bold]"
            )
            model.close()
            return

    if not model.has_model(cfg.base_model):
        if not _confirm_pull(
            cfg.base_model,
            "Required to build Miniton, the local answer model.",
            yes=yes,
        ):
            console.print("[yellow]![/yellow] skipped model pull")
            model.close()
            return
        console.print(f"[dim]pulling Miniton base model ({cfg.base_model})...[/dim]")
        subprocess.run(["ollama", "pull", cfg.base_model], check=False)
        if not model.has_model(cfg.base_model):
            console.print(f"[red]error:[/red] failed to pull base model [bold]{cfg.base_model}[/bold]")
            model.close()
            return
    if not model.has_model(cfg.embed_model):
        if not _confirm_pull(
            cfg.embed_model,
            "Required for local embeddings and better semantic memory.",
            yes=yes,
        ):
            console.print("[yellow]![/yellow] skipped embedding model pull")
            model.close()
            return
        console.print(f"[dim]pulling {cfg.embed_model}...[/dim]")
        subprocess.run(["ollama", "pull", cfg.embed_model], check=False)

    modelfile = _project_modelfile()
    if modelfile is not None:
        rendered = _render_modelfile(modelfile, cfg)
        console.print(f"[dim]building {cfg.model} from {modelfile.name}...[/dim]")
        if model.build(rendered):
            console.print(f"[green]✓[/green] Miniton ready (as [bold]{cfg.model}[/bold])")
        else:
            console.print("[red]error:[/red] failed to build Miniton")
    else:
        console.print("[yellow]![/yellow] Modelfile not found — using base model directly")
    model.close()


@app.command()
def add(
    path: Path = typer.Argument(..., exists=True, help="file or directory to ingest"),
    wing: str = typer.Option("default", "--wing", "-w"),
    room: str = typer.Option("default", "--room", "-r"),
) -> None:
    """Ingest a file or directory into the palace."""
    cfg = _cfg()
    mem = Memory(cfg)
    files = list(walk(path))
    total_drawers = 0
    skipped = 0

    for f in files:
        try:
            text = read_file(f)
        except (ValueError, RuntimeError, UnicodeDecodeError) as e:
            err_console.print(f"  [dim]skip[/dim] {f.name}: {e}")
            skipped += 1
            continue
        if not text.strip():
            continue
        for chunk in chunk_text(text):
            mem.add(text=chunk, source=str(f), wing=wing, room=room)
            total_drawers += 1
        console.print(f"  [green]+[/green] {f.relative_to(path) if path.is_dir() else f.name}")

    mem.close()
    console.print(
        f"\n[green]✓[/green] ingested [bold]{total_drawers}[/bold] drawers from "
        f"{len(files) - skipped} file(s)"
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
    raw_hits = mem.search(question, limit=max(k, 8))
    from superton.shell import _looks_memory_specific, _relevant_hits

    hits = _relevant_hits(question, raw_hits)[:k]
    if raw_hits and not hits and not _looks_memory_specific(question):
        hits = raw_hits[:k]
    if _looks_memory_specific(question) and not hits:
        console.print(
            "  [yellow]![/yellow] no matching memory found. Add the source first with "
            "[bold]superton add <path>[/bold]."
        )
        mem.close()
        return

    if why:
        table = Table(title="retrieval", show_header=True, header_style="dim")
        table.add_column("drawer", style="cyan")
        table.add_column("source", style="dim")
        table.add_column("preview")
        for h in hits:
            preview = h.drawer.text.replace("\n", " ")[:80]
            table.add_row(h.drawer.id[:8], Path(h.drawer.source).name, preview)
        if not hits:
            table.add_row("-", "-", "no memory drawers matched")
        console.print(table)

    context = "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} · {Path(h.drawer.source).name}]\n{h.drawer.text}"
        for h in hits
    )
    if hits:
        prompt = (
            f"Context drawers from the palace:\n\n{context}\n\n"
            f"Question: {question}\n\nAnswer concisely. Cite drawer IDs inline."
        )
    else:
        prompt = (
            "No palace drawers matched this question.\n\n"
            f"Question: {question}\n\nAnswer naturally and concisely."
        )

    model = Model(cfg)
    if model.backend() is None:
        model.start_ollama(timeout=5.0)
    if model.backend() is None:
        console.print("[yellow]![/yellow] no model backend available")
        console.print("  run: [bold]superton init[/bold]")
        model.close()
        mem.close()
        return

    console.print(f"  {PROMPT_GLYPH} ", end="")
    try:
        for tok in model.generate(prompt):
            console.print(tok, end="")
        console.print()
    except (OllamaError, ModelError) as e:
        err_console.print(f"\n[red]error:[/red] {e}")
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
    table = Table(show_header=True, header_style="dim")
    table.add_column("id", style="cyan")
    table.add_column("wing/room", style="magenta")
    table.add_column("source", style="dim")
    table.add_column("preview")
    for d in rows:
        preview = d.text.replace("\n", " ")[:70]
        table.add_row(d.id[:8], f"{d.wing}/{d.room}", Path(d.source).name, preview)
    console.print(table)
    mem.close()


@app.command()
def search(query: str, limit: int = typer.Option(10, "--limit", "-n")) -> None:
    """Semantic search across drawers with SQLite fallback."""
    mem = Memory(_cfg())
    hits = mem.search(query, limit=limit)
    if not hits:
        console.print("[dim]no drawers matched.[/dim]")
        mem.close()
        return
    for h in hits:
        console.print(f"[cyan]drawer:{h.drawer.id[:8]}[/cyan] · [dim]{Path(h.drawer.source).name}[/dim]")
        console.print(h.drawer.text[:400])
        console.print("[dim]" + "─" * 60 + "[/dim]")
    mem.close()


@app.command()
def forget(drawer_id: str) -> None:
    """Remove a drawer by ID."""
    mem = Memory(_cfg())
    # accept short prefix
    if len(drawer_id) < 16:
        for d in mem.all(limit=10000):
            if d.id.startswith(drawer_id):
                drawer_id = d.id
                break
    ok = mem.forget(drawer_id)
    mem.close()
    if ok:
        console.print(f"[green]✓[/green] forgot {drawer_id[:8]}")
    else:
        console.print(f"[yellow]![/yellow] no drawer matched {drawer_id}")


@app.command()
def stats() -> None:
    """Palace statistics."""
    mem = Memory(_cfg())
    s = mem.stats()
    mem.close()
    table = Table(show_header=False, box=None)
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("drawers", str(s["drawers"]))
    table.add_row("wings", str(s["wings"]))
    table.add_row("rooms", str(s["rooms"]))
    table.add_row("backend", str(s["backend"]))
    table.add_row("disk", f"{s['bytes'] / 1024:.1f} KB")
    if s.get("semantic_error"):
        table.add_row("semantic", f"fallback active: {s['semantic_error']}")
    console.print("[bold]palace[/bold]")
    console.print(table)


@app.command()
def doctor() -> None:
    """Check local runtime, memory, and model setup."""
    cfg = _cfg()
    mem = Memory(cfg)
    s = mem.stats()
    mem.close()

    table = Table(show_header=True, header_style="dim")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")

    def row(name: str, ok: bool, detail: str) -> None:
        status = "[green]ok[/green]" if ok else "[yellow]warn[/yellow]"
        table.add_row(name, status, detail)

    row("home", cfg.home.exists(), str(cfg.home))
    row("palace", cfg.palace_dir.exists(), str(cfg.palace_dir))
    row("drawers", True, str(s["drawers"]))
    row("memory backend", True, cfg.memory_backend)
    row("model backend", True, cfg.model_backend)

    try:
        import mempalace

        row("mempalace", True, getattr(mempalace, "__version__", "installed"))
    except Exception as e:
        row("mempalace", False, str(e))

    row("ollama binary", shutil.which("ollama") is not None, shutil.which("ollama") or "missing")
    model = Model(cfg)
    ollama_ok = model.ollama_ready()
    row("ollama daemon", ollama_ok, cfg.ollama_url)
    if ollama_ok:
        row("Miniton model", model.has_model(cfg.model), cfg.model)
        row("base model", model.has_model(cfg.base_model), cfg.base_model)
        row("embed model", model.has_model(cfg.embed_model), cfg.embed_model)
    row("hugging face", model.hf_ready(), cfg.hf_model if model.hf_ready() else "HF_TOKEN missing")
    model.close()

    if s.get("semantic_error"):
        row("semantic index", False, str(s["semantic_error"]))
    else:
        row("semantic index", bool(s["semantic_enabled"]), cfg.semantic_collection)

    console.print("[bold]doctor[/bold]")
    console.print(table)


@app.command()
def reindex() -> None:
    """Rebuild semantic index from the SQLite drawer store."""
    mem = Memory(_cfg())
    total = mem.reindex_semantic()
    s = mem.stats()
    mem.close()
    if s.get("semantic_error"):
        console.print(f"[yellow]![/yellow] semantic reindex incomplete: {s['semantic_error']}")
        return
    console.print(f"[green]✓[/green] reindexed [bold]{total}[/bold] drawers")


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
        console.print("[yellow]![/yellow] ollama not found")
        return

    names = [cfg.model]
    if all_models:
        names.extend([cfg.base_model, cfg.embed_model])

    model = Model(cfg)
    for name in dict.fromkeys(names):
        ok = model.stop(name)
        status = "[green]✓[/green]" if ok else "[dim]-[/dim]"
        console.print(f"{status} stopped {name}")
    model.close()

    if force_daemon:
        console.print("[yellow]![/yellow] force-stopping ollama daemon")
        subprocess.run(["pkill", "-f", "ollama serve"], check=False)


import_app = typer.Typer(help="Import conversations from other AI tools.")
app.add_typer(import_app, name="import")


@import_app.command("claude-code")
def import_claude_code(
    root: Path | None = typer.Option(None, "--root", help="defaults to ~/.claude/projects"),
) -> None:
    """Import Claude Code session transcripts."""
    from superton.importers.claude_code import ClaudeCodeImporter
    mem = Memory(_cfg())
    importer = ClaudeCodeImporter(mem)
    sessions, drawers = importer.import_all(root)
    mem.close()
    console.print(
        f"[green]✓[/green] imported [bold]{drawers}[/bold] drawers from "
        f"[bold]{sessions}[/bold] Claude Code sessions"
    )


@import_app.command("chatgpt")
def import_chatgpt(
    root: Path = typer.Argument(..., exists=True, help="ChatGPT export directory or conversations.json"),
) -> None:
    """Import ChatGPT data export conversations."""
    from superton.importers.chatgpt import ChatGPTImporter

    mem = Memory(_cfg())
    conversations, drawers = ChatGPTImporter(mem).import_all(root)
    mem.close()
    console.print(
        f"[green]✓[/green] imported [bold]{drawers}[/bold] drawers from "
        f"[bold]{conversations}[/bold] ChatGPT conversations"
    )


@import_app.command("cursor")
def import_cursor(
    root: Path | None = typer.Option(None, "--root", help="defaults to ~/.cursor"),
) -> None:
    """Import readable Cursor conversation/log files."""
    from superton.importers.generic_threads import GenericThreadImporter

    mem = Memory(_cfg())
    files, drawers = GenericThreadImporter(mem, "cursor", Path.home() / ".cursor").import_all(root)
    mem.close()
    console.print(f"[green]✓[/green] imported [bold]{drawers}[/bold] drawers from {files} Cursor files")


@import_app.command("amp")
def import_amp(
    root: Path | None = typer.Option(None, "--root", help="defaults to ~/.amp"),
) -> None:
    """Import readable Amp conversation/log files."""
    from superton.importers.generic_threads import GenericThreadImporter

    mem = Memory(_cfg())
    files, drawers = GenericThreadImporter(mem, "amp", Path.home() / ".amp").import_all(root)
    mem.close()
    console.print(f"[green]✓[/green] imported [bold]{drawers}[/bold] drawers from {files} Amp files")


@app.command()
def tune() -> None:
    """Open the Modelfile in $EDITOR and rebuild Miniton."""
    cfg = _cfg()
    modelfile = _project_modelfile()
    if modelfile is None:
        console.print("[red]Modelfile not found[/red]")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(modelfile)], check=False)
    if shutil.which("ollama"):
        rendered = _render_modelfile(modelfile, cfg)
        model = Model(cfg)
        if model.build(rendered):
            console.print(f"[green]✓[/green] {cfg.model} rebuilt")
        model.close()


if __name__ == "__main__":
    app()
