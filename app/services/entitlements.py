"""What each subscription level is allowed to do.

One place answers every "may this user …" question. The numbers come from
settings, so a price or quota change is a configuration change, never a code
change. Quotas use ``-1`` for "unlimited"; rule counts are always real numbers
because they are compared against live counts.

The ladder is denominated in scrape requests per minute — the thing that
actually costs money. A tier has a base interval for its rules plus a number of
fast slots, i.e. rules that may run at the tier's fastest interval.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import settings
from app.database.models.enums import SubscriptionTier

UNLIMITED = -1

#: Feature keys used in the per-tier feature lists.
FEATURE_FLIP_MODE = "flip_mode"
FEATURE_RULE_POWER = "rule_power"
FEATURE_EXPORT = "export"
FEATURE_MARKET_REPORT = "market_report"
FEATURE_FORWARDING = "forwarding"

TIER_LABELS: dict[SubscriptionTier, str] = {
    SubscriptionTier.FREE: "Free",
    SubscriptionTier.STARTER: "Starter",
    SubscriptionTier.PRO: "Profi",
    SubscriptionTier.UNLIMITED: "Händler",
}

#: Prefix of the settings keys for each level.
_PREFIX: dict[SubscriptionTier, str] = {
    SubscriptionTier.FREE: "free",
    SubscriptionTier.STARTER: "starter",
    SubscriptionTier.PRO: "pro",
    SubscriptionTier.UNLIMITED: "dealer",
}


def is_unlimited(value: int) -> bool:
    """``-1`` means no cap. Only quota fields ever carry it."""
    return value < 0


@dataclass(frozen=True, slots=True)
class Entitlements:
    tier: SubscriptionTier
    label: str
    max_rules: int
    base_interval_seconds: int
    min_interval_seconds: int
    fast_slots: int
    queue_name: str
    daily_notifications: int
    photo_evals_per_month: int
    quick_searches_per_day: int
    quick_search_cooldown_seconds: int
    negotiations_per_month: int
    max_sites_per_rule: int
    history_days: int
    features: frozenset[str]

    def has(self, feature: str) -> bool:
        return feature in self.features

    @property
    def is_paid(self) -> bool:
        return self.tier is not SubscriptionTier.FREE

    def interval_floor(self, fast: bool) -> int:
        """Lowest interval a rule may use, in or out of a fast slot."""
        base = self.min_interval_seconds if fast else self.base_interval_seconds
        return max(base, settings.scraper_hard_min_interval_seconds)

    def requests_per_minute(self, active_rules: int) -> float:
        """Worst-case scrape load this tier can generate with N active rules."""
        fast = min(active_rules, self.fast_slots)
        slow = max(0, active_rules - fast)
        return fast * 60 / self.interval_floor(True) + slow * 60 / self.interval_floor(False)


def _get(prefix: str, key: str, default=0):
    return getattr(settings, f"{prefix}_{key}", default)


def for_tier(tier: SubscriptionTier) -> Entitlements:
    """Resolve the entitlements of a level (legacy values map to their meaning)."""
    canonical = tier.canonical
    prefix = _PREFIX[canonical]
    features = {
        f.strip() for f in str(_get(prefix, "features", "")).split(",") if f.strip()
    }
    return Entitlements(
        tier=canonical,
        label=TIER_LABELS[canonical],
        max_rules=int(_get(prefix, "max_rules", 3)),
        base_interval_seconds=int(_get(prefix, "base_interval_seconds", 600)),
        min_interval_seconds=int(_get(prefix, "min_interval_seconds", 600)),
        fast_slots=int(_get(prefix, "fast_slots", 0)),
        queue_name=str(_get(prefix, "queue_name", "celery")),
        daily_notifications=int(_get(prefix, "daily_notifications", UNLIMITED)),
        photo_evals_per_month=int(_get(prefix, "photo_evals_per_month", 0)),
        quick_searches_per_day=int(_get(prefix, "quick_searches_per_day", UNLIMITED)),
        quick_search_cooldown_seconds=int(_get(prefix, "quick_search_cooldown_seconds", 60)),
        negotiations_per_month=int(_get(prefix, "negotiations_per_month", UNLIMITED)),
        max_sites_per_rule=int(_get(prefix, "max_sites_per_rule", UNLIMITED)),
        history_days=int(_get(prefix, "history_days", 30)),
        features=frozenset(features),
    )


def all_tiers() -> list[Entitlements]:
    """Every level, cheapest first — for comparison tables."""
    return [
        for_tier(t)
        for t in (
            SubscriptionTier.FREE,
            SubscriptionTier.STARTER,
            SubscriptionTier.PRO,
            SubscriptionTier.UNLIMITED,
        )
    ]


def unlocks(feature: str) -> SubscriptionTier | None:
    """The cheapest level whose feature list includes ``feature``.

    What a locked button should say: not "no", but "from Profi". None when no
    level has it — a flag that exists in code but in no configured list.
    """
    for e in all_tiers():
        if e.has(feature):
            return e.tier
    return None


def next_tier(tier: SubscriptionTier) -> SubscriptionTier | None:
    """The level a user would upgrade to (None at the top)."""
    order = [
        SubscriptionTier.FREE,
        SubscriptionTier.STARTER,
        SubscriptionTier.PRO,
        SubscriptionTier.UNLIMITED,
    ]
    index = order.index(tier.canonical)
    return order[index + 1] if index + 1 < len(order) else None


def fmt_quota(value: int, unit: str = "", lang: str | None = None) -> str:
    """Human form of a quota value, in the reader's language.

    The word for "unlimited" used to be hardcoded German, which then leaked
    into every English, Russian and Ukrainian rendering of the comparison.
    """
    if is_unlimited(value):
        from app.bot.texts import t

        return t("quota.unlimited", lang)
    return f"{value}{unit}"
