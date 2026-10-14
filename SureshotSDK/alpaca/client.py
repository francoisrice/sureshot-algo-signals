"""
Alpaca market-data client (stocks).

Same read surface the strategies already use on PolygonClient / DataFetcherClient:
`get_current_price`, `get_current_bar` ({t, o, h, l, c, v} with `t` in epoch ms)
and `get_historical_data` (list of those bars), so it drops in as a price source.

Environment:
    ALPACA_API_KEY_ID      Alpaca key id (paper or live keys both work for data).
    ALPACA_API_SECRET_KEY  Alpaca secret key.
    ALPACA_DATA_FEED       'iex' (free, real-time IEX only) or 'sip' (all US
                           exchanges; requires the Algo Trader Plus plan). Default 'iex'.
    ALPACA_DATA_URL        Override the base URL (default https://data.alpaca.markets).
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_DATA_URL = "https://data.alpaca.markets"

TIMEFRAME_TO_ALPACA = {
    '1m': '1Min',
    '5m': '5Min',
    '15m': '15Min',
    '30m': '30Min',
    '1h': '1Hour',
    '1d': '1Day',
}

MAX_BARS_PER_PAGE = 10000


def _rfc3339_to_epoch_ms(timestamp: str) -> int:
    # Alpaca emits nanosecond precision ("...:16.845580544Z"); fromisoformat accepts at most microseconds
    seconds, _, fraction = timestamp.rstrip('Z').partition('.')
    parsed = datetime.fromisoformat(f"{seconds}.{fraction[:6].ljust(6, '0')}+00:00")
    return int(parsed.timestamp() * 1000)


def _to_sureshot_bar(alpacaBar: Dict) -> Dict:
    return {
        't': _rfc3339_to_epoch_ms(alpacaBar['t']),
        'o': alpacaBar['o'],
        'h': alpacaBar['h'],
        'l': alpacaBar['l'],
        'c': alpacaBar['c'],
        'v': alpacaBar['v'],
    }


class AlpacaDataClient:

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        api_secret_key: Optional[str] = None,
        feed: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.apiKeyId = api_key_id or os.environ.get('ALPACA_API_KEY_ID', '')
        self.apiSecretKey = api_secret_key or os.environ.get('ALPACA_API_SECRET_KEY', '')
        if not (self.apiKeyId and self.apiSecretKey):
            raise ValueError("Alpaca credentials missing: set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")
        self.feed = (feed or os.environ.get('ALPACA_DATA_FEED', 'iex')).lower()
        self.baseUrl = (base_url or os.environ.get('ALPACA_DATA_URL', DEFAULT_DATA_URL)).rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'APCA-API-KEY-ID': self.apiKeyId,
            'APCA-API-SECRET-KEY': self.apiSecretKey,
            'Accept': 'application/json',
        })

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        response = self.session.get(
            f"{self.baseUrl}{path}",
            params={'feed': self.feed, **(params or {})},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_latest_trade(self, symbol: str) -> Optional[Dict]:
        """{'price': float, 'size': float, 't': epoch ms} or None on failure."""
        try:
            trade = self._get(f"/v2/stocks/{symbol.upper()}/trades/latest").get('trade')
            if not trade:
                return None
            return {'price': float(trade['p']), 'size': float(trade['s']), 't': _rfc3339_to_epoch_ms(trade['t'])}
        except Exception as e:
            logger.error(f"Alpaca latest trade for {symbol} failed: {e}")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        latestTrade = self.get_latest_trade(symbol)
        return latestTrade['price'] if latestTrade else None

    def get_snapshot(self, symbol: str) -> Optional[Dict]:
        """Raw Alpaca snapshot: latestTrade, latestQuote, minuteBar, dailyBar, prevDailyBar."""
        try:
            return self._get(f"/v2/stocks/{symbol.upper()}/snapshot")
        except Exception as e:
            logger.error(f"Alpaca snapshot for {symbol} failed: {e}")
            return None

    def get_current_bar(self, symbol: str) -> Optional[Dict]:
        """Today's running daily bar with the close replaced by the latest trade."""
        snapshot = self.get_snapshot(symbol)
        if not snapshot or not snapshot.get('dailyBar'):
            return None
        currentBar = _to_sureshot_bar(snapshot['dailyBar'])
        latestTrade = snapshot.get('latestTrade')
        if latestTrade:
            currentBar['c'] = float(latestTrade['p'])
        return currentBar

    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = '1d',
        adjustment: str = 'raw',
    ) -> List[Dict]:
        alpacaTimeframe = TIMEFRAME_TO_ALPACA.get(timeframe)
        if alpacaTimeframe is None:
            raise ValueError(f"Unsupported timeframe {timeframe!r}; use one of {sorted(TIMEFRAME_TO_ALPACA)}")

        params = {
            'timeframe': alpacaTimeframe,
            'start': start_date.isoformat() if start_date.tzinfo else start_date.strftime('%Y-%m-%d'),
            'end': end_date.isoformat() if end_date.tzinfo else end_date.strftime('%Y-%m-%d'),
            'adjustment': adjustment,
            'limit': MAX_BARS_PER_PAGE,
        }
        bars: List[Dict] = []
        while True:
            page = self._get(f"/v2/stocks/{symbol.upper()}/bars", params)
            bars.extend(_to_sureshot_bar(bar) for bar in page.get('bars') or [])
            nextPageToken = page.get('next_page_token')
            if not nextPageToken:
                return bars
            params['page_token'] = nextPageToken

    def close(self) -> None:
        self.session.close()
