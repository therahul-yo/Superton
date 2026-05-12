"""SuperTon CLI — entry point.

Commands:
  superton init                set up palace + check ollama + build mini-ton
  superton add <path>          ingest file or directory
  superton ask "..."           query mini-ton with palace context
  superton list                show recent drawers
  superton search "..."        lexical search (semantic in Phase 1)
  superton forget <id>         remove a drawer
  superton stats               palace statistics
  superton import <source>     pull conversations from other AI tools
  superton tune                edit Modelfile and rebuild mini-ton
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from superton import __version__
from superton.blackhole import play_boot, static_frame
from superton.config import Config
from superton.ingest import chunk_text, read_file, walk
from superton.memory import Memory
from superton.model import Model, OllamaError

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


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="show version"),
) -> None:
    if version:
        console.print(f"superton {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _print_header()
        console.print("  try: [bold]superton init[/bold] · [bold]superton add <file>[/bold] · "
                      "[bold]superton ask \"...\"[/bold]\n")


@app.command()
def init(
    skip_animation: bool = typer.Option(False, "--no-animation"),
    skip_model: bool = typer.Option(False, "--no-model", help="skip ollama model build"),
) -> None:
    """Initialize the palace and build mini-ton."""
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
        return

    model = Model(cfg)
    if not model.ping():
        console.print("[yellow]![/yellow] ollama daemon not responding — start it with: "
                      "[bold]ollama serve[/bold]")
        return

    if not model.has_model(cfg.base_model):
        console.print(f"[dim]pulling {cfg.base_model}...[/dim]")
        subprocess.run(["ollama", "pull", cfg.base_model], check=False)
    if not model.has_model(cfg.embed_model):
        console.print(f"[dim]pulling {cfg.embed_model}...[/dim]")
        subprocess.run(["ollama", "pull", cfg.embed_model], check=False)

    modelfile = Path(__file__).resolve().parent.parent / "Modelfile"
    if not modelfile.exists():
        modelfile = Path.cwd() / "Modelfile"
    if modelfile.exists():
        console.print(f"[dim]building {cfg.model} from {modelfile.name}...[/dim]")
        subprocess.run(["ollama", "create", cfg.model, "-f", str(modelfile)], check=False)
        console.print(f"[green]✓[/green] mini-ton ready (as [bold]{cfg.model}[/bold])")
    else:
        console.print("[yellow]![/yellow] Modelfile not found — using base model directly")


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
    """Ask mini-ton a question. Answer is grounded in palace drawers."""
    cfg = _cfg()
    mem = Memory(cfg)
    hits = mem.search(question, limit=k)

    if not hits:
        console.print(f"  {PROMPT_GLYPH} [dim]not yet in the palace.[/dim]")
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
        console.print(table)

    context = "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} · {Path(h.drawer.source).name}]\n{h.drawer.text}"
        for h in hits
    )
    prompt = (
        f"Context drawers from the palace:\n\n{context}\n\n"
        f"Question: {question}\n\nAnswer concisely. Cite drawer IDs inline."
    )

    model = Model(cfg)
    if not model.ping():
        console.print("[yellow]![/yellow] ollama not running — falling back to raw retrieval")
        for h in hits:
            console.print(Panel(h.drawer.text[:400],
                                title=f"[cyan]drawer:{h.drawer.id[:8]}[/cyan]",
                                border_style="dim"))
        mem.close()
        return

    console.print(f"  {PROMPT_GLYPH} ", end="")
    try:
        for tok in model.generate(prompt):
            console.print(tok, end="")
        console.print()
    except OllamaError as e:
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
    """Lexical search across drawers."""
    mem = Memory(_cfg())
    hits = mem.search(query, limit=limit)
    if not hits:
        console.print("[dim]no drawers matched.[/dim]")
        mem.close()
        return
    for h in hits:
        console.print(Panel(
            h.drawer.text[:400],
            title=f"[cyan]drawer:{h.drawer.id[:8]}[/cyan] · "
                  f"[dim]{Path(h.drawer.source).name}[/dim]",
            border_style="dim",
        ))
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
    table.add_row("disk", f"{s['bytes'] / 1024:.1f} KB")
    console.print(Panel(table, title="palace", border_style="dim"))


import_app = typer.Typer(help="Import conversations from other AI tools.")
app.add_typer(import_app, name="import")


@import_app.command("claude-code")
def import_claude_code(
    root: Optional[Path] = typer.Option(None, "--root",
                                        help="defaults to ~/.claude/projects"),
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


@app.command()
def tune() -> None:
    """Open the Modelfile in $EDITOR and rebuild mini-ton."""
    cfg = _cfg()
    modelfile = Path(__file__).resolve().parent.parent / "Modelfile"
    if not modelfile.exists():
        console.print(f"[red]Modelfile not found at {modelfile}[/red]")
        raise typer.Exit(1)
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(modelfile)], check=False)
    if shutil.which("ollama"):
        subprocess.run(["ollama", "create", cfg.model, "-f", str(modelfile)], check=False)
        console.print(f"[green]✓[/green] {cfg.model} rebuilt")


if __name__ == "__main__":
    app()
