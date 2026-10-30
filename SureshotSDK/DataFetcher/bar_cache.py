import asyncio
import time
from typing import Awaitable, Callable, Optional

DEFAULT_TTL_SECONDS = 60.0


class BarCache:
    """
    Per-symbol cache in front of the scraper so every strategy and portfolio
    asking for the same ticker within ttlSeconds gets the same bar.

    Concurrent misses for one symbol share a single scrape; failures are not cached.
    """

    def __init__(
        self,
        fetch_bar: Callable[[str], Awaitable[Optional[dict]]],
        ttlSeconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._fetchBar = fetch_bar
        self._ttlSeconds = ttlSeconds
        self._clock = clock
        self._barsBySymbol: dict[str, tuple[dict, float]] = {}
        self._fetchLocksBySymbol: dict[str, asyncio.Lock] = {}

    def age_seconds(self, symbol: str) -> Optional[float]:
        cachedEntry = self._barsBySymbol.get(symbol)
        if cachedEntry is None:
            return None
        return self._clock() - cachedEntry[1]

    def _fresh_bar(self, symbol: str) -> Optional[dict]:
        ageSeconds = self.age_seconds(symbol)
        if ageSeconds is None or ageSeconds > self._ttlSeconds:
            return None
        return dict(self._barsBySymbol[symbol][0])

    async def get_bar(self, symbol: str) -> tuple[Optional[dict], bool]:
        """Returns (bar, servedFromCache). bar is None only when a fresh scrape failed."""
        cachedBar = self._fresh_bar(symbol)
        if cachedBar is not None:
            return cachedBar, True

        fetchLock = self._fetchLocksBySymbol.setdefault(symbol, asyncio.Lock())
        async with fetchLock:
            # Another caller may have refreshed this symbol while we waited for the lock
            cachedBar = self._fresh_bar(symbol)
            if cachedBar is not None:
                return cachedBar, True

            fetchedBar = await self._fetchBar(symbol)
            if fetchedBar is None:
                return None, False
            self._barsBySymbol[symbol] = (fetchedBar, self._clock())
            return dict(fetchedBar), False
