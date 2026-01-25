"""
Intraday Data Manager

Efficiently manages fetching and caching of minute-bar data for backtesting.
Designed to minimize API calls by caching entire trading days of minute data.
"""

import logging
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import json
from .Polygon import PolygonClient

logger = logging.getLogger(__name__)


class IntradayDataManager:
    """
    Manages intraday (minute-level) data with aggressive caching strategy

    This class fetches and caches minute bars for entire trading days at a time,
    minimizing API calls during backtesting iterations.
    """

    def __init__(self, cache_dir: str = ".intraday_cache"):
        """
        Initialize the intraday data manager

        Args:
            cache_dir: Directory to store cached minute-bar data
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.polygon_client = PolygonClient()

        # In-memory cache for current session
        # Format: {symbol: {date: List[bars]}}
        self.memory_cache: Dict[str, Dict[date, List[Dict]]] = {}

    def get_minute_bars(
        self,
        symbol: str,
        trading_date: date,
        start_time: Optional[time] = None,
        end_time: Optional[time] = None
    ) -> List[Dict]:
        """
        Get minute bars for a specific trading day

        Args:
            symbol: Stock symbol
            trading_date: Trading date
            start_time: Optional start time (default: market open 9:30 AM)
            end_time: Optional end time (default: market close 4:00 PM)

        Returns:
            List of minute bars with OHLCV data
        """
        # Set default market hours if not specified
        if start_time is None:
            start_time = time(9, 30)  # Market open
        if end_time is None:
            end_time = time(16, 0)  # Market close

        # Check memory cache first
        if symbol in self.memory_cache:
            if trading_date in self.memory_cache[symbol]:
                logger.debug(f"Found {symbol} data for {trading_date} in memory cache")
                return self._filter_by_time(
                    self.memory_cache[symbol][trading_date],
                    start_time,
                    end_time
                )

        # Check disk cache
        cached_data = self._load_from_cache(symbol, trading_date)
        if cached_data is not None:
            logger.debug(f"Found {symbol} data for {trading_date} in disk cache")
            self._add_to_memory_cache(symbol, trading_date, cached_data)
            return self._filter_by_time(cached_data, start_time, end_time)

        # Fetch from API
        logger.info(f"Fetching minute bars for {symbol} on {trading_date}")
        minute_data = self._fetch_minute_bars(symbol, trading_date)

        if minute_data:
            # Save to both caches
            self._save_to_cache(symbol, trading_date, minute_data)
            self._add_to_memory_cache(symbol, trading_date, minute_data)
            return self._filter_by_time(minute_data, start_time, end_time)

        logger.warning(f"No minute data available for {symbol} on {trading_date}")
        return []

    def get_opening_range_bars(
        self,
        symbol: str,
        trading_date: date,
        minutes: int = 5
    ) -> List[Dict]:
        """
        Get the opening range bars (first N minutes after market open)

        Args:
            symbol: Stock symbol
            trading_date: Trading date
            minutes: Number of minutes for opening range (default: 5)

        Returns:
            List of minute bars for the opening range
        """
        market_open = time(9, 30)
        end_time = (datetime.combine(trading_date, market_open) + timedelta(minutes=minutes)).time()

        return self.get_minute_bars(symbol, trading_date, market_open, end_time)

    def _fetch_minute_bars(self, symbol: str, trading_date: date) -> List[Dict]:
        """
        Fetch minute bars from Polygon API for a single trading day

        Args:
            symbol: Stock symbol
            trading_date: Trading date

        Returns:
            List of minute bars
        """
        try:
            # Convert date to datetime with market hours
            start_dt = datetime.combine(trading_date, time(9, 30))
            end_dt = datetime.combine(trading_date, time(16, 0))

            # Fetch 1-minute bars
            data = self.polygon_client.get_historical_data(
                symbol,
                start_dt,
                end_dt,
                timeframe='1min'
            )

            return data if data else []

        except Exception as e:
            logger.error(f"Error fetching minute bars for {symbol} on {trading_date}: {e}")
            return []

    def _filter_by_time(
        self,
        bars: List[Dict],
        start_time: time,
        end_time: time
    ) -> List[Dict]:
        """
        Filter bars by time range

        Args:
            bars: List of bars
            start_time: Start time
            end_time: End time

        Returns:
            Filtered list of bars
        """
        filtered = []
        for bar in bars:
            bar_time = datetime.fromtimestamp(bar['t'] / 1000).time()
            if start_time <= bar_time <= end_time:
                filtered.append(bar)

        return filtered

    def _get_cache_filepath(self, symbol: str, trading_date: date) -> Path:
        """
        Get the cache file path for a symbol and date

        Args:
            symbol: Stock symbol
            trading_date: Trading date

        Returns:
            Path to cache file
        """
        # Organize by year/month for better file system organization
        year_month = trading_date.strftime("%Y%m")
        cache_subdir = self.cache_dir / symbol / year_month
        cache_subdir.mkdir(parents=True, exist_ok=True)

        filename = f"{symbol}_1min_{trading_date.strftime('%Y%m%d')}.json"
        return cache_subdir / filename

    def _load_from_cache(self, symbol: str, trading_date: date) -> Optional[List[Dict]]:
        """
        Load minute bars from disk cache

        Args:
            symbol: Stock symbol
            trading_date: Trading date

        Returns:
            List of bars or None if not cached
        """
        filepath = self._get_cache_filepath(symbol, trading_date)

        if not filepath.exists():
            return None

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                return data.get('bars', [])
        except Exception as e:
            logger.warning(f"Error loading cache from {filepath}: {e}")
            return None

    def _save_to_cache(self, symbol: str, trading_date: date, bars: List[Dict]):
        """
        Save minute bars to disk cache

        Args:
            symbol: Stock symbol
            trading_date: Trading date
            bars: List of minute bars
        """
        filepath = self._get_cache_filepath(symbol, trading_date)

        try:
            cache_data = {
                'symbol': symbol,
                'date': trading_date.isoformat(),
                'bars': bars,
                'cached_at': datetime.now().isoformat()
            }

            with open(filepath, 'w') as f:
                json.dump(cache_data, f)

            logger.debug(f"Cached {len(bars)} bars for {symbol} on {trading_date}")

        except Exception as e:
            logger.warning(f"Error saving cache to {filepath}: {e}")

    def _add_to_memory_cache(self, symbol: str, trading_date: date, bars: List[Dict]):
        """
        Add bars to in-memory cache

        Args:
            symbol: Stock symbol
            trading_date: Trading date
            bars: List of minute bars
        """
        if symbol not in self.memory_cache:
            self.memory_cache[symbol] = {}

        self.memory_cache[symbol][trading_date] = bars

    def clear_memory_cache(self):
        """Clear the in-memory cache"""
        self.memory_cache.clear()
        logger.info("Cleared intraday memory cache")

    def get_market_open_close_prices(
        self,
        symbol: str,
        trading_date: date
    ) -> Optional[Dict[str, float]]:
        """
        Get market open and close prices for a trading day

        Args:
            symbol: Stock symbol
            trading_date: Trading date

        Returns:
            Dictionary with 'open' and 'close' prices, or None if unavailable
        """
        bars = self.get_minute_bars(symbol, trading_date)

        if not bars:
            return None

        # First bar open, last bar close
        return {
            'open': float(bars[0]['o']),
            'close': float(bars[-1]['c']),
            'high': max(float(bar['h']) for bar in bars),
            'low': min(float(bar['l']) for bar in bars),
            'volume': sum(int(bar['v']) for bar in bars)
        }

    def calculate_opening_range(
        self,
        symbol: str,
        trading_date: date,
        minutes: int = 5
    ) -> Optional[Dict[str, float]]:
        """
        Calculate opening range high, low, and other metrics

        Args:
            symbol: Stock symbol
            trading_date: Trading date
            minutes: Number of minutes for opening range

        Returns:
            Dictionary with opening range metrics, or None if unavailable
        """
        bars = self.get_opening_range_bars(symbol, trading_date, minutes)

        if not bars:
            return None

        highs = [float(bar['h']) for bar in bars]
        lows = [float(bar['l']) for bar in bars]
        volumes = [int(bar['v']) for bar in bars]

        return {
            'high': max(highs),
            'low': min(lows),
            'open': float(bars[0]['o']),
            'close': float(bars[-1]['c']),
            'volume': sum(volumes),
            'range': max(highs) - min(lows),
            'num_bars': len(bars)
        }


if __name__ == "__main__":
    # Example usage
    manager = IntradayDataManager()

    # Test fetching opening range
    test_date = date(2024, 1, 5)
    test_symbol = "SPY"

    print(f"Fetching opening range for {test_symbol} on {test_date}...")
    opening_range = manager.calculate_opening_range(test_symbol, test_date, minutes=5)

    if opening_range:
        print(f"Opening Range (5 min):")
        print(f"  High: ${opening_range['high']:.2f}")
        print(f"  Low: ${opening_range['low']:.2f}")
        print(f"  Range: ${opening_range['range']:.2f}")
        print(f"  Volume: {opening_range['volume']:,}")
    else:
        print("No data available")
