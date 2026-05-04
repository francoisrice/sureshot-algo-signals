"""
DataFetcher microservice.

Runs as a standalone FastAPI service that strategy containers call via HTTP.
Holds one DataFetcherPool (one AsyncStagehand client + 30 pre-warmed sessions)
shared across all callers — across containers.

Run: uvicorn SureshotSDK.DataFetcher.service:app --host 0.0.0.0 --port 3100
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .pool import DataFetcherPool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_pool: DataFetcherPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = DataFetcherPool()
    await _pool.initialize()
    logger.info("DataFetcherService ready")
    yield
    await _pool.close()
    logger.info("DataFetcherService stopped")


app = FastAPI(title="DataFetcher Service", lifespan=lifespan)


@app.get("/bar/{symbol}")
async def get_bar(symbol: str):
    bar = await _pool.get_current_bar(symbol.upper())
    if bar is None:
        raise HTTPException(status_code=503, detail=f"Failed to fetch bar for {symbol}")
    return bar


@app.get("/health")
async def health():
    return {"status": "ok", "pool_size": _pool._pool_size if _pool else 0}
