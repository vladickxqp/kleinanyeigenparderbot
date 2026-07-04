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
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
        )
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
    """Dispose of the engine's connection pool (call on shutdown)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
