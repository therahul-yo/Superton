"""Interactive CLI shell for SuperTon."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from superton import __version__
from superton.config import Config
from superton.memory import Memory
from superton.model import Model, ModelError

console = Console()
GREETINGS = {"hi", "hey", "hello", "yo", "sup"}
STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "from",
    "give",
    "gimme",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "the",
    "this",
    "to",
    "u",
    "use",
    "what",
    "you",
}


def _prompt() -> str:
    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.formatted_text import HTML

        return prompt(
            "› ",
            placeholder=HTML("<gray>Ask from memory, paste a file path, or type /search &lt;query&gt;</gray>"),
        )
    except (ImportError, ValueError):
        return input("› ")


def _print_assistant(answer: str) -> None:
    console.print()
    console.print("[bold]Miniton[/bold]")
    console.print(answer)
    console.print()


def _print_intro(cfg: Config, mem: Memory) -> None:
    s = mem.stats()
    status = f"{s['drawers']}d · {s['wings']}w · {s['rooms']}r"
    card = Text()
    card.append("›_ SuperTon", style="bold")
    card.append(f"  (v{__version__})\n", style="dim")
    card.append("\n")
    card.append("model:  ", style="dim")
    card.append("Miniton", style="bold")
    card.append("   /model\n", style="dim")
    card.append("memory: ", style="dim")
    card.append("local palace", style="bold")
    card.append(f"   {status}\n", style="dim")
    card.append("dir:    ", style="dim")
    card.append(str(Path.cwd()))

    console.print()
    console.print(
        Panel(
            card,
            border_style="dim",
            width=min(console.width - 4, 56),
            padding=(0, 1),
        )
    )
    console.print()
    console.print(
        "[bold]Tip:[/bold] paste a file path to ingest it, or ask a question grounded in your palace."
    )
    console.print('Try: "what projects are in my resume?"  ·  /search rate limiting  ·  /stats')
    if s["drawers"] == 0:
        console.print("[yellow]⚠[/yellow] no drawers yet. Add a file with [bold]/add <path>[/bold].")
    filler = max(3, min(10, console.height - 17))
    console.print("\n" * filler, end="")
    console.print("[dim]" + "─" * min(console.width, 110) + "[/dim]")


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
            console.print(f"[yellow]![/yellow] skipped {file.name}: {e}")
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
        "resume",
        "resue",
        "cv",
        "pdf",
        "document",
        "file",
        "from my",
        "from his",
        "fromhis",
        "rahul",
    )
    if any(marker in normalized for marker in personal_markers):
        return True
    return "project" in normalized and ("my" in normalized or "rahul" in normalized)


def _relevant_hits(question: str, hits):
    tokens = _query_tokens(question)
    if not tokens:
        return []
    required = 2 if _looks_memory_specific(question) and len(tokens) > 1 else 1
    relevant = []
    for hit in hits:
        haystack = f"{Path(hit.drawer.source).name} {hit.drawer.text[:2500]}".lower()
        matches = sum(1 for token in tokens if token in haystack)
        if matches >= required:
            relevant.append(hit)
    return relevant


def _print_search_hits(hits) -> None:
    console.print()
    for hit in hits:
        preview = " ".join(hit.drawer.text.split())[:220]
        console.print(f"[cyan]{hit.drawer.id[:8]}[/cyan] · [dim]{Path(hit.drawer.source).name}[/dim]")
        console.print(f"  {preview}")
    console.print()


def _should_retrieve(question: str) -> bool:
    normalized = question.lower().strip(" !?.")
    return normalized not in GREETINGS


def _answer(mem: Memory, model: Model, question: str) -> None:
    raw_hits = mem.search(question, limit=8) if _should_retrieve(question) else []
    hits = _relevant_hits(question, raw_hits)
    if raw_hits and not hits and not _looks_memory_specific(question):
        hits = raw_hits[:3]
    if _looks_memory_specific(question) and not hits:
        _print_assistant(
            "I do not have matching memory for that. Add the resume or document first with "
            "`/add <path>` or paste the file path directly."
        )
        return
    context = "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} source:{Path(h.drawer.source).name}]\n{h.drawer.text[:900]}"
        for h in hits[:3]
    )
    system = (
        "You are Miniton inside the SuperTon CLI. Answer conversationally and briefly. "
        "If memory drawers are supplied, use ONLY those drawers for user, resume, document, project, "
        "or palace-specific factual claims and cite drawer IDs. If the answer is not in the drawers, "
        "say you do not have it in memory. If no drawers are supplied, answer normally as the local model. "
        "Do not paste raw drawers."
    )
    if hits:
        prompt = (
            f"Memory drawers:\n\n{context}\n\n"
            f"User message: {question}\n\n"
            "Write a concise answer, not a dump of the context."
        )
    else:
        prompt = (
            "No memory drawers were retrieved for this message.\n\n"
            f"User message: {question}\n\n"
            "Answer naturally and concisely."
        )
    try:
        if hasattr(model, "backend") and model.backend() is None and hasattr(model, "start_ollama"):
            model.start_ollama(timeout=5.0)
        answer = "".join(model.generate(prompt, system=system)).strip()
    except ModelError:
        if hits:
            answer = (
                "I found related memory, but the model backend is unavailable. "
                f"Top match: [{hits[0].drawer.id[:8]}] {Path(hits[0].drawer.source).name}"
            )
        else:
            answer = "Miniton is not available. Run `superton init` to start/build the local model."
    if not answer:
        answer = "I found related memory, but Miniton returned an empty answer."
    _print_assistant(answer)


def run() -> None:
    cfg = Config.load()
    mem = Memory(cfg)
    model = Model(cfg)
    try:
        _print_intro(cfg, mem)
        while True:
            try:
                text = _prompt().strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not text:
                continue
            if text in {"/quit", "/exit", "quit", "exit"}:
                break
            if text in {"/help", "?"}:
                console.print("/add <path> · /search <query> · /stats · /quit")
                continue
            if text == "/stats":
                s = mem.stats()
                console.print()
                console.print(
                    f"drawers {s['drawers']} · wings {s['wings']} · rooms {s['rooms']} · "
                    f"backend {s['backend']}"
                )
                console.print()
                continue
            path = _path_from_input(text)
            if path is not None:
                files, drawers = _ingest_path(mem, path)
                console.print(f"[green]✓[/green] ingested {drawers} drawers from {files} file(s)")
                continue
            if text == "/search":
                console.print()
                console.print("usage: /search <query>")
                console.print()
                continue
            if text.startswith("/search "):
                query = text.removeprefix("/search ").strip()
                hits = _relevant_hits(query, mem.search(query, limit=8))
                if not hits:
                    console.print()
                    console.print("[dim]no drawers matched.[/dim]")
                    console.print()
                    continue
                _print_search_hits(hits[:5])
                continue
            if text.startswith("/add "):
                path = Path(text.removeprefix("/add ").strip()).expanduser()
                if not path.exists():
                    console.print()
                    console.print(f"[yellow]![/yellow] not found: {path}")
                    console.print()
                    continue
                files, drawers = _ingest_path(mem, path)
                console.print()
                console.print(f"[green]✓[/green] ingested {drawers} drawers from {files} file(s)")
                console.print()
                continue
            _answer(mem, model, text)
    finally:
        mem.close()
        model.close()
