"""Per-URL fetch-and-extract — port of webpull/src/worker.ts.

Each task fetches one URL, optionally renders it through Playwright if
the response looks like an SPA shell, then extracts title + markdown body
via trafilatura (with the <main>/<article>/<body> fallback).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from superton.puller.detect import is_spa_shell
from superton.puller.extractor import extract
from superton.puller.ua import get_headers

logger = logging.getLogger(__name__)

_MARKDOWN_SIGNAL = re.compile(
    r"^(#{1,6}\s|[-*]\s|\d+\.\s|```|>\s|\[.+\]\(.+\))", re.MULTILINE
)


@dataclass(slots=True)
class WorkerResult:
    ok: bool
    url: str | None = None
    title: str | None = None
    content: str | None = None  # markdown body, no frontmatter
    error: str | None = None


async def fetch_and_extract(
    url: str,
    *,
    client: httpx.AsyncClient,
    use_browser: bool = False,
    render_timeout: float = 20.0,
) -> WorkerResult:
    """Fetch `url`, render if SPA shell and use_browser=True, extract content."""
    try:
        headers = {**get_headers(), "Accept": "text/markdown, text/html, */*;q=0.8"}
        r = await client.get(url, headers=headers)
    except Exception as e:
        return WorkerResult(ok=False, error=f"fetch: {e}")

    if r.status_code != 200:
        return WorkerResult(ok=False, error=f"HTTP {r.status_code}: {url}")

    text = r.text
    final_url = url if "#" in url else str(r.url)
    content_type = r.headers.get("content-type", "").lower()

    # Raw markdown — pass through untouched.
    if "text/markdown" in content_type or (
        "text/html" not in content_type and _MARKDOWN_SIGNAL.search(text)
    ):
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        from urllib.parse import urlparse

        fallback_title = urlparse(final_url).path or final_url
        title = (m.group(1).strip() if m else fallback_title)
        return WorkerResult(ok=True, url=final_url, title=title, content=text)

    # SPA shell — render in Chromium if the caller opted in.
    if use_browser and is_spa_shell(text):
        try:
            from superton.puller.renderer import (
                is_browser_launched,
                launch_browser,
                render_page,
            )

            if not is_browser_launched():
                await launch_browser()
            render_url = url if "#" in url else final_url
            rendered = await render_page(render_url, timeout=render_timeout)
            if rendered is not None:
                text = rendered.html
                final_url = rendered.url if "#" not in url else url
        except Exception as e:
            logger.debug("browser render failed for %s: %s", url, e)

    extracted = extract(text, url=final_url)
    if not extracted.title and not extracted.content:
        return WorkerResult(ok=False, error="extractor produced empty output")
    return WorkerResult(
        ok=True,
        url=final_url,
        title=extracted.title or "",
        content=extracted.content or "",
    )
