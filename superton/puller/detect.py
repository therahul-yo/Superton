"""SPA-shell detection, ported from webpull/src/detect.ts.

An SPA shell is an HTML response whose <body> is effectively empty (just
a mount <div>) and whose content is materialized at runtime by JavaScript.
We detect this to decide whether to render with Playwright Chromium.
"""

from __future__ import annotations

import re

_BODY_RE = re.compile(r"<body[^>]*>([\s\S]*?)</body>", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_LINK_RE = re.compile(r"<link[^>]*>", re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_TAG_RE = re.compile(r"<[^>]+>")
_ROOT_DIV_RE = re.compile(
    r"""<div\s+id=["'](root|app|__next|__nuxt|__svelte)["']\s*>\s*</div>""",
    re.IGNORECASE,
)
_ANY_EMPTY_DIV_RE = re.compile(
    r"""<div\s+id=["'][^"']+["']\s*>\s*</div>""",
    re.IGNORECASE,
)
_MODULE_SCRIPT_RE = re.compile(r"""type=["']module["']""", re.IGNORECASE)


def is_spa_shell(html: str) -> bool:
    """True if `html` looks like an SPA mount shell (empty body + mount div)."""
    body_match = _BODY_RE.search(html)
    if not body_match:
        return False
    body = body_match.group(1) or ""
    body = _SCRIPT_RE.sub("", body)
    body = _LINK_RE.sub("", body)
    body = _STYLE_RE.sub("", body)
    body = _COMMENT_RE.sub("", body).strip()

    text = _TAG_RE.sub("", body).strip()
    if len(text) > 200:
        return False

    has_root = bool(_ROOT_DIV_RE.search(body) or _ANY_EMPTY_DIV_RE.search(body))
    has_framework = bool(
        _MODULE_SCRIPT_RE.search(html)
        or "__NEXT_DATA__" in html
        or "__NUXT__" in html
    )
    return has_root and (len(text) < 50 or has_framework)


def is_empty_content(content: str) -> bool:
    """True if extracted page body is effectively empty."""
    stripped = re.sub(r"\s+", " ", content).strip()
    return len(stripped) < 50
