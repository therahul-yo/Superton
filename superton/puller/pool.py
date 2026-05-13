"""Async worker pool."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

import httpx

from superton.puller.ua import get_headers
from superton.puller.worker import WorkerResult, fetch_and_extract

logger = logging.getLogger(__name__)
OnStart = Callable[[int, str], None]
OnDone = Callable[[WorkerResult, int], Awaitable[None] | None]


class WorkerPool:
    def __init__(
        self,
        concurrency: int = 8,
        *,
        use_browser: bool = False,
        timeout: float = 30.0,
    ):
        self.concurrency = max(1, concurrency)
        self.use_browser = use_browser
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> WorkerPool:
        self._client = httpx.AsyncClient(
            headers=get_headers(), follow_redirects=True, timeout=self.timeout
        )
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self.use_browser:
            with contextlib.suppress(Exception):
                from superton.puller.renderer import close_browser

                await close_browser()

    async def pull_all(
        self,
        urls: list[str],
        *,
        on_start: OnStart | None = None,
        on_done: OnDone | None = None,
    ) -> list[WorkerResult]:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=get_headers(), follow_redirects=True, timeout=self.timeout
            )
        sem = asyncio.Semaphore(self.concurrency)
        results: list[WorkerResult | None] = [None] * len(urls)

        async def _task(idx: int, url: str) -> None:
            async with sem:
                if on_start:
                    with contextlib.suppress(Exception):
                        on_start(idx, url)
                assert self._client
                res = await fetch_and_extract(
                    url, client=self._client, use_browser=self.use_browser
                )
                results[idx] = res
                if on_done:
                    try:
                        r = on_done(res, idx)
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        pass

        await asyncio.gather(*(_task(i, u) for i, u in enumerate(urls)))
        return [r or WorkerResult(ok=False, error="cancelled") for r in results]
