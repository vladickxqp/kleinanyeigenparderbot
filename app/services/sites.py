"""Which marketplaces a rule actually searches.

A rule stores the sites its owner picked, and an empty list has always meant
"every one we have". Both have to pass through the owner's level before a
single request goes out.

Searching several marketplaces at once is one of the things the paid plans
sell, and it is also the expensive one: every extra site multiplies a rule's
share of the scraping budget, which this project prices in requests per
minute. A free rule that quietly polls all four gives away four times what it
pays for — and the dial for it (``max_sites_per_rule``) already existed in
settings, read by nobody.

Two rules keep this honest:

* **The cap bites where the search runs**, not only in the keyboard. A rule
  written before the cap existed, a rule created from the Mini App, and a rule
  whose owner downgraded yesterday all go through the same resolution.
* **A capped rule says so.** Silently searching one site while the rule card
  claims "all" is the failure mode this project keeps meeting: the user just
  gets fewer deals and has no way to find out why.
"""

from __future__ import annotations

from app.database.models.enums import SiteName
from app.services import entitlements as ent

#: Order the cap keeps when a rule asks for "all" and may not have all.
#: Kleinanzeigen first because it is the marketplace this bot was built for and
#: the only one with private sellers, posting dates and real bargains;
#: AutoScout24 second because a car is the largest single amount of money the
#: bot can save anybody. Everything else follows in registration order.
PREFERRED_ORDER: tuple[SiteName, ...] = (
    SiteName.KLEINANZEIGEN,
    SiteName.AUTOSCOUT24,
    SiteName.EBAY,
    SiteName.IDEALO,
)


def available() -> list[SiteName]:
    """Every marketplace that has a registered parser, in preferred order."""
    from app.parsers import registry

    registered = set(registry.available_sites)
    ordered = [site for site in PREFERRED_ORDER if site in registered]
    ordered += [site for site in registry.available_sites if site not in ordered]
    return ordered


def cap_for(user) -> int:  # noqa: ANN001 - User, imported lazily by callers
    """How many marketplaces one of this user's rules may search at once."""
    if user is None:
        return ent.UNLIMITED
    return user.entitlements.max_sites_per_rule


def is_capped(user) -> bool:  # noqa: ANN001
    """True when this user cannot search every marketplace in one rule."""
    limit = cap_for(user)
    return not ent.is_unlimited(limit) and limit < len(available())


def upgrade_level(user) -> str | None:  # noqa: ANN001
    """Label of the cheapest level that would lift this user's cap.

    None when nothing would — either the cap is already gone, or no level
    offers more, and then promising an upgrade would be a lie.
    """
    if not is_capped(user):
        return None
    mine = cap_for(user)
    for tier in ent.all_tiers():
        limit = tier.max_sites_per_rule
        if ent.is_unlimited(limit) or limit > mine:
            return tier.label
    return None


def resolve(chosen: list[str] | list[SiteName] | None, user=None) -> list[SiteName]:  # noqa: ANN001
    """The marketplaces a rule really searches, after the owner's level.

    ``chosen`` empty (or None) means "all" — which for a capped user resolves
    to the first :data:`PREFERRED_ORDER` entries rather than to everything.
    An explicit choice keeps the user's own order, so the site they picked
    first is the one they keep.

    A downgrade deliberately does NOT rewrite what the rule stores. The cap is
    applied here, on every run, and the stored choice survives it — so an
    upgrade gives the user back exactly the marketplaces they picked instead of
    a list somebody trimmed for them while they were not paying.
    """
    offered = available()
    picked: list[SiteName] = []
    for value in chosen or []:
        try:
            site = value if isinstance(value, SiteName) else SiteName(value)
        except ValueError:
            continue  # a site whose parser was removed since
        if site in offered and site not in picked:
            picked.append(site)

    wanted = picked or offered
    limit = cap_for(user)
    if ent.is_unlimited(limit):
        return wanted
    return wanted[: max(0, limit)]


def withheld(chosen: list[str] | list[SiteName] | None, user=None) -> list[SiteName]:  # noqa: ANN001
    """The marketplaces the level left out — what an upgrade would add."""
    granted = set(resolve(chosen, user))
    return [site for site in resolve(chosen, None) if site not in granted]
