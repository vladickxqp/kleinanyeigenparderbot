"""ORM models. Importing this package registers all models on ``Base.metadata``."""

from app.database.models.enums import (
    Condition,
    DealVerdict,
    NotificationChannel,
    SiteName,
    SubscriptionTier,
    UserRole,
)
from app.database.models.listing import Listing
from app.database.models.notification import Notification
from app.database.models.price_history import PriceHistory
from app.database.models.search_rule import SearchRule
from app.database.models.subscription import PlanType, Subscription, SubscriptionStatus
from app.database.models.user import User

__all__ = [
    "Condition",
    "DealVerdict",
    "Listing",
    "Notification",
    "NotificationChannel",
    "PlanType",
    "PriceHistory",
    "SearchRule",
    "SiteName",
    "Subscription",
    "SubscriptionStatus",
    "SubscriptionTier",
    "User",
    "UserRole",
]
