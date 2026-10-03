import os
import logging
import threading
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .Polygon import PolygonClient
from .MarketDataStore import MarketDataStore, get_shared_store, is_store_timeframe

logger = logging.getLogger(__name__)

# PolygonClient silently maps unknown timeframe strings to '1d'; normalizing
# here keeps requests on the caller's intended resolution
TIMEFRAME_ALIASES = {
    '1min': '1m',
    '5min': '5m',
    '15min': '15m',
    '30min': '30m',
    '60min': '1h',
}

# Provider splits newer than the archive's table are refetched with this much overlap
SPLITS_REFRESH_OVERLAP_DAYS = 30

_splitsRefreshAttempted = False
_splitsRefreshLock = threading.Lock()


class HistoricalDataClient:
    """
    Historical market data client with the same interface as PolygonClient.

    Where the shared data store exists (DATA_ROOT, default ../data beside this repo),
    historical bars come from the sureshot-marketdata archive, and sessions after it
    are filled from Polygon (the archive's own vendor) and written back unadjusted.
    Without it (e.g. live pods), bars come straight from Polygon. London Strategic
    Edge is deliberately not a source: its bars don't match the consolidated tape.
    """

    def __init__(
        self,
        polygon_client: Optional[PolygonClient] = None,
        use_vault: bool = False,
        market_store: Optional[MarketDataStore] = None,
        data_root: Optional[str] = None,
        use_market_store: bool = True
    ):
        self.polygon_client = polygon_client or self._build_polygon_client(use_vault)
        self.market_store = (market_store or get_shared_store(data_root)) if use_market_store else None

        if not self.polygon_client and not self.market_store:
            raise ValueError(
                "No market data source found. Set POLYGON_API_KEY in the environment, "
                "or DATA_ROOT to the shared data store."
            )

        sources = [name for name, source in [
            ('MarketDataStore', self.market_store),
            ('Polygon', self.polygon_client)
        ] if source]
        logger.info(f"HistoricalDataClient initialized with sources: {', '.join(sources)}")

    @staticmethod
    def _build_polygon_client(use_vault: bool) -> Optional[PolygonClient]:
        if not os.getenv('POLYGON_API_KEY') and not use_vault:
            return None
        try:
            return PolygonClient(use_vault=use_vault)
        except Exception as e:
            logger.warning(f"Could not initialize PolygonClient: {e}")
            return None

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        return TIMEFRAME_ALIASES.get(timeframe, timeframe)

    def _uses_store(self, timeframe: str) -> bool:
        return self.market_store is not None and is_store_timeframe(timeframe)

    def _call_polygon(self, method: str, *args):
        if not self.polygon_client:
            return None
        try:
            return getattr(self.polygon_client, method)(*args)
        except Exception as e:
            logger.warning(f"Polygon.{method} failed: {e}")
            return None

    def _fetch_unadjusted(self,
                          symbol: str,
                          start_date: datetime,
                          end_date: datetime,
                          timeframe: str) -> List[Dict]:
        """MarketDataStore gap-fill callback for one symbol's raw bars"""
        self._refresh_splits_once()
        bars = self._call_polygon('get_unadjusted_historical_data', symbol, start_date, end_date, timeframe) or []
        if bars:
            logger.info(f"Filled {symbol} {timeframe} {start_date.date()}..{end_date.date()} from Polygon")
        return [{**bar, 'src': 'polygon'} for bar in bars]

    def _fetch_market_day(self, session_date: date) -> Optional[List[Dict]]:
        """MarketDataStore gap-fill callback for every ticker's raw daily bar on one session"""
        self._refresh_splits_once()
        bars = self._call_polygon('get_unadjusted_grouped_daily', datetime.combine(session_date, datetime.min.time()))
        if bars is None:
            return None
        return [{**bar, 'src': 'polygon'} for bar in bars]

    def _refresh_splits_once(self):
        """Keep the split table current before storing post-archive bars; once per process and day"""
        global _splitsRefreshAttempted
        with _splitsRefreshLock:
            if _splitsRefreshAttempted or not self.polygon_client or self.market_store.splits_refreshed_today():
                return
            _splitsRefreshAttempted = True
            archiveLast = self.market_store.archive_last_date('1d') or datetime.now().date()
            since = datetime.combine(archiveLast, datetime.min.time()) - timedelta(days=SPLITS_REFRESH_OVERLAP_DAYS)
            splits = self._call_polygon('get_splits', since)
            if splits:
                self.market_store.save_splits(splits)
                logger.info(f"Refreshed {len(splits)} split events since {since.date()}")

    def get_historical_data(self,
                            symbol: str,
                            start_date: datetime,
                            end_date: datetime,
                            timeframe: str = '1d') -> List[Dict]:
        """
        Fetch split-adjusted historical OHLCV bars from the shared data store (filling
        sessions after the archive from Polygon), else straight from Polygon.

        Returns:
            List of Polygon-format bars: {'t', 'o', 'h', 'l', 'c', 'v', 'n'}
        """
        timeframe = self._normalize_timeframe(timeframe)
        if self._uses_store(timeframe):
            hasPolygon = self.polygon_client is not None
            return self.market_store.get(
                symbol, start_date, end_date, timeframe,
                fetch_fn=self._fetch_unadjusted if hasPolygon else None,
                fetch_market_day_fn=self._fetch_market_day if hasPolygon else None
            )
        return self._call_polygon('get_historical_data', symbol, start_date, end_date, timeframe) or []

    def preload_daily(self, symbols: List[str]):
        """Warm many symbols' daily history in a few batched reads; a no-op without a data store"""
        if self.market_store:
            self.market_store.preload_daily(symbols)

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
        if self._uses_store('1d'):
            dayStart = datetime(date.year, date.month, date.day)
            bars = self.get_historical_data(symbol, dayStart, dayStart, '1d')
            return float(bars[-1]['c']) if bars else None
        return self._call_polygon('get_single_day_price', symbol, date)

    def get_historical_price(self, symbol: str, currentDate: datetime, timeframe: str = '1m') -> Optional[float]:
        """Get the price at (or just before) a historical datetime, falling back to the prior week's last daily close"""
        timeframe = self._normalize_timeframe(timeframe)
        if self._uses_store(timeframe):
            bars = self.get_historical_data(symbol, currentDate - timedelta(minutes=1), currentDate, timeframe)
            if bars:
                return float(bars[-1]['c'])
            dailyBars = self.get_historical_data(symbol, currentDate - timedelta(weeks=1), currentDate, '1d')
            return float(dailyBars[-1]['c']) if dailyBars else None
        return self._call_polygon('get_historical_price', symbol, currentDate, timeframe)

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the current price from Polygon's live trade feed"""
        return self._call_polygon('get_current_price', symbol)

    def get_last_quote(self, symbol: str) -> Optional[Dict]:
        """Get the last NBBO quote from Polygon"""
        return self._call_polygon('get_last_quote', symbol)

    def is_market_open(self) -> bool:
        """Check whether the US equity market is currently open"""
        if self.polygon_client:
            try:
                return self.polygon_client.is_market_open()
            except Exception as e:
                logger.warning(f"Polygon.is_market_open failed ({e}), using the clock")

        now = datetime.now()
        if now.weekday() >= 5:
            return False
        return 9 <= now.hour < 16
