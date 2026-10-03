"""
Tests for MarketDataStore: archive reads in Polygon bar format, read-time split
adjustment, raw flat-file fallback, and Polygon gap fills for sessions after the
archive written to supplement/.
"""

import importlib
import os
import sys
from datetime import date, datetime
from unittest.mock import Mock

import duckdb
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.MarketDataStore import MarketDataStore, aggregate_bars, subtract_ranges, trim_weekends
from .conftest import ARCHIVE_DAYS, day_row, epoch_ms, write_raw_day_file

storeModule = importlib.import_module('SureshotSDK.MarketDataStore')


def raw_bar(sessionDate: date, close: float, hour: int = 0, minute: int = 0, **extra):
    return {'t': epoch_ms(sessionDate, hour, minute), 'o': close, 'h': close + 1, 'l': close - 1, 'c': close, 'v': 500, 'n': 5, **extra}


def grouped_day(sessionDate: date, closesByTicker: dict):
    """Polygon grouped-daily shape: 't' is the 16:00 ET close, not the archive's midnight"""
    return [raw_bar(sessionDate, close, 16, 0, T=ticker, src='polygon') for ticker, close in closesByTicker.items()]


def market_day_files(root):
    folder = root / 'supplement' / 'bars' / 'timeframe=1d'
    return sorted(os.listdir(folder)) if folder.is_dir() else []


def minute_files(root, symbol):
    folder = root / 'supplement' / 'bars' / 'timeframe=1m' / f'ticker={symbol}'
    return sorted(os.listdir(folder)) if folder.is_dir() else []


class TestArchiveReads:

    def test_daily_bars_use_polygon_format_and_timestamps(self, market_archive):
        bars = MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 7))
        assert [b['t'] for b in bars] == [epoch_ms(d) for d in ARCHIVE_DAYS]
        assert [b['c'] for b in bars] == [100, 101, 102, 103]
        assert set(bars[0]) == {'v', 'o', 'c', 'h', 'l', 't', 'n'}

    def test_range_is_inclusive_of_the_end_session(self, market_archive):
        bars = MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 2), datetime(2026, 7, 6))
        assert [b['c'] for b in bars] == [101, 102]

    def test_bars_before_a_split_are_adjusted(self, market_archive):
        bars = MarketDataStore(str(market_archive)).get('ABC', datetime(2026, 7, 1), datetime(2026, 7, 7))
        assert [b['c'] for b in bars] == [25, 25, 50, 50]
        assert [b['v'] for b in bars] == [2000, 2000, 1000, 1000]

    def test_splits_dated_after_today_are_ignored(self, market_archive):
        bars = MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 7))
        assert bars[0]['c'] == 100

    def test_raw_flat_file_serves_sessions_parquet_lacks(self, market_archive):
        write_raw_day_file(market_archive, [day_row('SPY', date(2026, 7, 8), 104.0)])
        store = MarketDataStore(str(market_archive))
        bars = store.get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 8))
        assert bars[-1]['t'] == epoch_ms(date(2026, 7, 8))
        assert bars[-1]['c'] == 104
        assert store.archive_last_date('1d') == date(2026, 7, 8)

    def test_minute_bars_and_aggregated_timeframes(self, market_archive):
        store = MarketDataStore(str(market_archive))
        session = ARCHIVE_DAYS[0]
        minuteBars = store.get('SPY', datetime(2026, 7, 1, 9, 30), datetime(2026, 7, 1, 9, 49), '1m')
        assert len(minuteBars) == 20

        fifteenMinuteBars = store.get('SPY', datetime(2026, 7, 1, 9, 30), datetime(2026, 7, 1, 9, 49), '15m')
        assert [b['t'] for b in fifteenMinuteBars] == [epoch_ms(session, 9, 30), epoch_ms(session, 9, 45)]
        first = fifteenMinuteBars[0]
        assert (first['o'], first['c'], first['h'], first['l']) == (100, 114.25, 114.5, 99.5)
        assert first['v'] == 1500


    def test_preload_matches_individual_loads(self, market_archive):
        preloaded = MarketDataStore(str(market_archive))
        preloaded.preload_daily(['SPY', 'ABC', 'XYZ'])
        individual = MarketDataStore(str(market_archive))
        for symbol in ['SPY', 'ABC', 'XYZ']:
            assert preloaded.get(symbol, datetime(2026, 7, 1), datetime(2026, 7, 7)) == \
                individual.get(symbol, datetime(2026, 7, 1), datetime(2026, 7, 7))
        assert preloaded.get('XYZ', datetime(2026, 7, 1), datetime(2026, 7, 7)) == []


class TestDailyGapFills:

    def test_each_missing_session_is_fetched_once_for_the_whole_market(self, market_archive):
        fetchDay = Mock(side_effect=lambda d: grouped_day(d, {'SPY': 105.0, 'ABC': 60.0}))
        store = MarketDataStore(str(market_archive))
        bars = store.get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 10), fetch_market_day_fn=fetchDay)

        assert [call.args[0] for call in fetchDay.call_args_list] == [date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)]
        assert market_day_files(market_archive) == ['date=2026-07-08.parquet', 'date=2026-07-09.parquet', 'date=2026-07-10.parquet']
        assert [b['c'] for b in bars][-3:] == [105, 105, 105]

        otherSymbol = store.get('ABC', datetime(2026, 7, 8), datetime(2026, 7, 10), fetch_market_day_fn=fetchDay)
        assert [b['c'] for b in otherSymbol] == [60, 60, 60]
        assert fetchDay.call_count == 3

    def test_filled_sessions_use_the_archives_midnight_timestamp(self, market_archive):
        bars = MarketDataStore(str(market_archive)).get(
            'SPY', datetime(2026, 7, 8), datetime(2026, 7, 8),
            fetch_market_day_fn=lambda d: grouped_day(d, {'SPY': 105.0})
        )
        assert [b['t'] for b in bars] == [epoch_ms(date(2026, 7, 8))]

    def test_stored_sessions_are_not_fetched_by_later_runs(self, market_archive):
        MarketDataStore(str(market_archive)).get(
            'SPY', datetime(2026, 7, 1), datetime(2026, 7, 10),
            fetch_market_day_fn=lambda d: grouped_day(d, {'SPY': 105.0})
        )
        fetchDay = Mock(return_value=[])
        bars = MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 10), fetch_market_day_fn=fetchDay)
        fetchDay.assert_not_called()
        assert len(bars) == 7

    def test_sessions_within_the_archive_are_never_fetched(self, market_archive):
        fetchDay, fetch = Mock(return_value=[]), Mock(return_value=[])
        bars = MarketDataStore(str(market_archive)).get(
            'XYZ', datetime(2026, 7, 1), datetime(2026, 7, 7), fetch_fn=fetch, fetch_market_day_fn=fetchDay
        )
        assert bars == []
        fetchDay.assert_not_called()
        fetch.assert_not_called()

    def test_holiday_is_stored_as_covered(self, market_archive):
        store = MarketDataStore(str(market_archive))
        store.get('SPY', datetime(2026, 7, 8), datetime(2026, 7, 8), fetch_market_day_fn=Mock(return_value=[]))
        assert market_day_files(market_archive) == ['date=2026-07-08.parquet']
        fetchDay = Mock(return_value=[])
        MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 8), datetime(2026, 7, 8), fetch_market_day_fn=fetchDay)
        fetchDay.assert_not_called()

    def test_failed_fetch_is_not_stored_or_retried_in_process(self, market_archive):
        store = MarketDataStore(str(market_archive))
        fetchDay = Mock(return_value=None)
        store.get('SPY', datetime(2026, 7, 8), datetime(2026, 7, 8), fetch_market_day_fn=fetchDay)
        store.get('SPY', datetime(2026, 7, 8), datetime(2026, 7, 8), fetch_market_day_fn=fetchDay)
        assert fetchDay.call_count == 1
        assert market_day_files(market_archive) == []

    def test_filled_bars_are_split_adjusted_on_read(self, market_archive):
        fetchDay = Mock(side_effect=lambda d: grouped_day(d, {'NEW': 50.0 if d < date(2026, 7, 9) else 25.0}))
        bars = MarketDataStore(str(market_archive)).get('NEW', datetime(2026, 7, 8), datetime(2026, 7, 9), fetch_market_day_fn=fetchDay)
        assert [b['c'] for b in bars] == [25, 25]

    def test_todays_bar_is_served_but_never_stored(self, market_archive, monkeypatch):
        monkeypatch.setattr(storeModule, 'market_today', lambda: date(2026, 7, 9))
        fetchDay = Mock(side_effect=lambda d: grouped_day(d, {'SPY': 104.0}))
        fetch = Mock(return_value=[raw_bar(date(2026, 7, 9), 105.0, 16, 0)])
        bars = MarketDataStore(str(market_archive)).get(
            'SPY', datetime(2026, 7, 1), datetime(2026, 7, 9), fetch_fn=fetch, fetch_market_day_fn=fetchDay
        )
        assert [call.args[0] for call in fetchDay.call_args_list] == [date(2026, 7, 8)]
        assert [(b['t'], b['c']) for b in bars][-2:] == [(epoch_ms(date(2026, 7, 8)), 104), (epoch_ms(date(2026, 7, 9)), 105)]
        assert market_day_files(market_archive) == ['date=2026-07-08.parquet']

    def test_market_day_file_holds_raw_prices_and_source(self, market_archive):
        MarketDataStore(str(market_archive)).get(
            'NEW', datetime(2026, 7, 8), datetime(2026, 7, 8),
            fetch_market_day_fn=lambda d: grouped_day(d, {'NEW': 50.0, 'SPY': 104.0})
        )
        stored = duckdb.sql(
            f"SELECT ticker, close, source FROM '{market_archive}/supplement/bars/timeframe=1d/*.parquet' ORDER BY ticker"
        ).fetchall()
        assert stored == [('NEW', 50.0, 'polygon'), ('SPY', 104.0, 'polygon')]


class TestMinuteGapFills:

    def test_sessions_after_the_archive_are_fetched_per_symbol_and_stored(self, market_archive):
        fetch = Mock(return_value=[raw_bar(date(2026, 7, 2), 101.0, 9, 30, src='polygon')])
        bars = MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 2), datetime(2026, 7, 2, 23, 59), '1m', fetch_fn=fetch)
        fetch.assert_called_once_with('SPY', datetime(2026, 7, 2), datetime(2026, 7, 2, 23, 59, 59), '1m')
        assert [b['c'] for b in bars] == [101]
        assert minute_files(market_archive, 'SPY') == ['20260702_20260702.parquet']

    def test_minute_sessions_within_the_archive_are_not_fetched(self, market_archive):
        fetch = Mock(return_value=[])
        MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 1, 23, 59), '1m', fetch_fn=fetch)
        fetch.assert_not_called()

    def test_stored_minutes_are_not_fetched_again(self, market_archive):
        MarketDataStore(str(market_archive)).get(
            'SPY', datetime(2026, 7, 2), datetime(2026, 7, 2, 23, 59), '1m',
            fetch_fn=Mock(return_value=[raw_bar(date(2026, 7, 2), 101.0, 9, 30)])
        )
        fetch = Mock(return_value=[])
        bars = MarketDataStore(str(market_archive)).get('SPY', datetime(2026, 7, 2), datetime(2026, 7, 2, 23, 59), '1m', fetch_fn=fetch)
        fetch.assert_not_called()
        assert len(bars) == 1


class TestSplitTable:

    def test_saved_provider_splits_apply_to_archive_bars(self, market_archive):
        store = MarketDataStore(str(market_archive))
        store.get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 7))
        store.save_splits([{'ticker': 'SPY', 'execution_date': '2026-07-06', 'split_from': 1, 'split_to': 4}])
        bars = store.get('SPY', datetime(2026, 7, 1), datetime(2026, 7, 7))
        assert [b['c'] for b in bars] == [25, 25.25, 102, 103]
        assert store.splits_refreshed_today()

    def test_empty_split_refresh_still_marks_today_done(self, market_archive):
        store = MarketDataStore(str(market_archive))
        store.save_splits([])
        assert store.splits_refreshed_today()
        assert store.get('ABC', datetime(2026, 7, 1), datetime(2026, 7, 1))[0]['c'] == 25


class TestHelpers:

    def test_subtract_ranges_leaves_uncovered_edges(self):
        gaps = subtract_ranges((date(2026, 7, 1), date(2026, 7, 31)), [(date(2026, 7, 5), date(2026, 7, 10))])
        assert gaps == [(date(2026, 7, 1), date(2026, 7, 4)), (date(2026, 7, 11), date(2026, 7, 31))]

    def test_trim_weekends_drops_weekend_only_gaps(self):
        assert trim_weekends((date(2026, 7, 11), date(2026, 7, 12))) is None
        assert trim_weekends((date(2026, 7, 11), date(2026, 7, 14))) == (date(2026, 7, 13), date(2026, 7, 14))

    def test_missing_archive_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            MarketDataStore(str(tmp_path))

    def test_aggregate_keeps_first_open_and_last_close(self):
        session = date(2026, 7, 1)
        bars = [raw_bar(session, 10.0, 9, 30), raw_bar(session, 12.0, 9, 31)]
        assert aggregate_bars(bars, 5) == [{**bars[0], 'c': 12.0, 'h': 13.0, 'v': 1000, 'n': 10}]
