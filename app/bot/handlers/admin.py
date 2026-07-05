"""Admin-only commands (restricted to BOT_ADMIN_IDS).

/settier <telegram_id> <free|pro|unlimited> — change a user's subscription.
/tiers — list all users with their tier and rule quota usage.
"""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import SearchRule, User
from app.database.models.enums import SubscriptionTier

router = Router(name="admin")

#: Tiers that can be assigned via /settier (legacy values are not offered).
ASSIGNABLE_TIERS = {
    "free": SubscriptionTier.FREE,
    "pro": SubscriptionTier.PRO,
    "unlimited": SubscriptionTier.UNLIMITED,
}


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


@router.message(Command("settier"))
async def cmd_settier(
    message: Message, session: AsyncSession, command: CommandObject
) -> None:
    if not _is_admin(message):
        return  # silently ignore for non-admins

    args = (command.args or "").split()
    if len(args) != 2 or args[1].lower() not in ASSIGNABLE_TIERS:
        await message.answer(
            "Nutzung: <code>/settier &lt;telegram_id&gt; "
            "&lt;free|pro|unlimited&gt;</code>\n"
            "Beispiel: <code>/settier 123456789 pro</code>"
        )
        return

    raw_id, tier_name = args
    try:
        target_id = int(raw_id)
    except ValueError:
        await message.answer("⚠️ Die Telegram-ID muss eine Zahl sein.")
        return

    result = await session.execute(select(User).where(User.telegram_id == target_id))
    target = result.scalar_one_or_none()
    if target is None:
        await message.answer(
            f"⚠️ Kein Nutzer mit ID <code>{target_id}</code> gefunden — "
            "die Person muss den Bot zuerst mit /start benutzt haben."
        )
        return

    target.subscription = ASSIGNABLE_TIERS[tier_name.lower()]
    await session.flush()
    await message.answer(
        f"✅ <b>{escape(target.display_name)}</b> (ID {target.telegram_id}) "
        f"ist jetzt <b>{target.subscription.value}</b> "
        f"(max. {target.max_rules if target.max_rules < 1_000_000 else '∞'} Suchen)."
    )


@router.message(Command("tiers"))
async def cmd_tiers(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message):
        return

    rules_count = (
        select(SearchRule.user_id, func.count(SearchRule.id).label("cnt"))
        .group_by(SearchRule.user_id)
        .subquery()
    )
    result = await session.execute(
        select(User, func.coalesce(rules_count.c.cnt, 0))
        .outerjoin(rules_count, rules_count.c.user_id == User.id)
        .order_by(User.created_at.asc())
        .limit(50)
    )
    rows = result.all()
    if not rows:
        await message.answer("Noch keine Nutzer.")
        return

    lines = ["👥 <b>Nutzer & Tarife</b>\n"]
    for user, cnt in rows:
        quota = "∞" if user.max_rules >= 1_000_000 else str(user.max_rules)
        lines.append(
            f"• <b>{escape(user.display_name)}</b> "
            f"(<code>{user.telegram_id}</code>) — "
            f"{user.subscription.value}, Suchen: {cnt}/{quota}"
        )
    lines.append("\nÄndern: <code>/settier &lt;id&gt; &lt;free|pro|unlimited&gt;</code>")
    await message.answer("\n".join(lines))
