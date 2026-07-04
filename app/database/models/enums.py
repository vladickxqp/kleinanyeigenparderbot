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
    ADMIN = "admin"
    MODERATOR = "moderator"
    USER = "user"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    PREMIUM = "premium"
    ULTIMATE = "ultimate"


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
