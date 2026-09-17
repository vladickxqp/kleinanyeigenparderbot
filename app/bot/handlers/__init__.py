"""Handler routers aggregated into a single router for the dispatcher."""

from __future__ import annotations

from aiogram import Router

from app.bot.handlers import (
    admin,
    broadcast,
    edit_rule,
    flips,
    legal,
    listings,
    menu,
    photo_eval,
    premium,
    privacy,
    quick_search,
    rules,
    settings,
    start,
    support,
    usage,
)


def build_router() -> Router:
    """Combine all feature routers. Order matters: specific before generic."""
    root = Router(name="root")
    root.include_router(admin.router)
    root.include_router(broadcast.router)
    root.include_router(premium.router)
    root.include_router(usage.router)
    root.include_router(support.router)
    root.include_router(flips.router)
    root.include_router(photo_eval.router)
    root.include_router(privacy.router)
    root.include_router(legal.router)
    root.include_router(quick_search.router)
    root.include_router(start.router)
    root.include_router(rules.router)
    root.include_router(edit_rule.router)
    root.include_router(settings.router)
    root.include_router(listings.router)
    root.include_router(menu.router)  # generic menu callbacks last
    return root


__all__ = ["build_router"]
