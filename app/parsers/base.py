"""Abstract base class for all marketplace parsers.

Subclasses implement :meth:`search`. The base class provides a shared, polite
httpx client with rotating user-agents, retry/backoff, optional proxy support and
a per-site rate limiter, so individual parsers stay focused on extraction logic.
"""

from __future__ import annotations

import asyncio
import random
import time
import weakref
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config.settings import settings
from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing, SearchQuery

_FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


class BaseParser(ABC):
    """Base class every site parser must inherit from."""

    #: The marketplace this parser handles. Subclasses MUST override.
    site: SiteName
    #: Human-readable label for logs / admin UI.
    label: str = ""
    #: Whether this parser needs a real browser (Playwright) rather than httpx.
    requires_browser: bool = False

    def __init__(self) -> None:
        if not getattr(self, "site", None):
            raise TypeError(f"{type(self).__name__} must set a `site` attribute")
        self.label = self.label or self.site.value.title()
        self._last_request_ts: float = 0.0
        # Parser instances are process-wide singletons, but the Celery worker
        # runs every task in a fresh event loop. An asyncio.Lock binds to the
        # loop it is first awaited in and raises "bound to a different event
        # loop" afterwards — so keep one lock per loop (weak keys let dead
        # loops be garbage-collected).
        self._loop_locks: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Lock
        ] = weakref.WeakKeyDictionary()

    def _throttle_lock(self) -> asyncio.Lock:
        """Return the rate-limit lock for the currently running event loop."""
        loop = asyncio.get_running_loop()
        lock = self._loop_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._loop_locks[loop] = lock
        return lock

    # --- Public API ---------------------------------------------------------
    @abstractmethod
    async def search(self, query: SearchQuery) -> list[ParsedListing]:
        """Run ``query`` against the marketplace and return parsed listings."""
        raise NotImplementedError

    async def collect(self, query: SearchQuery) -> list[ParsedListing]:
        """Wrapper around :meth:`search` with logging and error isolation."""
        try:
            results = await self.search(query)
        except Exception as exc:  # noqa: BLE001 - one bad site must not kill the run
            logger.exception("[{}] search failed: {}", self.site.value, exc)
            await self._report_health(ok=False)
            return []
        logger.info(
            "[{}] found {} listing(s) for {!r}",
            self.site.value,
            len(results),
            query.keywords,
        )
        await self._report_health(ok=True)
        return results

    async def _report_health(self, *, ok: bool) -> None:
        """Feed the admin-alerting failure counter (never raises)."""
        try:
            from app.services import health  # lazy: avoid import cycles

            await health.record_parser_result(self.site.value, ok=ok)
        except Exception:  # noqa: BLE001
            pass

    # --- HTTP helpers -------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._random_user_agent(),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    @staticmethod
    def _random_user_agent() -> str:
        try:
            from fake_useragent import UserAgent

            return UserAgent().random
        except Exception:  # noqa: BLE001 - offline / dataset missing
            return random.choice(_FALLBACK_USER_AGENTS)

    def _random_proxy(self) -> str | None:
        proxies = settings.proxy_list
        return random.choice(proxies) if proxies else None

    async def _throttle(self) -> None:
        """Enforce a polite minimum delay between requests to this site.

        Uses ``time.monotonic()`` (process-wide) instead of ``loop.time()``:
        the worker spawns a new event loop per task, and per-loop clocks have
        unrelated epochs, which would corrupt the elapsed-time math.
        """
        async with self._throttle_lock():
            elapsed = time.monotonic() - self._last_request_ts
            wait = settings.scraper_min_delay_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait + random.uniform(0, 0.5))
            self._last_request_ts = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def fetch(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET ``url`` politely, with retries, returning the response."""
        await self._throttle()
        proxy = self._random_proxy()
        async with httpx.AsyncClient(
            headers=self._headers(),
            timeout=settings.scraper_request_timeout,
            follow_redirects=True,
            proxy=proxy,
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp

    async def fetch_text(self, url: str, params: dict | None = None) -> str:
        resp = await self.fetch(url, params=params)
        return resp.text

    async def fetch_rendered(
        self, url: str, *, wait_selector: str | None = None
    ) -> str:
        """Render ``url`` with Playwright (for JS-heavy sites) and return HTML."""
        await self._throttle()
        from app.parsers.browser import render_html  # lazy: avoid browser import

        return await render_html(url, wait_selector=wait_selector)

    async def iter_pages(
        self, urls: list[str]
    ) -> AsyncIterator[httpx.Response]:  # pragma: no cover - convenience helper
        for url in urls:
            yield await self.fetch(url)
