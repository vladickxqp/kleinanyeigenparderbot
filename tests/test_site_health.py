"""Per-site failure tracking: backoff, "down", and the probe that brings a site back.

The old design had one fleet-wide switch: any site under block backoff
stretched EVERY interval on EVERY site by ×3. eBay refuses every scrape with a
403, so a marketplace that never delivered anything slowed the ones that did —
for exactly the paying users who were sold speed. And a dead site kept costing
a request per rule run, forever, because nothing ever took it out.

These tests pin down the replacement: backoff and "down" are per site, a rule
that never touches the blocked site is not slowed, a site that is down leaves
the rotation and is probed instead, and a probe that succeeds brings it back.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.config.settings import settings
from app.database.models.enums import SiteName
from app.services import health


class FakeRedis:
    """The string commands health.py uses, in memory, with TTLs remembered."""

    def __init__(self, *, broken: bool = False) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}
        self.broken = broken

    def _check(self) -> None:
        if self.broken:
            raise ConnectionError("redis is down")

    async def set(self, key, value, nx=False, ex=None):  # noqa: ANN001
        self._check()
        if nx and key in self.data:
            return None
        self.data[key] = str(value)
        if ex is not None:
            self.ttl[key] = ex
        return True

    async def get(self, key):  # noqa: ANN001
        self._check()
        return self.data.get(key)

    async def delete(self, *keys):  # noqa: ANN001
        self._check()
        removed = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                self.ttl.pop(key, None)
                removed += 1
        return removed

    async def incr(self, key):  # noqa: ANN001
        self._check()
        self.data[key] = str(int(self.data.get(key, "0")) + 1)
        return int(self.data[key])

    async def expire(self, key, ttl):  # noqa: ANN001
        self._check()
        self.ttl[key] = ttl

    async def keys(self, pattern):  # noqa: ANN001
        self._check()
        prefix = pattern.rstrip("*")
        return [key for key in self.data if key.startswith(prefix)]

    async def rpush(self, key, value):  # noqa: ANN001
        self._check()
        self.lists.setdefault(key, []).append(str(value))

    async def aclose(self) -> None:
        return None

    # --- test helpers -----------------------------------------------------
    @property
    def alerts(self) -> list[str]:
        return self.lists.get(health.ALERT_QUEUE, [])


@pytest.fixture()
def redis(monkeypatch):
    client = FakeRedis()

    @asynccontextmanager
    async def _redis():
        yield client

    monkeypatch.setattr(health, "_redis", _redis)
    monkeypatch.setattr(settings, "block_backoff_enabled", True)
    monkeypatch.setattr(settings, "block_backoff_multiplier", 3.0)
    return client


def fail(site: str, times: int) -> None:
    async def run():
        for _ in range(times):
            await health.record_parser_result(site, ok=False)

    asyncio.run(run())


# --- Backoff is per site ------------------------------------------------------------
def test_a_blocked_site_slows_only_the_rules_that_touch_it(redis):
    fail("ebay", health.FAIL_THRESHOLD)
    backed = asyncio.run(health.backed_off_sites())
    assert backed == {"ebay"}

    # The rule that searches Kleinanzeigen only keeps its speed.
    assert health.multiplier_for([SiteName.KLEINANZEIGEN], backed) == 1.0
    # The one that includes eBay is slowed — that is the point of backoff.
    assert health.multiplier_for([SiteName.KLEINANZEIGEN, SiteName.EBAY], backed) == 3.0
    # Slugs and enum members are both accepted.
    assert health.multiplier_for(["ebay"], backed) == 3.0


def test_nothing_backed_off_means_full_speed_for_everyone(redis):
    assert health.multiplier_for([SiteName.EBAY], set()) == 1.0
    assert asyncio.run(health.block_multiplier([SiteName.EBAY])) == 1.0


def test_backoff_fires_at_the_threshold_and_names_the_site(redis):
    fail("ebay", health.FAIL_THRESHOLD - 1)
    assert asyncio.run(health.backed_off_sites()) == set()
    assert redis.alerts == []

    fail("ebay", 1)
    assert asyncio.run(health.backed_off_sites()) == {"ebay"}
    assert len(redis.alerts) == 1
    assert "ebay" in redis.alerts[0]
    # The old text promised "alle Intervalle" — that is exactly what no longer happens.
    assert "Alle Intervalle" not in redis.alerts[0]


def test_backoff_is_switched_off_by_settings(redis, monkeypatch):
    monkeypatch.setattr(settings, "block_backoff_enabled", False)
    fail("ebay", health.FAIL_THRESHOLD)
    assert asyncio.run(health.backed_off_sites()) == set()


# --- A site that keeps failing goes down ------------------------------------------
def test_a_site_that_keeps_failing_leaves_the_rotation(redis):
    fail("ebay", health.DOWN_THRESHOLD - 1)
    assert asyncio.run(health.down_sites()) == set()

    fail("ebay", 1)
    assert asyncio.run(health.down_sites()) == {"ebay"}
    # Two alerts in total: the backoff one and the "down" one — not one per failure.
    assert len(redis.alerts) == 2
    assert "Rotation" in redis.alerts[1]


def test_a_down_site_is_reported_once_a_day_not_once_per_run(redis):
    fail("ebay", health.DOWN_THRESHOLD + 50)
    down_alerts = [a for a in redis.alerts if "Rotation" in a]
    assert len(down_alerts) == 1


def test_a_down_site_is_probed_once_per_interval_not_every_run(redis):
    fail("ebay", health.DOWN_THRESHOLD)
    first = asyncio.run(health.should_probe("ebay"))
    second = asyncio.run(health.should_probe("ebay"))
    assert (first, second) == (True, False)
    assert redis.ttl["health:probe:ebay"] == health.PROBE_INTERVAL_SECONDS


def test_a_successful_probe_brings_the_site_back_and_says_so(redis):
    fail("ebay", health.DOWN_THRESHOLD)
    assert asyncio.run(health.down_sites()) == {"ebay"}

    asyncio.run(health.record_parser_result("ebay", ok=True))
    assert asyncio.run(health.down_sites()) == set()
    assert asyncio.run(health.backed_off_sites()) == set()
    assert any("antwortet wieder" in a for a in redis.alerts)
    # And the counter is gone, so the next hiccup starts from zero.
    assert "health:fail:ebay" not in redis.data


def test_a_success_on_a_healthy_site_is_quiet(redis):
    asyncio.run(health.record_parser_result("kleinanzeigen", ok=True))
    assert redis.alerts == []


def test_other_sites_are_untouched_by_one_going_down(redis):
    fail("ebay", health.DOWN_THRESHOLD)
    assert asyncio.run(health.down_sites()) == {"ebay"}
    assert "kleinanzeigen" not in asyncio.run(health.backed_off_sites())
    assert health.multiplier_for([SiteName.KLEINANZEIGEN], asyncio.run(health.backed_off_sites())) == 1.0


# --- Redis trouble never breaks a search ------------------------------------------
def test_without_redis_everything_fails_open(monkeypatch):
    broken = FakeRedis(broken=True)

    @asynccontextmanager
    async def _redis():
        yield broken

    monkeypatch.setattr(health, "_redis", _redis)
    monkeypatch.setattr(settings, "block_backoff_enabled", True)

    asyncio.run(health.record_parser_result("ebay", ok=False))  # no raise
    assert asyncio.run(health.backed_off_sites()) == set()
    assert asyncio.run(health.down_sites()) == set()
    # Nobody can coordinate a probe without Redis, so the site is simply searched.
    assert asyncio.run(health.should_probe("ebay")) is True
