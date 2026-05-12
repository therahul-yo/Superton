"""SuperTon terminal UI — themes and polished primitives.

All user-facing console output should flow through this module so visual
output stays consistent and swappable via `superton theme <name>`.

Design goals:
- Consistent icon vocabulary (✓ ! ✗ ℹ → ›)
- Dim metadata, bold emphasis, restrained color
- Tables without heavy borders — breathing room
- Spinners for any work > ~200ms

Themes are chosen by, in order:
  1. `SUPERTON_THEME` environment variable
  2. `theme = "..."` in the persisted config file
  3. the built-in default `nebula`
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text


@dataclass(frozen=True)
class Theme:
    """A visual palette for the SuperTon CLI."""

    name: str
    label: str
    primary: str
    secondary: str
    muted: str
    success: str
    warning: str
    error: str
    info: str
    neutral: str
    rule: str
    prompt: str
    prompt_glyph: str
    bullet: str


# Four hand-tuned themes. Colors are hex where we want fine control and
# named rich colors (e.g. "grey50") where terminal remapping is desirable.
THEMES: dict[str, Theme] = {
    "nebula": Theme(
        name="nebula",
        label="amber + violet · default",
        primary="#FFD93D",
        secondary="#87D1FF",
        muted="grey50",
        success="#7FE79B",
        warning="#FFB02E",
        error="#F0471F",
        info="#87D1FF",
        neutral="white",
        rule="grey30",
        prompt="#FFD93D",
        prompt_glyph="❍",
        bullet="›",
    ),
    "mono": Theme(
        name="mono",
        label="monochrome · bold only",
        primary="bold white",
        secondary="bold grey70",
        muted="grey50",
        success="bold white",
        warning="bold grey82",
        error="bold red",
        info="bold grey82",
        neutral="white",
        rule="grey30",
        prompt="bold white",
        prompt_glyph="›",
        bullet="·",
    ),
    "solar": Theme(
        name="solar",
        label="warm amber · sunrise",
        primary="#FFB02E",
        secondary="#FFD37A",
        muted="#8C6F2A",
        success="#FFD37A",
        warning="#FFB02E",
        error="#E04A1F",
        info="#FFEAB2",
        neutral="#FFEFCC",
        rule="#6B531F",
        prompt="#FFB02E",
        prompt_glyph="◉",
        bullet="▸",
    ),
    "frost": Theme(
        name="frost",
        label="cool cyan · arctic",
        primary="#87D1FF",
        secondary="#B7E4FF",
        muted="#5C7A94",
        success="#7FE7C1",
        warning="#FFD37A",
        error="#F98B9B",
        info="#87D1FF",
        neutral="#E8F2FF",
        rule="#3E5569",
        prompt="#87D1FF",
        prompt_glyph="◇",
        bullet="›",
    ),
}

DEFAULT_THEME = "nebula"


def _resolve_theme_name() -> str:
    override = os.environ.get("SUPERTON_THEME")
    if override and override in THEMES:
        return override
    # Import lazily to avoid a circular import at module load.
    try:
        from superton.config import Config

        cfg = Config.load()
        if cfg.theme in THEMES:
            return cfg.theme
    except Exception:
        pass
    return DEFAULT_THEME


_console = Console()
_err_console = Console(stderr=True)
_current: Theme = THEMES[_resolve_theme_name()]


def console() -> Console:
    return _console


def err_console() -> Console:
    return _err_console


def theme() -> Theme:
    return _current


def list_themes() -> list[Theme]:
    return list(THEMES.values())


def set_theme(name: str) -> Theme:
    global _current
    if name not in THEMES:
        choices = ", ".join(THEMES)
        raise ValueError(f"unknown theme {name!r}. choose one of: {choices}")
    _current = THEMES[name]
    return _current


# --- semantic print helpers ---------------------------------------------------

def _line(icon_style: str, icon: str, msg: str, detail: str | None) -> Text:
    text = Text()
    text.append(f"{icon} ", style=icon_style)
    text.append(msg)
    if detail:
        text.append(f"  {detail}", style=_current.muted)
    return text


def ok(msg: str, detail: str | None = None) -> None:
    _console.print(_line(_current.success, "✓", msg, detail))


def warn(msg: str, detail: str | None = None) -> None:
    _console.print(_line(_current.warning, "!", msg, detail))


def err(msg: str, detail: str | None = None) -> None:
    _err_console.print(_line(_current.error, "✗", msg, detail))


def info(msg: str, detail: str | None = None) -> None:
    _console.print(_line(_current.info, "ℹ", msg, detail))


def step(msg: str) -> None:
    """Dim progress breadcrumb used during multi-step work."""
    _console.print(f"[{_current.muted}]→ {msg}[/]")


def hint(msg: str) -> None:
    """Softer secondary line with indentation; used after ok()/warn()."""
    _console.print(f"  [{_current.muted}]{msg}[/]")


def blank() -> None:
    _console.print()


def rule(title: str | None = None) -> None:
    _console.rule(title or "", style=_current.rule)


def section(title: str, subtitle: str | None = None) -> None:
    _console.print()
    line = Text()
    line.append(title, style="bold")
    if subtitle:
        line.append(f"  {subtitle}", style=_current.muted)
    _console.print(line)


# --- structured output --------------------------------------------------------

def kv(pairs: list[tuple[str, str]]) -> None:
    """Render a two-column key/value block without a visible table frame."""
    t = Table(show_header=False, box=None, pad_edge=False)
    t.add_column(style=_current.muted, no_wrap=True)
    t.add_column(style="bold")
    for k, v in pairs:
        t.add_row(k, v)
    _console.print(t)


def make_table(*headers: str, show_header: bool = True) -> Table:
    """Create a theme-styled table for the caller to populate."""
    t = Table(
        show_header=show_header and bool(headers),
        header_style=_current.muted,
        box=None,
        pad_edge=False,
        expand=False,
    )
    for h in headers:
        t.add_column(h)
    return t


def print_table(t: Table) -> None:
    _console.print(t)


def panel(content: Any, *, title: str | None = None, width: int | None = None) -> None:
    _console.print(
        Panel(
            content,
            title=title,
            border_style=_current.rule,
            padding=(0, 1),
            width=width,
        )
    )


@contextmanager
def spinner(label: str):
    """Show a Rich spinner while a block of work runs."""
    if not _console.is_terminal:
        yield
        return
    with _console.status(f"[{_current.muted}]{label}[/]", spinner="dots"):
        yield


# --- domain helpers -----------------------------------------------------------

def prompt_glyph() -> str:
    """Styled prompt glyph for REPL / ask output."""
    return f"[{_current.prompt}]{_current.prompt_glyph}[/]"


def cite(drawer_id: str | None, source: str | None) -> str:
    """Short inline citation — `cyan_id grey_filename`."""
    short = (drawer_id or "-")[:8]
    name = Path(source).name if source else ""
    return f"[{_current.secondary}]{short}[/] [{_current.muted}]{name}[/]"


def header(cfg, stats: dict, cwd: Path | None = None) -> None:
    """Production-feel launch card shown by the interactive shell and init."""
    from superton import __version__

    cwd = cwd or Path.cwd()
    body = Text()
    body.append("SuperTon", style=f"bold {_current.primary}")
    body.append(f"  v{__version__}\n", style=_current.muted)
    body.append("\n")
    body.append("model   ", style=_current.muted)
    body.append("Miniton", style="bold")
    body.append(f"  {cfg.model_profile} · {cfg.base_model}\n", style=_current.muted)
    body.append("memory  ", style=_current.muted)
    body.append("palace", style="bold")
    body.append(
        f"   {stats.get('drawers', 0)} drawers · "
        f"{stats.get('wings', 0)} wings · {stats.get('rooms', 0)} rooms\n",
        style=_current.muted,
    )
    body.append("theme   ", style=_current.muted)
    body.append(_current.name, style="bold")
    body.append(f"  {_current.label}\n", style=_current.muted)
    body.append("cwd     ", style=_current.muted)
    body.append(str(cwd), style=_current.muted)

    _console.print()
    panel(body, width=min(_console.width - 2, 74))
    _console.print()


def footer_hints(lines: list[str]) -> None:
    """Two or three short tip lines shown below the header."""
    for line in lines:
        _console.print(f"[{_current.muted}]{line}[/]")


# --- progress, animations, citations ------------------------------------------


@contextmanager
def progress(description: str, total: int | None = None):
    """Context-managed progress bar styled by the active theme.

    Usage:
        with ui.progress("ingesting", total=len(files)) as advance:
            for file in files:
                ...
                advance()
    """
    cols: list = [
        SpinnerColumn(style=_current.primary),
        TextColumn(f"[{_current.muted}]{{task.description}}[/]"),
    ]
    if total is not None and total > 0:
        cols.extend([
            BarColumn(
                bar_width=None,
                complete_style=_current.primary,
                finished_style=_current.success,
                pulse_style=_current.secondary,
            ),
            MofNCompleteColumn(),
        ])
    cols.append(TimeElapsedColumn())

    prog = Progress(*cols, console=_console, transient=True)
    with prog:
        task = prog.add_task(description, total=total)

        def advance(step: int = 1, description: str | None = None) -> None:
            if description is not None:
                prog.update(task, description=description)
            prog.advance(task, step)

        yield advance


def boot_splash(duration: float = 0.6) -> None:
    """Brief fade-in header used on shell startup.

    A few frames of the primary-colored wordmark blending from muted to
    primary. Non-terminal contexts get a single frame (no flicker).
    """
    from superton import __version__

    if not _console.is_terminal:
        _console.print(
            f"[bold {_current.primary}]SuperTon[/] "
            f"[{_current.muted}]v{__version__}[/]"
        )
        return

    # Fade through a handful of muted steps then settle on primary.
    frames = [
        _current.muted,
        _current.muted,
        _current.secondary,
        _current.primary,
    ]
    wordmark = "SuperTon"
    version = f"  v{__version__}"
    step = duration / max(len(frames), 1)
    with Live("", console=_console, refresh_per_second=24, transient=True) as live:
        for color in frames:
            t = Text()
            t.append(wordmark, style=f"bold {color}")
            t.append(version, style=_current.muted)
            live.update(t)
            time.sleep(step)
    # Final static frame stays in scrollback.
    t = Text()
    t.append(wordmark, style=f"bold {_current.primary}")
    t.append(version, style=_current.muted)
    _console.print(t)


def citations(hits) -> None:
    """Compact `Sources` footer listing the drawers used for an answer."""
    if not hits:
        return
    _console.print()
    _console.print(f"[{_current.muted}]sources[/]")
    for i, h in enumerate(hits, 1):
        src = Path(h.drawer.source).name
        _console.print(
            f"  [{_current.muted}]{i}.[/] "
            f"[{_current.secondary}]{h.drawer.id[:8]}[/] "
            f"[{_current.muted}]{src}[/]"
        )


def typing_cursor(char: str = "▎") -> str:
    """Inline styled cursor for streaming output."""
    return f"[{_current.primary}]{char}[/]"


# --- staged flow, markdown, score coloring, next-steps card -------------------

@contextmanager
def stage(title: str):
    """A numbered step shown during multi-stage work like `superton init`.

    Usage:
        with ui.stage("creating palace"):
            ...
            ui.stage_detail("palace at {path}")
    """
    _console.print(f"[{_current.primary}]→[/] {title}")
    try:
        yield
    except Exception:
        _console.print(f"  [{_current.error}]✗ {title} failed[/]")
        raise


def stage_ok(msg: str) -> None:
    """Indented success line paired with the preceding `stage()`."""
    _console.print(f"  [{_current.success}]✓[/] {msg}")


def stage_warn(msg: str) -> None:
    _console.print(f"  [{_current.warning}]![/] {msg}")


def stage_skip(msg: str) -> None:
    _console.print(f"  [{_current.muted}]- {msg}[/]")


def markdown(text: str) -> None:
    """Render assistant output as markdown. Code blocks get syntax highlighting,
    lists get proper bullets, headings are bolded. Safe on non-markdown plain
    text because rich.markdown degrades gracefully.
    """
    if not text:
        return
    _console.print(Markdown(text, code_theme="ansi_dark"))


def score_color(score: float) -> str:
    """Map a similarity score to a theme-aware confidence color."""
    if score >= 0.65:
        return _current.success
    if score >= 0.40:
        return _current.warning
    return _current.muted


def next_steps_card(cfg) -> None:
    """Polished 'you're ready' panel shown at the end of init and by
    `superton welcome`."""
    body = Text()
    body.append("SuperTon is ready.\n", style=f"bold {_current.primary}")
    body.append("\n")
    body.append("Try one of:\n", style=_current.muted)
    body.append("  superton add ~/notes\n", style="bold")
    body.append("  superton import claude-code\n", style="bold")
    body.append('  superton ask "what did I decide about X?"\n', style="bold")
    body.append("  superton                              ", style="bold")
    body.append("# interactive shell\n", style=_current.muted)
    body.append("\n")
    body.append("Power commands:\n", style=_current.muted)
    body.append("  superton theme                        ", style="bold")
    body.append("# change look & feel\n", style=_current.muted)
    body.append("  superton mcp serve                    ", style="bold")
    body.append("# expose palace to Claude/Cursor\n", style=_current.muted)
    body.append("  superton dedup --dry-run              ", style="bold")
    body.append("# find near-duplicates\n", style=_current.muted)
    body.append("\n")
    body.append(f"palace   {cfg.palace_dir}\n", style=_current.muted)
    body.append(f"model    Miniton · {cfg.model_profile} · {cfg.base_model}", style=_current.muted)

    panel(body, title="ready", width=min(_console.width - 2, 78))


def welcome_tour(cfg, stats: dict) -> None:
    """Friendly 3-line introduction usable as `superton welcome` or on first
    run when the palace is empty."""
    header(cfg, stats)
    _console.print(
        f"[{_current.muted}]SuperTon is a local-first personal second brain.[/] "
        f"Feed it files and conversations; ask it questions grounded in what it "
        f"has seen."
    )
    _console.print(
        f"[{_current.muted}]Your palace lives on-disk at[/] "
        f"[bold]{cfg.palace_dir}[/]"
        f"[{_current.muted}] — nothing leaves your machine by default.[/]"
    )
    _console.print()
    next_steps_card(cfg)


def stream_answer(token_iter, label: str = "Miniton") -> str:
    """Stream tokens live under a header. Returns the full answer string.

    Uses rich.Live so tokens appear as they arrive. After the stream ends,
    the final answer is re-rendered as markdown for a tidy output.

    Exceptions from the token iterator propagate to the caller so that
    model errors (e.g. ModelError) can be handled upstream.
    """
    _console.print()
    _console.print(f"[bold {_current.primary}]{label}[/]")
    buf: list[str] = []
    if _console.is_terminal:
        with Live(
            Text(""),
            console=_console,
            refresh_per_second=30,
            transient=True,
        ) as live:
            for tok in token_iter:
                buf.append(tok)
                running = "".join(buf)
                t = Text(running)
                # Show a soft cursor at the tail while streaming.
                t.append("▎", style=_current.primary)
                live.update(t)
    else:
        for tok in token_iter:
            buf.append(tok)
    answer = "".join(buf).strip()
    if answer:
        markdown(answer)
    return answer
