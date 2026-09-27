import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .LondonStrategicEdge import LondonStrategicEdgeClient
from .Polygon import PolygonClient
from .BacktestingPriceCache import BacktestingPriceCache, get_shared_cache

logger = logging.getLogger(__name__)

# PolygonClient silently maps unknown timeframe strings to '1d'; normalizing
# here keeps both providers on the caller's intended resolution
TIMEFRAME_ALIASES = {
    '1min': '1m',
    '5min': '5m',
    '15min': '15m',
    '30min': '30m',
    '60min': '1h',
}


class HistoricalDataClient:
    """
    Historical market data client with provider fallback.

    Exposes the same interface as PolygonClient / LondonStrategicEdgeClient so
    it is drop-in interchangeable with either. Historical fetches try London
    Strategic Edge first, then Polygon; local caches (BacktestingPriceCache,
    IntradayDataManager) sit above this client, giving backtests and
    optimization the order: local data -> London Strategic Edge -> Polygon.

    Historical fetches: disk cache -> London Strategic Edge -> Polygon,
    with fetched bars written back to the cache. Real-time lookups prefer
    Polygon. Pass an existing price_cache to share one cache with the caller.
    """

    def __init__(
        self,
        lse_client: Optional[LondonStrategicEdgeClient] = None,
        polygon_client: Optional[PolygonClient] = None,
        use_vault: bool = False,
        price_cache: Optional[BacktestingPriceCache] = None,
        cache_dir: str = '.price_cache'
    ):
        self.lse_client = lse_client or self._build_lse_client()
        self.polygon_client = polygon_client or self._build_polygon_client(use_vault)
        self.price_cache = price_cache or get_shared_cache(cache_dir)

        if not self.lse_client and not self.polygon_client:
            raise ValueError(
                "No market data API key found. Set LONDONSTRATEGICEDGE_API_KEY "
                "and/or POLYGON_API_KEY in the environment."
            )

        providers = [name for name, client in [
            ('LondonStrategicEdge', self.lse_client),
            ('Polygon', self.polygon_client)
        ] if client]
        logger.info(f"HistoricalDataClient initialized with providers: {', '.join(providers)}")

    @staticmethod
    def _build_lse_client() -> Optional[LondonStrategicEdgeClient]:
        if not os.getenv('LONDONSTRATEGICEDGE_API_KEY'):
            return None
        try:
            return LondonStrategicEdgeClient()
        except Exception as e:
            logger.warning(f"Could not initialize LondonStrategicEdgeClient: {e}")
            return None

    @staticmethod
    def _build_polygon_client(use_vault: bool) -> Optional[PolygonClient]:
        if not os.getenv('POLYGON_API_KEY') and not use_vault:
            return None
        try:
            return PolygonClient(use_vault=use_vault)
        except Exception as e:
            logger.warning(f"Could not initialize PolygonClient: {e}")
            return None

    def _historical_providers(self) -> List[Tuple[str, object]]:
        """Providers in historical-fetch preference order: LSE, then Polygon"""
        return [(name, client) for name, client in [
            ('LondonStrategicEdge', self.lse_client),
            ('Polygon', self.polygon_client)
        ] if client]

    def _realtime_providers(self) -> List[Tuple[str, object]]:
        """Providers in real-time preference order: Polygon, then LSE"""
        return [(name, client) for name, client in [
            ('Polygon', self.polygon_client),
            ('LondonStrategicEdge', self.lse_client)
        ] if client]

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        return TIMEFRAME_ALIASES.get(timeframe, timeframe)

    def _first_result(self, providers: List[Tuple[str, object]], method: str, *args):
        """Call method on each provider in order, returning the first usable result"""
        for providerName, client in providers:
            try:
                result = getattr(client, method)(*args)
                if result:
                    return result
                logger.debug(f"{providerName}.{method} returned no data, trying next provider")
            except Exception as e:
                logger.warning(f"{providerName}.{method} failed ({e}), trying next provider")
        return None

    def _fetch_from_providers(self,
                              symbol: str,
                              start_date: datetime,
                              end_date: datetime,
                              timeframe: str) -> List[Dict]:
        data = self._first_result(
            self._historical_providers(), 'get_historical_data',
            symbol, start_date, end_date, timeframe
        )
        return data if data else []

    def get_historical_data(self,
                            symbol: str,
                            start_date: datetime,
                            end_date: datetime,
                            timeframe: str = '1d') -> List[Dict]:
        """
        Fetch historical OHLCV bars: disk cache first, then London Strategic
        Edge, then Polygon. Remote fetches (including cache range extensions)
        are written back to the disk cache when caching is enabled.

        Returns:
            List of Polygon-format bars: {'t', 'o', 'h', 'l', 'c', 'v'}
        """
        timeframe = self._normalize_timeframe(timeframe)

        cachedData = self.price_cache.get(
            symbol, start_date, end_date, timeframe,
            fetch_fn=self._fetch_from_providers
        )
        if cachedData:
            return cachedData

        data = self._fetch_from_providers(symbol, start_date, end_date, timeframe)

        if data:
            self.price_cache.set(symbol, start_date, end_date, timeframe, data)

        return data

    def get_ohlcv_data(self,
                       symbol: str,
                       start_date: datetime,
                       end_date: datetime,
                       timeframe: str = '1d') -> List[Tuple[datetime, float, float, float, float, int]]:
        """Get OHLCV data as (timestamp, open, high, low, close, volume) tuples"""
        rawData = self.get_historical_data(symbol, start_date, end_date, timeframe)

        formattedData = []
        for item in rawData:
            formattedData.append((
                datetime.fromtimestamp(item['t'] / 1000),
                float(item['o']),
                float(item['h']),
                float(item['l']),
                float(item['c']),
                int(item['v'])
            ))
        return formattedData

    def get_close_prices(self,
                         symbol: str,
                         start_date: datetime,
                         end_date: datetime,
                         timeframe: str = '1d') -> List[float]:
        """Get only close prices for a symbol"""
        rawData = self.get_historical_data(symbol, start_date, end_date, timeframe)
        return [float(item['c']) for item in rawData if 'c' in item]

    def get_single_day_price(self, symbol: str, date: datetime) -> Optional[float]:
        """Get the daily close price for a symbol on a specific date"""
        return self._first_result(
            self._historical_providers(), 'get_single_day_price', symbol, date
        )

    def get_historical_price(self, symbol: str, currentDate: datetime, timeframe: str = '1m') -> Optional[float]:
        """Get the price at (or just before) a historical datetime"""
        timeframe = self._normalize_timeframe(timeframe)
        return self._first_result(
            self._historical_providers(), 'get_historical_price',
            symbol, currentDate, timeframe
        )

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the current price, preferring Polygon's live trade feed"""
        return self._first_result(self._realtime_providers(), 'get_current_price', symbol)

    def get_last_quote(self, symbol: str) -> Optional[Dict]:
        """Get the last NBBO quote (Polygon only; LSE returns None)"""
        return self._first_result(self._realtime_providers(), 'get_last_quote', symbol)

    def is_market_open(self) -> bool:
        """Check whether the US equity market is currently open"""
        for providerName, client in self._realtime_providers():
            try:
                return client.is_market_open()
            except Exception as e:
                logger.warning(f"{providerName}.is_market_open failed ({e}), trying next provider")

        now = datetime.now()
        if now.weekday() >= 5:
            return False
        return 9 <= now.hour < 16
