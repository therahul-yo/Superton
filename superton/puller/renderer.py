"""Optional Playwright Chromium renderer for JavaScript-rendered pages.

Port of webpull/src/renderer.ts. Only imported when the caller sets
render_js=True — keeps Playwright (and the ~350MB Chromium download) a
strictly optional dep behind `pip install superton[web]`.

The module maintains a single Browser/BrowserContext for the process
lifetime so we don't pay the spin-up cost per page.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_browser: Any = None
_context: Any = None
_lock: asyncio.Lock | None = None


@dataclass(slots=True)
class RenderedPage:
    html: str
    url: str


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


class PlaywrightMissing(RuntimeError):
    """Raised when Playwright or Chromium is not installed."""


async def launch_browser() -> None:
    """Start a shared headless Chromium + context, idempotent."""
    global _browser, _context
    if _browser is not None:
        return
    async with _get_lock():
        if _browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:  # pragma: no cover
            raise PlaywrightMissing(
                "Playwright not installed. Install with: pip install 'superton[web]' "
                "and then: playwright install chromium"
            ) from e

        pw = await async_playwright().start()
        try:
            _browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        except Exception as e:  # pragma: no cover
            msg = str(e).lower()
            if "executable doesn" in msg or "browsertype.launch" in msg:
                raise PlaywrightMissing(
                    "Chromium not found. Run: playwright install chromium"
                ) from e
            raise
        _context = await _browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )


async def render_page(url: str, *, timeout: float = 15.0) -> RenderedPage | None:
    """Navigate a page, wait for content, return final HTML + URL.

    Mirrors webpull's renderer.ts wait strategy: `networkidle`, then try
    to see a main/article/content-ish selector, then a short extra beat.
    """
    if _context is None:
        await launch_browser()
    if _context is None:
        return None

    page = await _context.new_page()
    try:
        try:
            await page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
        except Exception:
            return None

        try:
            await page.wait_for_selector(
                "main, article, [class*='content'], [class*='docs'], h1, h2",
                timeout=5000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(500)

        html = await page.content()
        final_url = page.url
        return RenderedPage(html=html, url=final_url)
    finally:
        await page.close()


async def close_browser() -> None:
    """Shut down the shared Chromium, idempotent."""
    global _browser, _context
    if _context is not None:
        try:
            await _context.close()
        except Exception:
            pass
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
    _context = None
    _browser = None


def is_browser_launched() -> bool:
    return _browser is not None
