"""Telegram Mini App API — the user's own data, authenticated via initData.

Every endpoint is scoped to the calling Telegram user; there is no way to
address another user's rules, flips or payments.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.webapp_auth import current_webapp_user
from app.bot.texts import feature_label, t
from app.config.settings import settings
from app.database.models import Listing, SearchRule, User
from app.database.session import get_session
from app.services import entitlements as ent
from app.services import flips as flip_svc
from app.services import premium, quota
from app.services.repositories import SearchRuleRepository
from app.services.roles import effective_role

router = APIRouter(prefix="/webapp", tags=["webapp"])


# --- Schemas ----------------------------------------------------------------------
class QuotaOut(BaseModel):
    """One metered quota with its window, as the usage bars need it."""

    kind: str
    label: str
    used: int
    limit: int          # -1 = unlimited
    remaining: int      # -1 = unlimited
    unlimited: bool
    exhausted: bool
    window: str


class LevelOut(BaseModel):
    """One level of the ladder — every figure resolved from its entitlements."""

    tier: str
    label: str
    price_stars: int
    price_eur: float
    purchasable: bool
    note: str | None
    max_rules: int
    base_interval_seconds: int
    min_interval_seconds: int
    fast_slots: int
    daily_notifications: int
    photo_evals_per_month: int
    quick_searches_per_day: int
    negotiations_per_month: int
    history_days: int
    max_sites_per_rule: int
    features: list[str]


class MarketplaceOut(BaseModel):
    """One marketplace the picker may offer."""

    slug: str
    label: str


class MeOut(BaseModel):
    telegram_id: int
    name: str
    role: str
    tier: str
    is_paid: bool
    premium_until: datetime | None
    renews: bool
    last_charge_at: datetime | None
    next_charge_at: datetime | None
    flip_min_net: float | None
    price_stars: int
    price_eur: float
    #: Whether the Konto tab may offer the cancel action at all, and which of
    #: the two it is — the client must not guess this from ``renews``.
    can_cancel: bool
    cancel_kind: str | None
    entitlements: LevelOut
    usage: list[QuotaOut]
    levels: list[LevelOut]
    #: Every marketplace with a parser, in the order the cap keeps them.
    marketplaces: list[MarketplaceOut]


class CancelOut(BaseModel):
    """The outcome of a cancellation, in the words the Konto tab shows."""

    #: ``cancel_at_period_end`` — renewal stopped, premium runs until
    #: ``active_until``; ``ended`` — premium was handed back right away.
    outcome: str
    detail: str
    active_until: datetime | None
    tier: str
    label: str
    is_paid: bool
    renews: bool


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    keywords: str
    is_active: bool
    interval_seconds: int
    min_price: float | None
    max_price: float | None
    location: str | None
    max_distance_km: int | None
    category: str | None
    max_mileage_km: int | None = None
    min_year: int | None = None
    seller_type: str = "any"
    #: What the owner picked (empty = every marketplace).
    sites: list[str] = []
    #: What the rule REALLY searches after the owner's level, and what
    #: the level held back — so the app never claims more than it does.
    searched_sites: list[str] = []
    withheld_sites: list[str] = []


class RuleIn(BaseModel):
    """Payload for creating or editing a rule from the Mini App."""

    name: str = Field(min_length=1, max_length=128)
    keywords: str = Field(min_length=1, max_length=256)
    min_price: float | None = Field(default=None, ge=0, le=10_000_000)
    max_price: float | None = Field(default=None, ge=0, le=10_000_000)
    location: str | None = Field(default=None, max_length=64)
    max_distance_km: int | None = Field(default=None, ge=0, le=500)
    interval_seconds: int = Field(default=600, ge=60, le=86_400)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=20)
    #: Car bounds. The upper limits are what the filter can still mean, not
    #: what a client may claim: everything from outside is bounded here.
    max_mileage_km: int | None = Field(default=None, ge=0, le=2_000_000)
    min_year: int | None = Field(default=None, ge=1950, le=2100)
    #: Marketplace slugs; unknown ones are dropped and the owner's cap is
    #: applied server-side, never by the client.
    sites: list[str] = Field(default_factory=list, max_length=20)
    #: "any" | "private" | "dealer"; anything else is refused below.
    seller_type: str = "any"

    def apply_to(self, rule: SearchRule, user: User) -> None:
        """Copy the validated values onto a rule, honouring the user's tier."""
        rule.name = self.name.strip()[:128]
        rule.keywords = self.keywords.strip()[:256]
        rule.min_price = self.min_price
        rule.max_price = self.max_price
        location = (self.location or "").strip()[:64]
        rule.location = location or None
        rule.zip_code = (
            location if location.isdigit() and 4 <= len(location) <= 5 else None
        )
        rule.max_distance_km = self.max_distance_km
        rule.max_mileage_km = self.max_mileage_km
        rule.min_year = self.min_year
        # An unknown value means "no preference", never a filter the
        # client invented.
        from app.database.models.enums import SellerType

        try:
            rule.seller_type = SellerType(self.seller_type)
        except ValueError:
            rule.seller_type = SellerType.ANY
        # The level decides how many marketplaces a rule may search; an
        # empty list keeps meaning "every one we have".
        from app.services import sites as site_access

        rule.sites = [s.value for s in site_access.resolve(self.sites, user)]
        if len(rule.sites) == len(site_access.available()):
            rule.sites = []
        # The tier decides the floor, never the client.
        rule.interval_seconds = max(self.interval_seconds, user.min_interval_seconds)
        rule.exclude_keywords = [
            word.strip()[:64] for word in self.exclude_keywords if word.strip()
        ][:20]


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site: str
    title: str
    #: How the marketplace writes its own name ("AutoScout24"), so the card
    #: does not print a database slug at the reader.
    site_label: str = ""
    url: str
    image_url: str | None
    price: float | None
    estimated_market_price: float | None
    deal_score: int
    deal_verdict: str
    location: str | None
    is_favorite: bool
    created_at: datetime
    # Signals the card shows: how far below market, negotiable price, shipping.
    discount_percent: float | None = None
    is_negotiable: bool = False
    shipping_cost: float | None = None

    @model_validator(mode="after")
    def _name_the_marketplace(self) -> "ListingOut":
        if not self.site_label:
            from app.parsers.registry import site_label

            self.site_label = site_label(self.site)
        return self


class PricePointOut(BaseModel):
    at: datetime
    price: float


class ComparisonOut(BaseModel):
    """What comparable ads cost. ``usable`` is false below the minimum."""

    usable: bool
    count: int
    median: float | None
    minimum: float | None
    maximum: float | None
    discount_percent: float | None


class ListingDetailOut(BaseModel):
    """One listing with the context its deal score was computed from."""

    listing: ListingOut
    description: str | None
    #: Words in the ad text that say it is broken, e.g. ["defekt"].
    defect_markers: list[str]
    is_defective: bool
    is_part: bool
    #: This ad's own price over time, oldest first.
    history: list[PricePointOut]
    #: How much it came down since it was first seen, if it did.
    price_fell: float | None
    #: How many comparable ads of the SAME kind the comparison used.
    compared_with: int
    asking: ComparisonOut | None
    sold: ComparisonOut | None
    #: Which of the two the app should lead with — sold when there is enough.
    reference: str | None


class FlipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    buy_price: float
    sell_price: float | None
    net_profit: float | None
    status: str
    bought_at: datetime
    sold_at: datetime | None


class FlipStatsOut(BaseModel):
    open_count: int
    invested_open: float
    sold_count: int
    revenue: float
    fees: float
    net_profit: float
    net_last_30d: float
    avg_margin_pct: float | None
    best_title: str | None
    best_net: float | None


class FlipsOut(BaseModel):
    stats: FlipStatsOut
    open: list[FlipOut]


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    amount_stars: int
    amount_eur: float
    status: str
    refunded: bool
    is_renewal: bool
    coupon_code: str | None
    created_at: datetime


# --- Cancelling: the same two cases the bot knows ------------------------------------
#: Which of the two cancellations applies. "renewal" stops the Stars
#: auto-renewal (premium keeps running), "premium" hands a non-charging premium
#: (trial, grant, coupon) back immediately.
CANCEL_RENEWAL = "renewal"
CANCEL_PREMIUM = "premium"


def _cancellable(sub) -> bool:
    """True if this subscription auto-renews via Stars and can be cancelled.

    Mirrors ``app.bot.handlers.premium._cancellable`` — chat and Mini App must
    never disagree about what a cancellation does to the same subscription.
    """
    return (
        sub is not None
        and sub.payment_provider == "telegram_stars"
        and bool(sub.telegram_charge_id)
        and sub.payment_status != premium.CANCEL_AT_PERIOD_END
    )


def _endable(sub) -> bool:
    """True if a non-renewing premium (trial/grant/coupon) can be ended early.

    Mirrors ``app.bot.handlers.premium._endable``.
    """
    return (
        sub is not None
        and not _cancellable(sub)
        and sub.payment_status != premium.CANCEL_AT_PERIOD_END
    )


def _cancel_kind(sub) -> str | None:
    """Which cancel action the account screen may offer for ``sub``, if any."""
    if _cancellable(sub):
        return CANCEL_RENEWAL
    if _endable(sub):
        return CANCEL_PREMIUM
    return None


# --- Level and usage payloads -------------------------------------------------------
def level_out(e: ent.Entitlements, lang: str) -> LevelOut:
    """Serialise one level; Free carries no price and is never purchasable."""
    plan = premium.plan_for_tier(e.tier) if e.is_paid else None
    on_sale = plan is not None and plan.key in {p.key for p in premium.available_plans()}
    return LevelOut(
        tier=e.tier.value,
        label=e.label,
        price_stars=plan.price_stars if plan else 0,
        price_eur=plan.price_eur if plan else 0.0,
        purchasable=on_sale,
        note=None if on_sale or plan is None else t("premium.not_bookable_short", lang),
        max_rules=e.max_rules,
        base_interval_seconds=e.interval_floor(fast=False),
        min_interval_seconds=e.interval_floor(fast=True),
        fast_slots=e.fast_slots,
        daily_notifications=e.daily_notifications,
        photo_evals_per_month=e.photo_evals_per_month,
        quick_searches_per_day=e.quick_searches_per_day,
        negotiations_per_month=e.negotiations_per_month,
        history_days=e.history_days,
        max_sites_per_rule=e.max_sites_per_rule,
        features=[feature_label(f, lang) for f in sorted(e.features)],
    )


def usage_out(states: dict[str, quota.QuotaState], lang: str) -> list[QuotaOut]:
    """The quota snapshot in the order the bot's /usage page shows it."""
    return [
        QuotaOut(
            kind=state.kind,
            label=t(f"usage.kind.{state.kind}", lang),
            used=state.used,
            limit=state.limit,
            remaining=state.remaining,
            unlimited=state.unlimited,
            exhausted=state.exhausted,
            window=state.window_label(lang),
        )
        for state in states.values()
    ]


# --- Endpoints ----------------------------------------------------------------------
@router.get("/me", response_model=MeOut)
async def me(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    sub = await premium.get_active_subscription(session, user.telegram_id)
    billing = await premium.billing_info(session, user.telegram_id)
    renews = bool(
        sub
        and sub.payment_provider == "telegram_stars"
        and sub.payment_status != premium.CANCEL_AT_PERIOD_END
    )
    lang = user.language_code
    kind = _cancel_kind(sub) if user.is_paid_tier else None
    return MeOut(
        telegram_id=user.telegram_id,
        name=user.display_name,
        role=effective_role(user).value,
        tier=user.subscription.value,
        is_paid=user.is_paid_tier,
        premium_until=sub.subscription_end if sub else None,
        renews=renews,
        last_charge_at=billing.last_charge_at,
        next_charge_at=billing.next_charge_at if renews else None,
        flip_min_net=await flip_svc.get_flip_min(user.telegram_id),
        price_stars=settings.premium_price_stars,
        price_eur=settings.premium_price_eur,
        can_cancel=kind is not None,
        cancel_kind=kind,
        entitlements=level_out(user.entitlements, lang),
        usage=usage_out(await quota.snapshot(user), lang),
        levels=[level_out(e, lang) for e in ent.all_tiers()],
        marketplaces=_marketplaces(),
    )


def _marketplaces() -> list[MarketplaceOut]:
    """The marketplaces that actually have a parser, in preferred order."""
    from app.parsers.registry import site_label
    from app.services import sites as site_access

    return [
        MarketplaceOut(slug=site.value, label=site_label(site))
        for site in site_access.available()
    ]


def _rule_out(rule: SearchRule, user: User) -> RuleOut:
    """A rule plus what the owner's level actually lets it search.

    Resolved here rather than on the client: the app must never show a list of
    marketplaces the search does not visit.
    """
    from app.services import sites as site_access

    out = RuleOut.model_validate(rule)
    out.searched_sites = [s.value for s in site_access.resolve(rule.sites, user)]
    out.withheld_sites = [s.value for s in site_access.withheld(rule.sites, user)]
    return out


@router.get("/rules", response_model=list[RuleOut])
async def rules(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> list[RuleOut]:
    rules = await SearchRuleRepository(session).list_for_user(user.id)
    return [_rule_out(rule, user) for rule in rules]


@router.post("/rules/{rule_id}/toggle", response_model=RuleOut)
async def toggle_rule(
    rule_id: int,
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> RuleOut:
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Suche nicht gefunden")
    rule.is_active = not rule.is_active
    await session.commit()
    await session.refresh(rule)
    return _rule_out(rule, user)


@router.post("/rules", response_model=RuleOut, status_code=201)
async def create_rule(
    payload: RuleIn,
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> RuleOut:
    """Create a search from the Mini App, within the user's quota."""
    repo = SearchRuleRepository(session)
    if await repo.count_for_user(user.id) >= user.max_rules:
        raise HTTPException(
            status_code=409,
            detail=f"Tarif-Limit erreicht ({user.max_rules} Suchen).",
        )
    rule = SearchRule(user_id=user.id, name=payload.name, keywords=payload.keywords)
    payload.apply_to(rule, user)
    await repo.add(rule)
    await session.commit()
    await session.refresh(rule)
    logger.info("WEBAPP: {} created rule {}", user.telegram_id, rule.id)
    return _rule_out(rule, user)


@router.put("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: int,
    payload: RuleIn,
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> RuleOut:
    rule = await SearchRuleRepository(session).get(rule_id, user.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Suche nicht gefunden")
    payload.apply_to(rule, user)
    await session.commit()
    await session.refresh(rule)
    return _rule_out(rule, user)


@router.delete(
    "/rules/{rule_id}", status_code=204, response_class=Response, response_model=None
)
async def delete_rule(
    rule_id: int,
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    repo = SearchRuleRepository(session)
    rule = await repo.get(rule_id, user.id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Suche nicht gefunden")
    await repo.delete(rule)
    await session.commit()


@router.get("/listings", response_model=list[ListingOut])
async def listings(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=30, le=100),
    favorites: bool = Query(default=False),
) -> list[Listing]:
    stmt = (
        select(Listing)
        .join(SearchRule, SearchRule.id == Listing.rule_id)
        .where(SearchRule.user_id == user.id, Listing.is_ignored.is_(False))
    )
    if favorites:
        stmt = stmt.where(Listing.is_favorite.is_(True))
    else:
        stmt = stmt.where(Listing.notified.is_(True))
    result = await session.execute(
        stmt.order_by(Listing.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def _comparison_out(comparison) -> ComparisonOut | None:  # noqa: ANN001
    if comparison is None:
        return None
    stats = comparison.stats
    return ComparisonOut(
        usable=comparison.usable,
        count=stats.count,
        median=stats.median,
        minimum=stats.minimum,
        maximum=stats.maximum,
        discount_percent=comparison.discount_percent,
    )


@router.get("/listings/{listing_id}", response_model=ListingDetailOut)
async def listing_detail_view(
    listing_id: int,
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> ListingDetailOut:
    """Everything worth knowing about one of the caller's own listings.

    Scoped through the rule's owner, like every other endpoint here: a listing
    id from somebody else's search must not resolve.
    """
    from app.services import listing_detail as detail_svc

    row = (
        await session.execute(
            select(Listing)
            .join(SearchRule, SearchRule.id == Listing.rule_id)
            .where(Listing.id == listing_id, SearchRule.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Angebot nicht gefunden")

    detail = await detail_svc.build(session, row)
    reference = None
    if detail.best_reference is detail.sold and detail.sold is not None:
        reference = "sold"
    elif detail.best_reference is detail.asking and detail.asking is not None:
        reference = "asking"

    return ListingDetailOut(
        listing=ListingOut.model_validate(row),
        description=row.description,
        defect_markers=detail.defect_markers,
        is_defective=detail.is_defective,
        is_part=detail.is_part,
        history=[PricePointOut(at=p.at, price=p.price) for p in detail.history],
        price_fell=detail.price_fell,
        compared_with=detail.compared_with,
        asking=_comparison_out(detail.asking),
        sold=_comparison_out(detail.sold),
        reference=reference,
    )


@router.get("/flips", response_model=FlipsOut)
async def flips(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> FlipsOut:
    stats = await flip_svc.profit_stats(session, user.telegram_id)
    open_items = await flip_svc.open_flips(session, user.telegram_id)
    return FlipsOut(
        stats=FlipStatsOut(
            open_count=stats.open_count,
            invested_open=stats.invested_open,
            sold_count=stats.sold_count,
            revenue=stats.revenue,
            fees=stats.fees,
            net_profit=stats.net_profit,
            net_last_30d=stats.net_last_30d,
            avg_margin_pct=stats.avg_margin_pct,
            best_title=stats.best_title,
            best_net=stats.best_net,
        ),
        open=[FlipOut.model_validate(f) for f in open_items],
    )


@router.get("/payments", response_model=list[PaymentOut])
async def payments(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
):
    return await premium.payment_history(session, user.telegram_id)


@router.post("/subscription/cancel", response_model=CancelOut)
async def cancel_subscription(
    user: User = Depends(current_webapp_user),
    session: AsyncSession = Depends(get_session),
) -> CancelOut:
    """Cancel the caller's own premium — the chat's two cases, in the app.

    There is deliberately no id in the path: the subscription is always looked
    up by the authenticated user's telegram id, so nobody can cancel anyone
    else's premium. A second call finds nothing left to cancel and refuses
    cleanly (409) instead of charging Telegram again or ending premium twice.
    """
    sub = await premium.get_active_subscription(session, user.telegram_id)

    if _cancellable(sub):
        # Stop the auto-renewal at Telegram FIRST: only when Telegram confirms
        # may the row say "cancelled", otherwise the next charge still arrives.
        if not await premium.cancel_stars_subscription(
            user.telegram_id, sub.telegram_charge_id
        ):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Die Kündigung hat bei Telegram gerade nicht geklappt. "
                    "Bitte gleich nochmal versuchen — oder in Telegram: "
                    "Einstellungen → Meine Sterne → Abos → Deal Hunter."
                ),
            )
        sub.payment_status = premium.CANCEL_AT_PERIOD_END
        sub.renewal_date = None
        await session.commit()
        logger.info("WEBAPP: {} cancelled the Stars renewal", user.telegram_id)
        return CancelOut(
            outcome=premium.CANCEL_AT_PERIOD_END,
            detail=(
                "Gekündigt. Dein Premium bleibt bis "
                f"{sub.subscription_end:%d.%m.%Y} aktiv und verlängert sich "
                "danach nicht mehr — es wird nichts mehr abgebucht."
            ),
            active_until=sub.subscription_end,
            tier=user.subscription.value,
            label=user.entitlements.label,
            is_paid=user.is_paid_tier,
            renews=False,
        )

    if _endable(sub):
        # Trial, gift or coupon: nothing is charged, so it ends right away.
        await premium.deactivate_premium(session, user)
        await session.commit()
        logger.info("WEBAPP: {} ended a non-renewing premium", user.telegram_id)
        return CancelOut(
            outcome="ended",
            detail="Premium beendet. Du bist ab sofort wieder im Free-Tarif.",
            active_until=None,
            tier=user.subscription.value,
            label=user.entitlements.label,
            is_paid=user.is_paid_tier,
            renews=False,
        )

    raise HTTPException(
        status_code=409,
        detail="Es läuft gerade nichts, was gekündigt werden könnte.",
    )
