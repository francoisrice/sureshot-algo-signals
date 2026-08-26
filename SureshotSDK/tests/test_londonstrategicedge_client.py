"""
Tests for LondonStrategicEdgeClient: normalization to Polygon bar format,
timestamp handling, pagination, error handling, and PolygonClient parity.
"""

import inspect
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
import requests
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.LondonStrategicEdge.client import LondonStrategicEdgeClient
from SureshotSDK.Polygon.client import PolygonClient


def make_response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        response.raise_for_status.return_value = None
    return response


def make_client():
    client = LondonStrategicEdgeClient(api_key='test_key')
    client.minRequestInterval = 0
    return client


DAILY_ROWS = [
    {"ts": "2026-08-21 00:00:00.000000", "symbol": "SPY",
     "open": 764.69, "high": 767.84, "low": 764.17, "close": 767.0, "volume": 32516198},
    {"ts": "2026-08-24 00:00:00.000000", "symbol": "SPY",
     "open": 764.14, "high": 767.19, "low": 762.07, "close": 763.65, "volume": 25661855},
]

MINUTE_ROWS = [
    {"ts": "2026-08-24 13:30:00.000000", "symbol": "SPY",
     "open": 764.0, "high": 764.5, "low": 763.8, "close": 764.2, "volume": 100000},
    {"ts": "2026-08-24 13:31:00.000000", "symbol": "SPY",
     "open": 764.2, "high": 764.6, "low": 764.0, "close": 764.4, "volume": 90000},
]


class TestInitialization:

    def test_initialization_with_api_key(self):
        client = LondonStrategicEdgeClient(api_key='test_key_123')
        assert client.api_key == 'test_key_123'
        assert client.base_url == 'https://api.londonstrategicedge.com/vault'

    @patch.dict(os.environ, {'LONDONSTRATEGICEDGE_API_KEY': 'env_key_456'})
    def test_initialization_from_environment(self):
        client = LondonStrategicEdgeClient()
        assert client.api_key == 'env_key_456'

    @patch.dict(os.environ, {}, clear=True)
    def test_initialization_without_api_key_raises_error(self):
        with pytest.raises(ValueError, match="LONDONSTRATEGICEDGE_API_KEY not found"):
            LondonStrategicEdgeClient()

    def test_api_key_sent_as_header(self):
        client = LondonStrategicEdgeClient(api_key='header_key')
        assert client.session.headers['x-api-key'] == 'header_key'


class TestPolygonInterfaceParity:
    """The two clients must be drop-in interchangeable"""

    SHARED_METHODS = [
        'get_historical_data', 'get_ohlcv_data', 'get_close_prices',
        'get_single_day_price', 'get_historical_price', 'get_current_price',
        'get_last_quote', 'is_market_open',
    ]

    @pytest.mark.parametrize('method_name', SHARED_METHODS)
    def test_method_signatures_match_polygon(self, method_name):
        polygonParams = list(inspect.signature(getattr(PolygonClient, method_name)).parameters)
        lseParams = list(inspect.signature(getattr(LondonStrategicEdgeClient, method_name)).parameters)
        assert lseParams == polygonParams

    def test_constructor_accepts_polygon_kwargs(self):
        client = LondonStrategicEdgeClient(api_key='k', use_vault=True)
        assert client.api_key == 'k'

    def test_keyword_call_style_matches_polygon(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(DAILY_ROWS))
        data = client.get_historical_data(
            symbol='SPY',
            start_date=datetime(2026, 8, 21),
            end_date=datetime(2026, 8, 24),
            timeframe='1d'
        )
        assert len(data) == 2


class TestGetHistoricalData:

    def test_daily_bars_normalized_to_polygon_format(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(DAILY_ROWS))

        data = client.get_historical_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')

        assert len(data) == 2
        for bar in data:
            assert set(bar.keys()) == {'t', 'o', 'h', 'l', 'c', 'v'}
        assert data[0]['c'] == 767.0
        assert data[1]['v'] == 25661855

    def test_daily_bar_timestamp_anchored_to_local_midnight(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(DAILY_ROWS))

        data = client.get_historical_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')

        assert datetime.fromtimestamp(data[0]['t'] / 1000) == datetime(2026, 8, 21)

    def test_intraday_bar_timestamp_converted_from_utc(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(MINUTE_ROWS))

        data = client.get_historical_data('SPY', datetime(2026, 8, 24, 9, 30), datetime(2026, 8, 24, 16, 0), '1m')

        expected = int(datetime(2026, 8, 24, 13, 30, tzinfo=timezone.utc).timestamp() * 1000)
        assert data[0]['t'] == expected

    def test_daily_query_end_date_pushed_past_exclusive_bound(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(DAILY_ROWS))

        client.get_historical_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')

        params = client.session.get.call_args[1]['params']
        assert params['start'] == '2026-08-21'
        assert params['end'] == '2026-08-25'
        assert params['timeframe'] == '1d'
        assert params['order'] == 'asc'

    def test_timeframe_aliases_normalized(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(MINUTE_ROWS))

        client.get_historical_data('SPY', datetime(2026, 8, 24), datetime(2026, 8, 25), '1min')

        assert client.session.get.call_args[1]['params']['timeframe'] == '1m'

    def test_unsupported_timeframe_returns_empty(self):
        client = make_client()
        client.session.get = Mock()
        data = client.get_historical_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), 'bogus')
        assert data == []
        client.session.get.assert_not_called()

    def test_pagination_past_row_cap(self):
        client = make_client()
        fullPage = [
            {"ts": f"2026-08-24 {13 + i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}", "symbol": "SPY",
             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}
            for i in range(LondonStrategicEdgeClient.MAX_ROWS_PER_REQUEST)
        ]
        secondPage = [
            {"ts": "2026-08-24 19:58:00", "symbol": "SPY",
             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
            {"ts": "2026-08-24 19:59:00", "symbol": "SPY",
             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
        ]
        client.session.get = Mock(side_effect=[
            make_response(fullPage),
            make_response(secondPage),
        ])

        data = client.get_historical_data('SPY', datetime(2026, 8, 24), datetime(2026, 8, 25), '1m')

        assert client.session.get.call_count == 2
        assert len(data) == len(fullPage) + len(secondPage)

    def test_retries_once_on_429(self):
        client = make_client()
        client.session.get = Mock(side_effect=[
            make_response({"detail": "rate limited"}, status_code=429),
            make_response(DAILY_ROWS),
        ])

        with patch('SureshotSDK.LondonStrategicEdge.client.time.sleep'):
            data = client.get_historical_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')

        assert len(data) == 2
        assert client.session.get.call_count == 2

    def test_request_error_returns_empty_list(self):
        client = make_client()
        client.session.get = Mock(side_effect=requests.ConnectionError("network down"))
        data = client.get_historical_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')
        assert data == []

    def test_fx_row_missing_volume_defaults_to_zero(self):
        client = make_client()
        row = {k: v for k, v in DAILY_ROWS[0].items() if k != 'volume'}
        client.session.get = Mock(return_value=make_response([row]))

        data = client.get_historical_data('EUR/USD', datetime(2026, 8, 21), datetime(2026, 8, 21), '1d')

        assert data[0]['v'] == 0


class TestDerivedMethods:

    def test_get_close_prices(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(DAILY_ROWS))
        closes = client.get_close_prices('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')
        assert closes == [767.0, 763.65]

    def test_get_ohlcv_data_tuples(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response(DAILY_ROWS))
        ohlcv = client.get_ohlcv_data('SPY', datetime(2026, 8, 21), datetime(2026, 8, 24), '1d')
        timestamp, o, h, l, c, v = ohlcv[0]
        assert isinstance(timestamp, datetime)
        assert (o, h, l, c, v) == (764.69, 767.84, 764.17, 767.0, 32516198)

    def test_get_single_day_price(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response([DAILY_ROWS[0]]))
        assert client.get_single_day_price('SPY', datetime(2026, 8, 21)) == 767.0

    def test_get_current_price_uses_latest_minute_close(self):
        client = make_client()
        client.session.get = Mock(return_value=make_response([MINUTE_ROWS[-1]]))
        assert client.get_current_price('SPY') == 764.4
        params = client.session.get.call_args[1]['params']
        assert params['order'] == 'desc'
        assert params['limit'] == 1

    def test_get_current_price_returns_none_on_error(self):
        client = make_client()
        client.session.get = Mock(side_effect=requests.ConnectionError("down"))
        assert client.get_current_price('SPY') is None

    def test_get_last_quote_returns_none(self):
        client = make_client()
        assert client.get_last_quote('SPY') is None
