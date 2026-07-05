"""Regression tests for the per-task engine lifecycle.

The Celery worker executes every task in a fresh event loop; the DB engine and
sessionmaker are process-level singletons. After ``dispose_engine()`` both must
be rebuilt from scratch, otherwise the next task reuses pool connections (or a
sessionmaker bound to a disposed engine) from a dead loop and crashes with
``RuntimeError: ... attached to a different loop``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.database import session as db


@pytest.fixture()
def sqlite_engine(monkeypatch):
    """Point the engine factory at an in-memory SQLite DB for the test."""
    monkeypatch.setattr(
        db, "settings", SimpleNamespace(database_url="sqlite+aiosqlite://")
    )
    # Ensure a clean slate before and after.
    db._engine = None
    db._sessionmaker = None
    yield
    db._engine = None
    db._sessionmaker = None


def test_dispose_engine_resets_engine_and_sessionmaker(sqlite_engine):
    async def scenario() -> None:
        engine1 = db.get_engine()
        maker1 = db.get_sessionmaker()
        await db.dispose_engine()

        engine2 = db.get_engine()
        maker2 = db.get_sessionmaker()
        assert engine1 is not engine2, "engine must be rebuilt after dispose"
        assert maker1 is not maker2, "sessionmaker must be rebuilt after dispose"

    asyncio.run(scenario())


def test_engine_usable_across_fresh_event_loops_with_dispose(sqlite_engine):
    """Simulates the worker pattern: run -> dispose -> new loop -> run."""
    from sqlalchemy import text

    async def one_task() -> None:
        try:
            engine = db.get_engine()
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            await db.dispose_engine()

    # Three consecutive "Celery tasks", each in its own loop — must not raise.
    for _ in range(3):
        asyncio.run(one_task())