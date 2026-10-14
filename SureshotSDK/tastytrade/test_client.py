"""
Behavioral (hermetic) tests for the Tastytrade broker client.

These are written TDD-first: the client (`SureshotSDK/tastytrade/client.py`) does
not exist yet, so every test here fails (collection ImportError) until
`TastytradeClient` is implemented to satisfy this contract.

Nothing here touches the network — `requests` is fully mocked. The contract
mirrors `IBKRClient` (drop-in parity) so `orders.py` can route to either broker:
    fetch_conid(symbol) -> identifier
    buy(conid, quantity) / sell(conid, quantity)
    stop_order(conid, quantity, stopPrice)
    get_position_size(symbol) -> signed float | None
    invalidate_positions_cache() -> None (no-op for Tastytrade)
    fetch_acct_balance() / async_fetch_acct_balance() -> float | None
"""

import os
import json
import asyncio
from unittest.mock import patch, MagicMock

import pytest

# NOTE: this import is the first thing to fail until client.py exists.
from .client import TastytradeClient


LIVE_ENV = {
    'ENV': 'LIVE',
    'TT_USER': 'live-user',
    'PASSPHRASE_LIVE': 'live-pass',
    'PASSPHRASE_SANDBOX': 'sandbox-pass',
    'ACCT_NUMBER_LIVE': '5WL0001',
    'ACCT_NUMBER_SANDBOX': '5WT0001',
    'DRYRUN': 'FALSE',
}

SANDBOX_ENV = {**LIVE_ENV, 'ENV': 'SANDBOX'}


class MockResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, json_body, status_code=200):
        self._json = json_body
        self.status_code = status_code
        self.text = json.dumps(json_body)

    def json(self):
        return self._json


def _session_response(token='sess-token-123'):
    return MockResponse({'data': {'session-token': token, 'remember-token': 'rt-1'}})


def _order_ok_response(order_id=771043):
    return MockResponse({'data': {'order': {'id': order_id, 'status': 'Routed'}}})


def _positions_response(items):
    return MockResponse({'data': {'items': items}})


def _balance_response(nlv='2500.00'):
    return MockResponse({'data': {'net-liquidating-value': nlv}})


@pytest.fixture
def live_client():
    with patch.dict(os.environ, LIVE_ENV, clear=True):
        yield TastytradeClient()


@pytest.fixture
def sandbox_client():
    with patch.dict(os.environ, SANDBOX_ENV, clear=True):
        yield TastytradeClient()


# --------------------------------------------------------------------------- #
# Construction / environment selection
# --------------------------------------------------------------------------- #

def test_live_env_selects_live_base_url(live_client):
    assert live_client.baseUrl == 'https://api.tastyworks.com'
    assert live_client.accountNumber == '5WL0001'
    assert live_client.passphrase == 'live-pass'


def test_non_live_env_selects_sandbox_base_url(sandbox_client):
    assert sandbox_client.baseUrl == 'https://api.cert.tastyworks.com'
    assert sandbox_client.accountNumber == '5WT0001'
    assert sandbox_client.passphrase == 'sandbox-pass'


def test_session_token_starts_empty(live_client):
    assert live_client.session_token == ''


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

def test_login_posts_credentials_and_stores_token(live_client):
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _session_response('abc-token')
        token = live_client.login()

    assert token == 'abc-token'
    assert live_client.session_token == 'abc-token'

    # POST hit the /sessions endpoint with the login/password body
    args, kwargs = rq.request.call_args
    assert 'POST' in args or kwargs.get('method') == 'POST'
    url = kwargs.get('url') or args[1]
    assert url == 'https://api.tastyworks.com/sessions'
    body = json.loads(kwargs['data'])
    assert body['login'] == 'live-user'
    assert body['password'] == 'live-pass'


def test_request_reauthenticates_on_401(live_client):
    """A 401 triggers a fresh login then one retry (mirrors RetryClient)."""
    unauthorized = MockResponse({'error': {'code': 'unauthorized'}}, status_code=401)
    ok = _order_ok_response()

    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        # login (session) -> order 401 -> login again -> order ok
        rq.request.side_effect = [
            _session_response(),   # initial ensure-auth login
            unauthorized,          # first order attempt rejected
            _session_response(),   # re-login after 401
            ok,                    # retry succeeds
        ]
        resp = live_client.sell(conid='TQQQ', quantity=1, action='Sell to Close')

    assert resp['data']['order']['status'] == 'Routed'


# --------------------------------------------------------------------------- #
# Drop-in parity: symbol identity in place of IBKR conid
# --------------------------------------------------------------------------- #

def test_fetch_conid_returns_symbol_passthrough(live_client):
    """Tastytrade has no conid; the identifier threaded into buy/sell IS the symbol."""
    assert live_client.fetch_conid('TQQQ') == 'TQQQ'


# --------------------------------------------------------------------------- #
# Orders — equities, action inference (IBKR netting semantics)
# --------------------------------------------------------------------------- #

def _capture_order_payload(client, call):
    """Run `call`, return the JSON payload of the order POST (last /orders request)."""
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _session_response()
        # login first so it doesn't consume the order response
        client.login()
        rq.request.return_value = _order_ok_response()
        call()
        payload = None
        for c in rq.request.call_args_list:
            _args, _kwargs = c
            url = _kwargs.get('url') or (_args[1] if len(_args) > 1 else '')
            if url.endswith('/orders') or url.endswith('/orders/dry-run'):
                payload = json.loads(_kwargs['data'])
    return payload


def test_buy_defaults_to_buy_to_open_when_flat(live_client):
    with patch.object(live_client, 'get_position_size', return_value=0.0):
        payload = _capture_order_payload(
            live_client, lambda: live_client.buy(conid='TQQQ', quantity=1)
        )
    leg = payload['legs'][0]
    assert leg['action'] == 'Buy to Open'
    assert leg['symbol'] == 'TQQQ'
    assert leg['quantity'] == 1
    assert leg['instrument-type'] == 'Equity'
    assert payload['order-type'] == 'Market'


def test_buy_becomes_buy_to_close_when_short(live_client):
    with patch.object(live_client, 'get_position_size', return_value=-1.0):
        payload = _capture_order_payload(
            live_client, lambda: live_client.buy(conid='TQQQ', quantity=1)
        )
    assert payload['legs'][0]['action'] == 'Buy to Close'


def test_sell_defaults_to_sell_to_close_when_long(live_client):
    with patch.object(live_client, 'get_position_size', return_value=1.0):
        payload = _capture_order_payload(
            live_client, lambda: live_client.sell(conid='TQQQ', quantity=1)
        )
    assert payload['legs'][0]['action'] == 'Sell to Close'


def test_sell_becomes_sell_to_open_when_flat(live_client):
    with patch.object(live_client, 'get_position_size', return_value=0.0):
        payload = _capture_order_payload(
            live_client, lambda: live_client.sell(conid='TQQQ', quantity=1)
        )
    assert payload['legs'][0]['action'] == 'Sell to Open'


def test_explicit_action_override_skips_position_lookup(live_client):
    with patch.object(live_client, 'get_position_size') as gps:
        payload = _capture_order_payload(
            live_client,
            lambda: live_client.buy(conid='TQQQ', quantity=1, action='Buy to Close'),
        )
        gps.assert_not_called()
    assert payload['legs'][0]['action'] == 'Buy to Close'


# --------------------------------------------------------------------------- #
# Orders — option symbol inference
# --------------------------------------------------------------------------- #

def test_option_symbol_infers_equity_option_instrument(live_client):
    occ_symbol = 'SPY   191018C00295000'
    with patch.object(live_client, 'get_position_size', return_value=0.0):
        payload = _capture_order_payload(
            live_client, lambda: live_client.buy(conid=occ_symbol, quantity=1)
        )
    assert payload['legs'][0]['instrument-type'] == 'Equity Option'


# --------------------------------------------------------------------------- #
# Dry-run routing
# --------------------------------------------------------------------------- #

def test_dryrun_routes_to_dry_run_endpoint():
    env = {**LIVE_ENV, 'DRYRUN': 'TRUE'}
    with patch.dict(os.environ, env, clear=True):
        client = TastytradeClient()
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _session_response()
        client.login()
        rq.request.return_value = _order_ok_response()
        with patch.object(client, 'get_position_size', return_value=0.0):
            client.buy(conid='TQQQ', quantity=1)
        urls = [
            (c.kwargs.get('url') or (c.args[1] if len(c.args) > 1 else ''))
            for c in rq.request.call_args_list
        ]
    assert any(u.endswith('/orders/dry-run') for u in urls)


# --------------------------------------------------------------------------- #
# Stop orders
# --------------------------------------------------------------------------- #

def test_stop_order_sends_stop_type_with_price(live_client):
    with patch.object(live_client, 'get_position_size', return_value=0.0):
        payload = _capture_order_payload(
            live_client,
            lambda: live_client.stop_order(conid='TQQQ', quantity=1, stopPrice=50.0),
        )
    assert payload['order-type'] == 'Stop'
    assert float(payload['stop-trigger']) == 50.0


# --------------------------------------------------------------------------- #
# Positions
# --------------------------------------------------------------------------- #

def test_get_position_size_returns_signed_long(live_client):
    live_client.session_token = 'tok'
    items = [{'symbol': 'TQQQ', 'quantity': '3', 'quantity-direction': 'Long'}]
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _positions_response(items)
        assert live_client.get_position_size('TQQQ') == 3.0


def test_get_position_size_returns_signed_short(live_client):
    live_client.session_token = 'tok'
    items = [{'symbol': 'TQQQ', 'quantity': '2', 'quantity-direction': 'Short'}]
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _positions_response(items)
        assert live_client.get_position_size('TQQQ') == -2.0


def test_get_position_size_flat_when_symbol_absent(live_client):
    live_client.session_token = 'tok'
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _positions_response([])
        assert live_client.get_position_size('TQQQ') == 0.0


def test_invalidate_positions_cache_is_noop(live_client):
    # No cache on Tastytrade — the method exists for parity and must not raise or call out.
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        live_client.invalidate_positions_cache()
        rq.request.assert_not_called()


# --------------------------------------------------------------------------- #
# Account balance
# --------------------------------------------------------------------------- #

def test_fetch_acct_balance_returns_net_liquidating_value(live_client):
    live_client.session_token = 'tok'
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _balance_response('2500.00')
        assert live_client.fetch_acct_balance() == 2500.0


def test_async_fetch_acct_balance_returns_value(live_client):
    live_client.session_token = 'tok'
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _balance_response('1800.50')
        result = asyncio.run(live_client.async_fetch_acct_balance())
    assert result == 1800.5


# --------------------------------------------------------------------------- #
# OAuth2 (preferred auth once a refresh token + client secret are configured)
# --------------------------------------------------------------------------- #

OAUTH_LIVE_ENV = {
    'ENV': 'LIVE',
    'ACCT_NUMBER_LIVE': '5WL0001',
    'TT_CLIENT_SECRET_LIVE': 'live-secret',
    'TT_REFRESH_TOKEN_LIVE': 'live-refresh',
}


def _oauth_token_response(token='access-1', expiresIn=900):
    return MockResponse({'access_token': token, 'token_type': 'Bearer', 'expires_in': expiresIn})


@pytest.fixture
def oauth_client():
    with patch.dict(os.environ, OAUTH_LIVE_ENV, clear=True):
        yield TastytradeClient()


def test_oauth_credentials_select_oauth_mode(oauth_client, live_client):
    assert oauth_client.uses_oauth
    assert not live_client.uses_oauth


def test_oauth_login_posts_refresh_grant(oauth_client):
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _oauth_token_response('tok-xyz')
        token = oauth_client.login()

    assert token == 'tok-xyz'
    _, kwargs = rq.request.call_args
    assert kwargs['url'] == 'https://api.tastyworks.com/oauth/token'
    assert kwargs['headers']['User-Agent']
    body = json.loads(kwargs['data'])
    assert body == {'grant_type': 'refresh_token', 'refresh_token': 'live-refresh', 'client_secret': 'live-secret'}


def test_oauth_requests_send_bearer_header(oauth_client):
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.side_effect = [_oauth_token_response('tok-1'), _balance_response('1000')]
        oauth_client.fetch_acct_balance()

    _, kwargs = rq.request.call_args
    assert kwargs['headers']['Authorization'] == 'Bearer tok-1'


def test_oauth_refreshes_token_before_expiry(oauth_client):
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.side_effect = [
            _oauth_token_response('short-lived', expiresIn=30),  # inside the refresh margin
            _balance_response('1'),
            _oauth_token_response('fresh'),
            _balance_response('2'),
        ]
        oauth_client.fetch_acct_balance()
        oauth_client.fetch_acct_balance()

    _, kwargs = rq.request.call_args
    assert kwargs['headers']['Authorization'] == 'Bearer fresh'


def test_oauth_refresh_failure_raises_auth_error(oauth_client):
    from .client import TastytradeAuthError
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = MockResponse({'error': 'invalid_grant'}, status_code=400)
        with pytest.raises(TastytradeAuthError):
            oauth_client.login()


def test_explicit_environment_overrides_env_var():
    env = {**OAUTH_LIVE_ENV, 'ACCT_NUMBER_SANDBOX': '5WT0001'}
    with patch.dict(os.environ, env, clear=True):
        client = TastytradeClient(environment='SANDBOX')
    assert client.baseUrl == 'https://api.cert.tastyworks.com'
    assert client.accountNumber == '5WT0001'


# --------------------------------------------------------------------------- #
# Fill confirmation
# --------------------------------------------------------------------------- #

def test_wait_for_fill_polls_until_terminal(live_client):
    live_client.session_token = 'tok'
    routed = MockResponse({'data': {'id': 7, 'status': 'Routed'}})
    filled = MockResponse({'data': {'id': 7, 'status': 'Filled', 'legs': []}})
    with patch('SureshotSDK.tastytrade.client.requests') as rq, patch('SureshotSDK.tastytrade.client.time.sleep'):
        rq.request.side_effect = [routed, filled]
        order = live_client.wait_for_fill(7)
    assert order['status'] == 'Filled'


def test_average_fill_price_weights_by_quantity():
    order = {'legs': [{'fills': [
        {'quantity': '10', 'fill-price': '100.0'},
        {'quantity': '30', 'fill-price': '104.0'},
    ]}]}
    assert TastytradeClient.average_fill_price(order) == pytest.approx(103.0)
    assert TastytradeClient.average_fill_price({'legs': []}) is None


def test_fetch_position_details_returns_signed_quantity_and_basis(live_client):
    live_client.session_token = 'tok'
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = _positions_response([
            {'symbol': 'SHNY', 'quantity': '12', 'quantity-direction': 'Short', 'average-open-price': '40.5'},
        ])
        details = live_client.fetch_position_details('SHNY')
        flat = live_client.fetch_position_details('GLDM')
    assert details == {'quantity': -12.0, 'average_open_price': 40.5}
    assert flat is None


def test_cancel_order_sends_delete(live_client):
    live_client.session_token = 'tok'
    with patch('SureshotSDK.tastytrade.client.requests') as rq:
        rq.request.return_value = MockResponse({'data': {'id': 9, 'status': 'Cancel Requested'}})
        assert live_client.cancel_order(9) is True
    args, kwargs = rq.request.call_args
    assert args[0] == 'DELETE'
    assert kwargs['url'] == 'https://api.tastyworks.com/accounts/5WL0001/orders/9'
