"""Health and readiness endpoints (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter, Response
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


@router.get("/health/ready")
async def readiness(response: Response) -> dict[str, object]:
    """Deep check: database, cache and the search pipeline.

    Returns 503 when a dependency is down, so a container healthcheck or an
    uptime monitor sees the problem instead of a green page served by a
    process that cannot do any work.
    """
    from app.services import health as health_svc

    checks: dict[str, object] = {}
    healthy = True

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
        healthy = False

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        try:
            await client.ping()
            checks["redis"] = "ok"
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"
        healthy = False

    status = await health_svc.get_status()
    checks["pipeline"] = {
        "worker_alive": status.worker_alive,
        "last_dispatch_age_seconds": (
            round(status.last_dispatch_age) if status.last_dispatch_age else None
        ),
        "runs_today": status.runs_today,
        "cards_sent_today": status.cards_sent_today,
        "queue_depth": await health_svc.queue_depth(),
    }
    if not status.worker_alive:
        healthy = False

    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
