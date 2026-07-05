"""Regression test: parsers must survive multiple event loops.

The Celery worker wraps every task in its own ``asyncio.run`` loop while the
parser instances live as process-wide singletons in the registry. A plain
``asyncio.Lock`` binds to the first loop it is awaited in and then raises
``RuntimeError: ... is bound to a different event loop`` — which silently
killed every scheduled search after the first one per worker process.
"""

from __future__ import annotations

import asyncio

import pytest

from app.parsers import base
from app.parsers.sites.kleinanzeigen import KleinanzeigenParser


@pytest.fixture()
def fast_throttle(monkeypatch):
    """No real sleeping during the test."""
    monkeypatch.setattr(base.settings, "scraper_min_delay_seconds", 0.0)


def test_throttle_survives_fresh_event_loops(fast_throttle):
    """Simulates the worker: same parser instance, one loop per task."""
    parser = KleinanzeigenParser()

    async def one_task() -> None:
        await parser._throttle()
        await parser._throttle()

    # Three consecutive "tasks", each with its own loop — must not raise.
    for _ in range(3):
        asyncio.run(one_task())


def test_throttle_lock_is_shared_within_one_loop(fast_throttle):
    parser = KleinanzeigenParser()

    async def scenario() -> None:
        first = parser._throttle_lock()
        second = parser._throttle_lock()
        assert first is second  # same loop -> same lock

    asyncio.run(scenario())


def test_throttle_actually_delays(monkeypatch):
    """The rate limiter still works after the per-loop rework."""
    monkeypatch.setattr(base.settings, "scraper_min_delay_seconds", 0.05)
    parser = KleinanzeigenParser()

    async def scenario() -> float:
        loop = asyncio.get_running_loop()
        start = loop.time()
        await parser._throttle()
        await parser._throttle()  # must wait ~0.05s after the first call
        return loop.time() - start

    elapsed = asyncio.run(scenario())
    assert elapsed >= 0.04
