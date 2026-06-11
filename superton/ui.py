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
  3. the built-in default `ember`
"""

from __future__ import annotations

import os
import queue
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
from rich.spinner import Spinner
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
    spinner: str = "dots"
    rule_char: str = "─"


# Four hand-tuned themes. Colors are hex where we want fine control and
# named rich colors (e.g. "grey50") where terminal remapping is desirable.
THEMES: dict[str, Theme] = {
    "ember": Theme(
        name="ember",
        label="burnt orange · embers on black",
        primary="#FF7A1A",
        secondary="#FFB347",
        muted="grey42",
        success="#FFA94D",
        warning="#FFB347",
        error="#FF3B30",
        info="#FFD9A8",
        neutral="#F5E9DC",
        rule="grey23",
        prompt="#FF7A1A",
        prompt_glyph="◉",
        bullet="▸",
        spinner="dots",
        rule_char="─",
    ),
    "crimson": Theme(
        name="crimson",
        label="blood red · dark and sharp",
        primary="#E63946",
        secondary="#FF8FA3",
        muted="grey42",
        success="#F4A261",
        warning="#FF7A1A",
        error="#FF1F3D",
        info="#FFB3C1",
        neutral="#F2E6E6",
        rule="#4A1620",
        prompt="#E63946",
        prompt_glyph="✦",
        bullet="›",
        spinner="line",
        rule_char="·",
    ),
    "void": Theme(
        name="void",
        label="dark violet · deep space",
        primary="#9D6BFF",
        secondary="#C9A8FF",
        muted="#6B5C8A",
        success="#B58CFF",
        warning="#FF9E4D",
        error="#FF4D6D",
        info="#C9A8FF",
        neutral="#EDE6FA",
        rule="#352A52",
        prompt="#9D6BFF",
        prompt_glyph="◈",
        bullet="›",
        spinner="dots12",
        rule_char="╌",
    ),
    "ash": Theme(
        name="ash",
        label="white on black · stark mono",
        primary="bold white",
        secondary="grey74",
        muted="grey46",
        success="bold white",
        warning="#FF7A1A",
        error="bold #FF3B30",
        info="grey82",
        neutral="white",
        rule="grey27",
        prompt="bold white",
        prompt_glyph="›",
        bullet="·",
        spinner="line",
        rule_char="─",
    ),
}

DEFAULT_THEME = "ember"


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

# Install-flow palette — fire-toned signal vocabulary that stays readable
# against every active theme:
#   ORANGE → forward motion + structural success: ✓, →, headers, ready
#   YELLOW → attention without alarm: ! warnings, tight RAM, hints, "?" rows
#   RED    → hard failure: ✗, stage failed, unrecoverable error
#   PURPLE → affirmative match (specifically the "fits" RAM-fit pill); the
#            one cool tone in an otherwise warm palette so positive signal
#            chips don't collide with the orange used for progress glyphs.
INSTALL_ORANGE = "#FFB02E"
INSTALL_YELLOW = "#FFD93D"
INSTALL_RED = "#F0471F"
INSTALL_PURPLE = "#B392E9"

# Legacy alias — green collapses into purple (the affirmative chip). Kept
# so external callers and the older tests on disk don't break instantly;
# remove after one release.
INSTALL_GREEN = INSTALL_PURPLE


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
    """Two-tone gradient rule: bright near the left edge, fading into the
    theme's rule color. Gives each theme a distinctive horizontal line."""
    width = max(_console.width, 20)
    char = _current.rule_char
    head = max(6, width // 6)
    line = Text()
    line.append(char * head, style=_current.primary)
    if title:
        line.append(f" {title} ", style=f"bold {_current.primary}")
        head += len(title) + 2
    line.append(char * max(0, width - head), style=_current.rule)
    _console.print(line)


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
    with _console.status(f"[{_current.muted}]{label}[/]", spinner=_current.spinner, spinner_style=_current.primary) as status:
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
    Falls back to neutral if unknown.

    Tuples are `(bg_color, text_color)`. Saturated/light accent colors
    (primary, secondary, success, warning, info) all pair with `grey15`
    text so the label reads as bold dark on a coloured chip. Dark accents
    (error, the rule-grey used for `neutral`) pair with `neutral` text so
    a light label pops off the chip. The earlier `(primary, neutral)`
    layout gave white-on-yellow which was unreadable in most terminals.
    """
    palette = {
        "primary": (_current.primary, "grey15"),
        "secondary": (_current.secondary, "grey15"),
        "success": (_current.success, "grey15"),
        "warning": (_current.warning, "grey15"),
        "error": (_current.error, _current.neutral),
        "info": (_current.info, "grey15"),
        "neutral": (_current.rule, _current.neutral),
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
    row.append_text(pill(cfg.model, kind="secondary"))
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
        body_renderable: Any = Text.from_markup(body)
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


def pt_bg(rich_style: str) -> str:
    """Same as `pt_color` but emits `bg:` prefixes and drops modifiers.

    Useful when computing a highlight pair for prompt_toolkit completion
    menus: `bg:primary fg:dark` reads cleanly across every theme without
    relying on `reverse`, which on some terminals collapses the foreground
    into a near-invisible terminal-bg colour.
    """
    if not rich_style:
        return ""
    out: list[str] = []
    for part in rich_style.strip().split():
        lower = part.lower()
        if lower in _PT_MODIFIERS:
            # Modifiers (bold / italic / ...) don't apply to background.
            continue
        color = _GREY_MAP.get(lower, part)
        if color.startswith("bg:"):
            out.append(color)
        elif color.startswith("fg:"):
            out.append("bg:" + color[3:])
        else:
            out.append(f"bg:{color}")
    return " ".join(out)


def pt_raw_color(rich_style: str) -> str:
    """Return just the colour value (no `fg:` / `bg:` / modifier prefixes).

    Used when the caller needs to compose `fg:` + a different colour with
    `bg:` themselves — e.g. dark text on the theme's primary background.
    """
    if not rich_style:
        return ""
    for part in rich_style.strip().split():
        lower = part.lower()
        if lower in _PT_MODIFIERS:
            continue
        color = _GREY_MAP.get(lower, part)
        if color.startswith(("fg:", "bg:")):
            return color[3:]
        return color
    return ""


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
    body.append("Superton ", style="bold")
    body.append(f"{cfg.model} · {cfg.base_model}\n", style=_current.muted)
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
        dots = (
            f"[{INSTALL_ORANGE}]{'●' * step}[/]"
            f"[{_current.rule}]{'○' * max(0, total - step)}[/]"
        )
        header = (
            f"[{INSTALL_ORANGE}]→[/] {dots} "
            f"[{_current.muted}][{step}/{total}][/] {title}"
        )
    else:
        header = f"[{INSTALL_ORANGE}]→[/] {title}"
    _console.print(header)
    try:
        yield
    except Exception:
        _console.print(f"  [{INSTALL_RED}]✗ {title} failed[/]")
        raise


def stage_ok(msg: str) -> None:
    """Indented success line paired with the preceding `stage()`.

    The ✓ glyph carries the positive signal; colour stays in the orange
    family so the install flow keeps its bicolor (orange + red) palette.
    On a TTY the tick lands with a 3-frame pulse (dim → bright → settled)
    so each completed stage registers as a micro-interaction.
    """
    if _console.is_terminal:
        frames = [_current.muted, f"bold {INSTALL_ORANGE}", INSTALL_ORANGE]
        with Live(Text(f"  ✓ {msg}"), console=_console, refresh_per_second=30, transient=True) as live:
            for st in frames:
                t = Text("  ")
                t.append("✓", style=st)
                t.append(f" {msg}")
                live.update(t)
                time.sleep(0.035)
    _console.print(f"  [{INSTALL_ORANGE}]✓[/] {msg}")


def stage_warn(msg: str, hint: str | None = None) -> None:
    """Indented warning. `hint` is rendered on a follow-up line in the
    same dim style as `ui.hint()` so the user always sees a recovery
    suggestion right next to the problem.
    """
    # Yellow `!` separates "attention, but recoverable" from the red `✗`
    # the stage() context manager uses for hard failure.
    _console.print(f"  [{INSTALL_YELLOW}]![/] {msg}")
    if hint:
        _console.print(f"    [bold {INSTALL_YELLOW}]↳ {hint}[/]")


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
    # Orange when this machine fits the profile, yellow when it's underspec —
    # underspec is a caution, not a hard failure (init still proceeds with a
    # warning). Red is reserved for stages that actually crash.
    bar_color = INSTALL_ORANGE if fit else INSTALL_YELLOW
    out.append("■" * filled, style=bar_color)
    out.append("□" * empty, style=_current.muted)
    out.append(
        f"  {used_gb:.0f} / {recommended_gb:.0f} GB  ",
        style=_current.neutral,
    )
    # Render the result pill inline in the install palette (purple for
    # "fits", yellow for "tight") instead of routing through pill()'s
    # theme-aware "success/warning" kinds — the install flow has its own
    # four-color vocabulary and theme green would leak in otherwise.
    if fit:
        out.append(" fits ", style=f"bold grey15 on {INSTALL_PURPLE}")
    else:
        out.append(" tight ", style=f"bold grey15 on {INSTALL_YELLOW}")
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
        "✓": INSTALL_ORANGE,
        "→": INSTALL_ORANGE,
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
        Group(Text(summary, style=_current.muted), Text("^C safe at any prompt", style=_current.muted), Text(""), table)
        if summary
        else Group(Text("^C safe at any prompt", style=_current.muted), Text(""), table)
    )
    _console.print(
        Panel(
            body,
            title=Text(f"▸ {title}", style=f"bold {INSTALL_ORANGE}"),
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
    body.append("SuperTon is ready.\n", style=f"bold {INSTALL_ORANGE}")
    body.append("\n")
    body.append_text(status_pills(cfg, stats))
    body.append("\n\n")
    body.append("Start here:\n", style=_current.muted)
    body.append("  1.  superton add ~/notes           ", style="bold")
    body.append("# do this first\n", style=_current.muted)
    body.append("  2.  superton                       ", style="bold")
    body.append("# then chat\n", style=_current.muted)
    body.append("\n")
    body.append("Also available: ", style=_current.muted)
    body.append("superton demo", style="bold")
    body.append(" · ", style=_current.muted)
    body.append("superton import claude-code", style="bold")
    body.append(" · ", style=_current.muted)
    body.append("superton doctor", style="bold")
    body.append(" · ", style=_current.muted)
    body.append("superton mcp serve\n", style="bold")
    body.append("\n")
    body.append("palace at  ", style=_current.muted)
    body.append_text(Text(f"{cfg.palace_dir}", style=_current.muted, overflow="fold"))
    if stats.get("drawers", 0) == 0:
        body.append("\n")
        body.append("your palace is empty — ingest something to ground answers.", style=f"italic {_current.muted}")

    _console.print(
        Panel(
            body,
            title=Text("ready", style=f"bold {INSTALL_ORANGE}"),
            title_align="left",
            border_style=INSTALL_ORANGE,
            padding=(1, 2),
            expand=False,
            box=box.ROUNDED,
        )
    )
    _console.print(Text(f"{cfg.palace_dir}", style=_current.muted), soft_wrap=True)


def pick_theme_interactive(default: str) -> str | None:
    """Arrow-key theme picker: ↑/↓ (or j/k) to move, Enter to select.

    Repaints the theme list in place and live-previews the highlighted
    theme's colors. Returns the chosen theme name, or None when stdin
    isn't a real TTY (caller falls back to a typed prompt).
    """
    import sys

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        import termios
        import tty
    except ImportError:
        return None

    names = list(THEMES)
    idx = names.index(default) if default in THEMES else 0
    n = len(names)

    def draw(first: bool = False) -> None:
        if not first:
            sys.stdout.write(f"\x1b[{n + 1}A\r")
        for i, name in enumerate(names):
            t = THEMES[name]
            marker = "●" if i == idx else "○"
            row_style = f"bold {t.primary}" if i == idx else _current.muted
            swatch = (
                f"[{t.primary}]██[/] [{t.secondary}]██[/] "
                f"[{t.success}]✓[/] [{t.warning}]![/] [{t.error}]✗[/]"
            )
            _console.print(
                f"  [{row_style}]{marker} {name:<9}[/] {swatch}  "
                f"[{_current.muted}]{t.label}[/]"
            )
        _console.print(f"  [{_current.muted}]↑/↓ move · enter select[/]")

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    sys.stdout.write("\x1b[?25l")
    try:
        tty.setcbreak(fd)
        draw(first=True)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    idx = (idx - 1) % n
                elif seq == "[B":
                    idx = (idx + 1) % n
                else:
                    continue
            elif ch in ("k", "K"):
                idx = (idx - 1) % n
            elif ch in ("j", "J"):
                idx = (idx + 1) % n
            elif ch in ("\r", "\n"):
                return names[idx]
            elif ch in ("\x03", "\x04", "q"):
                return default
            else:
                continue
            set_theme(names[idx])
            draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


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
    body.append(f"{cfg.model} · {cfg.base_model}", style=_current.muted)

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


def farewell_card(removed: list[tuple[str, str]], manual_step: str | None = None) -> None:
    """Closing card for `superton uninstall`.

    `removed` is `[(label, detail), ...]` describing each artifact that
    was deleted (palace dir, ollama tags, etc.). `manual_step` is the
    one thing the user still has to do themselves — usually the
    `uv tool uninstall superton` / `pip uninstall superton` line since
    a running process can't unlink its own executable.
    """
    body = Text()
    body.append("SuperTon uninstalled.\n", style=f"bold {_current.primary}")
    body.append("\n")
    if removed:
        body.append("Removed:\n", style=_current.muted)
        for label, detail in removed:
            body.append("  - ", style=f"dim {_current.error}")
            body.append(f"{label:24}", style="bold")
            body.append(detail, style=_current.muted)
            body.append("\n")
    else:
        body.append("Nothing to remove — system was already clean.\n", style=_current.muted)
    if manual_step:
        body.append("\n")
        body.append("One step left (manual):\n", style=_current.muted)
        body.append(f"  {manual_step}\n", style="bold")
    body.append("\n")
    body.append("Thanks for using SuperTon. ❍", style=_current.muted)

    _console.print(
        Panel(
            body,
            title=Text("uninstalled", style=f"bold {_current.primary}"),
            title_align="left",
            border_style=_current.primary,
            padding=(1, 2),
            expand=False,
            box=box.ROUNDED,
        )
    )


def stream_answer(token_iter, label: str = "Superton") -> str:
    """Stream tokens live under a header. Returns the full answer string.

    Phases:
      1. *thinking* — between the user hitting Enter and the first token,
         a Rich `Spinner` ("dots") + dim "thinking…" line ticks in the
         Live region so the gap reads as work-in-progress, not a hang.
         Iterator consumption happens on a daemon thread so the spinner
         keeps animating even while `model.generate()` blocks on the
         first network round-trip.
      2. *streaming* — once the first token arrives, the spinner is
         dropped and tokens append live with a muted cursor (`▎`).
      3. *retire* — cursor fades muted → rule → erased over ~150 ms so
         the answer doesn't end on a hard cut.

    Exceptions from the token iterator propagate to the caller so that
    model errors (e.g. ModelError) can be handled upstream.
    """
    _console.print()
    _console.print(f"[bold {_current.primary}]{label}[/]")
    buf: list[str] = []
    if _console.is_terminal:
        # Pull tokens on a daemon thread so the Live region can keep
        # ticking the thinking spinner during the (potentially multi-
        # second) blocking wait for the model's first token.
        tok_q: queue.Queue[str] = queue.Queue()
        done = threading.Event()
        err_box: list[BaseException] = []

        def _pump() -> None:
            try:
                for tok in token_iter:
                    tok_q.put(tok)
            except BaseException as exc:  # noqa: BLE001 — propagated below
                err_box.append(exc)
            finally:
                done.set()

        pump = threading.Thread(target=_pump, daemon=True)
        pump.start()

        thinking = Spinner(
            "dots",
            text=Text("thinking…", style=_current.muted),
            style=_current.primary,
        )
        first_token_seen = False
        with Live(
            thinking,
            console=_console,
            refresh_per_second=30,
            transient=True,
        ) as live:
            while True:
                try:
                    tok = tok_q.get(timeout=0.08)
                except queue.Empty:
                    tok = None

                if tok is not None:
                    buf.append(tok)
                    first_token_seen = True
                    running = "".join(buf)
                    t = Text(running)
                    # Cursor stays muted so streamed content reads as the
                    # focus of the screen, not a glowing tail.
                    t.append("▎", style=_current.muted)
                    live.update(t)
                elif done.is_set() and tok_q.empty():
                    break
                # else: no token yet — Spinner keeps animating itself via
                # Live's auto_refresh; nothing to do here.

            if first_token_seen:
                # Cursor retire: fade through dimmer styles, then drop the
                # cursor entirely so the answer lands cleanly.
                running = "".join(buf)
                for style in (_current.muted, _current.rule):
                    faded = Text(running)
                    faded.append("▎", style=style)
                    live.update(faded)
                    time.sleep(0.06)
                live.update(Text(running))
                time.sleep(0.03)

        pump.join(timeout=0.1)
        if err_box:
            raise err_box[0]
    else:
        # Non-terminal: no animation, just collect.
        for tok in token_iter:
            buf.append(tok)
    answer = "".join(buf).strip()
    if answer:
        # Long answers (longer than the terminal can show without scrolling)
        # are routed through Rich's pager so the user sees the head first
        # and can browse with `q` to exit.
        maybe_pager(answer)
    return answer
