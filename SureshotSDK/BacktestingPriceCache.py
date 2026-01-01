import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class BacktestingPriceCache:
    """
    Cache for historical price data to reduce API calls and improve performance
    """

    def __init__(self, cache_dir: str = ".price_cache"):
        """
        Initialize price cache

        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        logger.info(f"Price cache initialized at {self.cache_dir}")

    def _get_cache_key(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str) -> str:
        """
        Generate cache key for a data request

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe ('1d', '1h', etc.)

        Returns:
            Cache key string
        """
        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')
        return f"{symbol}_{timeframe}_{start_str}_{end_str}"

    def _get_cache_path(self, cache_key: str) -> Path:
        """
        Get file path for cache key

        Args:
            cache_key: Cache key

        Returns:
            Path to cache file
        """
        return self.cache_dir / f"{cache_key}.json"

    def get(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str = '1d') -> Optional[List[Dict]]:
        """
        Get cached price data

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe

        Returns:
            Cached data or None if not found
        """
        cache_key = self._get_cache_key(symbol, start_date, end_date, timeframe)
        cache_path = self._get_cache_path(cache_key)

        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                logger.info(f"Cache HIT for {cache_key}")
                return data
            except Exception as e:
                logger.error(f"Error reading cache for {cache_key}: {e}")
                return None
        else:
            logger.info(f"Cache MISS for {cache_key}")
            return None

    def set(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str, data: List[Dict]):
        """
        Save price data to cache

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe
            data: Price data to cache
        """
        cache_key = self._get_cache_key(symbol, start_date, end_date, timeframe)
        cache_path = self._get_cache_path(cache_key)

        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f)
            logger.info(f"Cached data for {cache_key}")
        except Exception as e:
            logger.error(f"Error writing cache for {cache_key}: {e}")

    def clear(self):
        """Clear all cached data"""
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
            logger.info("Price cache cleared")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    def get_cache_size(self) -> int:
        """
        Get number of cached items

        Returns:
            Number of cache files
        """
        return len(list(self.cache_dir.glob("*.json")))
