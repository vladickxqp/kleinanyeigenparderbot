"""API routers."""

from app.api.routers import (
    auth,
    health,
    listings,
    parsers,
    rules,
    settings,
    stats,
    users,
    webapp,
)

__all__ = [
    "auth",
    "health",
    "listings",
    "parsers",
    "rules",
    "settings",
    "stats",
    "users",
    "webapp",
]
