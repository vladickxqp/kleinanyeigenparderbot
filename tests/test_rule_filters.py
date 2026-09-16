"""The three surviving rule filters: condition, shipping and auctions.

Covers the heuristic itself, the tri-state shipping rule, the sites that must
opt out of a filter they cannot honour, and the edit-menu wiring.
"""

from __future__ import annotations

from app.bot.keyboards import (
    AUCTION_VALUES,
    CONDITION_CHOICES,
    SHIPPING_VALUES,
    rule_edit_keyboard,
)
from app.database.models import SearchRule
from app.database.models.enums import Condition, SiteName
from app.parsers.schemas import ParsedListing, SearchQuery
from app.parsers.sites.ebay import EbayParser
from app.parsers.sites.idealo import IdealoParser
from app.parsers.sites.kleinanzeigen import (
    KleinanzeigenParser,
    guess_condition,
    matches_condition,
    matches_shipping,
    shipping_flag,
)
from app.services.relevance import is_relevant


def _item(
    title: str,
    desc: str | None = None,
    shipping: float | None = None,
    offers: bool | None = None,
) -> ParsedListing:
    return ParsedListing(
        site=SiteName.KLEINANZEIGEN,
        external_id=title,
        title=title,
        url="https://www.kleinanzeigen.de/x",
        price=500.0,
        description=desc,
        shipping_cost=shipping,
        shipping_available=offers,
    )


# --- Condition heuristic ---------------------------------------------------------
def test_new_needs_a_word_boundary():
    # The whole point of the regex: "Neupreis 1200 €" is a price reference in a
    # used ad, not a new item.
    assert guess_condition("iPhone 14, Neupreis war 1200 €") is Condition.USED
    assert guess_condition("iPhone 14 neuwertig") is Condition.USED
    assert guess_condition("Neuware? Nein: Neuauflage") is Condition.USED


def test_new_markers_are_recognised():
    assert guess_condition("iPhone 14 neu, OVP") is Condition.NEW
    assert guess_condition("PS5", "noch versiegelt in Folie") is Condition.NEW
    assert guess_condition("Kopfhörer ungeöffnet") is Condition.NEW
    assert guess_condition("Akku originalverpackt") is Condition.NEW
    assert guess_condition("Drohne unbenutzt") is Condition.NEW


def test_defect_markers_win_over_new():
    # "neu" plus a defect is a defect ad — the expensive mistake would be
    # selling it to a NEW-filter user as new.
    assert guess_condition("iPhone 14 neu, Display defekt") is Condition.DEFECTIVE
    assert guess_condition("MacBook für Bastler") is Condition.DEFECTIVE
    assert guess_condition("Golf 7 Ersatzteilträger") is Condition.DEFECTIVE
    assert guess_condition("Laptop", "Netzteil kaputte Buchse") is Condition.DEFECTIVE


def test_used_is_the_default_on_a_classifieds_site():
    assert guess_condition("Tesla Model 3 Long Range") is Condition.USED
    assert guess_condition("RTX 4090", None) is Condition.USED


def test_used_filter_only_excludes_defect_markers():
    assert matches_condition(Condition.USED, "RTX 4090 Founders Edition") is True
    # A new-looking ad is still a legitimate hit for a "gebraucht" search.
    assert matches_condition(Condition.USED, "RTX 4090 neu OVP") is True
    assert matches_condition(Condition.USED, "RTX 4090 defekt") is False


def test_new_and_defective_filters_are_strict():
    assert matches_condition(Condition.NEW, "RTX 4090 neu OVP") is True
    assert matches_condition(Condition.NEW, "RTX 4090 Founders Edition") is False
    assert matches_condition(Condition.DEFECTIVE, "RTX 4090 defekt") is True
    assert matches_condition(Condition.DEFECTIVE, "RTX 4090 neu OVP") is False


def test_any_and_undecidable_conditions_keep_everything():
    for wanted in (Condition.ANY, Condition.LIKE_NEW, Condition.REFURBISHED):
        assert matches_condition(wanted, "RTX 4090 defekt") is True
        assert matches_condition(wanted, "RTX 4090 neu") is True


# --- Shipping: tri-state ----------------------------------------------------------
def test_shipping_filter_never_drops_unknown_values():
    # Unknown on either side keeps the ad, otherwise a filter would silently
    # empty every marketplace that does not report the flag.
    assert matches_shipping(None, True) is True
    assert matches_shipping(None, None) is True
    assert matches_shipping(True, None) is True
    assert matches_shipping(False, None) is True


def test_shipping_filter_drops_only_known_mismatches():
    assert matches_shipping(True, True) is True
    assert matches_shipping(False, False) is True
    assert matches_shipping(True, False) is False
    assert matches_shipping(False, True) is False


def test_shipping_flag_reads_the_card_marker():
    # The parser reads the price/shipping block and says what it found.
    assert shipping_flag(_item("A", offers=True)) is True
    # Block present, hint absent: a real "no", the card says so.
    assert shipping_flag(_item("B", offers=False)) is False
    # shipping_cost == 0.0 is the older marker for the same "Versand möglich"
    # hint, so a card that carries only it still reads as a yes.
    assert shipping_flag(_item("C", shipping=0.0)) is True


def test_shipping_flag_shrugs_when_the_card_says_nothing():
    # No block at all means the markup changed, not that the seller refuses to
    # ship. Answering "no" here would silently empty a paid rule while the
    # health monitor still called the parser healthy — matches_shipping keeps
    # the ad instead.
    assert shipping_flag(_item("D")) is None
    assert matches_shipping(True, shipping_flag(_item("D"))) is True
    assert matches_shipping(False, shipping_flag(_item("D"))) is True


# --- Kleinanzeigen end to end ------------------------------------------------------
SAMPLE_HTML = """
<ul id="srchrslt-adtable">
  <article class="aditem" data-adid="1" data-href="/s-anzeige/x/1-225-1">
    <div class="aditem-main--middle">
      <h2><a class="ellipsis" href="/s-anzeige/x/1-225-1">RTX 4090 neu OVP</a></h2>
      <p class="aditem-main--middle--description">Versiegelt, mit Rechnung.</p>
      <div class="aditem-main--middle--price-shipping">
        <p class="aditem-main--middle--price-shipping--price">1.500 €</p>
        <span class="aditem-main--middle--price-shipping--shipping">Versand möglich</span>
      </div>
    </div>
  </article>
  <article class="aditem" data-adid="2" data-href="/s-anzeige/x/2-225-1">
    <div class="aditem-main--middle">
      <h2><a class="ellipsis" href="/s-anzeige/x/2-225-1">RTX 4090 defekt</a></h2>
      <p class="aditem-main--middle--description">Bastler, kein Bild.</p>
      <div class="aditem-main--middle--price-shipping">
        <p class="aditem-main--middle--price-shipping--price">400 €</p>
      </div>
    </div>
  </article>
  <article class="aditem" data-adid="3" data-href="/s-anzeige/x/3-225-1">
    <div class="aditem-main--middle">
      <h2><a class="ellipsis" href="/s-anzeige/x/3-225-1">RTX 4090 Gaming OC</a></h2>
      <p class="aditem-main--middle--description">Läuft einwandfrei.</p>
      <div class="aditem-main--middle--price-shipping">
        <p class="aditem-main--middle--price-shipping--price">1.200 €</p>
      </div>
    </div>
  </article>
</ul>
"""


def _kleinanzeigen_stub() -> KleinanzeigenParser:
    parser = KleinanzeigenParser()

    async def _fetch_text(url: str, params: dict | None = None) -> str:
        return SAMPLE_HTML

    parser.fetch_text = _fetch_text  # type: ignore[method-assign]
    return parser


async def test_kleinanzeigen_condition_filter_selects_the_right_ads():
    parser = _kleinanzeigen_stub()

    new_only = await parser.search(SearchQuery(keywords="rtx 4090", condition=Condition.NEW))
    assert [i.external_id for i in new_only] == ["1"]

    broken = await parser.search(SearchQuery(keywords="rtx 4090", condition=Condition.DEFECTIVE))
    assert [i.external_id for i in broken] == ["2"]

    used = await parser.search(SearchQuery(keywords="rtx 4090", condition=Condition.USED))
    assert [i.external_id for i in used] == ["1", "3"]

    every = await parser.search(SearchQuery(keywords="rtx 4090"))
    assert len(every) == 3


async def test_kleinanzeigen_shipping_filter_keeps_unknown_cards():
    parser = _kleinanzeigen_stub()

    shippable = await parser.search(
        SearchQuery(keywords="rtx 4090", shipping_available=True)
    )
    assert [i.external_id for i in shippable] == ["1"]

    # Pickup-only drops the ad that explicitly offers shipping and keeps the
    # cards that say nothing — unknown is never a "no".
    pickup = await parser.search(
        SearchQuery(keywords="rtx 4090", shipping_available=False)
    )
    assert [i.external_id for i in pickup] == ["2", "3"]


# --- eBay: cannot report shipping, must not filter on it -----------------------------
EBAY_HTML = """
<ul>
  <li class="s-item">
    <a class="s-item__link" href="https://www.ebay.de/itm/1234567890"></a>
    <div class="s-item__title">Nvidia RTX 4090 24GB</div>
    <span class="s-item__price">1.299,00 €</span>
  </li>
</ul>
"""


async def test_ebay_rule_with_shipping_filter_still_returns_results():
    parser = EbayParser()

    async def _fetch_text(url: str, params: dict | None = None) -> str:
        return EBAY_HTML

    parser.fetch_text = _fetch_text  # type: ignore[method-assign]

    for wanted in (True, False):
        found = await parser.search(
            SearchQuery(keywords="rtx 4090", shipping_available=wanted)
        )
        assert len(found) == 1


# --- Idealo: new retail only ----------------------------------------------------------
async def test_idealo_returns_nothing_for_used_or_defective():
    parser = IdealoParser()

    async def _fetch_rendered(url: str, *, wait_selector: str | None = None) -> str:
        raise AssertionError("Idealo must not even be rendered for these rules")

    parser.fetch_rendered = _fetch_rendered  # type: ignore[method-assign]

    for wanted in (Condition.USED, Condition.DEFECTIVE):
        assert await parser.search(SearchQuery(keywords="rtx 4090", condition=wanted)) == []


# --- Relevance: a defect hunt keeps repair ads ------------------------------------------
def test_defective_rule_keeps_repair_ads_through_the_relevance_pass():
    broken = SearchQuery(keywords="iphone 12", condition=Condition.DEFECTIVE)
    normal = SearchQuery(keywords="iphone 12")
    for title in (
        "iPhone 12 Ersatzdisplay",
        "iPhone 12 Reparatur Platine",
        "iPhone 12 Ersatzakku defekt",
        "iPhone 12 Ersatzteil Gehäuse",
    ):
        assert is_relevant(broken, _item(title)) is True
        assert is_relevant(normal, _item(title)) is False


def test_defective_rule_still_drops_real_accessories_and_wanted_ads():
    broken = SearchQuery(keywords="iphone 12", condition=Condition.DEFECTIVE)
    assert is_relevant(broken, _item("Hülle für iPhone 12")) is False
    assert is_relevant(broken, _item("Suche iPhone 12 defekt")) is False


# --- Edit menu ----------------------------------------------------------------------------
def _rule() -> SearchRule:
    return SearchRule(user_id=1, name="RTX", keywords="rtx 4090", sites=[])


def _callbacks(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def test_edit_menu_offers_only_dependable_conditions():
    slugs = [slug for slug, _ in CONDITION_CHOICES]
    assert slugs == ["any", "new", "used", "defective"]
    # Every offered slug must survive Condition(...) — the handler's allow-list
    # is built from exactly this list.
    assert [Condition(s) for s in slugs][0] is Condition.ANY
    assert "like_new" not in slugs and "refurbished" not in slugs


def test_choice_maps_cover_the_stored_values():
    assert set(SHIPPING_VALUES.values()) == {None, True, False}
    assert set(AUCTION_VALUES.values()) == {True, False}


def test_edit_menu_shows_the_three_filters_with_rule_power():
    data = _callbacks(rule_edit_keyboard(_rule(), "de", has_rule_power=True))
    assert any(c.startswith("edit:condition:") for c in data)
    assert any(c.startswith("edit:shipping:") for c in data)
    assert any(c.startswith("edit:auctions:") for c in data)
    assert not any(c.startswith("edit:locked:") for c in data)


def test_edit_menu_upsells_instead_of_hiding_without_rule_power():
    data = _callbacks(rule_edit_keyboard(_rule(), "de", has_rule_power=False))
    assert any(c.startswith("edit:locked:") for c in data)
    assert not any(c.startswith("edit:condition:") for c in data)
    # The rest of the menu is untouched.
    assert any(c.startswith("edit:name:") for c in data)


def test_unsaved_rule_renders_labels_without_column_defaults():
    # SQLAlchemy applies column defaults at INSERT, so a fresh rule carries
    # None in exactly the three fields the menu labels read.
    rule = _rule()
    assert rule.condition is None and rule.exclude_auctions is None
    rule_edit_keyboard(rule, "de", has_rule_power=True)
