"""Enumerations shared across models, parsers and services."""

from __future__ import annotations

import enum


class SiteName(str, enum.Enum):
    """Supported marketplace identifiers. Extend when adding a parser."""

    KLEINANZEIGEN = "kleinanzeigen"
    EBAY = "ebay"
    AUTOSCOUT24 = "autoscout24"
    AMAZON = "amazon"
    IDEALO = "idealo"
    VINTED = "vinted"
    MEDIAMARKT = "mediamarkt"
    SATURN = "saturn"
    OTTO = "otto"
    KAUFLAND = "kaufland"
    ALIEXPRESS = "aliexpress"
    TEMU = "temu"


class UserRole(str, enum.Enum):
    """Role hierarchy: OWNER > SUPER_ADMIN > ADMIN > MODERATOR > USER."""

    OWNER = "owner"
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class SubscriptionTier(str, enum.Enum):
    """Subscription levels: Free / Starter / Pro / Unlimited ("Händler").

    ``PREMIUM``/``ULTIMATE`` are legacy values kept so that rows written by
    older versions still load; treat them like PRO/UNLIMITED respectively.
    Limits per level live in settings and are resolved by
    :mod:`app.services.entitlements`.
    """

    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    UNLIMITED = "unlimited"
    PREMIUM = "premium"      # legacy, = PRO
    ULTIMATE = "ultimate"    # legacy, = UNLIMITED

    @property
    def canonical(self) -> "SubscriptionTier":
        """Map legacy values onto the level they mean."""
        if self is SubscriptionTier.PREMIUM:
            return SubscriptionTier.PRO
        if self is SubscriptionTier.ULTIMATE:
            return SubscriptionTier.UNLIMITED
        return self

    @property
    def rank(self) -> int:
        """Ordering for comparisons (Free < Starter < Pro < Unlimited)."""
        return {
            SubscriptionTier.FREE: 0,
            SubscriptionTier.STARTER: 1,
            SubscriptionTier.PRO: 2,
            SubscriptionTier.UNLIMITED: 3,
        }[self.canonical]


class SellerType(str, enum.Enum):
    """Who is selling — the single biggest predictor of a bargain.

    A dealer prices to a margin and a warranty; a private seller prices to be
    rid of the thing. ``ANY`` is the default because most marketplaces do not
    say, and a filter must never drop an ad whose seller is simply unknown.
    """

    ANY = "any"
    PRIVATE = "private"
    DEALER = "dealer"


class Condition(str, enum.Enum):
    """Item condition filter values."""

    ANY = "any"
    NEW = "new"
    LIKE_NEW = "like_new"
    USED = "used"
    DEFECTIVE = "defective"
    REFURBISHED = "refurbished"


class DealVerdict(str, enum.Enum):
    """Outcome of deal analysis for a listing."""

    UNKNOWN = "unknown"
    OVERPRICED = "overpriced"
    FAIR = "fair"
    GOOD = "good"
    GREAT = "great"
    STEAL = "steal"           # anomalously low — possible seller mistake


class NotificationChannel(str, enum.Enum):
    TELEGRAM = "telegram"
    CHANNEL = "channel"
    GROUP = "group"
    EMAIL = "email"
    WEBHOOK = "webhook"
    PUSH = "push"
