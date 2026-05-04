import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

from stagehand import AsyncStagehand

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "google/gemini-3-flash-preview"


class DataFetcherPool:
    """
    Async session pool for real-time price fetching via Stagehand + Browserbase.

    Maintains pool_size pre-warmed sessions. Callers beyond that concurrency
    limit are suspended by asyncio.Queue.get() until a session is returned.

    On session failure the broken session is ended and replaced so the pool
    never permanently shrinks below pool_size.
    """

    def __init__(self, pool_size: int | None = None, model: str = _DEFAULT_MODEL):
        pool_size = pool_size or int(os.environ.get("DATAFETCHER_POOL_SIZE", "3"))
        self._api_key = os.environ["BROWSERBASE_API_KEY"]
        self._project_id = os.environ["BROWSERBASE_PROJECT_ID"]
        self._pool_size = pool_size
        self._model = model
        # One shared client — Stagehand manages its own HTTP connection pool internally.
        # Do not create more than one client per application.
        self._client = AsyncStagehand(browserbase_api_key=self._api_key)
        self._session_pool: asyncio.Queue[str] = asyncio.Queue()

    async def initialize(self, batch_size: int = 3) -> None:
        """Pre-warm sessions in batches of 3 to respect API rate limits."""
        for i in range(0, self._pool_size, batch_size):
            batch = range(i, min(i + batch_size, self._pool_size))
            session_ids = await asyncio.gather(*[self._create_session() for _ in batch])
            for sid in session_ids:
                await self._session_pool.put(sid)
            logger.info(f"DataFetcherPool: {self._session_pool.qsize()}/{self._pool_size} sessions ready")
            if i + batch_size < self._pool_size:
                await asyncio.sleep(1)
        logger.info(f"DataFetcherPool fully initialized: {self._pool_size} sessions")

    async def _create_session(self) -> str:
        response = await self._client.sessions.start(model_name=self._model)
        return response.data.session_id

    async def get_current_bar(self, symbol: str) -> Optional[dict]:
        """
        Fetch real-time price for symbol from NASDAQ using Stagehand AI extraction.

        Returns bar dict {t, o, h, l, c, v} or None on failure.
        Acquires a pooled session and releases it in the finally block.
        """
        session_id = await self._session_pool.get()
        replacement = session_id
        try:
            url = f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}"
            await self._client.sessions.navigate(id=session_id, url=url)

            result = await self._client.sessions.extract(
                id=session_id,
                instruction="extract the price",
            )

            if not result:
                logger.warning(f"No extraction result for {symbol}")
                return None

            if "extraction" in result.data.result:
                raw = result.data.result.get("extraction")
            else:
                raw = json.loads(result.data.result)
                raw = raw["extraction"]

            price = float(raw.replace("$", ""))

            now_ms = int(datetime.now().timestamp() * 1000)
            return {"t": now_ms, "o": price, "h": price, "l": price, "c": price, "v": 0}

        except Exception as e:
            logger.error(f"get_current_bar('{symbol}') failed: {e} — replacing session")
            try:
                await self._client.sessions.end(id=session_id)
            except Exception:
                pass
            replacement = await self._create_session()
            return None

        finally:
            await self._session_pool.put(replacement)

    async def close(self) -> None:
        """End all pooled sessions."""
        while not self._session_pool.empty():
            try:
                sid = self._session_pool.get_nowait()
                await self._client.sessions.end(id=sid)
            except Exception:
                pass
        logger.info("DataFetcherPool closed")
