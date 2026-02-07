"""
Consolidate fragmented cache files into single files per symbol/timeframe.

Merges all {SYMBOL}_{TIMEFRAME}_{START}_{END}.json files into a single
{SYMBOL}_{TIMEFRAME}_{EARLIEST}_{LATEST}.json file.
"""

import os
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime


CACHE_DIR = Path(__file__).parent.parent.parent / ".backtest_cache"


def parse_filename(filename: str) -> tuple[str, str, str, str] | None:
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


def load_prices(filepath: Path) -> list[dict]:
    """Load price data from JSON file"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  Warning: Could not load {filepath}: {e}")
        return []


def get_date_from_bar(bar: dict) -> str:
    """Extract date string (YYYYMMDD) from price bar"""
    dt_str = bar.get('datetime', '')
    if dt_str:
        # Parse ISO format: "2021-02-01T05:00:00+00:00"
        dt = datetime.fromisoformat(dt_str.replace('+00:00', '+00:00'))
        return dt.strftime('%Y%m%d')
    # Fallback to timestamp
    ts = bar.get('t', 0)
    if ts:
        dt = datetime.utcfromtimestamp(ts / 1000)
        return dt.strftime('%Y%m%d')
    return ''


def consolidate():
    """Main consolidation function"""
    print(f"Scanning cache directory: {CACHE_DIR}")

    # Group files by symbol_timeframe
    groups = defaultdict(list)

    for filename in os.listdir(CACHE_DIR):
        if not filename.endswith('.json'):
            continue

        parsed = parse_filename(filename)
        if parsed:
            symbol, timeframe, start, end = parsed
            key = f"{symbol}_{timeframe}"
            groups[key].append(CACHE_DIR / filename)

    print(f"Found {len(groups)} symbol/timeframe groups")

    for key, files in groups.items():
        print(f"\nProcessing {key}: {len(files)} files")

        # Skip if only one file (already consolidated)
        if len(files) == 1:
            print(f"  Already consolidated, skipping")
            continue

        # Load and merge all price data
        all_bars = []
        for filepath in files:
            bars = load_prices(filepath)
            all_bars.extend(bars)
            print(f"  Loaded {len(bars)} bars from {filepath.name}")

        if not all_bars:
            print(f"  No data found, skipping")
            continue

        # Deduplicate by timestamp
        seen_timestamps = set()
        unique_bars = []
        for bar in all_bars:
            ts = bar.get('t')
            if ts and ts not in seen_timestamps:
                seen_timestamps.add(ts)
                unique_bars.append(bar)

        print(f"  Merged: {len(all_bars)} -> {len(unique_bars)} unique bars")

        # Sort by timestamp
        unique_bars.sort(key=lambda b: b.get('t', 0))

        # Get date range from actual data
        earliest_date = get_date_from_bar(unique_bars[0])
        latest_date = get_date_from_bar(unique_bars[-1])

        # Create consolidated filename
        symbol, timeframe = key.split('_', 1)
        new_filename = f"{symbol}_{timeframe}_{earliest_date}_{latest_date}.json"
        new_filepath = CACHE_DIR / new_filename

        print(f"  Writing {new_filename} ({len(unique_bars)} bars)")

        # Write consolidated file
        with open(new_filepath, 'w') as f:
            json.dump(unique_bars, f)

        # Remove old files (except the new consolidated one)
        for filepath in files:
            if filepath != new_filepath and filepath.exists():
                filepath.unlink()
                print(f"  Removed {filepath.name}")

    print("\nConsolidation complete!")


if __name__ == "__main__":
    consolidate()
