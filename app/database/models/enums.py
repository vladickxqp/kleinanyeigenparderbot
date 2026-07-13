"""Enumerations shared across models, parsers and services."""

from __future__ import annotations

import enum


class SiteName(str, enum.Enum):
    """Supported marketplace identifiers. Extend when adding a parser."""

    KLEINANZEIGEN = "kleinanzeigen"
    EBAY = "ebay"
    AMAZON = "amazon"
    IDEALO = "idealo"
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
    """Subscription plans: Free / Pro / Unlimited.

    ``PREMIUM``/``ULTIMATE`` are legacy values kept so that rows written by
    older versions still load; treat them like PRO/UNLIMITED respectively.
    """

    FREE = "free"
    PRO = "pro"
    UNLIMITED = "unlimited"
    PREMIUM = "premium"      # legacy, = PRO
    ULTIMATE = "ultimate"    # legacy, = UNLIMITED


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
