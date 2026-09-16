"""Weekly personal recap: what the bot was worth to this user.

A deal bot is judged by the deals it found, but the user only ever sees single
cards flying by. Once a week we add them up — savings against the market price,
the best find, realised flip profit — and give them a reason to come back and
to invite someone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.models import Flip, FlipStatus, Listing, SearchRule, User

RECAP_DAYS = 7
#: Users with fewer finds than this get no recap — an empty report is worse
#: than none at all.
MIN_FINDS_FOR_RECAP = 3


@dataclass(slots=True)
class Recap:
    finds: int
    best_title: str | None
    best_discount: float | None
    best_price: float | None
    potential_savings: float
    flips_sold: int
    flip_profit: float

    @property
    def worth_sending(self) -> bool:
        return self.finds >= MIN_FINDS_FOR_RECAP or self.flips_sold > 0


async def build_recap(
    session: AsyncSession, user: User, now: datetime | None = None
) -> Recap:
    """Collect one user's numbers for the last week."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=RECAP_DAYS)

    rows = (
        await session.execute(
            select(Listing)
            .join(SearchRule, SearchRule.id == Listing.rule_id)
            .where(
                SearchRule.user_id == user.id,
                Listing.notified.is_(True),
                Listing.created_at >= since,
            )
            .order_by(Listing.discount_percent.desc().nullslast())
        )
    ).scalars().all()

    savings = 0.0
    for row in rows:
        if row.estimated_market_price and row.price:
            savings += max(0.0, row.estimated_market_price - row.price)

    best = rows[0] if rows else None
    sold = (
        await session.execute(
            select(
                func.count(Flip.id),
                func.coalesce(func.sum(Flip.net_profit), 0.0),
            ).where(
                Flip.telegram_id == user.telegram_id,
                Flip.status == FlipStatus.SOLD,
                Flip.sold_at >= since,
            )
        )
    ).one()

    return Recap(
        finds=len(rows),
        best_title=best.title if best else None,
        best_discount=best.discount_percent if best else None,
        best_price=best.price if best else None,
        potential_savings=round(savings, 2),
        flips_sold=int(sold[0] or 0),
        flip_profit=round(float(sold[1] or 0.0), 2),
    )


def _money(value: float) -> str:
    return f"{value:,.0f} €".replace(",", ".")


def format_recap(recap: Recap, *, referral_link: str | None = None) -> str:
    """The message the user receives (HTML)."""
    lines = [
        "📊 <b>Deine Woche</b>\n",
        f"🔍 Passende Angebote: <b>{recap.finds}</b>",
    ]
    if recap.potential_savings >= 1:
        lines.append(
            f"💰 Gegenüber dem Marktpreis: <b>{_money(recap.potential_savings)}</b> "
            "Vorteil in den gefundenen Angeboten"
        )
    if recap.best_title:
        best = f"⭐ Bester Fund: <b>{escape(recap.best_title[:60])}</b>"
        if recap.best_price:
            best += f" — {_money(recap.best_price)}"
        if recap.best_discount:
            best += f" ({recap.best_discount:.0f}% unter Markt)"
        lines.append(best)
    if recap.flips_sold:
        lines.append(
            f"📦 Verkauft: <b>{recap.flips_sold}</b> · "
            f"Gewinn: <b>{_money(recap.flip_profit)}</b>"
        )

    lines.append("\n📋 Alle Funde: /menu · Deine Flips: /flips")
    if referral_link and settings.referral_enabled:
        lines.append(
            f"\n🎁 Freund einladen und <b>{settings.referral_reward_days} Tage "
            f"Premium</b> geschenkt bekommen:\n{referral_link}"
        )
    return "\n".join(lines)
