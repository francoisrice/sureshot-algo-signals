import requests
import os
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LondonStrategicEdgeClient:
    """
    London Strategic Edge (LSE) vault API client for historical market data.

    Returns bars normalized to the same format as PolygonClient
    ({'t': epoch_ms, 'o', 'h', 'l', 'c', 'v'}) so the two clients are
    interchangeable for backtesting and optimization.

    API behavior (verified against the live API):
    - Auth: 'x-api-key' request header
    - /candles params: symbol, timeframe, start, end, order, limit (max 5000)
    - start/end filter bar time as [start, end) - start inclusive, end EXCLUSIVE
    - Bar timestamps ('ts') are UTC wall-time strings "YYYY-MM-DD HH:MM:SS[.ffffff]";
      daily bars are stamped 00:00 UTC and get re-anchored to local midnight to
      match Polygon's convention
    - Rate limits: 200 calls/min, 5000 rows/request (paginated automatically)
    """

    BASE_URL = "https://api.londonstrategicedge.com/vault"
    # The CDN in front of the API blocks default library User-Agents
    USER_AGENT = "sureshot-algo-signals (+https://londonstrategicedge.com)"
    MAX_ROWS_PER_REQUEST = 5000
    DAILY_TIMEFRAMES = {'1d', '1w', '1mo'}

    TIMEFRAME_MAP = {
        '1min': '1m',
        '5min': '5m',
        '15min': '15m',
        '30min': '30m',
        '1m': '1m',
        '3m': '3m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '1h': '1h',
        '4h': '4h',
        '1d': '1d',
        '1w': '1w',
        '1mo': '1mo',
        '1s': '1s',
        '5s': '5s',
        '15s': '15s',
        '30s': '30s',
    }

    def __init__(self, api_key: Optional[str] = None, use_vault: bool = False):
        """
        Initialize London Strategic Edge client.
        Signature mirrors PolygonClient so the two are drop-in interchangeable;
        use_vault is accepted for compatibility but LSE keys are env/arg only.

        Args:
            api_key: LSE API key. If None, read from LONDONSTRATEGICEDGE_API_KEY
            use_vault: Ignored (PolygonClient signature compatibility)
        """
        self.api_key = api_key or os.getenv('LONDONSTRATEGICEDGE_API_KEY')

        if not self.api_key:
            raise ValueError(
                "LONDONSTRATEGICEDGE_API_KEY not found. Provide via:\n"
                "  1. Constructor argument: LondonStrategicEdgeClient(api_key='...')\n"
                "  2. Environment variable: LONDONSTRATEGICEDGE_API_KEY"
            )

        self.base_url = self.BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': self.api_key,
            'User-Agent': self.USER_AGENT,
        })
        self.lastRequestTime = 0
        self.minRequestInterval = 0.3  # 200 calls/min cap

    def _rate_limit(self):
        """Ensure we don't exceed API rate limits"""
        timeSinceLastRequest = time.time() - self.lastRequestTime
        if timeSinceLastRequest < self.minRequestInterval:
            sleepTime = self.minRequestInterval - timeSinceLastRequest
            logger.debug(f"Rate limiting: sleeping for {sleepTime:.3f}s")
            time.sleep(sleepTime)
        self.lastRequestTime = time.time()

    def _request_rows(self, path: str, params: Dict) -> List[Dict]:
        """
        GET a vault endpoint and return the JSON row list.
        Retries once on HTTP 429 (per-minute rate limit window).
        Raises requests.RequestException on failure.
        """
        url = f"{self.base_url}{path}"
        cleanParams = {k: v for k, v in params.items() if v is not None}

        self._rate_limit()
        response = self.session.get(url, params=cleanParams)

        if response.status_code == 429:
            logger.warning("LSE rate limit hit, waiting 3 seconds before retry...")
            time.sleep(3)
            self._rate_limit()
            response = self.session.get(url, params=cleanParams)

        response.raise_for_status()
        return response.json()

    @staticmethod
    def _parse_ts(ts: str) -> datetime:
        """Parse a vault timestamp string into a naive datetime (UTC wall time)"""
        ts = ts.replace('T', ' ').rstrip('Z')
        try:
            return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')

    @classmethod
    def _row_to_bar(cls, row: Dict, timeframe: str) -> Optional[Dict]:
        """Convert an LSE candle row into a Polygon-format bar dict"""
        ts = row.get('ts') or row.get('timestamp')
        if not ts:
            return None
        barTime = cls._parse_ts(ts)

        if timeframe in cls.DAILY_TIMEFRAMES:
            # LSE stamps daily bars 00:00 UTC; Polygon stamps them midnight ET.
            # Re-anchor to local midnight so fromtimestamp().date() gives the
            # correct trading date downstream.
            localMidnight = datetime(barTime.year, barTime.month, barTime.day)
            epochMs = int(localMidnight.timestamp() * 1000)
        else:
            epochMs = int(barTime.replace(tzinfo=timezone.utc).timestamp() * 1000)

        try:
            return {
                't': epochMs,
                'o': float(row['open']),
                'h': float(row['high']),
                'l': float(row['low']),
                'c': float(row['close']),
                'v': row.get('volume', 0) or 0,
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Skipping malformed LSE candle row {row}: {e}")
            return None

    @staticmethod
    def _to_utc_iso(localTime: datetime) -> str:
        """Convert a naive local datetime to a UTC ISO string for query params"""
        return datetime.utcfromtimestamp(localTime.timestamp()).strftime('%Y-%m-%dT%H:%M:%S')

    def get_historical_data(self,
                            symbol: str,
                            start_date: datetime,
                            end_date: datetime,
                            timeframe: str = '1d') -> List[Dict]:
        """
        Fetch historical OHLCV data from the LSE vault, paginating past the
        5000-row per-request cap.

        Args:
            symbol: Stock symbol
            start_date: Start date (inclusive, naive local time like PolygonClient)
            end_date: End date (inclusive, matching Polygon semantics)
            timeframe: Timeframe ('1d', '1h', '5m', '1m', etc.)

        Returns:
            List of Polygon-format bars: {'t', 'o', 'h', 'l', 'c', 'v'}
        """
        lseTimeframe = self.TIMEFRAME_MAP.get(timeframe)
        if lseTimeframe is None:
            logger.error(f"Unsupported timeframe for LSE: {timeframe}")
            return []

        if lseTimeframe in self.DAILY_TIMEFRAMES:
            # Date-only bounds: a time-of-day start would exclude the first
            # 00:00 UTC daily bar. The API's end is exclusive, so push it one
            # day past endDate to keep Polygon's inclusive-range semantics.
            startParam = start_date.strftime('%Y-%m-%d')
            endParam = (end_date + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            startParam = self._to_utc_iso(start_date)
            endParam = self._to_utc_iso(end_date + timedelta(seconds=1))

        bars: List[Dict] = []
        cursor = startParam

        try:
            for _ in range(1000):  # hard safety cap on pagination
                rows = self._request_rows('/candles', {
                    'symbol': symbol,
                    'timeframe': lseTimeframe,
                    'start': cursor,
                    'end': endParam,
                    'order': 'asc',
                    'limit': self.MAX_ROWS_PER_REQUEST,
                })

                for row in rows:
                    bar = self._row_to_bar(row, lseTimeframe)
                    if bar:
                        bars.append(bar)

                if len(rows) < self.MAX_ROWS_PER_REQUEST:
                    break

                lastTs = self._parse_ts(rows[-1].get('ts') or rows[-1].get('timestamp'))
                if lseTimeframe in self.DAILY_TIMEFRAMES:
                    cursor = (lastTs + timedelta(days=1)).strftime('%Y-%m-%d')
                else:
                    cursor = (lastTs + timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%S')

        except requests.RequestException as e:
            logger.error(f"Error fetching historical data from London Strategic Edge: {e}")

        dedupedBars = {bar['t']: bar for bar in bars}
        return [dedupedBars[t] for t in sorted(dedupedBars)]

    def get_ohlcv_data(self,
                       symbol: str,
                       start_date: datetime,
                       end_date: datetime,
                       timeframe: str = '1d') -> List[Tuple[datetime, float, float, float, float, int]]:
        """
        Get OHLCV data formatted as tuples (same shape as PolygonClient)

        Returns:
            List of (timestamp, open, high, low, close, volume) tuples
        """
        rawData = self.get_historical_data(symbol, start_date, end_date, timeframe)

        formattedData = []
        for item in rawData:
            timestamp = datetime.fromtimestamp(item['t'] / 1000)
            formattedData.append((
                timestamp,
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
        """Get only close prices for a symbol (same shape as PolygonClient)"""
        rawData = self.get_historical_data(symbol, start_date, end_date, timeframe)
        return [float(item['c']) for item in rawData if 'c' in item]

    def get_single_day_price(self, symbol: str, date: datetime) -> Optional[float]:
        """
        Get the daily close price for a symbol on a specific date

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            date: Trading date

        Returns:
            Close price or None if unavailable
        """
        try:
            dayStart = datetime(date.year, date.month, date.day)
            data = self.get_historical_data(symbol, dayStart, dayStart, '1d')
            if data:
                return float(data[-1]['c'])
            return None
        except Exception as e:
            logger.error(f"Error fetching single day price from London Strategic Edge: {e}")
            return None

    def get_historical_price(self, symbol: str, currentDate: datetime, timeframe: str = '1m') -> Optional[float]:
        """
        Fetch the price at (or just before) a historical datetime.
        Mirrors PolygonClient.get_historical_price: tries the bar at that
        minute, then falls back to the most recent daily close in the prior week.

        Args:
            symbol: Stock symbol
            currentDate: trading datetime to check
            timeframe: Timeframe ('1d', '1h', '5m', etc.)

        Returns:
            Float of price at that time, or None if unavailable
        """
        try:
            start = currentDate - timedelta(minutes=1)
            data = self.get_historical_data(symbol, start, currentDate, timeframe)
            if data:
                return float(data[-1]['c'])

            previousWeek = currentDate - timedelta(weeks=1)
            dailyData = self.get_historical_data(symbol, previousWeek, currentDate, '1d')
            if dailyData:
                return float(dailyData[-1]['c'])

            return None
        except Exception as e:
            logger.error(f"Error fetching historical price from London Strategic Edge: {e}")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get the most recent price for a symbol (close of the latest 1m candle).
        Candle data may lag a live trade feed by up to a minute; prefer
        Polygon's last-trade endpoint for live trading when available.

        Args:
            symbol: Stock symbol (e.g., 'SPY')

        Returns:
            Latest price or None if unavailable
        """
        try:
            rows = self._request_rows('/candles', {
                'symbol': symbol,
                'timeframe': '1m',
                'order': 'desc',
                'limit': 1,
            })
            if rows:
                return float(rows[0]['close'])
            return None
        except Exception as e:
            logger.error(f"Error fetching current price from London Strategic Edge: {e}")
            return None

    def get_last_quote(self, symbol: str) -> Optional[Dict]:
        """
        PolygonClient parity method. LSE has no NBBO quote endpoint, so this
        always returns None; callers already handle None from PolygonClient.
        """
        logger.warning("get_last_quote is not supported by London Strategic Edge; returning None")
        return None

    def is_market_open(self) -> bool:
        """
        Check if the US equity market is currently open.
        LSE has no market-status endpoint, so this uses the same time-based
        check PolygonClient falls back to on API errors.

        Returns:
            True if market is open, False otherwise
        """
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        return 9 <= now.hour < 16

    def __del__(self):
        """Clean up session on deletion"""
        if hasattr(self, 'session'):
            self.session.close()
