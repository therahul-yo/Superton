"""Content extraction — Defuddle equivalent via trafilatura + BeautifulSoup.

webpull uses Defuddle (TypeScript) to reduce messy HTML to clean markdown.
We do the same with trafilatura, the gold-standard Python article extractor.
If trafilatura can't find enough content, we fall back to the <main> /
<article> / <body> heuristic that webpull's `fallbackExtract` uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_STRIP_SCRIPT = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
_STRIP_STYLE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)


@dataclass(slots=True)
class Extracted:
    title: str
    content: str  # markdown body (no frontmatter)


def _strip_heavy_tags(html: str) -> str:
    html = _STRIP_SCRIPT.sub("", html)
    html = _STRIP_STYLE.sub("", html)
    return html


def _fallback_extract(html: str) -> Extracted:
    """Lifted from webpull/worker.ts — <title> plus <main>/<article>/<body>."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - trafilatura extra is required
        return Extracted(title="", content="")

    soup = BeautifulSoup(html, "lxml") if _has_lxml() else BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    title = (title_el.get_text() if title_el else "").strip()
    for tag in ("main", "article", "body"):
        node = soup.find(tag)
        if node is None:
            continue
        text = node.get_text(separator="\n").strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text:
            return Extracted(title=title, content=text)
    return Extracted(title=title, content="")


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:
        return False


def extract(html: str, url: str | None = None) -> Extracted:
    """Return (title, markdown body) for a page's HTML."""
    if not html:
        return Extracted(title="", content="")

    cleaned = _strip_heavy_tags(html)

    try:
        import trafilatura
        from trafilatura.settings import use_config
    except ImportError:  # pragma: no cover
        return _fallback_extract(cleaned)

    # Tune trafilatura for docs-site-style content: don't be too aggressive
    # about stripping, keep links + formatting, output markdown.
    cfg = use_config()
    cfg.set("DEFAULT", "MIN_OUTPUT_SIZE", "50")
    cfg.set("DEFAULT", "MIN_EXTRACTED_SIZE", "50")

    try:
        markdown = trafilatura.extract(
            cleaned,
            url=url,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=True,
            favor_recall=True,
            config=cfg,
        )
    except Exception:
        markdown = None

    title = _extract_title(cleaned)
    if markdown and markdown.strip():
        return Extracted(title=title, content=markdown.strip())

    # Trafilatura found nothing — use the fallback heuristic.
    return _fallback_extract(cleaned) if not title else Extracted(
        title=title, content=_fallback_extract(cleaned).content
    )


_TITLE_RE = re.compile(r"<title[^>]*>([\s\S]*?)</title>", re.IGNORECASE)
_H1_RE = re.compile(r"<h1[^>]*>([\s\S]*?)</h1>", re.IGNORECASE)


def _extract_title(html: str) -> str:
    m = _TITLE_RE.search(html)
    if m:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    m = _H1_RE.search(html)
    if m:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    return ""


def frontmatter(title: str, url: str) -> str:
    """Match webpull's YAML frontmatter format."""
    safe_title = title.replace('"', '\\"')
    return f'---\ntitle: "{safe_title}"\nurl: "{url}"\n---\n\n'
