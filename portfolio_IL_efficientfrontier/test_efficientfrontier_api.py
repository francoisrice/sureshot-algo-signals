"""
End-to-end tests for EfficientFrontier API

Tests the complete workflow of:
1. Creating a portfolio
2. Executing buy_all order
3. Querying invested status
4. Executing sell_all order
5. Verifying orders in database
6. Verifying portfolio state updates

Run with: pytest test_efficientfrontier_api.py -v
"""

import pytest
import requests
from typing import Dict, Any


# Configuration
API_BASE_URL = "http://localhost:30800"
STRATEGY_NAME = "IncredibleLeverage_SPXL"
SYMBOL = "SPXL"


@pytest.fixture(scope="module")
def api_client():
    """Fixture to provide API base URL"""
    return API_BASE_URL


@pytest.fixture(scope="module")
def strategy_name():
    """Fixture to provide strategy name"""
    return STRATEGY_NAME


class TestEfficientFrontierAPI:
    """End-to-end tests for EfficientFrontier API"""

    def test_01_health_check(self, api_client):
        """Test API health endpoint"""
        response = requests.get(f"{api_client}/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "EfficientFrontier API"
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"

    def test_02_create_portfolio(self, api_client, strategy_name):
        """Test creating a portfolio for a strategy"""
        portfolio_data = {
            "strategy_name": strategy_name,
            "cash": 100000.0,
            "initial_cash": 100000.0,
            "total_value": 100000.0,
            "invested": False
        }

        response = requests.post(
            f"{api_client}/portfolio",
            json=portfolio_data
        )

        assert response.status_code == 200
        data = response.json()

        assert data["strategy_name"] == strategy_name
        assert data["cash"] == 100000.0
        assert data["initial_cash"] == 100000.0
        assert data["total_value"] == 100000.0
        assert data["invested"] is False
        assert data["total_return"] == 0.0
        assert data["total_return_pct"] == 0.0
        assert "id" in data
        assert "last_updated" in data

    def test_03_get_portfolio_state(self, api_client, strategy_name):
        """Test retrieving portfolio state"""
        response = requests.get(f"{api_client}/portfolio/{strategy_name}")

        assert response.status_code == 200
        data = response.json()

        assert data["strategy_name"] == strategy_name
        assert data["cash"] == 100000.0
        assert data["invested"] is False

    def test_04_get_invested_status_before_buy(self, api_client, strategy_name):
        """Test querying invested status before buying"""
        response = requests.get(f"{api_client}/portfolio/{strategy_name}/invested")

        assert response.status_code == 200
        data = response.json()

        assert data["strategy_name"] == strategy_name
        assert data["invested"] is False

    def test_05_buy_all_order(self, api_client, strategy_name):
        """Test buy_all endpoint"""
        trade_data = {
            "strategy_name": strategy_name,
            "symbol": SYMBOL,
            "price": 125.50
        }

        response = requests.post(
            f"{api_client}/orders/buy_all",
            json=trade_data
        )

        assert response.status_code == 201
        data = response.json()

        # Verify order details
        assert data["strategy_name"] == strategy_name
        assert data["symbol"] == SYMBOL
        assert data["order_type"] == "BUY"
        assert data["quantity"] == 796.0  # 100000 // 125.50
        assert data["price"] == 125.50
        assert data["order_value"] == 99898.0  # 796 * 125.50
        assert data["remaining_cash"] == 102.0  # 100000 - 99898
        assert data["invested"] is True
        assert "order_id" in data

    def test_06_get_invested_status_after_buy(self, api_client, strategy_name):
        """Test querying invested status after buying"""
        response = requests.get(f"{api_client}/portfolio/{strategy_name}/invested")

        assert response.status_code == 200
        data = response.json()

        assert data["strategy_name"] == strategy_name
        assert data["invested"] is True

    def test_07_get_orders(self, api_client, strategy_name):
        """Test retrieving orders for a strategy"""
        response = requests.get(
            f"{api_client}/orders",
            params={"strategy_name": strategy_name}
        )

        assert response.status_code == 200
        orders = response.json()

        assert isinstance(orders, list)
        assert len(orders) >= 1

        # Check the most recent order (BUY)
        buy_order = orders[0]
        assert buy_order["strategy_name"] == strategy_name
        assert buy_order["symbol"] == SYMBOL
        assert buy_order["order_type"] == "BUY"
        assert buy_order["quantity"] == 796.0
        assert buy_order["price"] == 125.50
        assert buy_order["status"] == "EXECUTED"

    def test_08_get_positions(self, api_client, strategy_name):
        """Test retrieving positions for a strategy"""
        response = requests.get(
            f"{api_client}/positions",
            params={"strategy_name": strategy_name}
        )

        assert response.status_code == 200
        positions = response.json()

        assert isinstance(positions, list)
        assert len(positions) == 1

        position = positions[0]
        assert position["strategy_name"] == strategy_name
        assert position["symbol"] == SYMBOL
        assert position["quantity"] == 796.0
        assert position["avg_price"] == 125.50

    def test_09_sell_all_order(self, api_client, strategy_name):
        """Test sell_all endpoint"""
        trade_data = {
            "strategy_name": strategy_name,
            "symbol": SYMBOL,
            "price": 130.00
        }

        response = requests.post(
            f"{api_client}/orders/sell_all",
            json=trade_data
        )

        assert response.status_code == 201
        data = response.json()

        # Verify order details
        assert data["strategy_name"] == strategy_name
        assert data["symbol"] == SYMBOL
        assert data["order_type"] == "SELL"
        assert data["quantity"] == 796.0
        assert data["price"] == 130.00
        assert data["order_value"] == 103480.0  # 796 * 130
        assert data["remaining_cash"] == 103582.0  # 102 + 103480
        assert data["invested"] is False
        assert "order_id" in data

    def test_10_get_invested_status_after_sell(self, api_client, strategy_name):
        """Test querying invested status after selling"""
        response = requests.get(f"{api_client}/portfolio/{strategy_name}/invested")

        assert response.status_code == 200
        data = response.json()

        assert data["strategy_name"] == strategy_name
        assert data["invested"] is False

    def test_11_verify_final_portfolio_state(self, api_client, strategy_name):
        """Test final portfolio state after complete cycle"""
        response = requests.get(f"{api_client}/portfolio/{strategy_name}")

        assert response.status_code == 200
        data = response.json()

        assert data["strategy_name"] == strategy_name
        assert data["cash"] == 103582.0
        assert data["initial_cash"] == 100000.0
        assert data["invested"] is False

        # Note: total_value and returns depend on whether positions still exist
        # After selling, cash should equal total_value
        assert data["total_value"] == 103582.0

    def test_12_verify_all_orders(self, api_client, strategy_name):
        """Test retrieving all orders and verify both buy and sell"""
        response = requests.get(
            f"{api_client}/orders",
            params={"strategy_name": strategy_name}
        )

        assert response.status_code == 200
        orders = response.json()

        assert isinstance(orders, list)
        assert len(orders) >= 2

        # Orders should be sorted by timestamp desc
        # So first should be SELL, second should be BUY
        sell_order = orders[0]
        buy_order = orders[1]

        # Verify SELL order
        assert sell_order["order_type"] == "SELL"
        assert sell_order["quantity"] == 796.0
        assert sell_order["price"] == 130.00
        assert sell_order["status"] == "EXECUTED"

        # Verify BUY order
        assert buy_order["order_type"] == "BUY"
        assert buy_order["quantity"] == 796.0
        assert buy_order["price"] == 125.50
        assert buy_order["status"] == "EXECUTED"

    def test_13_verify_no_positions_after_sell(self, api_client, strategy_name):
        """Test that positions are empty after selling all"""
        response = requests.get(
            f"{api_client}/positions",
            params={"strategy_name": strategy_name}
        )

        assert response.status_code == 200
        positions = response.json()

        assert isinstance(positions, list)
        assert len(positions) == 0

    def test_14_calculate_profit(self, api_client, strategy_name):
        """Test profit calculation from complete trade cycle"""
        response = requests.get(f"{api_client}/portfolio/{strategy_name}")

        assert response.status_code == 200
        data = response.json()

        initial_cash = data["initial_cash"]
        final_cash = data["cash"]
        profit = final_cash - initial_cash
        profit_pct = (profit / initial_cash) * 100

        # Verify profit calculation
        # Bought at 125.50, sold at 130.00
        # 796 shares * (130 - 125.50) = 796 * 4.50 = 3582
        assert profit == 3582.0
        assert abs(profit_pct - 3.582) < 0.001  # Allow small floating point error


class TestEfficientFrontierAPIErrorCases:
    """Test error handling in the API"""

    def test_buy_all_without_portfolio(self, api_client):
        """Test buy_all fails without portfolio"""
        trade_data = {
            "strategy_name": "NonExistentStrategy",
            "symbol": SYMBOL,
            "price": 125.50
        }

        response = requests.post(
            f"{api_client}/orders/buy_all",
            json=trade_data
        )

        assert response.status_code == 404
        data = response.json()
        assert "Portfolio not found" in data["detail"]

    def test_sell_all_without_position(self, api_client):
        """Test sell_all fails without position"""
        # First create a portfolio
        portfolio_data = {
            "strategy_name": "TestStrategy_NoPosition",
            "cash": 100000.0,
            "initial_cash": 100000.0,
            "total_value": 100000.0,
            "invested": False
        }
        requests.post(f"{api_client}/portfolio", json=portfolio_data)

        # Try to sell without position
        trade_data = {
            "strategy_name": "TestStrategy_NoPosition",
            "symbol": SYMBOL,
            "price": 130.00
        }

        response = requests.post(
            f"{api_client}/orders/sell_all",
            json=trade_data
        )

        assert response.status_code == 400
        data = response.json()
        assert "No position found" in data["detail"]

    def test_get_portfolio_not_found(self, api_client):
        """Test getting non-existent portfolio returns 404"""
        response = requests.get(f"{api_client}/portfolio/NonExistentStrategy")

        assert response.status_code == 404
        data = response.json()
        assert "Portfolio state not found" in data["detail"]

    def test_buy_all_insufficient_cash(self, api_client):
        """Test buy_all fails with insufficient cash"""
        # Create portfolio with minimal cash
        portfolio_data = {
            "strategy_name": "TestStrategy_LowCash",
            "cash": 10.0,
            "initial_cash": 10.0,
            "total_value": 10.0,
            "invested": False
        }
        requests.post(f"{api_client}/portfolio", json=portfolio_data)

        # Try to buy at high price
        trade_data = {
            "strategy_name": "TestStrategy_LowCash",
            "symbol": SYMBOL,
            "price": 125.50
        }

        response = requests.post(
            f"{api_client}/orders/buy_all",
            json=trade_data
        )

        assert response.status_code == 400
        data = response.json()
        assert "Insufficient cash" in data["detail"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
