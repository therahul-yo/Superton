"""Public API: pull_url and pull_site."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass

import httpx

from superton.puller.detect import is_spa_shell
from superton.puller.discovery import discover
from superton.puller.extractor import frontmatter
from superton.puller.pool import WorkerPool
from superton.puller.ua import get_headers
from superton.puller.worker import WorkerResult, fetch_and_extract


@dataclass(slots=True)
class Page:
    url: str
    title: str
    markdown: str


def _as_page(r: WorkerResult) -> Page | None:
    if not r.ok or not r.url or not (r.content or "").strip():
        return None
    return Page(
        url=r.url,
        title=r.title or "",
        markdown=frontmatter(r.title or r.url, r.url) + (r.content or ""),
    )


async def pull_url(
    url: str, *, render_js: bool = False, timeout: float = 30.0
) -> Page | None:
    async with httpx.AsyncClient(
        headers=get_headers(), follow_redirects=True, timeout=timeout
    ) as client:
        result = await fetch_and_extract(url, client=client, use_browser=render_js)
    return _as_page(result)


async def pull_site(
    url: str,
    *,
    max_pages: int = 500,
    render_js: bool = False,
    concurrency: int | None = None,
    timeout: float = 30.0,
) -> AsyncIterator[Page]:
    urls = await discover(url, max_pages=max_pages, render_js=render_js, timeout=timeout)
    if not urls:
        return
    needs_browser = False
    if render_js:
        try:
            async with httpx.AsyncClient(
                headers=get_headers(), follow_redirects=True, timeout=timeout
            ) as c:
                r = await c.get(url)
                if r.status_code == 200 and is_spa_shell(r.text):
                    needs_browser = True
        except Exception:
            pass
    if concurrency is None:
        concurrency = max(8, (os.cpu_count() or 4) * 2)
    if needs_browser:
        concurrency = min(concurrency, 4)
    async with WorkerPool(
        concurrency=concurrency, use_browser=needs_browser, timeout=timeout
    ) as pool:
        queue: asyncio.Queue[Page | None] = asyncio.Queue()

        async def _on_done(res: WorkerResult, idx: int) -> None:
            _ = idx
            page = _as_page(res)
            if page:
                await queue.put(page)

        task = asyncio.create_task(pool.pull_all(urls, on_done=_on_done))

        async def _sentinel():
            try:
                await task
            finally:
                await queue.put(None)

        st = asyncio.create_task(_sentinel())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            st.cancel()
            with suppress(asyncio.CancelledError):
                await st
            if not task.done():
                task.cancel()
                with suppress(Exception):
                    await task
