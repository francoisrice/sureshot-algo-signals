"""
Tests for HistoricalDataClient: Polygon-only reads without a data store,
MarketDataStore-backed reads and Polygon gap fills with one, and PolygonClient
interface parity.
"""

import importlib
import inspect
import os
import sys
from datetime import date, datetime
from unittest.mock import Mock, patch

import duckdb
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.HistoricalDataClient import HistoricalDataClient
from SureshotSDK.Polygon.client import PolygonClient
from .conftest import epoch_ms

historicalModule = importlib.import_module('SureshotSDK.HistoricalDataClient')

START = datetime(2026, 7, 1)
END = datetime(2026, 7, 10)

BARS = [
    {'t': int(datetime(2026, 7, 2).timestamp() * 1000), 'o': 1.0, 'h': 2.0, 'l': 0.5, 'c': 1.5, 'v': 100},
    {'t': int(datetime(2026, 7, 6).timestamp() * 1000), 'o': 1.5, 'h': 2.5, 'l': 1.0, 'c': 2.0, 'v': 200},
]


def grouped_day(sessionDate: date, closesByTicker: dict):
    return [
        {'T': ticker, 't': epoch_ms(sessionDate, 16), 'o': close, 'h': close, 'l': close, 'c': close, 'v': 100, 'n': 1}
        for ticker, close in closesByTicker.items()
    ]


def make_client(data_root, polygon_bars=None, grouped=None, polygon=True):
    """A data_root without parquet/ gives the store-less path used by live pods"""
    polygonClient = Mock()
    polygonClient.get_historical_data.return_value = polygon_bars if polygon_bars is not None else []
    polygonClient.get_unadjusted_historical_data.return_value = polygon_bars if polygon_bars is not None else []
    polygonClient.get_unadjusted_grouped_daily.side_effect = grouped or (lambda sessionDate: [])
    polygonClient.get_splits.return_value = []
    client = HistoricalDataClient(polygon_client=polygonClient if polygon else None, data_root=str(data_root))
    if not polygon:
        client.polygon_client = None
    return client, polygonClient


@pytest.fixture(autouse=True)
def reset_splits_refresh(monkeypatch):
    monkeypatch.setattr(historicalModule, '_splitsRefreshAttempted', False)


class TestInitialization:

    @patch.dict(os.environ, {}, clear=True)
    def test_no_source_raises_error(self, tmp_path):
        with pytest.raises(ValueError, match="No market data source found"):
            HistoricalDataClient(data_root=str(tmp_path))

    @patch.dict(os.environ, {'POLYGON_API_KEY': 'poly_key'}, clear=True)
    def test_polygon_key_alone_is_sufficient(self, tmp_path):
        client = HistoricalDataClient(data_root=str(tmp_path))
        assert client.polygon_client is not None
        assert client.market_store is None

    @patch.dict(os.environ, {}, clear=True)
    def test_data_store_alone_is_sufficient(self, market_archive):
        client = HistoricalDataClient(data_root=str(market_archive))
        assert client.polygon_client is None
        assert [b['c'] for b in client.get_historical_data('SPY', START, END, '1d')] == [100, 101, 102, 103]

    @patch.dict(os.environ, {'LONDONSTRATEGICEDGE_API_KEY': 'lse_key'}, clear=True)
    def test_lse_key_is_not_a_source(self, tmp_path):
        with pytest.raises(ValueError, match="No market data source found"):
            HistoricalDataClient(data_root=str(tmp_path))


class TestWithoutDataStore:

    def test_bars_come_from_polygon_adjusted(self, tmp_path):
        client, polygon = make_client(tmp_path, polygon_bars=BARS)
        assert client.get_historical_data('SPY', START, END, '1d') == BARS
        polygon.get_historical_data.assert_called_once()
        polygon.get_unadjusted_historical_data.assert_not_called()

    def test_returns_empty_when_polygon_fails(self, tmp_path):
        client, polygon = make_client(tmp_path)
        polygon.get_historical_data.side_effect = RuntimeError("down")
        assert client.get_historical_data('SPY', START, END, '1d') == []

    def test_current_price_from_polygon(self, tmp_path):
        client, polygon = make_client(tmp_path)
        polygon.get_current_price.return_value = 100.5
        assert client.get_current_price('SPY') == 100.5


def stored_market_rows(data_root):
    return duckdb.sql(
        f"SELECT ticker, close, source FROM '{data_root}/supplement/bars/timeframe=1d/*.parquet' ORDER BY ALL"
    ).fetchall()


class TestWithDataStore:

    def test_archive_bars_served_without_polygon_calls(self, market_archive):
        client, polygon = make_client(market_archive)
        data = client.get_historical_data('SPY', START, datetime(2026, 7, 7), '1d')
        assert [b['c'] for b in data] == [100, 101, 102, 103]
        polygon.get_unadjusted_grouped_daily.assert_not_called()
        polygon.get_historical_data.assert_not_called()

    def test_daily_gap_filled_from_grouped_polygon_bars(self, market_archive):
        client, polygon = make_client(market_archive, grouped=lambda d: grouped_day(d, {'SPY': 104.0, 'ABC': 60.0}))
        data = client.get_historical_data('SPY', START, END, '1d')
        assert [b['c'] for b in data][-3:] == [104, 104, 104]
        assert polygon.get_unadjusted_grouped_daily.call_count == 3
        polygon.get_historical_data.assert_not_called()
        assert ('ABC', 60.0, 'polygon') in stored_market_rows(market_archive)

    def test_minute_gap_filled_from_unadjusted_polygon_bars(self, market_archive):
        minuteBar = {'t': epoch_ms(date(2026, 7, 2), 9, 30), 'o': 1.0, 'h': 1.0, 'l': 1.0, 'c': 1.0, 'v': 1, 'n': 1}
        client, polygon = make_client(market_archive, polygon_bars=[minuteBar])
        client.get_historical_data('SPY', datetime(2026, 7, 2), datetime(2026, 7, 2, 23, 59), '1min')
        polygon.get_unadjusted_historical_data.assert_called_once()
        assert polygon.get_unadjusted_historical_data.call_args[0][3] == '1m'
        assert os.listdir(market_archive / 'supplement' / 'bars') == ['timeframe=1m']

    def test_splits_refreshed_before_gap_fill(self, market_archive):
        client, polygon = make_client(market_archive, grouped=lambda d: [])
        client.get_historical_data('SPY', START, END, '1d')
        polygon.get_splits.assert_called_once()

    def test_without_polygon_only_the_archive_is_served(self, market_archive):
        client, _ = make_client(market_archive, polygon=False)
        data = client.get_historical_data('SPY', START, END, '1d')
        assert [b['c'] for b in data] == [100, 101, 102, 103]
        assert not (market_archive / 'supplement').exists()

    def test_historical_price_read_from_store(self, market_archive):
        client, polygon = make_client(market_archive)
        assert client.get_historical_price('SPY', datetime(2026, 7, 1, 9, 35), '1m') == 105.25
        polygon.get_historical_price.assert_not_called()

    def test_single_day_price_read_from_store(self, market_archive):
        client, polygon = make_client(market_archive)
        assert client.get_single_day_price('SPY', datetime(2026, 7, 6)) == 102
        polygon.get_single_day_price.assert_not_called()


class TestPolygonInterfaceParity:

    SHARED_METHODS = [
        'get_historical_data', 'get_ohlcv_data', 'get_close_prices',
        'get_single_day_price', 'get_historical_price', 'get_current_price',
        'get_last_quote', 'is_market_open',
    ]

    @pytest.mark.parametrize('method_name', SHARED_METHODS)
    def test_method_signatures_match_polygon(self, method_name):
        polygonParams = list(inspect.signature(getattr(PolygonClient, method_name)).parameters)
        wrapperParams = list(inspect.signature(getattr(HistoricalDataClient, method_name)).parameters)
        assert wrapperParams == polygonParams

    def test_get_close_prices_and_ohlcv_derive_from_historical_data(self, tmp_path):
        client, _ = make_client(tmp_path, polygon_bars=BARS)
        assert client.get_close_prices('SPY', START, END, '1d') == [1.5, 2.0]
        ohlcv = client.get_ohlcv_data('SPY', START, END, '1d')
        assert ohlcv[0][4] == 1.5
