"""Async SQLAlchemy engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the lazily-created global async engine."""
    global _engine
    if _engine is None:
        url = settings.database_url
        kwargs: dict = {"echo": False, "pool_pre_ping": True}
        if url.startswith("postgresql"):
            # Pool tuning only applies to real server databases; SQLite (used
            # in tests) rejects these arguments.
            kwargs.update(pool_size=10, max_overflow=20, pool_recycle=1800)
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the global session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional scope: commit on success, rollback on error."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session (no auto-commit)."""
    maker = get_sessionmaker()
    async with maker() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose of the engine's connection pool and reset the factories.

    Must be called at the end of every Celery task coroutine: the worker runs
    each task in its own event loop, and pooled asyncpg connections are bound
    to the loop they were created on — reusing them from the next task's loop
    raises RuntimeError. The sessionmaker is reset too, otherwise it would
    keep handing out sessions bound to the disposed engine.
    """
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _sessionmaker = None
