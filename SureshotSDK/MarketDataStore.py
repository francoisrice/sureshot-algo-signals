import logging
import os
import re
import threading
import time as clock
from array import array
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import duckdb
import numpy as np

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = "../data"
MARKET_TZ = ZoneInfo("America/New_York")

ARCHIVE_DATASETS = {'1d': 'day_official', '1m': 'minute'}
RAW_DATASETS = {'1d': 'day_aggs_v1', '1m': 'minute_aggs_v1'}
AGGREGATED_TIMEFRAMES = {'5m': 5, '15m': 15, '30m': 30, '1h': 60}

RAW_FILE_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})\.csv\.gz$')
PARTITION_KEY = re.compile(r'year=(\d{4})(?:/month=(\d{2}))?/')
SYMBOL_RANGE_FILE = re.compile(r'^(\d{8})_(\d{8})\.parquet$')
MARKET_DAY_FILE = re.compile(r'^date=(\d{4}-\d{2}-\d{2})\.parquet$')

MAX_CACHED_DAILY_SYMBOLS = 4000
MAX_CACHED_MINUTE_MONTHS = 64
# One query per batch: scanning the yearly files costs the same for 1 ticker or 500
DAILY_PRELOAD_BATCH_SIZE = 500

BAR_SELECT = "ticker, session_date, window_start_ns, open, high, low, close, volume, transactions"
SUPPLEMENT_COLUMNS = ("ticker VARCHAR, session_date DATE, window_start_ns BIGINT, open DOUBLE, high DOUBLE, "
                      "low DOUBLE, close DOUBLE, volume DOUBLE, transactions BIGINT, source VARCHAR, fetched_at_ns BIGINT")

FetchFn = Callable[[str, datetime, datetime, str], List[Dict]]
FetchMarketDayFn = Callable[[date], Optional[List[Dict]]]


def resolve_data_root(data_root: Optional[str] = None) -> Path:
    """Explicit argument, then $DATA_ROOT, then ../data; relative paths anchor to the repo root, not the CWD"""
    dataRoot = Path(data_root or os.getenv('DATA_ROOT') or DEFAULT_DATA_ROOT).expanduser()
    return dataRoot if dataRoot.is_absolute() else (REPO_ROOT / dataRoot).resolve()


def market_date(epoch_ms: int) -> date:
    return datetime.fromtimestamp(epoch_ms / 1000, MARKET_TZ).date()


def market_midnight_ns(sessionDate: date) -> int:
    """The archive stamps daily bars at 00:00 ET; Polygon's grouped endpoint uses 16:00 ET"""
    return int(datetime.combine(sessionDate, time.min, MARKET_TZ).timestamp()) * 1_000_000_000


def market_today() -> date:
    return datetime.now(MARKET_TZ).date()


def is_store_timeframe(timeframe: str) -> bool:
    return timeframe in ARCHIVE_DATASETS or timeframe in AGGREGATED_TIMEFRAMES


def compact_number(value: float):
    # Split factors leave float noise (18.779750000000003); vendor prices carry 6 decimals
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded


def sql_string(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def subtract_ranges(wanted: Tuple[date, date], covered: Iterable[Tuple[date, date]]) -> List[Tuple[date, date]]:
    gaps = [wanted]
    for coveredStart, coveredEnd in sorted(covered):
        remaining = []
        for gapStart, gapEnd in gaps:
            if coveredEnd < gapStart or coveredStart > gapEnd:
                remaining.append((gapStart, gapEnd))
                continue
            if gapStart < coveredStart:
                remaining.append((gapStart, coveredStart - timedelta(days=1)))
            if gapEnd > coveredEnd:
                remaining.append((coveredEnd + timedelta(days=1), gapEnd))
        gaps = remaining
    return gaps


def trim_weekends(gap: Tuple[date, date]) -> Optional[Tuple[date, date]]:
    gapStart, gapEnd = gap
    while gapStart <= gapEnd and gapStart.weekday() >= 5:
        gapStart += timedelta(days=1)
    while gapEnd >= gapStart and gapEnd.weekday() >= 5:
        gapEnd -= timedelta(days=1)
    return (gapStart, gapEnd) if gapStart <= gapEnd else None


def weekdays_between(firstDate: date, lastDate: date) -> List[date]:
    days = []
    day = firstDate
    while day <= lastDate:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def format_bar(bar: Dict) -> Dict:
    return {
        'v': compact_number(bar.get('v') or 0),
        'o': compact_number(bar['o']),
        'c': compact_number(bar['c']),
        'h': compact_number(bar['h']),
        'l': compact_number(bar['l']),
        't': int(bar['t']),
        'n': int(bar.get('n') or 0),
    }


def aggregate_bars(minuteBars: List[Dict], minutes: int) -> List[Dict]:
    """Epoch-aligned buckets, which match Polygon's for US sessions (ET offsets are whole hours)"""
    bucketMs = minutes * 60_000
    buckets: Dict[int, Dict] = {}
    for bar in minuteBars:
        bucketStart = bar['t'] - bar['t'] % bucketMs
        bucket = buckets.get(bucketStart)
        if bucket is None:
            buckets[bucketStart] = {**bar, 't': bucketStart}
            continue
        bucket['h'] = max(bucket['h'], bar['h'])
        bucket['l'] = min(bucket['l'], bar['l'])
        bucket['c'] = bar['c']
        bucket['v'] = compact_number(bucket['v'] + bar['v'])
        bucket['n'] = bucket['n'] + bar['n']
    return [buckets[t] for t in sorted(buckets)]


def supplement_columns(rows: List[Tuple]) -> Dict[str, np.ndarray]:
    """rows: (ticker, session_date, window_start_ns, open, high, low, close, volume, transactions, source)"""
    return {
        'ticker': np.array([r[0] for r in rows]),
        'session_date': np.array([r[1].isoformat() for r in rows]),
        'window_start_ns': np.array([r[2] for r in rows], dtype=np.int64),
        'open': np.array([float(r[3]) for r in rows]),
        'high': np.array([float(r[4]) for r in rows]),
        'low': np.array([float(r[5]) for r in rows]),
        'close': np.array([float(r[6]) for r in rows]),
        'volume': np.array([float(r[7] or 0) for r in rows]),
        'transactions': np.array([int(r[8] or 0) for r in rows], dtype=np.int64),
        'source': np.array([r[9] for r in rows]),
    }


class SplitAdjuster:
    """Price multiplier per (symbol, session date): the product of split_from/split_to for
    every split executed after that session. Splits dated after today are ignored."""

    def __init__(self, splitRows: Iterable[Tuple[str, date, float, float]]):
        today = market_today()
        ratiosBySymbol: Dict[str, Dict[date, float]] = {}
        for ticker, executionDate, splitFrom, splitTo in splitRows:
            if not executionDate or executionDate > today or not splitFrom or not splitTo:
                continue
            if splitFrom <= 0 or splitTo <= 0:
                continue
            ratiosBySymbol.setdefault(ticker, {})[executionDate] = splitFrom / splitTo

        self.executionDates: Dict[str, List[date]] = {}
        self.suffixFactors: Dict[str, List[float]] = {}
        for ticker, ratiosByDate in ratiosBySymbol.items():
            dates = sorted(ratiosByDate)
            suffix = [1.0] * (len(dates) + 1)
            for i in range(len(dates) - 1, -1, -1):
                suffix[i] = suffix[i + 1] * ratiosByDate[dates[i]]
            self.executionDates[ticker] = dates
            self.suffixFactors[ticker] = suffix

    def factor(self, symbol: str, sessionDate: date) -> float:
        dates = self.executionDates.get(symbol)
        if not dates:
            return 1.0
        return self.suffixFactors[symbol][bisect_right(dates, sessionDate)]


class BarSeries:
    """Split-adjusted bars as parallel arrays; dicts are only built for the requested slice"""

    __slots__ = ('times', 'opens', 'highs', 'lows', 'closes', 'volumes', 'transactions')

    def __init__(self, symbol: str, rows: List[Tuple], adjuster: SplitAdjuster):
        self.times = array('q')
        self.opens, self.highs, self.lows, self.closes, self.volumes = (array('d') for _ in range(5))
        self.transactions = array('q')
        for sessionDate, windowStartNs, o, h, l, c, v, n in rows:
            factor = adjuster.factor(symbol, sessionDate)
            self.times.append(windowStartNs // 1_000_000)
            self.opens.append(o * factor)
            self.highs.append(h * factor)
            self.lows.append(l * factor)
            self.closes.append(c * factor)
            self.volumes.append((v or 0) / factor)
            self.transactions.append(int(n or 0))

    def to_bars(self, startMs: int, endMs: int) -> List[Dict]:
        lo, hi = bisect_left(self.times, startMs), bisect_right(self.times, endMs)
        return [
            {
                'v': compact_number(self.volumes[i]),
                'o': compact_number(self.opens[i]),
                'c': compact_number(self.closes[i]),
                'h': compact_number(self.highs[i]),
                'l': compact_number(self.lows[i]),
                't': self.times[i],
                'n': self.transactions[i],
            }
            for i in range(lo, hi)
        ]


@dataclass
class ArchiveCoverage:
    firstDate: date
    lastDate: date
    partitionMaxDates: Dict[Tuple[int, int], date]


class MarketDataStore:
    """
    Historical bars from the shared data store at DATA_ROOT (default ../data beside this repo).

    Reads the sureshot-marketdata archive (parquet/, falling back to raw/ flat files for
    sessions not yet converted) plus supplement/, where Polygon bars for sessions after
    the archive's last one are written back. The archive is the whole market, so only
    sessions after it are ever fetched. Everything on disk is unadjusted; bars are
    split-adjusted on read and returned in Polygon format {'v','o','c','h','l','t','n'}.

    Layout written here:
        supplement/bars/timeframe=1d/date={YYYY-MM-DD}.parquet     every ticker, one session
        supplement/bars/timeframe=1m/ticker={SYMBOL}/{START}_{END}.parquet
        supplement/splits/{YYYYMMDD}.parquet
    A file's name is what it covers, so a fetched session is never fetched again even
    when it held no trading.
    """

    def __init__(self, data_root: Optional[str] = None):
        self.dataRoot = resolve_data_root(data_root)
        if not (self.dataRoot / 'parquet').is_dir():
            raise FileNotFoundError(f"No market data archive at {self.dataRoot}/parquet (set DATA_ROOT)")
        self.supplementRoot = self.dataRoot / 'supplement'
        self._threadState = threading.local()
        self._lock = threading.RLock()
        self._dailySeries: 'OrderedDict[str, BarSeries]' = OrderedDict()
        self._minuteSeries: 'OrderedDict[Tuple[str, int, int], BarSeries]' = OrderedDict()
        self._failedFetches = set()
        self._coverage: Dict[str, Optional[ArchiveCoverage]] = {}
        self._rawOnlyFiles: Dict[str, Dict[date, str]] = {}
        self._adjuster: Optional[SplitAdjuster] = None
        logger.info(f"MarketDataStore reading {self.dataRoot}")

    def _connection(self) -> duckdb.DuckDBPyConnection:
        connection = getattr(self._threadState, 'connection', None)
        if connection is None:
            connection = duckdb.connect()
            connection.execute("SET TimeZone='UTC'")
            self._threadState.connection = connection
        return connection

    def _archive_glob(self, timeframe: str) -> str:
        return str(self.dataRoot / 'parquet' / ARCHIVE_DATASETS[timeframe] / '**' / '*.parquet')

    @staticmethod
    def _partition_key(timeframe: str, sessionDate: date) -> Tuple[int, int]:
        return (sessionDate.year, sessionDate.month if timeframe == '1m' else 0)

    def _archive_coverage(self, timeframe: str) -> Optional[ArchiveCoverage]:
        """Per-partition session_date range from Parquet footers; no row data is read"""
        with self._lock:
            if timeframe in self._coverage:
                return self._coverage[timeframe]
            try:
                rows = self._connection().execute(f"""
                    SELECT file_name, min(stats_min_value), max(stats_max_value)
                    FROM parquet_metadata({sql_string(self._archive_glob(timeframe))})
                    WHERE path_in_schema = 'session_date'
                    GROUP BY file_name
                """).fetchall()
            except duckdb.IOException:
                rows = []

            coverage = None
            if rows:
                partitionMaxDates = {}
                for fileName, minValue, maxValue in rows:
                    match = PARTITION_KEY.search(fileName.replace(os.sep, '/'))
                    key = (int(match.group(1)), int(match.group(2) or 0))
                    partitionMaxDates[key] = max(partitionMaxDates.get(key, date.min), date.fromisoformat(maxValue))
                coverage = ArchiveCoverage(
                    firstDate=min(date.fromisoformat(r[1]) for r in rows),
                    lastDate=max(partitionMaxDates.values()),
                    partitionMaxDates=partitionMaxDates,
                )
            self._coverage[timeframe] = coverage
            return coverage

    def _raw_only_files(self, timeframe: str) -> Dict[date, str]:
        """Raw flat files for sessions the Parquet conversion hasn't reached yet"""
        with self._lock:
            if timeframe in self._rawOnlyFiles:
                return self._rawOnlyFiles[timeframe]
            coverage = self._archive_coverage(timeframe)
            partitionMaxDates = coverage.partitionMaxDates if coverage else {}
            rawOnly = {}
            rawDir = self.dataRoot / 'raw' / 'flatfiles' / RAW_DATASETS[timeframe]
            for path in rawDir.glob('*/*/*.csv.gz'):
                match = RAW_FILE_DATE.search(path.name)
                if not match:
                    continue
                sessionDate = date.fromisoformat(match.group(1))
                partitionMax = partitionMaxDates.get(self._partition_key(timeframe, sessionDate))
                if partitionMax is None or sessionDate > partitionMax:
                    rawOnly[sessionDate] = str(path)
            self._rawOnlyFiles[timeframe] = rawOnly
            return rawOnly

    def archive_last_date(self, timeframe: str = '1d') -> Optional[date]:
        coverage = self._archive_coverage(timeframe)
        rawDates = self._raw_only_files(timeframe)
        candidates = ([coverage.lastDate] if coverage else []) + list(rawDates)
        return max(candidates) if candidates else None

    def _splits(self) -> SplitAdjuster:
        with self._lock:
            if self._adjuster is None:
                sources = []
                refSplits = self.dataRoot / 'parquet' / 'ref' / 'splits.parquet'
                if refSplits.is_file():
                    sources.append(sql_string(refSplits))
                if any((self.supplementRoot / 'splits').glob('*.parquet')):
                    sources.append(sql_string(self.supplementRoot / 'splits' / '*.parquet'))
                rows = []
                for source in sources:
                    rows += self._connection().execute(
                        f"SELECT ticker, execution_date, split_from, split_to FROM read_parquet({source})"
                    ).fetchall()
                self._adjuster = SplitAdjuster(rows)
            return self._adjuster

    def _read_archive_rows(self, timeframe: str, symbols: List[str], startDate: date, endDate: date) -> List[Tuple]:
        connection = self._connection()
        rows = []
        if self._archive_coverage(timeframe):
            filters = [f"year BETWEEN {startDate.year} AND {endDate.year}", "ticker IN (SELECT unnest(?))",
                       "session_date BETWEEN ? AND ?"]
            if timeframe == '1m' and (startDate.year, startDate.month) == (endDate.year, endDate.month):
                filters.append(f"month = '{startDate.month:02d}'")
            rows = connection.execute(f"""
                SELECT {BAR_SELECT}
                FROM read_parquet({sql_string(self._archive_glob(timeframe))}, hive_partitioning = true)
                WHERE {' AND '.join(filters)}
            """, [symbols, startDate, endDate]).fetchall()

        rawFiles = [p for d, p in self._raw_only_files(timeframe).items() if startDate <= d <= endDate]
        if rawFiles:
            rows += connection.execute(f"""
                SELECT ticker, regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})\\.csv\\.gz$', 1)::DATE,
                       window_start, open, high, low, close, volume::DOUBLE, transactions::BIGINT
                FROM read_csv([{', '.join(map(sql_string, rawFiles))}], filename = true)
                WHERE ticker IN (SELECT unnest(?))
            """, [symbols]).fetchall()
        return rows

    def _supplement_timeframe_folder(self, timeframe: str) -> Path:
        return self.supplementRoot / 'bars' / f'timeframe={timeframe}'

    def _minute_supplement_folder(self, symbol: str) -> Path:
        return self._supplement_timeframe_folder('1m') / f"ticker={symbol.replace('/', '_')}"

    def _stored_market_days(self) -> set:
        folder = self._supplement_timeframe_folder('1d')
        if not folder.is_dir():
            return set()
        return {date.fromisoformat(m.group(1)) for m in map(MARKET_DAY_FILE.match, os.listdir(folder)) if m}

    def _minute_supplement_coverage(self, symbol: str) -> List[Tuple[date, date]]:
        folder = self._minute_supplement_folder(symbol)
        if not folder.is_dir():
            return []
        return [
            tuple(datetime.strptime(g, '%Y%m%d').date() for g in m.groups())
            for m in map(SYMBOL_RANGE_FILE.match, os.listdir(folder)) if m
        ]

    def _read_supplement_rows(self, timeframe: str, symbols: List[str], startDate: date, endDate: date) -> List[Tuple]:
        if timeframe == '1d':
            globs = [self._supplement_timeframe_folder('1d') / 'date=*.parquet'] if self._stored_market_days() else []
        else:
            globs = [self._minute_supplement_folder(s) / '*.parquet' for s in symbols if self._minute_supplement_coverage(s)]
        if not globs:
            return []
        return self._connection().execute(f"""
            SELECT {BAR_SELECT}
            FROM read_parquet([{', '.join(map(sql_string, globs))}])
            WHERE ticker IN (SELECT unnest(?)) AND session_date BETWEEN ? AND ?
            QUALIFY row_number() OVER (PARTITION BY ticker, window_start_ns ORDER BY fetched_at_ns DESC) = 1
        """, [symbols, startDate, endDate]).fetchall()

    def _load_series(self, timeframe: str, symbols: List[str], startDate: date, endDate: date) -> Dict[str, BarSeries]:
        """Archive bars win over supplement bars that share a timestamp"""
        rowsBySymbol: Dict[str, Dict[int, Tuple]] = {symbol: {} for symbol in symbols}
        for row in self._read_supplement_rows(timeframe, symbols, startDate, endDate):
            rowsBySymbol[row[0]][row[2]] = row[1:]
        for row in self._read_archive_rows(timeframe, symbols, startDate, endDate):
            rowsBySymbol[row[0]][row[2]] = row[1:]
        adjuster = self._splits()
        return {
            symbol: BarSeries(symbol, [rowsByTime[t] for t in sorted(rowsByTime)], adjuster)
            for symbol, rowsByTime in rowsBySymbol.items()
        }

    def preload_daily(self, symbols: Iterable[str]):
        """Load many symbols' full daily history in a few queries instead of one per symbol"""
        with self._lock:
            pending = [s for s in dict.fromkeys(symbols) if s not in self._dailySeries]
        for i in range(0, len(pending), DAILY_PRELOAD_BATCH_SIZE):
            loaded = self._load_series('1d', pending[i:i + DAILY_PRELOAD_BATCH_SIZE], date(1900, 1, 1), date(2999, 12, 31))
            with self._lock:
                self._dailySeries.update(loaded)
                while len(self._dailySeries) > MAX_CACHED_DAILY_SYMBOLS:
                    self._dailySeries.popitem(last=False)

    def _daily_series(self, symbol: str) -> BarSeries:
        with self._lock:
            series = self._dailySeries.get(symbol)
            if series is not None:
                self._dailySeries.move_to_end(symbol)
                return series
        series = self._load_series('1d', [symbol], date(1900, 1, 1), date(2999, 12, 31))[symbol]
        with self._lock:
            self._dailySeries[symbol] = series
            while len(self._dailySeries) > MAX_CACHED_DAILY_SYMBOLS:
                self._dailySeries.popitem(last=False)
        return series

    def _minute_series(self, symbol: str, year: int, month: int) -> BarSeries:
        key = (symbol, year, month)
        with self._lock:
            series = self._minuteSeries.get(key)
            if series is not None:
                self._minuteSeries.move_to_end(key)
                return series
        monthStart = date(year, month, 1)
        monthEnd = (monthStart + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        series = self._load_series('1m', [symbol], monthStart, monthEnd)[symbol]
        with self._lock:
            self._minuteSeries[key] = series
            while len(self._minuteSeries) > MAX_CACHED_MINUTE_MONTHS:
                self._minuteSeries.popitem(last=False)
        return series

    def _series_for_range(self, timeframe: str, symbol: str, startDate: date, endDate: date) -> List[BarSeries]:
        if timeframe == '1d':
            return [self._daily_series(symbol)]
        months = []
        year, month = startDate.year, startDate.month
        while (year, month) <= (endDate.year, endDate.month):
            months.append(self._minute_series(symbol, year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return months

    def _write_supplement(self, target: Path, rows: List[Tuple]):
        """Atomic write so parallel backtests can fill gaps concurrently without locks"""
        target.parent.mkdir(parents=True, exist_ok=True)
        tempPath = target.parent / f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        connection = duckdb.connect()
        try:
            connection.execute(f"CREATE TABLE supplement_rows ({SUPPLEMENT_COLUMNS})")
            if rows:
                connection.register('source_rows', supplement_columns(rows))
                connection.execute(f"""
                    INSERT INTO supplement_rows
                    SELECT ticker, session_date::DATE, window_start_ns, open, high, low, close, volume,
                           transactions, source, {clock.time_ns()} FROM source_rows
                """)
            connection.execute(f"COPY (SELECT * FROM supplement_rows ORDER BY ticker, window_start_ns) "
                               f"TO {sql_string(tempPath)} (FORMAT parquet)")
        finally:
            connection.close()
        os.replace(tempPath, target)

    def _fill_market_days(self, startDate: date, endDate: date, fetch_market_day_fn: FetchMarketDayFn):
        """Every completed session after the archive, fetched once for the whole market"""
        archiveLast = self.archive_last_date('1d')
        if archiveLast is None:
            return
        lastCompleted = market_today() - timedelta(days=1)
        storedDays = self._stored_market_days()
        wroteAny = False
        for sessionDate in weekdays_between(max(startDate, archiveLast + timedelta(days=1)), min(endDate, lastCompleted)):
            if sessionDate in storedDays or ('1d', sessionDate) in self._failedFetches:
                continue
            bars = fetch_market_day_fn(sessionDate)
            if bars is None:
                # In-process only: a failed request must stay retryable by later runs
                self._failedFetches.add(('1d', sessionDate))
                continue
            rows = [
                (b['T'], sessionDate, market_midnight_ns(sessionDate), b['o'], b['h'], b['l'], b['c'],
                 b.get('v'), b.get('n'), b.get('src', 'unknown'))
                for b in bars if b.get('T')
            ]
            self._write_supplement(self._supplement_timeframe_folder('1d') / f"date={sessionDate}.parquet", rows)
            logger.info(f"Stored {len(rows)} daily bars for {sessionDate}")
            wroteAny = True
        if wroteAny:
            with self._lock:
                self._dailySeries.clear()

    def _fill_minute_gaps(self, symbol: str, startDate: date, endDate: date, fetch_fn: FetchFn) -> List[Dict]:
        """Persist completed sessions after the archive; returns today's bars, served but never
        written because they are still forming"""
        today = market_today()
        covered = self._minute_supplement_coverage(symbol)
        archiveLast = self.archive_last_date('1m')
        if archiveLast:
            covered.append((date(1900, 1, 1), archiveLast))
        gaps = [g for g in map(trim_weekends, subtract_ranges((startDate, min(endDate, today)), covered)) if g]

        todaysBars = []
        for gapStart, gapEnd in gaps:
            failedKey = (symbol, '1m', gapStart, gapEnd)
            if failedKey in self._failedFetches:
                continue
            fetched = fetch_fn(symbol, datetime.combine(gapStart, time.min),
                               datetime.combine(gapEnd, time(23, 59, 59)), '1m') or []
            barsInGap = [b for b in fetched if gapStart <= market_date(b['t']) <= gapEnd]
            todaysBars += [format_bar(b) for b in barsInGap if market_date(b['t']) >= today]

            coverageEnd = min(gapEnd, today - timedelta(days=1))
            completedRows = [
                (symbol, market_date(b['t']), int(b['t']) * 1_000_000, b['o'], b['h'], b['l'], b['c'],
                 b.get('v'), b.get('n'), b.get('src', 'unknown'))
                for b in barsInGap if market_date(b['t']) < today
            ]
            if completedRows and coverageEnd >= gapStart:
                target = self._minute_supplement_folder(symbol) / f"{gapStart:%Y%m%d}_{coverageEnd:%Y%m%d}.parquet"
                self._write_supplement(target, completedRows)
                logger.info(f"Stored {len(completedRows)} {symbol} 1m bars for {gapStart}..{coverageEnd}")
                with self._lock:
                    for key in [k for k in self._minuteSeries if k[0] == symbol]:
                        del self._minuteSeries[key]
            elif not barsInGap:
                # In-process only: a rate-limited failure looks identical to no data
                self._failedFetches.add(failedKey)
        return todaysBars

    def _todays_daily_bars(self, symbol: str, startDate: date, endDate: date, fetch_fn: FetchFn) -> List[Dict]:
        today = market_today()
        if not (startDate <= today <= endDate) or today.weekday() >= 5:
            return []
        fetched = fetch_fn(symbol, datetime.combine(today, time.min), datetime.combine(today, time(23, 59, 59)), '1d') or []
        return [{**format_bar(b), 't': market_midnight_ns(today) // 1_000_000} for b in fetched if market_date(b['t']) == today]

    def get(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = '1d',
        fetch_fn: Optional[FetchFn] = None,
        fetch_market_day_fn: Optional[FetchMarketDayFn] = None
    ) -> List[Dict]:
        """
        Split-adjusted bars with start_date <= bar time <= end_date (naive local datetimes,
        matching how bar 't' values are decoded elsewhere).

        Sessions after the archive are filled from the callbacks, which must return
        UNADJUSTED Polygon-format bars: fetch_market_day_fn(date) every ticker's daily bar
        for one completed session (None on failure), fetch_fn(symbol, start, end, timeframe)
        one symbol's minute bars, and today's still-forming daily bar.
        """
        if timeframe in AGGREGATED_TIMEFRAMES:
            minuteBars = self.get(symbol, start_date, end_date, '1m', fetch_fn, fetch_market_day_fn)
            return aggregate_bars(minuteBars, AGGREGATED_TIMEFRAMES[timeframe])
        if timeframe not in ARCHIVE_DATASETS:
            raise ValueError(f"MarketDataStore does not serve timeframe {timeframe!r}")

        startDate, endDate = start_date.date(), end_date.date()
        todaysBars = []
        if timeframe == '1d':
            if fetch_market_day_fn:
                self._fill_market_days(startDate, endDate, fetch_market_day_fn)
            if fetch_fn:
                todaysBars = self._todays_daily_bars(symbol, startDate, endDate, fetch_fn)
        elif fetch_fn:
            todaysBars = self._fill_minute_gaps(symbol, startDate, endDate, fetch_fn)

        startMs, endMs = int(start_date.timestamp() * 1000), int(end_date.timestamp() * 1000)
        bars = [bar for series in self._series_for_range(timeframe, symbol, startDate, endDate)
                for bar in series.to_bars(startMs, endMs)]
        storedTimes = {b['t'] for b in bars}
        bars += [b for b in todaysBars if startMs <= b['t'] <= endMs and b['t'] not in storedTimes]
        return bars

    def splits_refreshed_today(self) -> bool:
        return (self.supplementRoot / 'splits' / f"{market_today():%Y%m%d}.parquet").is_file()

    def save_splits(self, splits: List[Dict]):
        """Persist provider split events newer than the archive's reference table"""
        folder = self.supplementRoot / 'splits'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{market_today():%Y%m%d}.parquet"
        tempPath = folder / f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        validSplits = [s for s in splits if s.get('ticker') and s.get('execution_date')]
        connection = duckdb.connect()
        try:
            connection.execute("CREATE TABLE splits (ticker VARCHAR, execution_date DATE, split_from DOUBLE, split_to DOUBLE)")
            if validSplits:
                connection.register('provider_splits', {
                    'ticker': np.array([s['ticker'] for s in validSplits]),
                    'execution_date': np.array([s['execution_date'] for s in validSplits]),
                    'split_from': np.array([float(s.get('split_from') or 0) for s in validSplits]),
                    'split_to': np.array([float(s.get('split_to') or 0) for s in validSplits]),
                })
                connection.execute("INSERT INTO splits SELECT ticker, execution_date::DATE, split_from, split_to FROM provider_splits")
            connection.execute(f"COPY splits TO {sql_string(tempPath)} (FORMAT parquet)")
        finally:
            connection.close()
        os.replace(tempPath, target)
        with self._lock:
            self._adjuster = None
            self._dailySeries.clear()
            self._minuteSeries.clear()


_sharedStores: Dict[Path, MarketDataStore] = {}
_sharedStoresLock = threading.Lock()


def get_shared_store(data_root: Optional[str] = None) -> Optional[MarketDataStore]:
    """One store per data root per process; None where no archive exists (e.g. live pods)"""
    root = resolve_data_root(data_root)
    if not (root / 'parquet').is_dir():
        return None
    with _sharedStoresLock:
        if root not in _sharedStores:
            _sharedStores[root] = MarketDataStore(str(root))
        return _sharedStores[root]
