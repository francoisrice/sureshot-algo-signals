"""
DataFetcher microservice.

Runs as a standalone FastAPI service that strategy containers call via HTTP.
Holds one DataFetcherPool (one AsyncStagehand client + pre-warmed sessions)
behind a BarCache, so every caller asking for a ticker within the TTL
(DATAFETCHER_CACHE_TTL_SECONDS, default 60) gets the same bar.

Run: uvicorn SureshotSDK.DataFetcher.service:app --host 0.0.0.0 --port 3100
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response

from .bar_cache import DEFAULT_TTL_SECONDS, BarCache
from .pool import DataFetcherPool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_pool: DataFetcherPool | None = None
_barCache: BarCache | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _barCache
    _pool = DataFetcherPool()
    await _pool.initialize()
    cacheTtlSeconds = float(os.environ.get("DATAFETCHER_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS))
    _barCache = BarCache(_pool.get_current_bar, ttlSeconds=cacheTtlSeconds)
    logger.info(f"DataFetcherService ready (bar cache TTL {cacheTtlSeconds:.0f}s)")
    yield
    await _pool.close()
    logger.info("DataFetcherService stopped")


app = FastAPI(title="DataFetcher Service", lifespan=lifespan)


@app.get("/bar/{symbol}")
async def get_bar(symbol: str, response: Response):
    symbol = symbol.upper()
    bar, servedFromCache = await _barCache.get_bar(symbol)
    if bar is None:
        raise HTTPException(status_code=503, detail=f"Failed to fetch bar for {symbol}")

    cacheStatus = "HIT" if servedFromCache else "MISS"
    ageSeconds = _barCache.age_seconds(symbol)
    response.headers["X-Bar-Cache"] = cacheStatus
    response.headers["X-Bar-Age-Seconds"] = f"{ageSeconds:.1f}"
    logger.info(f"bar {symbol} {cacheStatus} age={ageSeconds:.1f}s close={bar['c']}")
    return bar


@app.get("/health")
async def health():
    return {"status": "ok", "pool_size": _pool._pool_size if _pool else 0}
