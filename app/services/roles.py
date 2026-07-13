"""Role hierarchy and permission checks.

Permissions are role-based, never hardcoded-ID-based. The single exception is
the bootstrap: telegram ids listed in ``BOT_ADMIN_IDS`` are treated as OWNER so
the very first owner can exist before any role was assigned in the database
(and existing deployments keep working unchanged).

Hierarchy: OWNER > SUPER_ADMIN > ADMIN > MODERATOR > USER.
"""

from __future__ import annotations

from app.config.settings import settings
from app.database.models import User, UserRole

#: Numeric rank per role — higher outranks lower.
ROLE_RANK: dict[UserRole, int] = {
    UserRole.OWNER: 100,
    UserRole.SUPER_ADMIN: 90,
    UserRole.ADMIN: 80,
    UserRole.MODERATOR: 60,
    UserRole.USER: 0,
}

#: Roles an OWNER may assign via /promote (owner itself is bootstrap-only).
ASSIGNABLE_ROLES: dict[str, UserRole] = {
    "super_admin": UserRole.SUPER_ADMIN,
    "admin": UserRole.ADMIN,
    "moderator": UserRole.MODERATOR,
    "user": UserRole.USER,
}


def effective_role(user: User) -> UserRole:
    """The user's role, with the env-configured owner bootstrap applied."""
    if user.telegram_id in settings.admin_ids:
        return UserRole.OWNER
    return user.role


def has_role(user: User, minimum: UserRole) -> bool:
    """True if the user's effective role ranks at least ``minimum``."""
    return ROLE_RANK[effective_role(user)] >= ROLE_RANK[minimum]


def role_badge(user: User) -> str:
    """Short badge for user listings."""
    return {
        UserRole.OWNER: "👑",
        UserRole.SUPER_ADMIN: "🛡",
        UserRole.ADMIN: "🔧",
        UserRole.MODERATOR: "🎧",
        UserRole.USER: "",
    }[effective_role(user)]
