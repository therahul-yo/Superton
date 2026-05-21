"""Bridge: SuperTon `ui.Theme` → Textual CSS variables.

The existing `superton.ui` themes (nebula / mono / solar / frost) are the
source of truth. This module turns the active theme into a `.tcss` string
that Textual can hot-reload, so `/theme solar` in the TUI instantly
repaints without restarting the app.
"""

from __future__ import annotations

from superton.ui import Theme

# Map Rich's shade-named greys to hex so Textual's parser accepts them.
_GREY_HEX = {
    "grey15": "#262626",
    "grey30": "#4D4D4D",
    "grey35": "#595959",
    "grey50": "#808080",
    "grey60": "#999999",
    "grey70": "#B3B3B3",
    "grey82": "#D1D1D1",
    "grey85": "#D9D9D9",
}


def _color(rich_style: str, *, fallback: str = "#FFFFFF") -> str:
    """Strip Rich modifiers ('bold red') and shade-name greys, return a hex
    Textual will accept.
    """
    if not rich_style:
        return fallback
    parts = [p for p in rich_style.split() if p not in {"bold", "italic", "dim", "underline"}]
    if not parts:
        return fallback
    color = parts[-1].lower()
    if color in _GREY_HEX:
        return _GREY_HEX[color]
    if color in {"white", "black", "red", "green", "blue", "yellow", "cyan", "magenta"}:
        return color
    if color.startswith("#"):
        return color
    return fallback


def theme_to_css(theme: Theme) -> str:
    """Generate a Textual `.tcss` string for the given SuperTon theme.

    The selectors map onto the widget structure declared in `app.py`:
    `#header`, `#sidebar`, `#chat`, `#footer`, plus a few semantic classes
    (`.pill`, `.user-turn`, `.assistant-turn`, `.refused`).
    """
    primary = _color(theme.primary, fallback="#FFD93D")
    secondary = _color(theme.secondary, fallback="#87D1FF")
    muted = _color(theme.muted, fallback="#808080")
    success = _color(theme.success, fallback="#7FE79B")
    warning = _color(theme.warning, fallback="#FFB02E")
    error = _color(theme.error, fallback="#F0471F")
    rule = _color(theme.rule, fallback="#4D4D4D")
    neutral = _color(theme.neutral, fallback="#FFFFFF")

    return f"""
Screen {{
    background: $surface;
    color: {neutral};
}}

#header {{
    height: 1;
    background: $panel;
    color: {muted};
    padding: 0 1;
    border-bottom: solid {rule};
}}

#header .header-title {{
    color: {primary};
    text-style: bold;
}}

#header .header-pill {{
    background: {muted} 30%;
    color: {neutral};
    padding: 0 1;
}}

#header .header-pill.primary {{
    background: {primary} 30%;
    color: {primary};
}}

#header .header-pill.online {{
    color: {success};
}}

#header .header-pill.offline {{
    color: {warning};
}}

#sidebar {{
    width: 32;
    background: $panel;
    border-right: solid {rule};
    padding: 1 1;
}}

#sidebar:focus-within {{
    border-right: solid {primary};
}}

#sidebar #sidebar-title {{
    color: {muted};
    text-style: italic;
    height: 1;
    margin-bottom: 1;
}}

#sidebar #sidebar-list {{
    height: 1fr;
}}

#sidebar ListItem {{
    padding: 0 1;
    color: {neutral};
}}

#sidebar ListItem.--highlight {{
    background: {primary} 25%;
    color: {primary};
    text-style: bold;
}}

#chat-container {{
    width: 1fr;
}}

#chat {{
    padding: 1 2;
    height: 1fr;
}}

#chat .user-turn {{
    color: {secondary};
    text-style: bold;
    margin-top: 1;
}}

#chat .assistant-turn {{
    color: {neutral};
    margin-bottom: 1;
}}

#chat .refused {{
    color: {warning};
    text-style: italic;
}}

#chat .citation {{
    color: {muted};
    margin-top: 1;
}}

#chat .pending {{
    color: {muted};
    text-style: italic;
}}

#input-row {{
    height: 3;
    background: $panel;
    border-top: solid {rule};
    padding: 0 1;
}}

#input-row:focus-within {{
    border-top: solid {primary};
}}

#input-row #input-glyph {{
    color: {primary};
    text-style: bold;
    width: 2;
    content-align: center middle;
}}

Input {{
    background: $panel;
    color: {neutral};
}}

Input:focus {{
    background: $panel;
}}

#footer {{
    height: 1;
    background: $panel;
    color: {muted};
    padding: 0 1;
    border-top: solid {rule};
}}

#footer .mode {{
    color: {primary};
    text-style: bold;
}}

#footer .key {{
    color: {secondary};
}}

#palette {{
    background: $panel;
    border: round {primary};
    padding: 1 2;
    width: 60%;
    height: auto;
    max-height: 18;
    margin: 4 0;
}}

#palette Input {{
    border: none;
    background: $panel;
}}

#palette ListItem {{
    padding: 0 1;
    color: {neutral};
}}

#palette ListItem.--highlight {{
    background: {primary} 25%;
    color: {primary};
    text-style: bold;
}}

#help {{
    background: $panel;
    border: round {primary};
    padding: 1 2;
    width: 70%;
    height: auto;
    margin: 4 0;
}}

.toast {{
    background: {success} 20%;
    color: {success};
    padding: 0 1;
    border: solid {success};
    margin: 1 2;
}}

.toast.warning {{
    background: {warning} 20%;
    color: {warning};
    border: solid {warning};
}}

.toast.error {{
    background: {error} 20%;
    color: {error};
    border: solid {error};
}}
"""
