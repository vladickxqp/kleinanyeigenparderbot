"""The language picker promises four languages — these keep that promise."""

from __future__ import annotations

import re

from app.bot.formatting import format_deal_card, verdict_badge
from app.bot.texts import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, _TEXTS, t
from app.database.models import Listing, SiteName
from app.database.models.enums import DealVerdict


def test_every_key_exists_in_every_language():
    missing = [
        f"{key}:{lang}"
        for key, entry in _TEXTS.items()
        for lang in SUPPORTED_LANGUAGES
        if not entry.get(lang)
    ]
    assert missing == []


def test_placeholders_match_across_languages():
    """A translation that loses a placeholder would render a broken message."""
    pattern = re.compile(r"\{(\w+)\}")
    for key, entry in _TEXTS.items():
        expected = set(pattern.findall(entry[DEFAULT_LANGUAGE]))
        for lang in SUPPORTED_LANGUAGES:
            assert set(pattern.findall(entry[lang])) == expected, f"{key}/{lang}"


def test_unknown_key_and_language_degrade_gracefully():
    assert t("does.not.exist", "en") == "does.not.exist"
    assert t("card.auction", "fr") == t("card.auction", DEFAULT_LANGUAGE)
    assert t("card.auction", None) == t("card.auction", DEFAULT_LANGUAGE)


def _listing() -> Listing:
    return Listing(
        rule_id=1,
        site=SiteName.KLEINANZEIGEN,
        external_id="1",
        fingerprint="f",
        title="PS5 Slim",
        url="https://example.test/1",
        price=200.0,
        currency="EUR",
        original_price=260.0,
        estimated_market_price=300.0,
        discount_percent=33.0,
        deal_score=88,
        deal_verdict=DealVerdict.STEAL,
        shipping_cost=0.0,
        is_negotiable=True,
        is_auction=True,
    )


def test_deal_card_is_translated():
    """The card is the most-seen text in the product; it must follow the user."""
    listing = _listing()
    german = format_deal_card(listing, "de")
    english = format_deal_card(listing, "en")
    russian = format_deal_card(listing, "ru")

    assert "Marktpreis" in german and "Versand möglich" in german
    assert "Market price" in english and "Shipping available" in english
    assert "Рыночная цена" in russian and "Есть доставка" in russian

    # Structure stays identical in every language.
    for card in (german, english, russian):
        assert "88/100" in card
        assert 'href="https://example.test/1"' in card
        assert card.count("\n") == german.count("\n")


def test_verdict_badges_exist_for_every_verdict_and_language():
    for verdict in DealVerdict:
        for lang in SUPPORTED_LANGUAGES:
            badge = verdict_badge(verdict, lang)
            assert badge and badge != f"card.verdict.{verdict.value}"
