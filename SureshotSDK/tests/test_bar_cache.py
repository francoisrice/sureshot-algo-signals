"""
Tests for the DataFetcher BarCache and the /bar endpoint: callers asking for the same
ticker within the TTL share one scrape, and a bar is re-scraped only once it is older than the TTL.
"""

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.DataFetcher import service
from SureshotSDK.DataFetcher.bar_cache import BarCache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class CountingScraper:
    def __init__(self, delaySeconds: float = 0.0, failSymbols: tuple = ()):
        self.callsBySymbol = {}
        self.delaySeconds = delaySeconds
        self.failSymbols = failSymbols

    async def __call__(self, symbol: str):
        self.callsBySymbol[symbol] = self.callsBySymbol.get(symbol, 0) + 1
        if self.delaySeconds:
            await asyncio.sleep(self.delaySeconds)
        if symbol in self.failSymbols:
            return None
        price = 100.0 + self.callsBySymbol[symbol]
        return {'t': self.callsBySymbol[symbol], 'o': price, 'h': price, 'l': price, 'c': price, 'v': 0}


def test_same_symbol_within_ttl_is_served_from_cache():
    clock, scraper = FakeClock(), CountingScraper()
    cache = BarCache(scraper, ttlSeconds=60, clock=clock)

    firstBar, firstFromCache = asyncio.run(cache.get_bar('TQQQ'))
    clock.now += 59.9
    secondBar, secondFromCache = asyncio.run(cache.get_bar('TQQQ'))

    assert (firstFromCache, secondFromCache) == (False, True)
    assert secondBar == firstBar
    assert scraper.callsBySymbol == {'TQQQ': 1}


def test_bar_exactly_one_minute_old_is_still_reused():
    clock, scraper = FakeClock(), CountingScraper()
    cache = BarCache(scraper, ttlSeconds=60, clock=clock)

    asyncio.run(cache.get_bar('TQQQ'))
    clock.now += 60
    _, fromCache = asyncio.run(cache.get_bar('TQQQ'))

    assert fromCache is True
    assert scraper.callsBySymbol == {'TQQQ': 1}


def test_bar_older_than_ttl_is_rescraped():
    clock, scraper = FakeClock(), CountingScraper()
    cache = BarCache(scraper, ttlSeconds=60, clock=clock)

    firstBar, _ = asyncio.run(cache.get_bar('TQQQ'))
    clock.now += 60.1
    secondBar, fromCache = asyncio.run(cache.get_bar('TQQQ'))

    assert fromCache is False
    assert secondBar['c'] != firstBar['c']
    assert scraper.callsBySymbol == {'TQQQ': 2}
    assert cache.age_seconds('TQQQ') == 0


def test_symbols_are_cached_independently():
    scraper = CountingScraper()
    cache = BarCache(scraper, ttlSeconds=60, clock=FakeClock())

    async def fetch_all():
        for symbol in ['TQQQ', 'USO', 'TQQQ', 'UCO', 'USO']:
            await cache.get_bar(symbol)

    asyncio.run(fetch_all())

    assert scraper.callsBySymbol == {'TQQQ': 1, 'USO': 1, 'UCO': 1}


def test_concurrent_requests_for_one_symbol_share_a_single_scrape():
    scraper = CountingScraper(delaySeconds=0.05)
    cache = BarCache(scraper, ttlSeconds=60)

    async def fetch_concurrently():
        return await asyncio.gather(*[cache.get_bar('TQQQ') for _ in range(5)])

    results = asyncio.run(fetch_concurrently())

    assert scraper.callsBySymbol == {'TQQQ': 1}
    assert len({bar['c'] for bar, _ in results}) == 1
    assert sorted(fromCache for _, fromCache in results) == [False, True, True, True, True]


def test_failed_scrape_is_not_cached():
    clock, scraper = FakeClock(), CountingScraper(failSymbols=('TQQQ',))
    cache = BarCache(scraper, ttlSeconds=60, clock=clock)

    firstBar, _ = asyncio.run(cache.get_bar('TQQQ'))
    secondBar, fromCache = asyncio.run(cache.get_bar('TQQQ'))

    assert firstBar is None and secondBar is None
    assert fromCache is False
    assert scraper.callsBySymbol == {'TQQQ': 2}
    assert cache.age_seconds('TQQQ') is None


def test_callers_cannot_mutate_the_cached_bar():
    cache = BarCache(CountingScraper(), ttlSeconds=60, clock=FakeClock())

    firstBar, _ = asyncio.run(cache.get_bar('TQQQ'))
    firstBar['c'] = -1
    secondBar, _ = asyncio.run(cache.get_bar('TQQQ'))

    assert secondBar['c'] == 101.0


class FakePool:
    scraper = None

    def __init__(self):
        self._pool_size = 1

    async def initialize(self):
        pass

    async def get_current_bar(self, symbol: str):
        return await FakePool.scraper(symbol)

    async def close(self):
        pass


@pytest.fixture
def serviceClient(monkeypatch):
    FakePool.scraper = CountingScraper()
    monkeypatch.setattr(service, 'DataFetcherPool', FakePool)
    with TestClient(service.app) as client:
        yield client


def test_endpoint_reuses_bar_and_reports_cache_status(serviceClient):
    firstResponse = serviceClient.get('/bar/tqqq')
    secondResponse = serviceClient.get('/bar/TQQQ')

    assert firstResponse.status_code == secondResponse.status_code == 200
    assert firstResponse.headers['X-Bar-Cache'] == 'MISS'
    assert secondResponse.headers['X-Bar-Cache'] == 'HIT'
    assert secondResponse.json() == firstResponse.json()
    assert FakePool.scraper.callsBySymbol == {'TQQQ': 1}


def test_endpoint_returns_503_when_scrape_fails(serviceClient):
    FakePool.scraper.failSymbols = ('USO',)

    response = serviceClient.get('/bar/USO')

    assert response.status_code == 503
