"""
Comprehensive test suite for the Portfolio class
Tests position management, buying/selling, and integration with PolygonClient
"""

import pytest
from unittest.mock import Mock, patch
import sys
import os

# Add parent's parent directory to path so we can import SureshotSDK as a package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.Portfolio import Portfolio


class TestPortfolioInitialization:
    """Test Portfolio initialization"""

    @pytest.mark.unit()
    def test_default_initialization(self):
        """Test portfolio with default cash amount"""
        portfolio = Portfolio()
        assert portfolio.cash == 100000
        assert portfolio.initial_cash == 100000
        assert portfolio.positions == {}
        assert portfolio.position_values == {}
        assert not portfolio.invested

    @pytest.mark.unit()
    def test_custom_initialization(self):
        """Test portfolio with custom cash amount"""
        portfolio = Portfolio(cash=50000)
        assert portfolio.cash == 50000
        assert portfolio.initial_cash == 50000
        assert portfolio.positions == {}
        assert not portfolio.invested


class TestPortfolioBuyOperations:
    """Test buying operations"""

    @pytest.mark.unit()
    def test_buy_all_success(self):
        """Test buying all shares with available cash"""

        portfolio = Portfolio(cash=10000)
        shares = portfolio.buy_all('SPY', current_price=100.0)

        assert shares == 100  # 10000 / 100
        assert portfolio.positions['SPY'] == 100
        assert portfolio.cash == 0
        assert portfolio.invested

    @pytest.mark.unit()
    def test_buy_all_with_remainder(self):
        """Test buy_all with cash remainder"""

        portfolio = Portfolio(cash=10050)
        shares = portfolio.buy_all('SPY', current_price=100.0)

        assert shares == 100  # Can only buy whole shares
        assert portfolio.positions['SPY'] == 100
        assert portfolio.cash == 50  # Remainder
        assert portfolio.invested

    @pytest.mark.unit()
    def test_buy_all_insufficient_cash(self):
        """Test buy_all with insufficient cash"""

        portfolio = Portfolio(cash=50)
        shares = portfolio.buy_all('SPY', current_price=100.0)

        assert shares == 0
        assert 'SPY' not in portfolio.positions
        assert portfolio.cash == 50
        assert not portfolio.invested

    @pytest.mark.unit()
    def test_buy_specific_shares_success(self):
        """Test buying specific number of shares"""

        portfolio = Portfolio(cash=10000)
        result = portfolio.buy('SPY', shares=50, current_price=100.0)

        assert result is True
        assert portfolio.positions['SPY'] == 50
        assert portfolio.cash == 5000
        assert portfolio.invested

    @pytest.mark.unit()
    def test_buy_insufficient_cash(self):
        """Test buy fails with insufficient cash"""

        portfolio = Portfolio(cash=4000)
        result = portfolio.buy('SPY', shares=50, current_price=100.0)

        assert result is False
        assert 'SPY' not in portfolio.positions
        assert portfolio.cash == 4000
        assert not portfolio.invested

    @pytest.mark.unit()
    def test_buy_accumulates_position(self):
        """Test buying accumulates existing position"""

        portfolio = Portfolio(cash=20000)
        portfolio.buy('SPY', shares=50, current_price=100.0)
        portfolio.buy('SPY', shares=30, current_price=100.0)

        assert portfolio.positions['SPY'] == 80
        assert portfolio.cash == 12000


class TestPortfolioSellOperations:
    """Test selling operations"""

    @pytest.mark.unit()
    def test_sell_all_success(self):
        """Test selling all shares of a position"""

        portfolio = Portfolio(cash=10000)
        portfolio.buy('SPY', shares=100, current_price=100.0)

        proceeds = portfolio.sell_all('SPY', current_price=110.0)

        assert proceeds == 11000  # 100 shares * 110
        assert 'SPY' not in portfolio.positions
        assert portfolio.cash == 11000
        assert not portfolio.invested

    @pytest.mark.unit()
    def test_sell_all_no_position(self):
        """Test sell_all with no position"""

        portfolio = Portfolio(cash=10000)
        proceeds = portfolio.sell_all('SPY', current_price=100.0)

        assert proceeds == 0
        assert portfolio.cash == 10000

    @pytest.mark.unit()
    def test_sell_specific_shares_success(self):
        """Test selling specific number of shares"""

        portfolio = Portfolio(cash=10000)
        portfolio.buy('SPY', shares=100, current_price=100.0)

        result = portfolio.sell('SPY', shares=60, current_price=110.0)

        assert result is True
        assert portfolio.positions['SPY'] == 40
        assert portfolio.cash == 6600  # 0 + (60 * 110)
        assert portfolio.invested  # Still has position

    @pytest.mark.unit()
    def test_sell_all_shares_via_sell(self):
        """Test selling all shares using sell() removes position"""

        portfolio = Portfolio(cash=10000)
        portfolio.buy('SPY', shares=100, current_price=100.0)

        result = portfolio.sell('SPY', shares=100, current_price=110.0)

        assert result is True
        assert 'SPY' not in portfolio.positions
        assert portfolio.cash == 11000
        assert not portfolio.invested

    @pytest.mark.unit()
    def test_sell_insufficient_shares(self):
        """Test sell fails with insufficient shares"""

        portfolio = Portfolio(cash=10000)
        portfolio.buy('SPY', shares=50, current_price=100.0)

        result = portfolio.sell('SPY', shares=60, current_price=110.0)

        assert result is False
        assert portfolio.positions['SPY'] == 50
        assert portfolio.cash == 5000


class TestPortfolioMultiplePositions:
    """Test portfolio with multiple positions"""

    @pytest.mark.unit()
    def test_multiple_positions(self):
        """Test managing multiple positions"""

        portfolio = Portfolio(cash=35000)
        portfolio.buy('SPY', shares=100, current_price=100.0)  # $10,000
        portfolio.buy('AAPL', shares=50, current_price=150.0)  # $7,500
        portfolio.buy('MSFT', shares=75, current_price=200.0)  # $15,000
        # Total: $32,500

        assert len(portfolio.positions) == 3
        assert portfolio.positions['SPY'] == 100
        assert portfolio.positions['AAPL'] == 50
        assert portfolio.positions['MSFT'] == 75
        assert portfolio.cash == 2500  # 35000 - 32500
        assert portfolio.invested

    @pytest.mark.unit()
    def test_sell_one_position_keeps_invested(self):
        """Test selling one position keeps invested flag true"""

        portfolio = Portfolio(cash=25000)
        portfolio.buy('SPY', shares=100, current_price=100.0)
        portfolio.buy('AAPL', shares=100, current_price=150.0)

        portfolio.sell_all('SPY', current_price=110.0)

        assert 'SPY' not in portfolio.positions
        assert portfolio.positions['AAPL'] == 100
        assert portfolio.invested  # Still has AAPL


class TestPortfolioValueCalculation:
    """Test portfolio value calculations"""

    @pytest.mark.unit()
    def test_get_total_value_cash_only(self):
        """Test total value with only cash"""

        portfolio = Portfolio(cash=10000)
        total = portfolio.get_total_value()

        assert total == 10000

    @pytest.mark.integration("Requires PolygonClient connection to fetch values")
    def test_get_total_value_with_position(self):
        """Test total value with positions"""
        pytest.skip("Requires API key or complex mocking")

    @pytest.mark.integration("Requires PolygonClient connection to fetch values")
    def test_get_total_value_multiple_positions(self):
        """Test total value with multiple positions"""
        pytest.skip("Requires API key or complex mocking")


class TestPortfolioHelperMethods:
    """Test helper methods"""

    @pytest.mark.unit()
    def test_get_positions(self):
        """Test get_positions returns copy"""

        portfolio = Portfolio(cash=20000)
        portfolio.buy('SPY', shares=100, current_price=100.0)

        positions = portfolio.get_positions()
        positions['AAPL'] = 50  # Modify copy

        # Original should be unchanged
        assert 'AAPL' not in portfolio.positions
        assert portfolio.positions == {'SPY': 100}

    @pytest.mark.unit()
    def test_get_cash(self):
        """Test get_cash method"""

        portfolio = Portfolio(cash=10000)
        assert portfolio.get_cash() == 10000

        portfolio.buy('SPY', shares=50, current_price=100.0)
        assert portfolio.get_cash() == 5000

    @pytest.mark.unit()
    def test_reset(self):
        """Test reset method"""

        portfolio = Portfolio(cash=10000)
        portfolio.buy('SPY', shares=100, current_price=100.0)

        portfolio.reset(cash=50000)

        assert portfolio.cash == 50000
        assert portfolio.initial_cash == 50000
        assert portfolio.positions == {}
        assert portfolio.position_values == {}
        assert not portfolio.invested


class TestPortfolioErrorHandling:
    """Test error handling"""

    @pytest.mark.unit()
    def test_buy_with_zero_price(self):
        """Test buy fails with zero price"""

        portfolio = Portfolio(cash=10000)
        result = portfolio.buy('SPY', shares=100, current_price=0.0)

        assert result is False
        assert 'SPY' not in portfolio.positions

    @pytest.mark.unit()
    def test_buy_all_with_negative_price(self):
        """Test buy_all fails with negative price"""

        portfolio = Portfolio(cash=10000)
        shares = portfolio.buy_all('SPY', current_price=-100.0)

        assert shares == 0
        assert 'SPY' not in portfolio.positions
