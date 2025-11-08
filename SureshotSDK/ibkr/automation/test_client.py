import pytest
import os
import sys
from unittest.mock import patch
from .client import IBKRClient
import urllib3

# TODO: Make better tests
#   The tests should match SPECIFIC exceptions. Not any exception.

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ibkr = IBKRClient()
# ibkr.refresh_connection()

def test_fetch_conid():
    """Test that fetch_conid() returns as expected"""
    assert ibkr.fetch_conid('AAPL') == 265598

def test_fetch_conids():
    """Test that fetch_conid() returns as expected"""
    symbols = ['AAPL','GOOGL','F','TSLA']
    assert ibkr.fetch_conids(symbols) == [265598,208813719,9599491,76792991]

    