"""Thin data-access helpers (repository pattern) over the ORM.

Keeping queries here means the bot handlers, API routers and worker tasks all
share the same, tested database access paths.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Listing, SearchRule, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        language_code: str | None = None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code or "de",
            )
            self.session.add(user)
            await self.session.flush()
        else:
            # Keep the profile fresh on each interaction.
            user.username = username or user.username
            user.first_name = first_name or user.first_name
            user.last_name = last_name or user.last_name
        return user


class SearchRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, rule_id: int) -> SearchRule | None:
        return await self.session.get(SearchRule, rule_id)

    async def list_for_user(self, user_id: int) -> Sequence[SearchRule]:
        result = await self.session.execute(
            select(SearchRule)
            .where(SearchRule.user_id == user_id)
            .order_by(SearchRule.created_at.desc())
        )
        return result.scalars().all()

    async def list_active(self) -> Sequence[SearchRule]:
        result = await self.session.execute(
            select(SearchRule).where(SearchRule.is_active.is_(True))
        )
        return result.scalars().all()

    async def count_for_user(self, user_id: int) -> int:
        result = await self.session.execute(
            select(SearchRule).where(SearchRule.user_id == user_id)
        )
        return len(result.scalars().all())

    async def add(self, rule: SearchRule) -> SearchRule:
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def delete(self, rule: SearchRule) -> None:
        await self.session.delete(rule)


class ListingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def existing_fingerprints(self, rule_id: int) -> set[str]:
        result = await self.session.execute(
            select(Listing.fingerprint).where(Listing.rule_id == rule_id)
        )
        return set(result.scalars().all())

    async def add_all(self, listings: list[Listing]) -> None:
        self.session.add_all(listings)
        await self.session.flush()

    async def unnotified_for_rule(self, rule_id: int) -> Sequence[Listing]:
        result = await self.session.execute(
            select(Listing)
            .where(Listing.rule_id == rule_id, Listing.notified.is_(False))
            .order_by(Listing.deal_score.desc())
        )
        return result.scalars().all()

    async def by_external_ids(
        self, rule_id: int, external_ids: list[str]
    ) -> Sequence[Listing]:
        """Stored listings of this rule matching any of the given ad ids."""
        if not external_ids:
            return []
        result = await self.session.execute(
            select(Listing).where(
                Listing.rule_id == rule_id,
                Listing.external_id.in_(external_ids),
            )
        )
        return result.scalars().all()

    async def notified_elsewhere(
        self, user_id: int, exclude_rule_id: int, external_ids: list[str]
    ) -> set[tuple[object, str]]:
        """(site, external_id) pairs already delivered via the user's OTHER rules.

        Prevents duplicate cards when two rules of the same user match the
        same ad (e.g. "Tesla" and "Tesla Model 3").
        """
        if not external_ids:
            return set()
        result = await self.session.execute(
            select(Listing.site, Listing.external_id)
            .join(SearchRule, SearchRule.id == Listing.rule_id)
            .where(
                SearchRule.user_id == user_id,
                Listing.rule_id != exclude_rule_id,
                Listing.notified.is_(True),
                Listing.external_id.in_(external_ids),
            )
        )
        return {(site, ext) for site, ext in result.all()}

    async def rule_stats(
        self, rule_id: int, days: int = 7
    ) -> tuple[int, float | None, float | None]:
        """(count, avg price, min price) of this rule's finds in the last days."""
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(
                func.count(Listing.id),
                func.avg(Listing.price),
                func.min(Listing.price),
            ).where(Listing.rule_id == rule_id, Listing.created_at >= cutoff)
        )
        count, avg_price, min_price = result.one()
        return (
            int(count or 0),
            float(avg_price) if avg_price is not None else None,
            float(min_price) if min_price is not None else None,
        )

    async def recent_prices(self, rule_id: int, days: int = 30) -> list[float]:
        """Prices of this rule's listings seen within the last ``days`` days.

        Feeds the market-price estimate, which becomes far more stable than a
        single scrape batch once some history has accumulated.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(Listing.price).where(
                Listing.rule_id == rule_id,
                Listing.created_at >= cutoff,
                Listing.price.isnot(None),
            )
        )
        return [p for p in result.scalars().all() if p is not None]
