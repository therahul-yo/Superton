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

from rich import box
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
    # Small themed anchor (prompt glyph) gives each section header a visual tie
    # to the active theme without being noisy.
    line.append(f"{_current.prompt_glyph} ", style=_current.primary)
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


def panel(content: Any, *, title: str | None = None, width: int | None = None, anchor: bool = False) -> None:
    """Render a panel around content.

    `anchor=True` uses the default ROUNDED border (for landing moments like
    the welcome / ready card). Otherwise we use a very subtle SIMPLE box —
    no heavy corners, just a thin separator vibe.

    If `width` is not given, the panel shrinks to fit its content instead
    of stretching to the console width — prevents the 'too wide' look on
    big terminals.
    """
    _console.print(
        Panel(
            content,
            title=title,
            border_style=_current.rule,
            padding=(0, 1),
            width=width,
            expand=width is not None,
            box=box.ROUNDED if anchor else box.SIMPLE,
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
    """Short inline citation — `cyan_id muted_filename`."""
    short = (drawer_id or "-")[:8]
    name = Path(source).name if source else ""
    return f"{style_id(short)} {style_path(name)}"


# --- semantic styling ---------------------------------------------------------
# A single place to decide how paths, ids, commands, and key bindings are
# rendered. Callers should prefer these over ad-hoc f-strings so the look
# stays consistent across the app.


def style_path(s: Any) -> str:
    """Filesystem paths and filenames — always muted."""
    return f"[{_current.muted}]{s}[/]"


def style_id(s: Any) -> str:
    """Drawer ids, commit SHAs, session ids — always the secondary accent."""
    return f"[{_current.secondary}]{s}[/]"


def style_cmd(s: Any) -> str:
    """Runnable commands — bold primary."""
    return f"[bold {_current.primary}]{s}[/]"


def style_kbd(s: Any) -> str:
    """Keyboard shortcut, rendered like [key]."""
    return (
        f"[{_current.muted}]\\[[/]"
        f"[{_current.secondary}]{s}[/]"
        f"[{_current.muted}]\\][/]"
    )


# --- git project awareness ----------------------------------------------------

def git_info(start: Path | None = None) -> tuple[str | None, str | None]:
    """Return (repo_name, branch) if `start` is inside a git repository,
    otherwise (None, None). File-based detection — no subprocess calls."""
    if start is None:
        start = Path.cwd()
    try:
        current = start.resolve()
    except OSError:
        return None, None
    while True:
        git_entry = current / ".git"
        if git_entry.is_dir():
            head_path = git_entry / "HEAD"
        elif git_entry.is_file():
            # Linked worktree: .git is a file pointing to the real gitdir.
            try:
                text = git_entry.read_text(encoding="utf-8").strip()
            except OSError:
                return None, None
            if not text.startswith("gitdir: "):
                return None, None
            real_git = Path(text[len("gitdir: "):]).expanduser()
            if not real_git.is_absolute():
                real_git = (current / real_git).resolve()
            head_path = real_git / "HEAD"
        else:
            if current.parent == current:
                return None, None
            current = current.parent
            continue
        try:
            head = head_path.read_text(encoding="utf-8").strip()
        except OSError:
            return current.name, None
        branch = head.rsplit("/", 1)[-1] if head.startswith("ref: ") else head[:7]
        return current.name, branch


# --- micro-animations ---------------------------------------------------------

def flash(content: Any, duration: float = 0.2) -> None:
    """Briefly display `content` in a transient Live frame and clear it.

    Used for 200 ms confirmation animations on theme/model switches.
    Non-terminal contexts are a no-op to avoid noise.
    """
    if not _console.is_terminal or duration <= 0:
        return
    with Live(content, console=_console, refresh_per_second=24, transient=True):
        time.sleep(duration)


def header(cfg, stats: dict, cwd: Path | None = None) -> None:
    """Quiet launch card shown by the interactive shell and init.

    Deliberately uses the SIMPLE panel border (not ROUNDED) and a single
    left-aligned column. The goal is the Claude Code CLI feel — present
    state up-front, but recede into the background once the user starts
    typing. Only `next_steps_card()` keeps the louder ROUNDED panel.
    """
    from superton import __version__

    cwd = cwd or Path.cwd()
    repo, branch = git_info(cwd)
    body = Text()
    body.append("SuperTon ", style=f"bold {_current.primary}")
    body.append(f"v{__version__}\n", style=_current.muted)
    body.append("\n")
    body.append("model   ", style=_current.muted)
    body.append("Miniton ", style="bold")
    body.append(f"{cfg.model_profile} · {cfg.base_model}\n", style=_current.muted)
    body.append("memory  ", style=_current.muted)
    body.append("palace  ", style="bold")
    body.append(
        f"{stats.get('drawers', 0)} drawers · "
        f"{stats.get('wings', 0)} wings · {stats.get('rooms', 0)} rooms\n",
        style=_current.muted,
    )
    body.append("theme   ", style=_current.muted)
    body.append(f"{_current.name} ", style="bold")
    body.append(f"{_current.label}\n", style=_current.muted)
    if repo:
        body.append("repo    ", style=_current.muted)
        body.append(repo, style="bold")
        if branch:
            body.append(f"  ·  {branch}\n", style=_current.muted)
        else:
            body.append("\n")
    body.append("cwd     ", style=_current.muted)
    body.append(str(cwd), style=_current.muted)

    _console.print()
    panel(body)
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
    """Brief fade-in wordmark shown on shell startup.

    Pure typography: the 'SuperTon' wordmark fades from muted → primary
    over a few frames. The mascot is intentionally NOT drawn here — the
    welcome panel that follows is its anchor, and rendering the mascot
    twice reads as duplication on the screen.
    """
    from superton import __version__

    wordmark_static = Text()
    wordmark_static.append("SuperTon", style=f"bold {_current.primary}")
    wordmark_static.append(f"  v{__version__}", style=_current.muted)

    if not _console.is_terminal:
        _console.print(wordmark_static)
        return

    steps = [_current.muted, _current.muted, _current.secondary, _current.primary]
    step_time = duration / max(len(steps), 1)
    with Live("", console=_console, refresh_per_second=24, transient=True) as live:
        for color in steps:
            wm = Text()
            wm.append("SuperTon", style=f"bold {color}")
            wm.append(f"  v{__version__}", style=_current.muted)
            live.update(wm)
            time.sleep(step_time)

    _console.print(wordmark_static)


def citations(hits) -> None:
    """Compact single-line `sources` footer.

    Renders all cited drawers on one row as numbered badges so the footer
    stays above the fold even when the answer is long. Multi-line fallback
    only kicks in if the row would not fit a typical 100-column terminal.
    """
    if not hits:
        return
    _console.print()
    badges: list[str] = []
    for i, h in enumerate(hits, 1):
        src = Path(h.drawer.source).name
        badges.append(
            f"[{_current.muted}][{i}][/] "
            f"{style_id(h.drawer.id[:8])} "
            f"{style_path(src)}"
        )
    # Rough width budget — fall back to one-per-line if the joined badge
    # row would wrap. Console.width is None in some test contexts.
    width = _console.width or 100
    joined_plain = "  ".join(
        f"[{i}] {h.drawer.id[:8]} {Path(h.drawer.source).name}"
        for i, h in enumerate(hits, 1)
    )
    label = f"[{_current.muted}]sources[/]"
    if len(joined_plain) + len("sources  ") <= width:
        _console.print(f"{label}  " + "  ".join(badges))
    else:
        _console.print(label)
        for badge in badges:
            _console.print(f"  {badge}")


def typing_cursor(char: str = "▎") -> str:
    """Inline styled cursor for streaming output."""
    return f"[{_current.muted}]{char}[/]"


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
    body.append("palace   ", style=_current.muted)
    body.append(f"{cfg.palace_dir}\n", style=_current.muted)
    body.append("model    ", style=_current.muted)
    body.append(f"Miniton · {cfg.model_profile} · {cfg.base_model}", style=_current.muted)

    panel(body, title="ready", anchor=True)


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
                # Cursor stays muted so streamed content reads as the focus
                # of the screen, not a glowing tail. Matches Claude Code.
                t.append("▎", style=_current.muted)
                live.update(t)
    else:
        for tok in token_iter:
            buf.append(tok)
    answer = "".join(buf).strip()
    if answer:
        markdown(answer)
    return answer
