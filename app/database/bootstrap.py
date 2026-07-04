"""Development bootstrap: create all tables directly from ORM metadata.

Convenient for a first local run when you don't yet have Alembic migrations.
For staging/production, prefer generating and applying real migrations:

    alembic revision --autogenerate -m "init"
    alembic upgrade head

Run this with: ``python -m app.database.bootstrap``
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.config.logging import setup_logging
from app.database.base import Base
from app.database.session import dispose_engine, get_engine

# Ensure all models are registered on the metadata.
import app.database.models  # noqa: F401


async def create_all() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await dispose_engine()
    logger.info("✅ Database tables created ({} tables)", len(Base.metadata.tables))


def main() -> None:
    setup_logging()
    asyncio.run(create_all())


if __name__ == "__main__":
    main()
