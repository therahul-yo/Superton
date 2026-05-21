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
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console, Group
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
    except (ImportError, OSError, ValueError):
        # Config file unreadable or platformdirs misbehaving — fall through to default.
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


def section(title: str, subtitle: str | None = None, *, sweep: bool = True) -> None:
    """Print a themed section header.

    With `sweep=True` on a TTY, the prefix glyph briefly fades muted →
    secondary → primary (~120ms) so each new section registers visually.
    Falls back to a single static print in non-terminal contexts.
    """
    _console.print()

    def _line(glyph_style: str) -> Text:
        out = Text()
        out.append(f"{_current.prompt_glyph} ", style=glyph_style)
        out.append(title, style="bold")
        if subtitle:
            out.append(f"  {subtitle}", style=_current.muted)
        return out

    if not sweep or not _console.is_terminal:
        _console.print(_line(_current.primary))
        return

    sweep_styles = [_current.muted, _current.secondary, _current.primary]
    with Live(_line(sweep_styles[0]), console=_console, refresh_per_second=30, transient=True) as live:
        for style in sweep_styles:
            live.update(_line(style))
            time.sleep(0.04)
    # Live was transient; print the final line so it persists in scrollback.
    _console.print(_line(_current.primary))


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
def spinner(
    label: str,
    *,
    phases: Iterable[str] | None = None,
    phase_interval: float = 0.85,
):
    """Show a Rich spinner while a block of work runs.

    Yields a `set_status(label)` callable so long-running work can update
    the spinner text live (e.g. `pulling … 42/100 pages`). The setter is
    a no-op in non-terminal contexts.

    `phases`, when supplied, is cycled in a background daemon thread —
    the spinner text rotates through the verbs every `phase_interval`
    seconds. Calling `set_status` mid-stream takes over and overrides
    the cycle until the next phase tick.
    """
    if not _console.is_terminal:
        def _noop(_label: str) -> None:
            return None

        yield _noop
        return

    phase_list = list(phases) if phases else None
    with _console.status(f"[{_current.muted}]{label}[/]", spinner="dots") as status:
        stop = threading.Event()
        cycler: threading.Thread | None = None
        if phase_list:
            def _cycle() -> None:
                idx = 0
                while not stop.wait(phase_interval):
                    status.update(f"[{_current.muted}]{phase_list[idx % len(phase_list)]}…[/]")
                    idx += 1

            cycler = threading.Thread(target=_cycle, daemon=True)
            cycler.start()

        def _set(new_label: str) -> None:
            status.update(f"[{_current.muted}]{new_label}[/]")

        try:
            yield _set
        finally:
            stop.set()
            if cycler is not None:
                cycler.join(timeout=0.1)


# --- card / pill primitives ---------------------------------------------------


def pill(label: str, *, kind: str = "neutral") -> Text:
    """Compact background-tinted badge for status displays.

    `kind` is one of: primary, secondary, success, warning, error, neutral.
    Falls back to neutral if unknown. The background colors lean on the
    active theme's `rule` value so pills sit naturally next to it.
    """
    palette = {
        "primary": (_current.primary, _current.neutral),
        "secondary": (_current.secondary, _current.neutral),
        "success": (_current.success, "grey15"),
        "warning": (_current.warning, "grey15"),
        "error": (_current.error, _current.neutral),
        "info": (_current.info, "grey15"),
        "neutral": (_current.muted, _current.neutral),
    }
    fg, bg_hint = palette.get(kind, palette["neutral"])
    text = Text()
    text.append(f" {label} ", style=f"bold {bg_hint} on {fg}")
    return text


def status_pills(cfg: Any, stats: dict[str, Any]) -> Text:
    """GitHub-style row of pills summarizing the current session.

    Reads as a single visual stripe: theme · model · palace size. Designed
    to replace the dim text line under the welcome card.
    """
    row = Text()
    row.append_text(pill(_current.name, kind="primary"))
    row.append("  ")
    row.append_text(pill(f"miniton:{cfg.model_profile}", kind="secondary"))
    row.append("  ")
    row.append_text(pill(f"palace · {stats.get('drawers', 0)}", kind="neutral"))
    if stats.get("semantic_error"):
        row.append("  ")
        row.append_text(pill("semantic offline", kind="warning"))
    return row


def card(
    title: str,
    body: Any,
    *,
    status: tuple[str, str] | None = None,
) -> None:
    """Rounded tool-result card with optional status pill in the title.

    Usage:
        ui.card("search", body_text, status=("ok", "success"))

    `body` is any Rich-renderable (Text, Markdown, Group, Table, str).
    """
    title_text = Text()
    title_text.append(f"▸ {title}", style=f"bold {_current.primary}")
    if status is not None:
        label, kind = status
        title_text.append("  ")
        title_text.append_text(pill(label, kind=kind))

    if isinstance(body, str):
        body_renderable: Any = Text(body)
    else:
        body_renderable = body

    _console.print(
        Panel(
            body_renderable,
            title=title_text,
            title_align="left",
            border_style=_current.rule,
            padding=(0, 1),
            expand=False,
            box=box.ROUNDED,
        )
    )


# --- diff / shimmer / pager ---------------------------------------------------


def diff_summary(removed: int, added: int, *, label: str = "drawers") -> None:
    """Render `refresh`-style output as a two-line diff for at-a-glance reads."""
    minus = Text()
    minus.append(f"  - {removed:>4} {label}", style=f"dim {_current.error}")
    plus = Text()
    plus.append(f"  + {added:>4} {label}", style=f"dim {_current.success}")
    _console.print(minus)
    _console.print(plus)


def shimmer(label: str, *, cycles: int = 3, interval: float = 0.12) -> None:
    """Brief 'scanning…' pulse used before printing an empty-state message.

    Cycles the label through muted → secondary → muted to imply "we did
    actually look". No-op in non-terminal contexts.
    """
    if not _console.is_terminal:
        return
    styles = [_current.muted, _current.secondary, _current.primary, _current.secondary]
    with Live(Text(label, style=styles[0]), console=_console, refresh_per_second=30, transient=True) as live:
        for _ in range(cycles):
            for style in styles:
                live.update(Text(label, style=style))
                time.sleep(interval)


def maybe_pager(text: str, *, threshold_lines: int | None = None) -> None:
    """Print `text` directly, or pipe through a pager when it would overflow.

    The pager activates only on a TTY and only when the rendered text exceeds
    `threshold_lines` (default: terminal height minus 4). Markdown is rendered
    inside the pager too so `q` exits cleanly.
    """
    if not _console.is_terminal or not text:
        if text:
            markdown(text)
        return
    threshold = threshold_lines if threshold_lines is not None else max(20, (_console.size.height or 24) - 4)
    line_count = text.count("\n") + 1
    if line_count <= threshold:
        markdown(text)
        return
    with _console.pager(styles=True):
        markdown(text)


def numbered_chip(n: int, drawer_id: str | None, source: str | None) -> Text:
    """Pill-style numbered citation chip.

    Used by `citations()` to render `[ 1 ] abcd1234 file.md` with the
    number inside a real background tint instead of plain brackets.
    """
    label = f" {n} "
    text = Text()
    text.append(label, style=f"bold {_current.neutral} on {_current.muted}")
    text.append(" ")
    text.append((drawer_id or "-")[:8], style=_current.secondary)
    text.append(" ")
    text.append(Path(source).name if source else "", style=_current.muted)
    return text


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


# --- prompt_toolkit color bridge ---------------------------------------------
# Rich understands shade-named greys (grey50, grey70, ...) but prompt_toolkit
# does not; it wants hex or a small set of named colors. Translate on the fly
# so we can keep themes expressed in Rich's natural vocabulary.
_GREY_MAP: dict[str, str] = {
    "grey15": "#262626",
    "grey30": "#4D4D4D",
    "grey35": "#595959",
    "grey50": "#808080",
    "grey60": "#999999",
    "grey70": "#B3B3B3",
    "grey82": "#D1D1D1",
    "grey85": "#D9D9D9",
}

_PT_MODIFIERS: frozenset[str] = frozenset(
    {"bold", "italic", "underline", "reverse", "blink", "dim", "noreverse"}
)


def pt_color(rich_style: str) -> str:
    """Convert a Rich-style color/modifier string to a prompt_toolkit-safe
    style string.

    Rich strings look like 'bold white', 'grey50', 'bold #FFD93D'. This
    function normalizes them into prompt_toolkit's syntax — modifiers stay
    as bare tokens, color names get a 'fg:' prefix, and Rich's shade-named
    greys map to hex equivalents. An empty input returns an empty string so
    callers can hand pt_style bare defaults.
    """
    if not rich_style:
        return ""
    out: list[str] = []
    for part in rich_style.strip().split():
        lower = part.lower()
        if lower in _PT_MODIFIERS:
            out.append(lower)
            continue
        color = _GREY_MAP.get(lower, part)
        if color.startswith(("fg:", "bg:")):
            out.append(color)
        else:
            out.append(f"fg:{color}")
    return " ".join(out)


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
    if _console.is_terminal:
        # Status pills sit under the header — gives a GitHub-style readout
        # of the active session at a glance.
        row = Text("  ")
        row.append_text(status_pills(cfg, stats))
        _console.print(row)
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
    """Compact single-line `sources` footer with pill-style numbered chips.

    Numbered chips have a real background tint so they read as discrete
    badges instead of plain text. Multi-line fallback only kicks in if the
    chip row would not fit the current terminal width.
    """
    if not hits:
        return
    _console.print()

    chips: list[Text] = [
        numbered_chip(i, h.drawer.id, h.drawer.source) for i, h in enumerate(hits, 1)
    ]

    width = _console.width or 100
    # Plain-text length estimate (chips render as " N  abcd1234 file.md").
    joined_plain = "  ".join(
        f" {i}  {h.drawer.id[:8]} {Path(h.drawer.source).name}"
        for i, h in enumerate(hits, 1)
    )
    label = Text("sources", style=_current.muted)

    if len(joined_plain) + len("sources  ") <= width:
        row = Text()
        row.append_text(label)
        row.append("  ")
        for idx, chip in enumerate(chips):
            row.append_text(chip)
            if idx != len(chips) - 1:
                row.append("  ")
        _console.print(row)
    else:
        _console.print(label)
        for chip in chips:
            row = Text("  ")
            row.append_text(chip)
            _console.print(row)


def typing_cursor(char: str = "▎") -> str:
    """Inline styled cursor for streaming output."""
    return f"[{_current.muted}]{char}[/]"


# --- staged flow, markdown, score coloring, next-steps card -------------------

@contextmanager
def stage(title: str, *, step: int | None = None, total: int | None = None):
    """A numbered step shown during multi-stage work like `superton init`.

    When `step` and `total` are passed, the header prints as
    `→ [3/6] checking ollama`, giving the user a visible sense of how
    much remains. Without them, falls back to the original `→ title`
    layout for back-compat with callers that don't track step counts.
    """
    if step is not None and total is not None:
        header = (
            f"[{_current.primary}]→[/] "
            f"[{_current.muted}][{step}/{total}][/] {title}"
        )
    else:
        header = f"[{_current.primary}]→[/] {title}"
    _console.print(header)
    try:
        yield
    except Exception:
        _console.print(f"  [{_current.error}]✗ {title} failed[/]")
        raise


def stage_ok(msg: str) -> None:
    """Indented success line paired with the preceding `stage()`."""
    _console.print(f"  [{_current.success}]✓[/] {msg}")


def stage_warn(msg: str, hint: str | None = None) -> None:
    """Indented warning. `hint` is rendered on a follow-up line in the
    same dim style as `ui.hint()` so the user always sees a recovery
    suggestion right next to the problem.
    """
    _console.print(f"  [{_current.warning}]![/] {msg}")
    if hint:
        _console.print(f"    [{_current.muted}]↳ {hint}[/]")


def stage_skip(msg: str) -> None:
    _console.print(f"  [{_current.muted}]- {msg}[/]")


# --- install-flow primitives --------------------------------------------------


def ram_bar(used_gb: float | None, recommended_gb: float, *, width: int = 6) -> Text:
    """Visual RAM fit chip: ■■■■□□ 8 / 16 GB · fits.

    `used_gb` is the host's detected RAM; `recommended_gb` is the profile's
    minimum recommendation. The bar colours green if the host fits, red if
    it doesn't, muted if the host RAM is unknown.
    """
    out = Text()
    if used_gb is None:
        out.append("□" * width, style=_current.muted)
        out.append(f"  ?? / {recommended_gb:.0f} GB", style=_current.muted)
        return out

    ratio = min(1.0, used_gb / max(recommended_gb * 2, 1.0))
    filled = max(1, int(ratio * width))
    empty = width - filled
    fit = used_gb >= recommended_gb
    bar_color = _current.success if fit else _current.warning
    out.append("■" * filled, style=bar_color)
    out.append("□" * empty, style=_current.muted)
    out.append(
        f"  {used_gb:.0f} / {recommended_gb:.0f} GB  ",
        style=_current.neutral,
    )
    out.append_text(pill("fits" if fit else "tight", kind="success" if fit else "warning"))
    return out


def preflight_card(
    title: str,
    rows: list[tuple[str, str, str]],
    *,
    summary: str | None = None,
) -> None:
    """Show what an upcoming multi-stage flow will do, with per-row status.

    Each row is `(status, name, detail)`:
      status: "✓" (already done), "→" (will run), "?" (unknown), "-" (skip)
    Rendered as a rounded card so init feels like a deliberate plan rather
    than a wall of prompts.
    """
    icon_styles = {
        "✓": _current.success,
        "→": _current.primary,
        "?": _current.muted,
        "-": _current.muted,
    }
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(width=2)
    table.add_column(min_width=22)
    table.add_column()
    for status, name, detail in rows:
        marker = Text(status, style=icon_styles.get(status, _current.muted))
        table.add_row(marker, Text(name, style="bold"), Text(detail, style=_current.muted))
    body: Any = (
        Group(Text(summary, style=_current.muted), Text(""), table) if summary else table
    )
    _console.print(
        Panel(
            body,
            title=Text(f"▸ {title}", style=f"bold {_current.primary}"),
            title_align="left",
            border_style=_current.rule,
            padding=(0, 1),
            expand=False,
            box=box.ROUNDED,
        )
    )


def ready_card(cfg, stats: dict) -> None:
    """Hero 'you're ready' card shown at the end of init.

    Replaces the older next_steps_card with a more deliberate finale:
    SuperTon wordmark, a row of status pills, then two compact
    command-and-hint columns. Designed to feel like a landing moment,
    not a help screen.
    """
    body = Text()
    body.append("SuperTon is ready.\n", style=f"bold {_current.primary}")
    body.append("\n")
    body.append_text(status_pills(cfg, stats))
    body.append("\n\n")
    body.append("Start here:\n", style=_current.muted)
    body.append("  superton add ~/notes              ", style="bold")
    body.append("# ingest a directory\n", style=_current.muted)
    body.append("  superton import claude-code        ", style="bold")
    body.append("# pull past Claude Code sessions\n", style=_current.muted)
    body.append('  superton ask "..."                 ', style="bold")
    body.append("# grounded answer with citations\n", style=_current.muted)
    body.append("  superton                           ", style="bold")
    body.append("# interactive shell · type / for commands\n", style=_current.muted)
    body.append("\n")
    body.append("Power tools:\n", style=_current.muted)
    body.append("  superton tui                       ", style="bold")
    body.append("# full-screen Textual TUI\n", style=_current.muted)
    body.append("  superton mcp serve                 ", style="bold")
    body.append("# expose palace to Claude / Cursor / Gemini\n", style=_current.muted)
    body.append("  superton doctor                    ", style="bold")
    body.append("# verify install + show recovery hints\n", style=_current.muted)
    body.append("\n")
    body.append("palace at  ", style=_current.muted)
    body.append(f"{cfg.palace_dir}", style=_current.muted)

    _console.print(
        Panel(
            body,
            title=Text("ready", style=f"bold {_current.primary}"),
            title_align="left",
            border_style=_current.primary,
            padding=(1, 2),
            expand=False,
            box=box.ROUNDED,
        )
    )


def profile_card(
    name: str,
    *,
    base_model: str,
    download_gb: float,
    min_ram_gb: int,
    label: str,
    ram_gb: float | None,
    selected: bool,
) -> None:
    """One model-profile card used by the init picker.

    Stacks a header pill (active marker + profile name + base model),
    a RAM-fit bar, and the human description. Cards are visually
    distinguishable at a glance — easier than reading a table.
    """
    marker_pill = pill(
        f"● {name}" if selected else f"○ {name}",
        kind="primary" if selected else "neutral",
    )
    header = Text()
    header.append_text(marker_pill)
    header.append("  ")
    header.append(base_model, style=_current.muted)
    header.append("    ")
    header.append(f"~{download_gb:.1f} GB download", style=_current.muted)

    bar = ram_bar(ram_gb, float(min_ram_gb))

    note = Text(label, style=_current.muted)

    body = Group(header, bar, note)
    _console.print(
        Panel(
            body,
            border_style=_current.primary if selected else _current.rule,
            padding=(0, 1),
            expand=False,
            box=box.ROUNDED,
        )
    )


def theme_picker_card(active: str) -> None:
    """Show all available themes side-by-side with color swatches.

    Used during `superton init` so first-run users see the palette options
    rather than learning about them later via `superton theme`.
    """
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(width=4)
    table.add_column(min_width=8)
    table.add_column()
    table.add_column()
    for theme_obj in list_themes():
        marker = "●" if theme_obj.name == active else "○"
        swatch = (
            f"[{theme_obj.primary}]██[/] "
            f"[{theme_obj.secondary}]██[/] "
            f"[{theme_obj.success}]✓[/] "
            f"[{theme_obj.warning}]![/] "
            f"[{theme_obj.error}]✗[/]"
        )
        table.add_row(
            marker,
            Text(theme_obj.name, style="bold"),
            swatch,
            Text(theme_obj.label, style=_current.muted),
        )
    _console.print(
        Panel(
            table,
            title=Text("▸ themes", style=f"bold {_current.primary}"),
            title_align="left",
            border_style=_current.rule,
            padding=(0, 1),
            expand=False,
            box=box.ROUNDED,
        )
    )


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
    the cursor fades muted → rule → erased over ~150 ms so the answer
    doesn't end on a hard cut. The final text is re-rendered as markdown.

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
            # Cursor retire: fade through dimmer styles, then drop entirely
            # so the answer lands cleanly instead of clipping mid-glyph.
            running = "".join(buf)
            for style in (_current.muted, _current.rule):
                faded = Text(running)
                faded.append("▎", style=style)
                live.update(faded)
                time.sleep(0.06)
            live.update(Text(running))
            time.sleep(0.03)
    else:
        for tok in token_iter:
            buf.append(tok)
    answer = "".join(buf).strip()
    if answer:
        # Long answers (longer than the terminal can show without scrolling)
        # are routed through Rich's pager so the user sees the head first
        # and can browse with `q` to exit.
        maybe_pager(answer)
    return answer
