"""API routers."""

from app.api.routers import (
    auth,
    health,
    listings,
    parsers,
    rules,
    settings,
    stats,
)

__all__ = [
    "auth",
    "health",
    "listings",
    "parsers",
    "rules",
    "settings",
    "stats",
]
