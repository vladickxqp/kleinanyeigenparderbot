"""Tests for AI availability/fallback and the parser registry."""

from __future__ import annotations

from app.config.settings import settings
from app.database.models.enums import DealVerdict, SiteName
from app.parsers import registry
from app.services import ai
from app.services.ai import AIScore, _parse_response


def test_registry_has_registered_parsers():
    sites = registry.available_sites
    assert SiteName.KLEINANZEIGEN in sites
    assert SiteName.EBAY in sites
    assert SiteName.IDEALO in sites


def test_registry_resolve_all_when_empty():
    assert len(registry.resolve([])) == len(registry)
    assert len(registry.resolve([SiteName.EBAY])) == 1


def test_flagged_parser_stays_out_of_the_all_sites_fallback():
    """A rule with ``sites=[]`` runs on EVERY registered parser.

    That is why Vinted registers itself only behind ``VINTED_ENABLED``: an
    unconditional registration would put an unverified parser in front of every
    existing user on the next deploy, because every rule resolves to "all".
    """
    registered = SiteName.VINTED in registry.available_sites
    assert registered is settings.vinted_enabled
    if not settings.vinted_enabled:
        assert registry.resolve([SiteName.VINTED]) == []
        assert all(p.site is not SiteName.VINTED for p in registry.resolve([]))


def test_ai_disabled_by_default(monkeypatch):
    # With default settings (AI_ENABLED false), AI must report unavailable.
    monkeypatch.setattr(ai.settings, "ai_enabled", False, raising=False)
    assert ai.is_available() is False


def test_ai_parse_valid_json():
    raw = (
        '{"score": 88, "verdict": "great", "resale_probability": 0.7, '
        '"estimated_profit_eur": 250, "reasoning": "well below market"}'
    )
    result = _parse_response(raw)
    assert isinstance(result, AIScore)
    assert result.score == 88
    assert result.verdict is DealVerdict.GREAT


def test_ai_parse_handles_code_fence():
    raw = '```json\n{"score": 50, "verdict": "fair", "resale_probability": 0.1, ' \
          '"estimated_profit_eur": 0, "reasoning": "x"}\n```'
    result = _parse_response(raw)
    assert result is not None
    assert result.verdict is DealVerdict.FAIR


def test_ai_parse_rejects_garbage():
    assert _parse_response("not json at all") is None
