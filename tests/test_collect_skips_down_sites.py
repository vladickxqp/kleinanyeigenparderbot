"""A site that is down is probed, not searched.

Every rule run used to hit every resolved site, including one that had
refused the last hundred requests. That was budget the working sites could
have used, spent on a page that never answers. Now a down site gets one request
per probe interval across the whole fleet; the rest of the runs skip it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.database.models.enums import SiteName
from app.services import health
from app.services import search_service as svc


class StubParser:
    def __init__(self, site: SiteName) -> None:
        self.site = site
        self.calls = 0

    async def collect(self, query):  # noqa: ANN001
        self.calls += 1
        return [SimpleNamespace(site=self.site, external_id=f"{self.site.value}-1")]


@pytest.fixture()
def parsers(monkeypatch):
    kl = StubParser(SiteName.KLEINANZEIGEN)
    eb = StubParser(SiteName.EBAY)
    monkeypatch.setattr(svc.registry, "resolve", lambda sites: [kl, eb])
    monkeypatch.setattr(svc.site_access, "resolve", lambda chosen, user=None: [kl.site, eb.site])
    return kl, eb


class _Session:
    async def get(self, model, pk):  # noqa: ANN001
        return None


def _collect(parsers_down: set[str], probe: bool):
    async def down_sites():
        return parsers_down

    async def should_probe(site):  # noqa: ANN001
        return probe

    service = svc.SearchService(_Session())  # type: ignore[arg-type]
    rule = SimpleNamespace(id=1, user_id=1, sites=[])
    return service, rule, down_sites, should_probe


def test_a_healthy_fleet_searches_every_site(parsers, monkeypatch):
    kl, eb = parsers
    service, rule, down, probe = _collect(set(), probe=False)
    monkeypatch.setattr(health, "down_sites", down)
    monkeypatch.setattr(health, "should_probe", probe)

    found = asyncio.run(service._collect(rule, query=None))
    assert (kl.calls, eb.calls) == (1, 1)
    assert len(found) == 2


def test_a_down_site_is_skipped_between_probes(parsers, monkeypatch):
    kl, eb = parsers
    service, rule, down, probe = _collect({"ebay"}, probe=False)
    monkeypatch.setattr(health, "down_sites", down)
    monkeypatch.setattr(health, "should_probe", probe)

    found = asyncio.run(service._collect(rule, query=None))
    # Kleinanzeigen ran as always; eBay did not cost a request.
    assert (kl.calls, eb.calls) == (1, 0)
    assert [item.site for item in found] == [SiteName.KLEINANZEIGEN]


def test_the_probe_run_still_asks_the_down_site(parsers, monkeypatch):
    kl, eb = parsers
    service, rule, down, probe = _collect({"ebay"}, probe=True)
    monkeypatch.setattr(health, "down_sites", down)
    monkeypatch.setattr(health, "should_probe", probe)

    asyncio.run(service._collect(rule, query=None))
    # This is the request that notices when the site is back.
    assert (kl.calls, eb.calls) == (1, 1)


def test_a_rule_whose_only_site_is_down_returns_nothing_quietly(parsers, monkeypatch):
    kl, eb = parsers
    monkeypatch.setattr(svc.registry, "resolve", lambda sites: [eb])
    service, rule, down, probe = _collect({"ebay"}, probe=False)
    monkeypatch.setattr(health, "down_sites", down)
    monkeypatch.setattr(health, "should_probe", probe)

    assert asyncio.run(service._collect(rule, query=None)) == []
    assert eb.calls == 0
