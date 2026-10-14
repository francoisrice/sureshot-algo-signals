"""
Tastytrade broker client.

Drop-in parity with `SureshotSDK.ibkr.automation.client.IBKRClient`: the same
method surface (`fetch_conid`, `buy`, `sell`, `stop_order`, `get_position_size`,
`invalidate_positions_cache`, `fetch_positions`, `fetch_acct_balance`,
`async_fetch_acct_balance`) so `orders.py` can route to either broker.

Unlike IBKR — which talks to a *local* Client Portal Gateway behind a
browser-automated login and a bridge warm-up — Tastytrade is a plain cloud REST
API. There is no gateway, no Playwright, and no positions cache to invalidate.

Auth prefers OAuth2 (refresh token + client secret -> 15-minute Bearer access
token) and falls back to the legacy username/password `session-token` when no
OAuth credentials are configured. Either way the token is re-issued on any 401.

Environment:
    ENV                       'LIVE' selects api.tastyworks.com + the *_LIVE creds;
                              anything else selects the api.cert.tastyworks.com sandbox.
    TT_CLIENT_SECRET_LIVE     OAuth client secret (live).
    TT_REFRESH_TOKEN_LIVE     OAuth personal-grant refresh token (live).
    TT_CLIENT_SECRET_SANDBOX  OAuth client secret (sandbox).
    TT_REFRESH_TOKEN_SANDBOX  OAuth personal-grant refresh token (sandbox).
    TT_USER                   Legacy login (shared across live/sandbox).
    PASSPHRASE_LIVE           Legacy password for live.
    PASSPHRASE_SANDBOX        Legacy password for sandbox (cert) environment.
    ACCT_NUMBER_LIVE          Live account number.
    ACCT_NUMBER_SANDBOX       Sandbox account number.
    DRYRUN                    If it contains a 'T' (e.g. 'TRUE'), orders route to the
                              /orders/dry-run endpoint — validated, never executed.
"""

import os
import json
import asyncio
import logging
import re
import time

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_USER_AGENT = 'sureshot-executor/1.0.0'

# OCC-style option symbol: 6-char padded underlying + YYMMDD + C/P + 8-digit strike.
# e.g. "SPY   191018C00295000". Anything else is treated as a plain equity symbol.
_OPTION_SYMBOL_RE = re.compile(r'^[A-Z ]{6}\d{6}[CP]\d{8}$')

# Refresh the OAuth access token this long before it expires, so a request never races expiry
_ACCESS_TOKEN_REFRESH_MARGIN_SECONDS = 60
_DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS = 900

FILLED_ORDER_STATUS = 'Filled'
TERMINAL_ORDER_STATUSES = {'Filled', 'Cancelled', 'Canceled', 'Rejected', 'Expired', 'Removed'}


class TastytradeAuthError(Exception):
    pass


class TastytradeClient:

    def __init__(self, environment: str | None = None):
        self.session_token = ""
        self.accessTokenExpiresAt = 0.0
        self.dryrun = 'T' in os.environ.get('DRYRUN', '').upper()

        isLive = (environment or os.environ['ENV']).upper() == 'LIVE'
        credentialSuffix = 'LIVE' if isLive else 'SANDBOX'
        if isLive:
            self.baseUrl = "https://api.tastyworks.com"
            self.websocketUrl = "https://streamer.tastyworks.com"
        else:
            self.baseUrl = "https://api.cert.tastyworks.com"
            self.websocketUrl = "https://streamer.cert.tastyworks.com"

        self.accountNumber = os.environ[f'ACCT_NUMBER_{credentialSuffix}']
        self.clientSecret = os.environ.get(f'TT_CLIENT_SECRET_{credentialSuffix}', '')
        self.refreshToken = os.environ.get(f'TT_REFRESH_TOKEN_{credentialSuffix}', '')
        self.username = os.environ.get('TT_USER', '')
        self.passphrase = os.environ.get(f'PASSPHRASE_{credentialSuffix}', '')

    @property
    def uses_oauth(self) -> bool:
        return bool(self.clientSecret and self.refreshToken)

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #

    def login(self):
        """Obtain a fresh token and cache it. Called directly (not via _request)
        to avoid recursion, since _request itself ensures auth."""
        if self.uses_oauth:
            return self._refresh_access_token()
        return self._create_legacy_session()

    def _refresh_access_token(self):
        response = requests.request(
            "POST",
            url=f"{self.baseUrl}/oauth/token",
            headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': _USER_AGENT},
            data=json.dumps({
                "grant_type": "refresh_token",
                "refresh_token": self.refreshToken,
                "client_secret": self.clientSecret,
            }),
        )
        if response.status_code >= 300:
            raise TastytradeAuthError(f"OAuth token refresh failed ({response.status_code}): {response.text}")
        tokenBody = response.json()
        self.session_token = tokenBody['access_token']
        tokenLifetime = float(tokenBody.get('expires_in') or _DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS)
        self.accessTokenExpiresAt = time.monotonic() + tokenLifetime
        return self.session_token

    def _create_legacy_session(self):
        payload = json.dumps({
            "login": self.username,
            "password": self.passphrase,
            "remember-me": False,
        })
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': _USER_AGENT,
        }
        response = requests.request("POST", url=f"{self.baseUrl}/sessions", headers=headers, data=payload)
        try:
            self.session_token = response.json()['data']['session-token']
        except (KeyError, TypeError, ValueError):
            raise TastytradeAuthError(f"Session login failed ({response.status_code}): {response.text}")
        return self.session_token

    def _access_token_expiring(self) -> bool:
        return self.uses_oauth and time.monotonic() >= self.accessTokenExpiresAt - _ACCESS_TOKEN_REFRESH_MARGIN_SECONDS

    def _ensure_authenticated(self):
        if not self.session_token or self._access_token_expiring():
            self.login()

    def _auth_headers(self):
        authorization = f'Bearer {self.session_token}' if self.uses_oauth else f'{self.session_token}'
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': _USER_AGENT,
            'Authorization': authorization,
        }

    def _request(self, method, url, data=None):
        """Single HTTP choke-point. Lazily logs in, then retries once on a 401
        after re-authenticating — mirrors IBKR's RetryClient._request."""
        self._ensure_authenticated()
        response = requests.request(method, url=url, headers=self._auth_headers(), data=data)
        if response.status_code == 401:
            logger.warning("Tastytrade returned 401 — re-authenticating and retrying")
            self.login()
            response = requests.request(method, url=url, headers=self._auth_headers(), data=data)
            if response.status_code == 401:
                raise Exception("Unauthorized")
        return response

    # ------------------------------------------------------------------ #
    # Contract identity (drop-in parity with IBKR conid)
    # ------------------------------------------------------------------ #

    def fetch_conid(self, symbol):
        """Tastytrade has no numeric contract id — the symbol IS the identifier.
        Returned so the value threaded into buy(conid=...) is the symbol itself,
        keeping orders.py broker-agnostic."""
        return symbol

    # ------------------------------------------------------------------ #
    # Orders
    # ------------------------------------------------------------------ #

    def _orders_url(self):
        url = f"{self.baseUrl}/accounts/{self.accountNumber}/orders"
        if self.dryrun:
            url += "/dry-run"
        return url

    def _instrument_type(self, symbol):
        return "Equity Option" if _OPTION_SYMBOL_RE.match(symbol) else "Equity"

    def _resolve_action(self, symbol, side, action):
        """Map IBKR's flat BUY/SELL onto Tastytrade's open/close semantics by
        netting against the current position, unless an explicit action is given.

        BUY  while short (<0) -> Buy to Close,  else Buy to Open
        SELL while long  (>0) -> Sell to Close, else Sell to Open
        """
        if action is not None:
            return action
        position = self.get_position_size(symbol) or 0.0
        if side == "Buy":
            return "Buy to Close" if position < 0 else "Buy to Open"
        return "Sell to Close" if position > 0 else "Sell to Open"

    def _place_market_order(self, symbol, quantity, side, action):
        resolved = self._resolve_action(symbol, side, action)
        payload = json.dumps({
            "order-type": "Market",
            "time-in-force": "Day",
            "legs": [{
                "instrument-type": self._instrument_type(symbol),
                "action": resolved,
                "quantity": quantity,
                "symbol": symbol,
            }],
        })
        response = self._request("POST", self._orders_url(), data=payload)
        return response.json()

    def buy(self, conid, quantity, action=None):
        """Market buy. `conid` is the Tastytrade symbol (see fetch_conid)."""
        return self._place_market_order(conid, quantity, "Buy", action)

    def sell(self, conid, quantity, action=None):
        """Market sell. `conid` is the Tastytrade symbol (see fetch_conid)."""
        return self._place_market_order(conid, quantity, "Sell", action)

    def stop_order(self, conid, quantity, stopPrice, action=None):
        """Stop (market-on-trigger) order. Defaults to a protective Sell to Close
        unless an explicit action is supplied."""
        symbol = conid
        resolved = self._resolve_action(symbol, "Sell", action)
        payload = json.dumps({
            "order-type": "Stop",
            "stop-trigger": str(stopPrice),
            "time-in-force": "Day",
            "legs": [{
                "instrument-type": self._instrument_type(symbol),
                "action": resolved,
                "quantity": quantity,
                "symbol": symbol,
            }],
        })
        response = self._request("POST", self._orders_url(), data=payload)
        if response.status_code >= 300:
            return {"message": "Error: Stop Loss Request Failed"}
        return response.json()

    def get_order(self, orderId):
        response = self._request("GET", f"{self.baseUrl}/accounts/{self.accountNumber}/orders/{orderId}")
        return response.json().get('data', {})

    def cancel_order(self, orderId) -> bool:
        """Request cancellation of a working order. True when tastytrade accepted the request."""
        response = self._request("DELETE", f"{self.baseUrl}/accounts/{self.accountNumber}/orders/{orderId}")
        return response.status_code < 300

    def wait_for_fill(self, orderId, timeoutSeconds: float = 60.0, pollIntervalSeconds: float = 1.0):
        """Poll an order until it reaches a terminal status or the timeout lapses.
        Returns the last order body seen (check its 'status')."""
        deadline = time.monotonic() + timeoutSeconds
        order = {}
        while True:
            order = self.get_order(orderId)
            if order.get('status') in TERMINAL_ORDER_STATUSES or time.monotonic() >= deadline:
                return order
            time.sleep(pollIntervalSeconds)

    @staticmethod
    def average_fill_price(order) -> float | None:
        """Quantity-weighted fill price across every leg fill of an order body."""
        filledQuantity = 0.0
        filledNotional = 0.0
        for leg in order.get('legs', []):
            for fill in leg.get('fills', []):
                fillQuantity = float(fill.get('quantity', 0))
                filledQuantity += fillQuantity
                filledNotional += fillQuantity * float(fill.get('fill-price', 0))
        return filledNotional / filledQuantity if filledQuantity else None

    def close_position(self, symbol, quantity):
        """Convenience close (buy-to-close), matching the template's semantics."""
        return self.buy(conid=symbol, quantity=quantity, action="Buy to Close")

    # ------------------------------------------------------------------ #
    # Positions
    # ------------------------------------------------------------------ #

    def _positions_url(self):
        return f"{self.baseUrl}/accounts/{self.accountNumber}/positions"

    def get_position_size(self, symbol):
        """Signed position size for `symbol` (0.0 if flat), or None if unavailable.
        Tastytrade reports magnitude + direction ('Long'/'Short'/'Zero')."""
        try:
            response = self._request("GET", self._positions_url())
            items = response.json().get('data', {}).get('items', [])
            symbol_upper = symbol.upper()
            for item in items:
                if (item.get('symbol') or '').upper() == symbol_upper:
                    qty = abs(float(item.get('quantity', 0)))
                    direction = (item.get('quantity-direction') or '').lower()
                    if direction == 'short':
                        return -qty
                    if direction == 'zero':
                        return 0.0
                    return qty
            return 0.0  # symbol not in the positions list means flat
        except Exception as e:
            logger.warning(f"get_position_size({symbol}) failed: {e}")
            return None

    def invalidate_positions_cache(self):
        """No-op. Tastytrade has no server-side positions cache to bust; the method
        exists only so the broker-agnostic call site in orders.py stays uniform."""
        return None

    def fetch_positions(self):
        response = self._request("GET", self._positions_url())
        return json.dumps(response.json())

    def fetch_position(self, symbol):
        return self.get_position_size(symbol)

    def fetch_position_details(self, symbol) -> dict | None:
        """{'quantity': signed float, 'average_open_price': float} for `symbol`,
        or None when flat or unavailable."""
        response = self._request("GET", self._positions_url())
        for item in response.json().get('data', {}).get('items', []):
            if (item.get('symbol') or '').upper() != symbol.upper():
                continue
            quantity = abs(float(item.get('quantity', 0)))
            if (item.get('quantity-direction') or '').lower() == 'short':
                quantity = -quantity
            if quantity == 0:
                return None
            return {'quantity': quantity, 'average_open_price': float(item.get('average-open-price') or 0)}
        return None

    # ------------------------------------------------------------------ #
    # Account balance
    # ------------------------------------------------------------------ #

    def _balances_url(self):
        return f"{self.baseUrl}/accounts/{self.accountNumber}/balances"

    def fetch_acct_balance(self):
        """Net liquidating value (total account value) in USD, or None on error.
        Sync — do not call from inside an asyncio event loop."""
        try:
            response = self._request("GET", self._balances_url())
            nlv = response.json().get('data', {}).get('net-liquidating-value')
            if nlv is None:
                logger.warning("net-liquidating-value missing from balances response")
                return None
            return float(nlv)
        except Exception as e:
            logger.exception(f"fetch_acct_balance() failed: {e}")
            return None

    async def async_fetch_acct_balance(self):
        """Async-safe net liquidating value. Tastytrade auth is a plain REST call
        (no Playwright), so we just offload the blocking request to a thread."""
        return await asyncio.to_thread(self.fetch_acct_balance)
