"""Health and readiness endpoints (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.schemas import HealthResponse
from app.config.settings import settings
from app.database.session import get_engine
from app.parsers import registry

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version=__version__,
        parsers=len(registry),
    )


@router.get("/health/db")
async def health_db() -> dict[str, str]:
    """Verify the database is reachable."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"database": "ok"}
