from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from SureshotSDK.alpaca import AlpacaDataClient
from SureshotSDK.alpaca.client import _rfc3339_to_epoch_ms


def _response(body):
    response = MagicMock()
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def client():
    alpacaClient = AlpacaDataClient(api_key_id='key', api_secret_key='secret')
    alpacaClient.session = MagicMock()
    return alpacaClient


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.delenv('ALPACA_API_KEY_ID', raising=False)
    monkeypatch.delenv('ALPACA_API_SECRET_KEY', raising=False)
    with pytest.raises(ValueError):
        AlpacaDataClient()


def test_auth_headers_and_default_iex_feed():
    alpacaClient = AlpacaDataClient(api_key_id='key', api_secret_key='secret')
    assert alpacaClient.session.headers['APCA-API-KEY-ID'] == 'key'
    assert alpacaClient.session.headers['APCA-API-SECRET-KEY'] == 'secret'
    assert alpacaClient.feed == 'iex'


def test_nanosecond_timestamps_parse_to_epoch_ms():
    expected = int(datetime(2022, 8, 17, 9, 53, 16, 845580, tzinfo=timezone.utc).timestamp() * 1000)
    assert _rfc3339_to_epoch_ms('2022-08-17T09:53:16.845580544Z') == expected
    assert _rfc3339_to_epoch_ms('2022-08-17T04:00:00Z') == int(datetime(2022, 8, 17, 4, tzinfo=timezone.utc).timestamp() * 1000)


def test_get_current_price_reads_latest_trade(client):
    client.session.get.return_value = _response({'symbol': 'GLDM', 'trade': {'p': 61.25, 's': 100, 't': '2026-10-07T19:50:01.5Z'}})
    assert client.get_current_price('gldm') == 61.25
    url = client.session.get.call_args.args[0]
    assert url.endswith('/v2/stocks/GLDM/trades/latest')
    assert client.session.get.call_args.kwargs['params']['feed'] == 'iex'


def test_get_current_price_returns_none_on_error(client):
    client.session.get.side_effect = RuntimeError('boom')
    assert client.get_current_price('GLDM') is None


def test_get_current_bar_uses_latest_trade_as_close(client):
    client.session.get.return_value = _response({
        'latestTrade': {'p': 40.1, 's': 5, 't': '2026-10-07T19:50:00Z'},
        'dailyBar': {'t': '2026-10-07T04:00:00Z', 'o': 39.0, 'h': 41.0, 'l': 38.5, 'c': 40.0, 'v': 1200},
    })
    bar = client.get_current_bar('SHNY')
    assert bar['c'] == 40.1
    assert bar['o'] == 39.0


def test_get_historical_data_follows_pagination(client):
    client.session.get.side_effect = [
        _response({'bars': [{'t': '2026-01-02T05:00:00Z', 'o': 1, 'h': 2, 'l': 0.5, 'c': 1.5, 'v': 10}], 'next_page_token': 'abc'}),
        _response({'bars': [{'t': '2026-01-05T05:00:00Z', 'o': 2, 'h': 3, 'l': 1.5, 'c': 2.5, 'v': 20}], 'next_page_token': None}),
    ]
    bars = client.get_historical_data('GLDM', datetime(2026, 1, 1), datetime(2026, 1, 31))
    assert [bar['c'] for bar in bars] == [1.5, 2.5]
    secondCallParams = client.session.get.call_args_list[1].kwargs['params']
    assert secondCallParams['page_token'] == 'abc'
    assert secondCallParams['timeframe'] == '1Day'


def test_unsupported_timeframe_raises(client):
    with pytest.raises(ValueError):
        client.get_historical_data('GLDM', datetime(2026, 1, 1), datetime(2026, 1, 2), timeframe='2d')
