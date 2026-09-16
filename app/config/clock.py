"""Time in the marketplace's timezone.

Marketplaces print wall-clock times ("Heute, 08:01") in German local time,
while a container usually runs on UTC. Mixing the two silently shifts every
listing age by an hour or two, which is enough to push ads across the
freshness cutoffs. Everything that compares scraped times uses this helper.
"""

from __future__ import annotations

from datetime import datetime

from app.config.settings import settings


def local_now() -> datetime:
    """Current time in ``settings.tz`` as a naive datetime."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(settings.tz)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 - no tz database available
        return datetime.now()
