"""/usage — what the user has actually spent against every quota.

The page answers three questions in one screen: how much of each quota is gone
in its window, which searches currently hold the scarce fast slots, and what
the next level would add. The upgrade line comes from
:func:`app.services.quota.upgrade_hint`, so /premium and /usage word the same
offer identically.
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import t
from app.database.models import SearchRule, User
from app.services import entitlements as ent
from app.services import quota

router = Router(name="usage")

#: Metered kinds in the order a user runs into them.
_KINDS = (quota.KIND_CARDS, quota.KIND_QUICK, quota.KIND_PHOTO, quota.KIND_NEGO)

#: Ten cells, so one cell reads as exactly ten percent of the quota.
_BAR_CELLS = 10
_BAR_FULL = "▰"
_BAR_EMPTY = "▱"


def _bar(state: quota.QuotaState) -> str:
    """A text meter of how much of the window is gone."""
    if state.limit <= 0:
        return _BAR_FULL * _BAR_CELLS
    filled = min(_BAR_CELLS, round(state.used / state.limit * _BAR_CELLS))
    # Anything already spent must show, otherwise the first hits look free.
    if state.used and not filled:
        filled = 1
    return _BAR_FULL * filled + _BAR_EMPTY * (_BAR_CELLS - filled)


def quota_block(states: dict[str, quota.QuotaState], lang: str) -> str:
    """The used/left lines for every metered kind."""
    lines: list[str] = []
    for kind in _KINDS:
        state = states.get(kind)
        if state is None:
            continue
        lines.append(
            t("usage.row_head", lang,
              name=t(f"usage.kind.{kind}", lang), window=state.window_label)
        )
        if state.unlimited:
            lines.append(t("usage.row_unlimited", lang, used=state.used))
        elif state.exhausted:
            lines.append(
                t("usage.row_exhausted", lang,
                  bar=_bar(state), used=state.used, limit=state.limit)
            )
        else:
            lines.append(
                t("usage.row_capped", lang, bar=_bar(state), used=state.used,
                  limit=state.limit, remaining=state.remaining)
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def upgrade_nudge(
    user: User, lang: str, states: dict[str, quota.QuotaState] | None = None
) -> str | None:
    """The one upgrade line every surface shows, or None at the top level.

    The kind on offer is the one that pinches most right now — an exhausted
    quota first, otherwise the one with the least left — so the nudge names
    the limit the user just ran into instead of a generic pitch.
    """
    if ent.next_tier(user.subscription) is None:
        return None
    capped = [s for s in (states or {}).values() if not s.unlimited]
    kind = (
        min(capped, key=lambda s: (not s.exhausted, s.remaining)).kind
        if capped
        else quota.KIND_CARDS
    )
    hint = quota.upgrade_hint(kind, user)
    return t("usage.upgrade", lang, hint=hint) if hint else None


async def _fast_slots_text(user: User, session: AsyncSession, lang: str) -> str:
    """Which searches hold the fast slots — same order the enforcement uses."""
    e = user.entitlements
    if not e.fast_slots:
        return t("usage.fast_locked", lang)
    result = await session.execute(
        select(SearchRule)
        .where(
            SearchRule.user_id == user.id,
            SearchRule.is_active.is_(True),
            SearchRule.interval_seconds < e.interval_floor(fast=False),
        )
        .order_by(SearchRule.created_at.asc(), SearchRule.id.asc())
        .limit(e.fast_slots)
    )
    rules = list(result.scalars().all())
    lines = [t("usage.fast_title", lang, used=len(rules), total=e.fast_slots)]
    if not rules:
        lines.append(t("usage.fast_none", lang))
    lines.extend(
        t("usage.fast_row", lang, name=escape(rule.name),
          minutes=max(1, rule.interval_seconds // 60))
        for rule in rules
    )
    return "\n".join(lines)


async def usage_text(user: User, session: AsyncSession, lang: str) -> str:
    states = await quota.snapshot(user)
    return "\n\n".join(
        [
            t("usage.title", lang) + "\n" + t("usage.level", lang, label=escape(user.tier_label)),
            quota_block(states, lang),
            await _fast_slots_text(user, session, lang),
            upgrade_nudge(user, lang, states) or t("usage.top_level", lang),
        ]
    )


def _keyboard(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn.premium", lang), callback_data="menu:premium")
    kb.button(text=t("btn.back", lang), callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("usage", "verbrauch"))
async def cmd_usage(
    message: Message, user: User, session: AsyncSession, lang: str
) -> None:
    await message.answer(
        await usage_text(user, session, lang), reply_markup=_keyboard(lang)
    )


@router.callback_query(F.data == "menu:usage")
async def cb_usage(
    cb: CallbackQuery, user: User, session: AsyncSession, lang: str
) -> None:
    await cb.message.edit_text(
        await usage_text(user, session, lang), reply_markup=_keyboard(lang)
    )
    await cb.answer()
