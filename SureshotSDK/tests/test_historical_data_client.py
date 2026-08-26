"""
Tests for HistoricalDataClient: cache -> London Strategic Edge -> Polygon
fallback ordering, cache persistence regardless of provider, and
PolygonClient interface parity.
"""

import inspect
import pytest
from unittest.mock import Mock, patch
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.HistoricalDataClient import HistoricalDataClient
from SureshotSDK.Polygon.client import PolygonClient

START = datetime(2026, 7, 1)
END = datetime(2026, 7, 10)

BARS = [
    {'t': int(datetime(2026, 7, 2).timestamp() * 1000), 'o': 1.0, 'h': 2.0, 'l': 0.5, 'c': 1.5, 'v': 100},
    {'t': int(datetime(2026, 7, 6).timestamp() * 1000), 'o': 1.5, 'h': 2.5, 'l': 1.0, 'c': 2.0, 'v': 200},
]


def make_client(tmp_path, lse_bars=None, polygon_bars=None, lse=True, polygon=True):
    lseClient = Mock()
    polygonClient = Mock()
    lseClient.get_historical_data.return_value = lse_bars if lse_bars is not None else []
    polygonClient.get_historical_data.return_value = polygon_bars if polygon_bars is not None else []
    client = HistoricalDataClient(
        lse_client=lseClient if lse else Mock(),
        polygon_client=polygonClient if polygon else Mock(),
        cache_dir=str(tmp_path)
    )
    if not lse:
        client.lse_client = None
    if not polygon:
        client.polygon_client = None
    return client, lseClient, polygonClient


class TestInitialization:

    @patch.dict(os.environ, {}, clear=True)
    def test_no_keys_raises_error(self, tmp_path):
        with pytest.raises(ValueError, match="No market data API key found"):
            HistoricalDataClient(cache_dir=str(tmp_path))

    @patch.dict(os.environ, {'LONDONSTRATEGICEDGE_API_KEY': 'lse_key'}, clear=True)
    def test_lse_key_alone_is_sufficient(self, tmp_path):
        client = HistoricalDataClient(cache_dir=str(tmp_path))
        assert client.lse_client is not None
        assert client.polygon_client is None

    @patch.dict(os.environ, {'POLYGON_API_KEY': 'poly_key'}, clear=True)
    def test_polygon_key_alone_is_sufficient(self, tmp_path):
        client = HistoricalDataClient(cache_dir=str(tmp_path))
        assert client.polygon_client is not None
        assert client.lse_client is None


class TestFallbackOrdering:

    def test_lse_preferred_for_historical_data(self, tmp_path):
        client, lse, polygon = make_client(tmp_path, lse_bars=BARS)
        data = client.get_historical_data('SPY', START, END, '1d')
        assert data == BARS
        lse.get_historical_data.assert_called_once()
        polygon.get_historical_data.assert_not_called()

    def test_falls_back_to_polygon_when_lse_empty(self, tmp_path):
        client, lse, polygon = make_client(tmp_path, lse_bars=[], polygon_bars=BARS)
        data = client.get_historical_data('SPY', START, END, '1d')
        assert data == BARS
        lse.get_historical_data.assert_called_once()
        polygon.get_historical_data.assert_called_once()

    def test_falls_back_to_polygon_when_lse_raises(self, tmp_path):
        client, lse, polygon = make_client(tmp_path, polygon_bars=BARS)
        lse.get_historical_data.side_effect = RuntimeError("LSE down")
        data = client.get_historical_data('SPY', START, END, '1d')
        assert data == BARS

    def test_returns_empty_when_all_providers_fail(self, tmp_path):
        client, lse, polygon = make_client(tmp_path)
        lse.get_historical_data.side_effect = RuntimeError("down")
        polygon.get_historical_data.side_effect = RuntimeError("down")
        assert client.get_historical_data('SPY', START, END, '1d') == []

    def test_polygon_preferred_for_current_price(self, tmp_path):
        client, lse, polygon = make_client(tmp_path)
        polygon.get_current_price.return_value = 100.5
        assert client.get_current_price('SPY') == 100.5
        polygon.get_current_price.assert_called_once()
        lse.get_current_price.assert_not_called()

    def test_current_price_falls_back_to_lse(self, tmp_path):
        client, lse, polygon = make_client(tmp_path)
        polygon.get_current_price.return_value = None
        lse.get_current_price.return_value = 99.5
        assert client.get_current_price('SPY') == 99.5


class TestCachePersistence:
    """Fetched bars must be stored on disk for subsequent runs, no matter
    which provider served them"""

    def test_lse_fetch_is_written_to_cache(self, tmp_path):
        client, _, _ = make_client(tmp_path, lse_bars=BARS)
        client.get_historical_data('SPY', START, END, '1d')
        assert os.listdir(tmp_path) == ['SPY_1d_20260701_20260710.json']

    def test_polygon_fetch_is_written_to_cache(self, tmp_path):
        client, _, _ = make_client(tmp_path, polygon_bars=BARS)
        client.get_historical_data('SPY', START, END, '1d')
        assert os.listdir(tmp_path) == ['SPY_1d_20260701_20260710.json']

    def test_cached_data_served_without_provider_calls(self, tmp_path):
        first, _, _ = make_client(tmp_path, lse_bars=BARS)
        fetched = first.get_historical_data('SPY', START, END, '1d')

        second, lse, polygon = make_client(tmp_path)
        cached = second.get_historical_data('SPY', START, END, '1d')

        assert cached == fetched
        lse.get_historical_data.assert_not_called()
        polygon.get_historical_data.assert_not_called()

    def test_range_extension_is_fetched_and_persisted(self, tmp_path):
        first, _, _ = make_client(tmp_path, lse_bars=BARS)
        first.get_historical_data('SPY', START, END, '1d')

        extensionBars = [
            {'t': int(datetime(2026, 7, 14).timestamp() * 1000), 'o': 2.0, 'h': 3.0, 'l': 1.5, 'c': 2.5, 'v': 300},
        ]
        second, lse, _ = make_client(tmp_path, lse_bars=extensionBars)
        data = second.get_historical_data('SPY', START, datetime(2026, 7, 15), '1d')

        assert len(data) == len(BARS) + 1
        lse.get_historical_data.assert_called_once()
        assert os.listdir(tmp_path) == ['SPY_1d_20260701_20260715.json']

    def test_empty_fetch_writes_nothing(self, tmp_path):
        client, _, _ = make_client(tmp_path)
        assert client.get_historical_data('SPY', START, END, '1d') == []
        assert os.listdir(tmp_path) == []


class TestTimeframeNormalization:

    def test_1min_alias_normalized_before_provider_call(self, tmp_path):
        client, lse, _ = make_client(tmp_path, lse_bars=BARS)
        client.get_historical_data('SPY', START, END, '1min')
        assert lse.get_historical_data.call_args[0][3] == '1m'

    def test_1min_and_1m_share_one_cache_entry(self, tmp_path):
        client, _, _ = make_client(tmp_path, lse_bars=BARS)
        client.get_historical_data('SPY', START, END, '1min')
        assert os.listdir(tmp_path) == ['SPY_1m_20260701_20260710.json']


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

    def test_get_close_prices_and_ohlcv_derive_from_cached_data(self, tmp_path):
        client, _, _ = make_client(tmp_path, lse_bars=BARS)
        assert client.get_close_prices('SPY', START, END, '1d') == [1.5, 2.0]
        ohlcv = client.get_ohlcv_data('SPY', START, END, '1d')
        assert ohlcv[0][4] == 1.5
