"""How many marketplaces one rule may search, and who decides.

Searching several marketplaces at once is one of the things the paid plans
sell, and the expensive one: every extra site multiplies a rule's share of the
scraping budget this project prices in requests per minute. The dial for it
existed in settings and was read by nobody, so every free rule quietly polled
all of them.

The tests below pin down that the cap bites where the search RUNS — not only
in the keyboard, which a Mini App rule, an older rule and a downgraded user all
walk straight past — and that a capped rule never claims more than it does.
"""

from __future__ import annotations

import pytest

from app.config.settings import settings
from app.database.models import SubscriptionTier, User
from app.database.models.enums import SiteName
from app.services import sites as site_access


def _user(tier: SubscriptionTier) -> User:
    return User(telegram_id=1, subscription=tier, language_code="de")


FREE = SubscriptionTier.FREE
PRO = SubscriptionTier.PRO


# --- The cap itself ---------------------------------------------------------------
def test_a_paid_level_searches_every_marketplace():
    everything = site_access.available()
    assert len(everything) > 1  # otherwise these tests prove nothing
    assert site_access.resolve([], _user(PRO)) == everything
    assert site_access.withheld([], _user(PRO)) == []
    assert site_access.is_capped(_user(PRO)) is False


def test_free_gets_one_marketplace_even_when_the_rule_says_all():
    """"Empty means all" is exactly how a free rule used to poll everything."""
    granted = site_access.resolve([], _user(FREE))
    assert granted == [SiteName.KLEINANZEIGEN]
    assert site_access.is_capped(_user(FREE)) is True
    # And the rest is nameable, so the app can say what an upgrade adds.
    assert len(site_access.withheld([], _user(FREE))) == len(
        site_access.available()
    ) - 1


def test_the_cap_keeps_the_user_s_own_first_choice():
    # They tapped eBay first, so eBay is the one they keep — not the one a
    # preferred order would have picked for them.
    granted = site_access.resolve(["ebay", "kleinanzeigen"], _user(FREE))
    assert granted == [SiteName.EBAY]


def test_an_explicit_choice_within_the_cap_is_left_alone():
    assert site_access.resolve(["ebay"], _user(FREE)) == [SiteName.EBAY]
    assert site_access.withheld(["ebay"], _user(FREE)) == []


def test_unknown_and_duplicate_slugs_are_dropped():
    granted = site_access.resolve(
        ["kleinanzeigen", "kleinanzeigen", "myspace"], _user(PRO)
    )
    assert granted == [SiteName.KLEINANZEIGEN]


def test_no_user_means_no_cap():
    """Internal callers (the preview, the comparison) see the full picture."""
    assert site_access.resolve([], None) == site_access.available()


def test_the_cap_follows_settings_not_a_hardcoded_number(monkeypatch):
    monkeypatch.setattr(settings, "free_max_sites_per_rule", 2)
    granted = site_access.resolve([], _user(FREE))
    assert granted == site_access.available()[:2]


def test_a_level_that_lifts_the_cap_can_be_named():
    level = site_access.upgrade_level(_user(FREE))
    assert level and level != _user(FREE).entitlements.label
    # Nothing to promise when there is no cap — a pitch there would be a lie.
    assert site_access.upgrade_level(_user(PRO)) is None


def test_a_downgrade_does_not_rewrite_what_the_rule_stored():
    """An upgrade must give back exactly the marketplaces they picked."""
    chosen = ["ebay", "kleinanzeigen"]
    assert site_access.resolve(chosen, _user(FREE)) == [SiteName.EBAY]
    # Same stored list, paid again: both are back.
    assert site_access.resolve(chosen, _user(PRO)) == [
        SiteName.EBAY,
        SiteName.KLEINANZEIGEN,
    ]


# --- Where it has to bite ---------------------------------------------------------
def test_the_search_itself_resolves_through_the_cap():
    """The keyboard is not a security boundary — the run is."""
    import inspect

    from app.services import search_service

    source = inspect.getsource(search_service.SearchService._collect)
    assert "site_access.resolve" in source
    assert "registry.resolve(rule.target_sites)" not in source


@pytest.mark.parametrize("tier, expected", [(FREE, 1), (PRO, None)])
def test_the_ladder_advertises_the_cap(tier, expected):
    from app.services import entitlements as ent

    limit = ent.for_tier(tier).max_sites_per_rule
    if expected is None:
        assert ent.is_unlimited(limit)
    else:
        assert limit == expected
