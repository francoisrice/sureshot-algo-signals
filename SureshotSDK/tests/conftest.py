"""
Pytest configuration file for handling imports
"""
import sys
import os
import gzip
from datetime import date, datetime
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pytest

# Add the parent directory (SureshotSDK) to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Tests mock the HTTP session but still run the throttle; real pacing would add 12.5s per call
os.environ.setdefault('POLYGON_MIN_REQUEST_INTERVAL', '0')

# Never let a test read or gap-fill the real shared store; tests that want one pass data_root
os.environ['DATA_ROOT'] = '/nonexistent/sureshot-test-data-root'

MARKET_TZ = ZoneInfo('America/New_York')
ARCHIVE_DAYS = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 7)]


def epoch_ms(sessionDate: date, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(sessionDate.year, sessionDate.month, sessionDate.day, hour, minute, tzinfo=MARKET_TZ).timestamp() * 1000)


def day_row(ticker: str, sessionDate: date, close: float, volume: float = 1000.0):
    return (ticker, sessionDate, epoch_ms(sessionDate) * 1_000_000, close, close + 1, close - 1, close, volume, 10)


def write_bar_partition(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {
        'ticker': np.array([r[0] for r in rows]),
        'session_date': np.array([r[1].isoformat() for r in rows]),
        'window_start_ns': np.array([r[2] for r in rows], dtype=np.int64),
        'open': np.array([r[3] for r in rows], dtype=float),
        'high': np.array([r[4] for r in rows], dtype=float),
        'low': np.array([r[5] for r in rows], dtype=float),
        'close': np.array([r[6] for r in rows], dtype=float),
        'volume': np.array([r[7] for r in rows], dtype=float),
        'transactions': np.array([r[8] for r in rows], dtype=np.int64),
    }
    connection = duckdb.connect()
    connection.register('bars', columns)
    connection.execute(f"""
        COPY (SELECT ticker, session_date::DATE AS session_date, window_start_ns, open, high, low, close,
                     volume, transactions FROM bars ORDER BY ticker, window_start_ns)
        TO '{path}' (FORMAT parquet)
    """)
    connection.close()


def write_raw_day_file(root, rows):
    """A vendor day_aggs flat file for one session, as sureshot-marketdata stores it"""
    sessionDate = rows[0][1]
    path = root / 'raw' / 'flatfiles' / 'day_aggs_v1' / f'{sessionDate:%Y}' / f'{sessionDate:%m}' / f'{sessionDate}.csv.gz'
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['ticker,volume,open,close,high,low,window_start,transactions']
    lines += [f'{r[0]},{r[7]},{r[3]},{r[6]},{r[4]},{r[5]},{r[2]},{r[8]}' for r in rows]
    with gzip.open(path, 'wt') as f:
        f.write('\n'.join(lines) + '\n')


def write_splits(root, splits):
    path = root / 'parquet' / 'ref' / 'splits.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register('splits', {
        'ticker': np.array([s[0] for s in splits]),
        'execution_date': np.array([s[1].isoformat() for s in splits]),
        'split_from': np.array([s[2] for s in splits], dtype=float),
        'split_to': np.array([s[3] for s in splits], dtype=float),
    })
    connection.execute(f"""
        COPY (SELECT ticker, execution_date::DATE AS execution_date, split_from, split_to FROM splits)
        TO '{path}' (FORMAT parquet)
    """)
    connection.close()


@pytest.fixture
def market_archive(tmp_path):
    """
    A minimal DATA_ROOT: SPY and ABC daily bars on four July 2026 sessions, twenty SPY
    minute bars from 09:30 on 2026-07-01, a 1:2 ABC split effective 2026-07-06, a 1:2
    split for NEW effective 2026-07-09 (after the archive's last session, 2026-07-07)
    and a far-future SPY split that must be ignored.
    """
    dailyRows = [day_row('SPY', d, 100.0 + i) for i, d in enumerate(ARCHIVE_DAYS)]
    dailyRows += [day_row('ABC', d, 50.0) for d in ARCHIVE_DAYS]
    write_bar_partition(tmp_path / 'parquet' / 'day_official' / 'year=2026' / 'part-0000.parquet', dailyRows)

    firstSession = ARCHIVE_DAYS[0]
    minuteRows = [
        ('SPY', firstSession, epoch_ms(firstSession, 9, 30 + m) * 1_000_000, 100.0 + m, 100.5 + m, 99.5 + m, 100.25 + m, 100.0, 1)
        for m in range(20)
    ]
    write_bar_partition(tmp_path / 'parquet' / 'minute' / 'year=2026' / 'month=07' / 'part-0000.parquet', minuteRows)

    write_splits(tmp_path, [
        ('ABC', date(2026, 7, 6), 1.0, 2.0),
        ('NEW', date(2026, 7, 9), 1.0, 2.0),
        ('SPY', date(2099, 1, 1), 1.0, 10.0),
    ])
    return tmp_path
