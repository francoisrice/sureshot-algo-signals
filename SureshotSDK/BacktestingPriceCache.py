import json
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class BacktestingPriceCache:
    """
    Cache for historical price data to reduce API calls and improve performance.

    Uses consolidated cache files: {SYMBOL}_{TIMEFRAME}_{START}_{END}.json
    Automatically extends cache when requested dates fall outside cached range.
    """

    def __init__(self, cache_dir: str = ".backtest_cache"):
        """
        Initialize price cache

        Args:
            cache_dir: Directory to store cache files
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        logger.info(f"Price cache initialized at {self.cache_dir}")

    def _parse_cache_filename(self, filename: str) -> Optional[Tuple[str, str, str, str]]:
        """
        Parse cache filename into components.

        Returns:
            Tuple of (symbol, timeframe, start_date, end_date) or None if invalid
        """
        pattern = r'^([A-Z]+)_(\w+)_(\d{8})_(\d{8})\.json$'
        match = re.match(pattern, filename)
        if match:
            return match.groups()
        return None

    def _find_cache_file(self, symbol: str, timeframe: str) -> Optional[Tuple[Path, str, str]]:
        """
        Find existing cache file for symbol/timeframe.

        Returns:
            Tuple of (path, start_date, end_date) or None if not found
        """
        for filename in os.listdir(self.cache_dir):
            parsed = self._parse_cache_filename(filename)
            if parsed:
                file_symbol, file_tf, start_str, end_str = parsed
                if file_symbol == symbol and file_tf == timeframe:
                    return (self.cache_dir / filename, start_str, end_str)
        return None

    def _load_cache_file(self, cache_path: Path) -> List[Dict]:
        """Load price data from cache file"""
        try:
            with open(cache_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading cache {cache_path}: {e}")
            return []

    def _save_cache_file(self, symbol: str, timeframe: str, start_str: str, end_str: str, data: List[Dict]):
        """Save price data to cache file"""
        filename = f"{symbol}_{timeframe}_{start_str}_{end_str}.json"
        cache_path = self.cache_dir / filename
        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f)
            logger.info(f"Saved cache: {filename} ({len(data)} bars)")
        except Exception as e:
            logger.error(f"Error writing cache {filename}: {e}")

    def _date_to_str(self, dt: datetime) -> str:
        """Convert datetime to YYYYMMDD string"""
        return dt.strftime('%Y%m%d')

    def _str_to_date(self, date_str: str) -> datetime:
        """Convert YYYYMMDD string to datetime"""
        return datetime.strptime(date_str, '%Y%m%d')

    def _get_bar_date(self, bar: dict) -> datetime:
        """Extract datetime from price bar """
        dt_str = bar.get('datetime', '')
        if dt_str:
            dt = datetime.fromisoformat(dt_str)
            # Convert to naive datetime for comparison
            return dt.replace(tzinfo=None)
        ts = bar.get('t', 0)
        if ts:
            return datetime.utcfromtimestamp(ts / 1000)
        return datetime.min

    def _filter_bars_by_date(self, bars: List[Dict], start_date: datetime, end_date: datetime) -> List[Dict]:
        """Filter bars to only include those within date range"""
        filtered = []
        for bar in bars:
            bar_date = self._get_bar_date(bar)
            if start_date <= bar_date <= end_date:
                filtered.append(bar)
        return filtered

    def _merge_bars(self, existing: List[Dict], new_bars: List[Dict]) -> List[Dict]:
        """Merge bar lists, deduplicate by timestamp, sort by time"""
        seen_timestamps = {}

        # Add existing bars first
        for bar in existing:
            ts = bar.get('t')
            if ts:
                seen_timestamps[ts] = bar

        # Add/update with new bars
        for bar in new_bars:
            ts = bar.get('t')
            if ts:
                seen_timestamps[ts] = bar

        # Sort by timestamp
        merged = list(seen_timestamps.values())
        merged.sort(key=lambda b: b.get('t', 0))
        return merged

    def get(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = '1d',
        fetch_fn: Optional[Callable[[str, datetime, datetime, str], List[Dict]]] = None
    ) -> Optional[List[Dict]]:
        """
        Get cached price data, extending cache if needed.

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe
            fetch_fn: Function to fetch missing data: fn(symbol, start, end, timeframe) -> List[Dict]

        Returns:
            Price data for requested range, or None if unavailable
        """
        req_start_str = self._date_to_str(start_date)
        req_end_str = self._date_to_str(end_date)

        # Find existing cache file
        cache_info = self._find_cache_file(symbol, timeframe)

        if not cache_info:
            # No cache exists
            logger.info(f"Cache MISS for {symbol}_{timeframe} (no cache file)")
            return None

        cache_path, cache_start_str, cache_end_str = cache_info
        cache_start = self._str_to_date(cache_start_str)
        cache_end = self._str_to_date(cache_end_str)

        logger.info(f"Found cache {cache_path.name}: {cache_start_str} to {cache_end_str}")

        # Load existing cache data
        cached_bars = self._load_cache_file(cache_path)
        if not cached_bars:
            return None

        result_bars = cached_bars
        new_start_str = cache_start_str
        new_end_str = cache_end_str
        cache_updated = False

        # Check if we need to extend backwards
        if start_date < cache_start:
            if fetch_fn:
                logger.info(f"Extending cache backwards: {req_start_str} to {cache_start_str}")
                pre_bars = fetch_fn(symbol, start_date, cache_start, timeframe)
                if pre_bars:
                    result_bars = self._merge_bars(pre_bars, result_bars)
                    new_start_str = req_start_str
                    cache_updated = True
            else:
                logger.warning(f"Requested start {req_start_str} before cache start {cache_start_str}, no fetch_fn provided")

        # Check if we need to extend forwards
        if end_date > cache_end:
            if fetch_fn:
                logger.info(f"Extending cache forwards: {cache_end_str} to {req_end_str}")
                post_bars = fetch_fn(symbol, cache_end, end_date, timeframe)
                if post_bars:
                    result_bars = self._merge_bars(result_bars, post_bars)
                    new_end_str = req_end_str
                    cache_updated = True
            else:
                logger.warning(f"Requested end {req_end_str} after cache end {cache_end_str}, no fetch_fn provided")

        # Save updated cache if extended
        if cache_updated:
            # Remove old cache file
            cache_path.unlink()
            # Save new consolidated cache
            self._save_cache_file(symbol, timeframe, new_start_str, new_end_str, result_bars)

        # Filter to requested range
        filtered_bars = self._filter_bars_by_date(result_bars, start_date, end_date)
        logger.info(f"Cache HIT for {symbol}_{timeframe}: returning {len(filtered_bars)} bars")

        return filtered_bars

    def set(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str, data: List[Dict]):
        """
        Save price data to cache, merging with existing data if present.

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe
            data: Price data to cache
        """
        if not data:
            return

        req_start_str = self._date_to_str(start_date)
        req_end_str = self._date_to_str(end_date)

        # Check for existing cache
        cache_info = self._find_cache_file(symbol, timeframe)

        if cache_info:
            cache_path, cache_start_str, cache_end_str = cache_info
            existing_bars = self._load_cache_file(cache_path)

            # Merge data
            merged = self._merge_bars(existing_bars, data)

            # Determine new date range
            new_start_str = min(cache_start_str, req_start_str)
            new_end_str = max(cache_end_str, req_end_str)

            # Remove old cache file
            cache_path.unlink()

            # Save merged data
            self._save_cache_file(symbol, timeframe, new_start_str, new_end_str, merged)
        else:
            # No existing cache, create new
            self._save_cache_file(symbol, timeframe, req_start_str, req_end_str, data)

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
