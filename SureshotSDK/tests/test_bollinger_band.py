"""
Comprehensive test suite for the BollingerBand class
Tests both manual price updates and Polygon API initialization
"""

import pytest
import statistics
from datetime import datetime
import sys
import os

# Add repo root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.BollingerBand import BollingerBand


class TestBollingerBandBasicFunctionality:
    """Test basic BollingerBand functionality without external dependencies"""

    @pytest.mark.unit()
    def test_initialization(self):
        """Test BollingerBand object initialization"""
        bb = BollingerBand('SPY', period=20, stddev=2.0, timeframe='1d')
        assert bb.symbol == 'SPY'
        assert bb.period == 20
        assert bb.stddev == 2.0
        assert bb.timeframe == '1d'
        assert bb.get_upper_band() is None
        assert bb.get_middle_band() is None
        assert bb.get_lower_band() is None
        assert bb.is_initialized is False

    @pytest.mark.unit()
    def test_update_single_price(self):
        """A single price sets the middle band with zero-width bands"""
        bb = BollingerBand('SPY', period=3, stddev=2.0, timeframe='1d')
        bb.Update(100.0)
        assert bb.get_middle_band() == 100.0
        assert bb.get_upper_band() == 100.0
        assert bb.get_lower_band() == 100.0
        assert not bb.is_ready()

    @pytest.mark.unit()
    def test_band_calculation_accuracy(self):
        """Test band calculation accuracy against manually computed population stddev"""
        bb = BollingerBand('TEST', period=4, stddev=2.0, timeframe='1d')
        prices = [100.0, 102.0, 104.0, 98.0]

        for price in prices:
            bb.Update(price)

        expected_mean = sum(prices) / len(prices)
        expected_std = statistics.pstdev(prices)

        assert pytest.approx(bb.get_middle_band(), rel=1e-6) == expected_mean
        assert pytest.approx(bb.get_upper_band(), rel=1e-6) == expected_mean + 2.0 * expected_std
        assert pytest.approx(bb.get_lower_band(), rel=1e-6) == expected_mean - 2.0 * expected_std
        assert bb.is_ready()

    @pytest.mark.unit()
    def test_bands_widen_with_volatility(self):
        """A more volatile price series should produce wider bands than a flat one"""
        flat = BollingerBand('TEST', period=4, stddev=2.0, timeframe='1d')
        volatile = BollingerBand('TEST', period=4, stddev=2.0, timeframe='1d')

        for price in [100.0, 100.0, 100.0, 100.0]:
            flat.Update(price)
        for price in [90.0, 110.0, 95.0, 105.0]:
            volatile.Update(price)

        flat_width = flat.get_upper_band() - flat.get_lower_band()
        volatile_width = volatile.get_upper_band() - volatile.get_lower_band()

        assert flat_width == 0.0
        assert volatile_width > flat_width

    @pytest.mark.unit()
    def test_rolling_window(self):
        """Test that BollingerBand maintains rolling window correctly"""
        bb = BollingerBand('TEST', period=3, stddev=2.0, timeframe='1d')
        prices = [100.0, 102.0, 104.0, 106.0, 108.0]

        for price in prices:
            bb.Update(price)

        # Should only keep last 3 prices: 104, 106, 108
        assert len(bb.prices) == 3
        expected_mean = (104.0 + 106.0 + 108.0) / 3
        assert pytest.approx(bb.get_middle_band(), rel=1e-6) == expected_mean

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
        bb = BollingerBand('TEST', period=period, stddev=2.0, timeframe='1d')

        for i in range(num_updates):
            bb.Update(100.0 + i)

        assert bb.is_ready() == should_be_ready

    @pytest.mark.unit()
    def test_get_value_returns_all_bands(self):
        """get_value should return a dict with upper/middle/lower keys"""
        bb = BollingerBand('TEST', period=3, stddev=2.0, timeframe='1d')
        for price in [100.0, 102.0, 104.0]:
            bb.Update(price)

        value = bb.get_value()
        assert set(value.keys()) == {'upper', 'middle', 'lower'}
        assert value['middle'] == bb.get_middle_band()
        assert value['upper'] == bb.get_upper_band()
        assert value['lower'] == bb.get_lower_band()

    @pytest.mark.unit()
    def test_reset(self):
        """Test reset functionality"""
        bb = BollingerBand('TEST', period=3, stddev=2.0, timeframe='1d')
        bb.Update(100.0)
        bb.Update(102.0)
        bb.Update(104.0)
        bb.is_initialized = True

        assert bb.is_ready()
        assert bb.get_middle_band() is not None

        bb.reset()

        assert len(bb.prices) == 0
        assert bb.get_middle_band() is None
        assert bb.get_upper_band() is None
        assert bb.get_lower_band() is None
        assert not bb.is_initialized
        assert not bb.is_ready()
