"""Playwright helper for JS-heavy marketplaces.

Provides a single async function that renders a URL in a headless Chromium and
returns the fully-loaded HTML. Kept separate so httpx-based parsers never pay the
cost of importing/launching a browser.
"""

from __future__ import annotations

import random

from loguru import logger

from app.config.settings import settings
from app.parsers.base import _FALLBACK_USER_AGENTS


async def render_html(
    url: str,
    *,
    wait_selector: str | None = None,
    timeout_ms: int = 30_000,
) -> str:
    """Load ``url`` in headless Chromium and return the rendered HTML.

    Optionally waits for ``wait_selector`` to appear before capturing content,
    which is more reliable than a fixed sleep on lazy-loaded result pages.
    """
    # Imported lazily: the browser stack is only needed by Playwright parsers.
    from playwright.async_api import async_playwright

    proxy = None
    if settings.proxy_list:
        proxy = {"server": random.choice(settings.proxy_list)}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=settings.playwright_headless,
            proxy=proxy,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                user_agent=random.choice(_FALLBACK_USER_AGENTS),
                locale="de-DE",
                viewport={"width": 1366, "height": 900},
            )
            page = await context.new_page()
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:  # noqa: BLE001 - selector may legitimately be absent
                    logger.debug("wait_selector {!r} not found on {}", wait_selector, url)
            return await page.content()
        finally:
            await browser.close()
