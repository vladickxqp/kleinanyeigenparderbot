"""Freshness policy: only recently posted ads are worth a notification.

"New to the bot" is not the same as "newly posted": the first scrape of a rule
(or a promoted TOP ad) surfaces listings that have been online for weeks. The
policy, as requested by the user:

- posted within the last 24 h            -> always notify
- posted within the last 3 days          -> notify only for really good deals
- older, or undated (promoted TOP ads)   -> never notify

The rule only applies to marketplaces whose parser extracts posting dates
(currently Kleinanzeigen); other sites keep the previous behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.database.models.enums import SiteName
from app.parsers.schemas import ParsedListing

#: Ads younger than this are always notify-worthy.
FRESH_HOURS = 24
#: Absolute ceiling: ads older than this are never notified.
MAX_AGE_DAYS = 3
#: Deal score required for ads between FRESH_HOURS and MAX_AGE_DAYS.
MIN_SCORE_FOR_OLDER = 70
#: Sites whose parsers deliver ``posted_at`` — only these are age-filtered.
DATE_AWARE_SITES: frozenset[SiteName] = frozenset({SiteName.KLEINANZEIGEN})


def is_fresh_enough(
    item: ParsedListing, deal_score: int, now: datetime | None = None
) -> bool:
    """Decide whether a listing's age still justifies a notification."""
    if item.site not in DATE_AWARE_SITES:
        return True
    if item.posted_at is None:
        # Undated card on a date-aware site = promoted TOP ad = old inventory.
        return False
    now = now or datetime.now()
    age = now - item.posted_at
    if age <= timedelta(hours=FRESH_HOURS):
        return True
    if age <= timedelta(days=MAX_AGE_DAYS):
        return deal_score >= MIN_SCORE_FOR_OLDER
    return False
