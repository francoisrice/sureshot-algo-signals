import requests
import os
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Union, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PolygonClient:
    """
    Polygon API client for fetching market data
    Supports both environment variables and Vault for API key retrieval
    """

    def __init__(self, api_key: Optional[str] = None, use_vault: bool = False):
        """
        Initialize Polygon client

        Args:
            api_key: Polygon API key. If None, will try to get from environment or Vault
            use_vault: If True, attempt to fetch API key from Vault
        """
        self.api_key = api_key

        if not self.api_key and use_vault:
            # Try to get API key from Vault
            try:
                # TODO: Fix this abomonation and move import to top of the file without breaking the import or the tests using it
                from ..vault_client import get_polygon_api_key_from_vault
                self.api_key = get_polygon_api_key_from_vault()
                if self.api_key:
                    logger.info("Successfully retrieved Polygon API key from Vault")
            except Exception as e:
                logger.warning(f"Failed to retrieve API key from Vault: {e}")

        if not self.api_key:
            # Fallback to environment variable
            self.api_key = os.getenv('POLYGON_API_KEY')

        if not self.api_key:
            raise ValueError(
                "POLYGON_API_KEY not found. Provide via:\n"
                "  1. Constructor argument: PolygonClient(api_key='...')\n"
                "  2. Environment variable: POLYGON_API_KEY\n"
                "  3. Vault: PolygonClient(use_vault=True)"
            )

        self.base_url = "https://api.polygon.io"
        self.session = requests.Session()
        self.last_request_time = 0
        self.min_request_interval = 0.15  # 150ms between requests (free tier: ~5 req/min)

    def _rate_limit(self):
        """Ensure we don't exceed API rate limits"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.3f}s")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get the current price for a symbol

        Args:
            symbol: Stock symbol (e.g., 'SPY')

        Returns:
            Current price or None if unavailable
        """
        try:
            self._rate_limit()
            url = f"{self.base_url}/v2/last/trade/{symbol}"
            params = {'apikey': self.api_key}

            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if 'results' in data:
                return float(data['results']['p'])  # 'p' is price

            return None

        except Exception as e:
            logger.error(f"Error fetching current price from Polygon: {e}")
            return None
        
    def get_single_day_price(self, symbol: str, date: datetime) -> Optional[float]:
        """
        Get the historical price for a symbol

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            date: Trading date

        Returns:
            Current price or None if unavailable
        """
        try:
            self._rate_limit()
            date = date.strftime("%Y-%m-%d")

            url = f"{self.base_url}/v1/open-close/{symbol}/{date}"
            params = {"adjusted": "true", 'apikey': self.api_key}

            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if 'close' in data:
                return float(data['close'])  # 'p' is price

            return None

        except Exception as e:
            logger.error(f"Error fetching single day price from Polygon: {e}")
        

    def get_historical_data(self,
                          symbol: str,
                          start_date: datetime,
                          end_date: datetime,
                          timeframe: str = '1d') -> List[Dict]:
        """
        Fetch historical OHLCV data from Polygon API

        Args:
            symbol: Stock symbol
            start_date: Start date for data
            end_date: End date for data
            timeframe: Timeframe ('1d', '1h', '5m', etc.)

        Returns:
            List of OHLCV data points
        """
        # Map timeframe to Polygon multiplier and timespan
        timeframe_map = {
            '1d': (1, 'day'),
            '1h': (1, 'hour'),
            '5m': (5, 'minute'),
            '15m': (15, 'minute'),
            '30m': (30, 'minute'),
            '1m': (1, 'minute')
        }

        multiplier, timespan = timeframe_map.get(timeframe, (1, 'day'))

        # Format dates for Polygon API
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        # Construct Polygon API URL
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{start_str}/{end_str}"

        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000,
            'apikey': self.api_key
        }

        try:
            self._rate_limit()
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if 'results' in data:
                return data['results']
            else:
                logger.debug(f"Polygon API response: {data}")
                return []

        except requests.RequestException as e:
            logger.error(f"Error fetching historical data from Polygon: {e}")
            # If rate limited, wait longer and retry once
            if '429' in str(e):
                logger.warning("Rate limit hit, waiting 12 seconds before retry...")
                time.sleep(12)
                try:
                    response = self.session.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                    if 'results' in data:
                        return data['results']
                except:
                    pass
            return []

    def get_ohlcv_data(self,
                       symbol: str,
                       start_date: datetime,
                       end_date: datetime,
                       timeframe: str = '1d') -> List[Tuple[datetime, float, float, float, float, int]]:
        """
        Get OHLCV data formatted as tuples

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe

        Returns:
            List of (timestamp, open, high, low, close, volume) tuples
        """
        raw_data = self.get_historical_data(symbol, start_date, end_date, timeframe)

        formatted_data = []
        for item in raw_data:
            timestamp = datetime.fromtimestamp(item['t'] / 1000)  # Convert from milliseconds
            open_price = float(item['o'])
            high_price = float(item['h'])
            low_price = float(item['l'])
            close_price = float(item['c'])
            volume = int(item['v'])

            formatted_data.append((timestamp, open_price, high_price, low_price, close_price, volume))

        return formatted_data

    def get_close_prices(self,
                        symbol: str,
                        start_date: datetime,
                        end_date: datetime,
                        timeframe: str = '1d') -> List[float]:
        """
        Get only close prices for a symbol

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe

        Returns:
            List of close prices
        """
        raw_data = self.get_historical_data(symbol, start_date, end_date, timeframe)
        return [float(item['c']) for item in raw_data if 'c' in item]

    def get_last_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get the last quote for a symbol

        Args:
            symbol: Stock symbol

        Returns:
            Quote data or None if unavailable
        """
        try:
            self._rate_limit()
            url = f"{self.base_url}/v2/last/nbbo/{symbol}"
            params = {'apikey': self.api_key}

            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if 'results' in data:
                return data['results']

            return None

        except Exception as e:
            logger.error(f"Error fetching last quote from Polygon: {e}")
            return None

    def is_market_open(self) -> bool:
        """
        Check if the market is currently open using Polygon's market status endpoint

        Returns:
            True if market is open, False otherwise
        """
        try:
            self._rate_limit()
            url = f"{self.base_url}/v1/marketstatus/now"
            params = {'apikey': self.api_key}

            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if data.get('market') == 'open':
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking market status from Polygon: {e}")
            # Fallback to basic time-based check
            now = datetime.now()
            # Simple check: weekday and rough market hours
            if now.weekday() >= 5:  # Weekend
                return False

            hour = now.hour
            return 9 <= hour < 16  # Rough market hours

    def __del__(self):
        """Clean up session on deletion"""
        if hasattr(self, 'session'):
            self.session.close()