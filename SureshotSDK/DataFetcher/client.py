import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class DataFetcherClient:
    """
    HTTP client for the DataFetcher microservice.

    Strategy containers use this to fetch real-time price bars.
    The microservice holds the shared Stagehand session pool (pool_size=30)
    so all containers draw from one set of pre-warmed browser sessions.

    Blocks until the bar is returned (synchronous by design — callers should
    not proceed with strategy logic until the price is confirmed).
    """

    def __init__(self, service_url: str | None = None):
        base = service_url or os.environ.get("DATA_FETCHER_URL", "http://localhost:3100")
        self._url = base.rstrip("/")
        self._session = requests.Session()

    def get_current_bar(self, symbol: str) -> Optional[dict]:
        """
        Fetch real-time price bar from the DataFetcher service.
        Returns bar dict {t, o, h, l, c, v} or None on failure.
        """
        try:
            resp = self._session.get(f"{self._url}/bar/{symbol}", timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"DataFetcherClient.get_current_bar('{symbol}') failed: {e}")
            return None

    def close(self) -> None:
        self._session.close()
