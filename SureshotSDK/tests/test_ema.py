"""
Comprehensive test suite for the EMA class
Tests both manual price updates and Polygon API initialization
"""

import pytest
from datetime import datetime
import sys
import os

# Add repo root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.EMA import EMA


class TestEMABasicFunctionality:
    """Test basic EMA functionality without external dependencies"""

    @pytest.mark.unit()
    def test_initialization(self):
        """Test EMA object initialization"""
        ema = EMA('SPY', period=10, timeframe='1d')
        assert ema.symbol == 'SPY'
        assert ema.period == 10
        assert ema.timeframe == '1d'
        assert ema.alpha == pytest.approx(2 / 11)
        assert ema.ema_value == 0
        assert ema.is_initialized is False

    @pytest.mark.unit()
    def test_update_single_price_seeds_value(self):
        """First update seeds the EMA directly with the price"""
        ema = EMA('SPY', period=3, timeframe='1d')
        ema.Update(100.0)
        assert ema.get_value() == 100.0
        assert not ema.is_ready()

    @pytest.mark.unit()
    def test_ema_calculation_accuracy(self):
        """Test EMA calculation accuracy against a manually computed series"""
        ema = EMA('TEST', period=3, timeframe='1d')  # alpha = 0.5
        prices = [100.0, 102.0, 104.0]

        expected = prices[0]
        for price in prices[1:]:
            expected = price * ema.alpha + expected * (1 - ema.alpha)

        for price in prices:
            ema.Update(price)

        assert pytest.approx(ema.get_value(), rel=1e-6) == expected
        assert ema.is_ready()

    @pytest.mark.unit()
    def test_ema_reacts_faster_than_flat_average(self):
        """EMA should weight the most recent price more than a simple average would"""
        ema = EMA('TEST', period=3, timeframe='1d')
        prices = [100.0, 100.0, 100.0, 200.0]

        for price in prices:
            ema.Update(price)

        simple_average = sum(prices) / len(prices)
        assert ema.get_value() > simple_average

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
        ema = EMA('TEST', period=period, timeframe='1d')

        for i in range(num_updates):
            ema.Update(100.0 + i)

        assert ema.is_ready() == should_be_ready

    @pytest.mark.unit()
    def test_reset(self):
        """Test reset functionality"""
        ema = EMA('TEST', period=3, timeframe='1d')
        ema.Update(100.0)
        ema.Update(102.0)
        ema.Update(104.0)
        ema.is_initialized = True

        # Verify EMA has data
        assert ema.is_ready()
        assert ema.get_value() is not None

        # Reset
        ema.reset()

        # Verify everything is cleared
        assert ema.num_updates == 0
        assert ema.ema_value == 0
        assert not ema.is_initialized
        assert not ema.is_ready()

    @pytest.mark.unit()
    def test_seeded_ema_value_blends_instead_of_reseeding(self):
        """A pre-seeded ema_value should be blended with, not overwritten by, the first Update"""
        ema = EMA('TEST', period=3, timeframe='1d', ema_value=100.0)
        ema.Update(110.0)

        expected = 110.0 * ema.alpha + 100.0 * (1 - ema.alpha)
        assert pytest.approx(ema.get_value(), rel=1e-6) == expected
