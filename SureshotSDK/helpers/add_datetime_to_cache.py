#!/usr/bin/env python3
"""
Script to add ISO datetime strings to price cache JSON files.
Automatically detects timezone (EST vs UTC) based on volume patterns during market hours.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict
import pytz


def detect_timezone(data: List[Dict]) -> str:
    """
    Detect if timestamps are in EST or UTC by analyzing volume patterns.
    Market hours are 9:30 AM - 4:00 PM EST.
    Returns 'America/New_York' or 'UTC'.
    """
    est = pytz.timezone('America/New_York')

    est_market_volume = 0
    est_non_market_volume = 0
    utc_market_volume = 0
    utc_non_market_volume = 0

    for entry in data[:100]:  # Sample first 100 entries
        timestamp_ms = entry.get('t')
        volume = entry.get('v', 0)

        if not timestamp_ms or not volume:
            continue

        # Check if EST interpretation puts it in market hours
        dt_est = datetime.fromtimestamp(timestamp_ms / 1000, tz=est)
        hour = dt_est.hour
        minute = dt_est.minute

        # Market hours: 9:30 AM - 4:00 PM EST
        if (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16:
            est_market_volume += volume
        else:
            est_non_market_volume += volume

        # Check if UTC interpretation puts it in market hours
        dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        dt_utc_as_est = dt_utc.astimezone(est)
        hour = dt_utc_as_est.hour
        minute = dt_utc_as_est.minute

        if (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16:
            utc_market_volume += volume
        else:
            utc_non_market_volume += volume

    # Calculate ratios
    est_ratio = est_market_volume / (est_non_market_volume + 1)
    utc_ratio = utc_market_volume / (utc_non_market_volume + 1)

    print(f"  EST market/non-market volume ratio: {est_ratio:.2f}")
    print(f"  UTC market/non-market volume ratio: {utc_ratio:.2f}")

    # Higher ratio means more volume during market hours
    if est_ratio > utc_ratio:
        print(f"  Detected timezone: EST (America/New_York)")
        return 'America/New_York'
    else:
        print(f"  Detected timezone: UTC")
        return 'UTC'


def add_datetime_field(file_path: Path, tz_name: str = None) -> None:
    """
    Add ISO datetime string field to each object in the JSON file.
    Modifies the file in place.
    """
    print(f"\nProcessing: {file_path.name}")

    # Read the JSON file
    with open(file_path, 'r') as f:
        data = json.load(f)

    if not data or not isinstance(data, list):
        print(f"  Skipping: Not a valid array")
        return

    # Detect timezone if not provided
    if tz_name is None:
        # tz_name = detect_timezone(data)
        tz_name = 'America/New_York'
    else:
        print(f"  Using timezone: {tz_name}")

    # Set up timezone
    if tz_name == 'UTC':
        tz = timezone.utc
    else:
        tz = pytz.timezone(tz_name)

    # Add datetime field to each entry
    modified_count = 0
    for entry in data:
        timestamp_ms = entry.get('t')
        if timestamp_ms:
            dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=tz)
            entry['datetime'] = dt.isoformat()
            modified_count += 1

    # Write back to file
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

    print(f"  Added datetime to {modified_count} entries")


def process_all_cache_files(cache_dir: str = '.price_cache') -> None:
    """
    Process all JSON files in the price cache directory.
    """
    cache_path = Path(cache_dir)

    if not cache_path.exists():
        print(f"Error: Cache directory '{cache_dir}' not found")
        return

    json_files = list(cache_path.glob('*.json'))

    if not json_files:
        print(f"No JSON files found in '{cache_dir}'")
        return

    print(f"Found {len(json_files)} JSON files to process")

    # Detect timezone from first file
    first_file = json_files[0]
    with open(first_file, 'r') as f:
        sample_data = json.load(f)

    print(f"\nDetecting timezone from {first_file.name}:")
    # detected_tz = detect_timezone(sample_data)
    detected_tz = 'America/New_York'

    # Process all files with detected timezone
    for file_path in json_files:
        add_datetime_field(file_path, detected_tz)

    print(f"\n✓ Completed processing {len(json_files)} files")


if __name__ == '__main__':
    # Change to project root directory
    # script_dir = Path(__file__).parent
    # project_root = script_dir.parent
    # os.chdir(project_root)
    os.chdir("/home/lenovo/Code/sureshot-algo-signals/")

    print("=" * 60)
    print("Adding datetime fields to price cache files")
    print("=" * 60)

    # process_all_cache_files('.price_cache')
    process_all_cache_files('.backtest_cache')
