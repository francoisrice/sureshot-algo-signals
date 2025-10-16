"""
Comprehensive test suite for the SMA class
Tests both manual price updates and Polygon API initialization
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from SureshotSDK.SMA import SMA


class TestSMABasicFunctionality:
    """Test basic SMA functionality without external dependencies"""

    @pytest.mark.unit()
    def test_initialization(self):
        """Test SMA object initialization"""
        sma = SMA('SPY', period=10, timeframe='1d')
        assert sma.symbol == 'SPY'
        assert sma.period == 10
        assert sma.timeframe == '1d'
        assert sma.sma_value is None
        assert sma.is_initialized is False

    @pytest.mark.unit()
    def test_update_single_price(self):
        """Test updating SMA with a single price"""
        sma = SMA('SPY', period=3, timeframe='1d')
        sma.Update(100.0)
        assert len(sma.prices) == 1
        assert sma.sma_value is None  # Not enough data yet
        assert not sma.is_ready()

    @pytest.mark.unit()
    @pytest.mark.parametrize("prices,expected", [
        ([100.0, 102.0, 104.0], 102.0),
        ([50.0, 60.0, 70.0], 60.0),
        ([10.0, 20.0, 30.0], 20.0),
    ])
    def test_sma_calculation_accuracy(self, prices, expected):
        """Test SMA calculation accuracy with various inputs"""
        sma = SMA('TEST', period=3, timeframe='1d')

        for price in prices:
            sma.Update(price)

        assert pytest.approx(sma.get_value(), rel=1e-2) == expected
        assert sma.is_ready()

    @pytest.mark.unit()
    def test_rolling_window(self):
        """Test that SMA maintains rolling window correctly"""
        sma = SMA('TEST', period=3, timeframe='1d')
        prices = [100, 102, 104, 106, 108]

        for price in prices:
            sma.Update(price)

        # Should only keep last 3 prices
        assert len(sma.prices) == 3
        # Last 3 prices: 104, 106, 108
        expected = (104 + 106 + 108) / 3
        assert pytest.approx(sma.get_value(), rel=1e-2) == expected

    @pytest.mark.unit()
    @pytest.mark.parametrize("period,num_updates,should_be_ready", [
        (5, 4, False),
        (5, 5, True),
        (5, 6, True),
        (2, 1, False),
        (2, 2, True),
    ])
    def test_is_ready_conditions(self, period, num_updates, should_be_ready):
        """Test is_ready with various period and data combinations"""
        sma = SMA('TEST', period=period, timeframe='1d')

        for i in range(num_updates):
            sma.Update(100.0 + i)

        assert sma.is_ready() == should_be_ready

    @pytest.mark.unit()
    def test_reset(self):
        """Test reset functionality"""
        sma = SMA('TEST', period=3, timeframe='1d')
        sma.Update(100.0)
        sma.Update(102.0)
        sma.Update(104.0)
        sma.is_initialized = True

        # Verify SMA has data
        assert sma.is_ready()
        assert sma.get_value() is not None

        # Reset
        sma.reset()

        # Verify everything is cleared
        assert len(sma.prices) == 0
        assert sma.sma_value is None
        assert not sma.is_initialized
        assert not sma.is_ready()

    @pytest.mark.unit()
    def test_get_value_returns_none_when_not_ready(self):
        """Test get_value returns None when SMA is not ready"""
        sma = SMA('TEST', period=5, timeframe='1d')
        sma.Update(100.0)

        assert sma.get_value() is None

