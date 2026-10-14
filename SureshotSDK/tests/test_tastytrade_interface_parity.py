"""
Interface-parity contract between the existing IBKRClient and the new
TastytradeClient.

`orders.py` and `MultiStrategyAPI/main.py` consume a small, fixed slice of the
broker client. This module pins that slice as an explicit contract:

  - `test_ibkr_client_exposes_broker_interface` runs against the CURRENT code and
    PASSES today — it documents exactly which methods the consumers rely on.
  - `test_tastytrade_client_exposes_broker_interface` asserts the SAME surface on
    the new client and FAILS until `TastytradeClient` is implemented.

Keeping both in one file makes the "passes for what exists, fails for what's new"
split visible at a glance, and guarantees the two brokers stay swappable.
"""

import inspect

import pytest

# The exact method surface orders.py / main.py call on the broker client.
BROKER_INTERFACE = [
    'fetch_conid',
    'buy',
    'sell',
    'stop_order',
    'get_position_size',
    'invalidate_positions_cache',
    'fetch_positions',
    'fetch_acct_balance',
    'async_fetch_acct_balance',
]


def _assert_has_interface(cls):
    missing = [name for name in BROKER_INTERFACE if not callable(getattr(cls, name, None))]
    assert not missing, f"{cls.__name__} missing broker-interface methods: {missing}"
    # async_fetch_acct_balance must be a coroutine on both brokers
    assert inspect.iscoroutinefunction(cls.async_fetch_acct_balance), (
        f"{cls.__name__}.async_fetch_acct_balance must be async"
    )


def test_ibkr_client_exposes_broker_interface():
    """Passes against current code — pins the contract the new broker must match."""
    from SureshotSDK.ibkr.automation.client import IBKRClient
    _assert_has_interface(IBKRClient)


def test_tastytrade_client_exposes_broker_interface():
    """Fails until TastytradeClient is implemented to the same surface."""
    from SureshotSDK.tastytrade.client import TastytradeClient
    _assert_has_interface(TastytradeClient)
