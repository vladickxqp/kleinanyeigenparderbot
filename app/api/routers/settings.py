"""Expose safe, non-secret configuration to the admin panel."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.security import require_admin
from app.config.settings import settings
from app.parsers import registry

router = APIRouter(prefix="/settings", tags=["settings"])


class SafeSettings(BaseModel):
    environment: str
    default_interval_seconds: int
    scraper_min_delay_seconds: float
    scraper_max_concurrency: int
    ai_enabled: bool
    ai_model: str
    prometheus_enabled: bool
    available_sites: list[str]


@router.get("", response_model=SafeSettings)
async def get_settings(_: dict = Depends(require_admin)) -> SafeSettings:
    """Return the operational configuration (no secrets)."""
    return SafeSettings(
        environment=settings.environment,
        default_interval_seconds=settings.scraper_default_interval_seconds,
        scraper_min_delay_seconds=settings.scraper_min_delay_seconds,
        scraper_max_concurrency=settings.scraper_max_concurrency,
        ai_enabled=settings.ai_enabled,
        ai_model=settings.ai_model,
        prometheus_enabled=settings.prometheus_enabled,
        available_sites=[s.value for s in registry.available_sites],
    )
