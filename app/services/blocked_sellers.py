"""Blocking a seller, not just one of their ads.

The 🙈 button hides a single listing. That is the wrong tool against a dealer
with two hundred cars, or against anyone who re-posts faster than the repost
window closes: the user does not want *that ad* gone, they want *that seller*
gone.

Two things this module is careful about:

* **The key is the marketplace's own seller id wherever it has one.** A dealer
  can rename itself overnight, and a block that follows the name would quietly
  stop working without anybody noticing — the worst kind of failure in a
  filter, because the only symptom is ads coming back.
* **Only sites that name a seller can be blocked.** Kleinanzeigen and eBay do
  not put one on the result card, so an ad from there can never match a block.
  :func:`can_block` says so, and the UI asks before it offers the button —
  promising a block that silently does nothing is worse than not offering one.
"""

from __future__ import annotations

import re

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BlockedSeller
from app.database.models.enums import SiteName

#: Nobody needs more than this, and an unbounded list is an unbounded query.
MAX_PER_USER = 200


def seller_key(seller_id: str | None, seller_name: str | None) -> str | None:
    """The stable handle for a seller, or None when the site names none."""
    if seller_id:
        return str(seller_id).strip()[:128] or None
    if seller_name:
        folded = re.sub(r"\s+", " ", seller_name).strip().lower()
        return folded[:128] or None
    return None


def can_block(seller_id: str | None, seller_name: str | None) -> bool:
    """Whether this ad identifies its seller well enough to block them."""
    return seller_key(seller_id, seller_name) is not None


async def blocked_keys(session: AsyncSession, user_id: int) -> set[tuple[str, str]]:
    """(site value, seller key) pairs this user has blocked."""
    rows = (
        await session.execute(
            select(BlockedSeller.site, BlockedSeller.seller_key).where(
                BlockedSeller.user_id == user_id
            )
        )
    ).all()
    return {(getattr(site, "value", site), key) for site, key in rows}


async def block(
    session: AsyncSession,
    user_id: int,
    site: SiteName | str,
    *,
    seller_id: str | None,
    seller_name: str | None,
) -> BlockedSeller | None:
    """Block a seller for this user. None when the ad names no seller."""
    key = seller_key(seller_id, seller_name)
    if key is None:
        return None
    value = getattr(site, "value", site)

    existing = (
        await session.execute(
            select(BlockedSeller).where(
                BlockedSeller.user_id == user_id,
                BlockedSeller.site == value,
                BlockedSeller.seller_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    count = len(await blocked_keys(session, user_id))
    if count >= MAX_PER_USER:
        logger.info("User {} reached the blocked-seller ceiling", user_id)
        return None

    row = BlockedSeller(
        user_id=user_id,
        site=value,
        seller_key=key,
        label=(seller_name or key)[:128],
    )
    session.add(row)
    await session.flush()
    return row


async def unblock(
    session: AsyncSession, user_id: int, site: SiteName | str, seller_key_value: str
) -> bool:
    """Lift a block. True when something was actually lifted."""
    result = await session.execute(
        delete(BlockedSeller).where(
            BlockedSeller.user_id == user_id,
            BlockedSeller.site == getattr(site, "value", site),
            BlockedSeller.seller_key == seller_key_value,
        )
    )
    return bool(result.rowcount)


async def listed(session: AsyncSession, user_id: int) -> list[BlockedSeller]:
    """Everything this user has blocked, newest first."""
    return list(
        (
            await session.execute(
                select(BlockedSeller)
                .where(BlockedSeller.user_id == user_id)
                .order_by(BlockedSeller.created_at.desc())
            )
        ).scalars().all()
    )


def drop_blocked(items, blocked: set[tuple[str, str]]):  # noqa: ANN001
    """Remove parsed listings whose seller this user blocked.

    An ad that names no seller is kept: it cannot match a block, and dropping
    it would silently empty every marketplace that does not report one.
    """
    if not blocked:
        return items
    kept = []
    for item in items:
        key = seller_key(
            getattr(item, "seller_id", None), getattr(item, "seller_name", None)
        )
        if key is not None and (item.site.value, key) in blocked:
            continue
        kept.append(item)
    return kept
