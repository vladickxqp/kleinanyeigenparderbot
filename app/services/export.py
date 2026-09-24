"""Finds as a CSV file — the export a Profi rule was sold with.

A spreadsheet is where a reseller does their own sums: which platform
delivers, how far under market the good ones were, what to look at again.
The file is what Excel, Numbers and Google Sheets open without a dialog:
UTF-8 with a byte-order mark, semicolon-separated, the decimal separator of
the reader's language, one row per stored find.

The export is a paid feature (``FEATURE_EXPORT``). The gate lives in the
handler; this module only knows how to write the file.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.texts import t
from app.database.models import Listing, SearchRule
from app.parsers.registry import site_label

#: Rows per file. Retention already bounds what a rule keeps; this only keeps
#: a Händler's hundred rules from producing a file Telegram refuses.
EXPORT_MAX_ROWS = 2000
#: Every column, in the order they appear. ``rule`` is left out of a
#: single-rule export, where it would repeat the same name down the sheet.
COLUMNS: tuple[str, ...] = (
    "found_at", "rule", "site", "title", "price", "market", "discount",
    "score", "verdict", "location", "seller", "favorite", "url",
)
#: Languages whose spreadsheets read "12,50", not "12.50".
_COMMA_DECIMAL = {"de", "ru", "uk"}
#: A cell starting with one of these is a formula to Excel. Scraped text can
#: carry anything, so free-text cells are neutralised with a leading quote.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


async def rows_for_rule(
    session: AsyncSession, rule_id: int, user_id: int, *, limit: int = EXPORT_MAX_ROWS
) -> Sequence[Listing]:
    """This user's finds under one rule, newest first. Scoped to the owner."""
    result = await session.execute(
        select(Listing)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .options(selectinload(Listing.rule))
        .where(Listing.rule_id == rule_id, SearchRule.user_id == user_id)
        .order_by(Listing.created_at.desc(), Listing.id.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def rows_for_user(
    session: AsyncSession, user_id: int, *, limit: int = EXPORT_MAX_ROWS
) -> Sequence[Listing]:
    """All of this user's finds across their rules, newest first."""
    result = await session.execute(
        select(Listing)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .options(selectinload(Listing.rule))
        .where(SearchRule.user_id == user_id)
        .order_by(Listing.created_at.desc(), Listing.id.desc())
        .limit(limit)
    )
    return result.scalars().all()


def to_csv(
    rows: Iterable[Listing], lang: str | None = None, *, include_rule: bool = True
) -> bytes:
    """Render ``rows`` as a spreadsheet-ready CSV, headers in ``lang``."""
    columns = [c for c in COLUMNS if include_rule or c != "rule"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([t(f"export.col.{column}", lang) for column in columns])
    for row in rows:
        writer.writerow([_cell(row, column, lang) for column in columns])
    return buffer.getvalue().encode("utf-8-sig")


def filename(label: str, when: datetime | None = None) -> str:
    """An ASCII file name: Telegram carries it as a header, not as text."""
    when = when or datetime.now()
    ascii_label = (
        unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_label.lower()).strip("-")[:40] or "export"
    return f"funde-{slug}-{when:%Y-%m-%d}.csv"


# --- Cells ---------------------------------------------------------------------------
def _cell(row: Listing, column: str, lang: str | None) -> str:
    if column == "found_at":
        return f"{row.created_at:%Y-%m-%d %H:%M}" if row.created_at else ""
    if column == "rule":
        return _safe(row.rule.name if row.rule is not None else "")
    if column == "site":
        return site_label(row.site)
    if column == "title":
        return _safe(row.title)
    if column == "price":
        return _number(row.price, lang)
    if column == "market":
        return _number(row.estimated_market_price, lang)
    if column == "discount":
        return _number(row.discount_percent, lang, digits=1)
    if column == "score":
        return str(row.deal_score or 0)
    if column == "verdict":
        return getattr(row.deal_verdict, "value", str(row.deal_verdict or ""))
    if column == "location":
        return _safe(row.location or "")
    if column == "seller":
        return _safe(row.seller_name or "")
    if column == "favorite":
        return t("export.yes" if row.is_favorite else "export.no", lang)
    if column == "url":
        return _safe(row.url)
    raise KeyError(column)  # pragma: no cover - COLUMNS is the contract


def _number(value: float | None, lang: str | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if (lang or "de") in _COMMA_DECIMAL else text


def _safe(text: str) -> str:
    """Keep a scraped title from executing as a spreadsheet formula."""
    text = text.replace("\n", " ").replace("\r", " ")
    return f"'{text}" if text.startswith(_FORMULA_LEADERS) else text
