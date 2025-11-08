import pytest
import os
import sys
from unittest.mock import patch
from .client import IBKRClient, RetryClient
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ibkr = IBKRClient()
retryClient = RetryClient()

def test_reauthenticate():
    """Test that RetryClient.reauthenticate() works"""
    if retryClient.auth_check() < 300:
        pytest.skip("Already Authenticated")
    assert retryClient.reauthenticate() == True

def test_fetch_conid():
    """Test that fetch_conid() returns as expected"""
    assert ibkr.fetch_conid('AAPL') == 265598

def test_fetch_conids():
    """Test that fetch_conid() returns as expected"""
    symbols = ['AAPL','GOOGL','F','TSLA']
    assert ibkr.fetch_conids(symbols) == [265598,208813719,9599491,76792991]