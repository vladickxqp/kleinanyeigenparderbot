"""The market report a Profi rule can ask for.

The rule page shows a one-line 7-day summary. The report answers the question
behind it: what does this thing cost right now, is that going up or down, what
did it actually SELL for, and which finds were the best. Everything comes from
rows the rule already stored — no request leaves the house for a report.

The report is a paid feature (``FEATURE_MARKET_REPORT``). The gate lives in
the handler; this module only knows how to build and word one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import verdict_badge
from app.bot.texts import t
from app.database.models import Listing, SearchRule
from app.parsers.registry import site_label
from app.services.formatting_helpers import money
from app.services.price_analysis import PriceStats, compute_price_stats

#: The window a report covers, and the length of the window it is compared to.
REPORT_DAYS = 30
#: How many of the best finds the report names.
TOP_FINDS = 3
#: A median that moved less than this (percent) is reported as stable, so a
#: single new ad does not turn into a "trend".
TREND_FLAT_BAND = 3.0
#: Titles are scraped text; keep the list readable on a phone.
TITLE_CHARS = 60


@dataclass(slots=True)
class MarketReport:
    rule_name: str
    days: int
    found: int
    asking: PriceStats
    previous: PriceStats
    sold: PriceStats
    by_site: list[tuple[str, int]]
    top: list[Listing]
    generated_at: datetime

    @property
    def trend_percent(self) -> float | None:
        """How far the asking median moved against the window before.

        None while there is nothing to compare with — a rule on its first
        month has no "before", and inventing a trend from one side is how a
        report starts lying.
        """
        if not (self.asking.has_data and self.previous.has_data):
            return None
        before = self.previous.median or 0.0
        if before <= 0:
            return None
        return round(((self.asking.median or 0.0) - before) / before * 100.0, 1)


async def build(
    session: AsyncSession,
    rule: SearchRule,
    *,
    days: int = REPORT_DAYS,
    now: datetime | None = None,
) -> MarketReport:
    """Assemble the report for ``rule`` from its stored finds."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    earlier = cutoff - timedelta(days=days)

    rows = (
        await session.execute(
            select(Listing).where(
                Listing.rule_id == rule.id, Listing.created_at >= cutoff
            )
        )
    ).scalars().all()
    before = (
        await session.execute(
            select(Listing.price).where(
                Listing.rule_id == rule.id,
                Listing.created_at >= earlier,
                Listing.created_at < cutoff,
                Listing.price.isnot(None),
            )
        )
    ).scalars().all()

    asking = compute_price_stats([r.price for r in rows if r.price is not None])
    previous = compute_price_stats([p for p in before if p is not None])
    sold = await _sold(rule.id, now)

    counts = Counter(site_label(r.site) for r in rows)
    by_site = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    # The best finds: highest score first, newest first among equals — by id,
    # because a stored timestamp may come back naive and refuse to compare.
    # Ignored rows stay out: the user already said they do not want them.
    candidates = [r for r in rows if r.price is not None and not r.is_ignored]
    candidates.sort(key=lambda r: (r.deal_score or 0, r.id or 0), reverse=True)

    return MarketReport(
        rule_name=rule.name,
        days=days,
        found=len(rows),
        asking=asking,
        previous=previous,
        sold=sold,
        by_site=by_site,
        top=candidates[:TOP_FINDS],
        generated_at=now,
    )


async def _sold(rule_id: int, now: datetime) -> PriceStats:
    """Realised prices, or an empty sample when the store is unavailable."""
    from app.services import sold_comps  # lazy: Redis-backed, optional

    try:
        return await sold_comps.realised_stats(rule_id, now=now)
    except Exception as exc:  # noqa: BLE001 - a report must never fail on this
        logger.debug("market_report: sold comps unavailable: {}", exc)
        return compute_price_stats([])


def render(report: MarketReport, lang: str | None = None) -> str:
    """The report as one Telegram HTML message."""
    name = escape(report.rule_name)
    if report.found == 0:
        return t("report.empty", lang, name=name, days=report.days)

    lines = [
        t("report.title", lang, name=name),
        t("report.window", lang, days=report.days),
        "",
        t("report.found", lang, count=report.found),
    ]
    if report.by_site:
        sites = " · ".join(f"{label} {count}" for label, count in report.by_site)
        lines.append(t("report.sites", lang, sites=sites))

    asking = report.asking
    if asking.has_data:
        lines.append(
            t(
                "report.prices", lang,
                median=money(asking.median), low=money(asking.minimum),
                high=money(asking.maximum), count=asking.count,
            )
        )
        trend = report.trend_percent
        if trend is None:
            lines.append(t("report.trend_none", lang))
        elif trend >= TREND_FLAT_BAND:
            lines.append(t("report.trend_up", lang, percent=f"{trend:.0f}", days=report.days))
        elif trend <= -TREND_FLAT_BAND:
            lines.append(t("report.trend_down", lang, percent=f"{abs(trend):.0f}", days=report.days))
        else:
            lines.append(t("report.trend_flat", lang, days=report.days))

    # Sold prices are held to the same bar as the deal score: a realised median
    # over two sales is an anecdote, and the report says so instead.
    sold = report.sold
    if sold.has_data and not sold.is_thin:
        lines.append(t("report.sold", lang, median=money(sold.median), count=sold.count))
    else:
        lines.append(t("report.sold_none", lang))

    if report.top:
        lines += ["", t("report.top", lang)]
        for index, row in enumerate(report.top, start=1):
            title = escape(row.title[:TITLE_CHARS])
            badge = verdict_badge(row.deal_verdict, lang or "de")
            lines.append(
                f"{index}. <a href=\"{escape(row.url)}\">{title}</a> — "
                f"{money(row.price)} · {badge}"
            )
    return "\n".join(lines)
