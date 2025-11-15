"""
Simple test script to verify EfficientFrontier API works
Run with: python -m EfficientFrontier.test_api
"""

import requests
import json
import time

API_URL = "http://localhost:8000"

def test_health():
    """Test health endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{API_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200
    print("✓ Health check passed\n")

def test_create_order():
    """Test creating an order"""
    print("Testing order creation...")
    order = {
        "strategy_name": "SPXL",
        "symbol": "SPXL",
        "order_type": "BUY",
        "quantity": 100,
        "price": 150.50
    }
    response = requests.post(f"{API_URL}/orders", json=order)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 201
    order_id = response.json()['id']
    print(f"✓ Order created with ID: {order_id}\n")
    return order_id

def test_get_orders():
    """Test getting orders"""
    print("Testing get orders...")
    response = requests.get(f"{API_URL}/orders")
    print(f"Status: {response.status_code}")
    orders = response.json()
    print(f"Found {len(orders)} orders")
    if orders:
        print(f"Latest order: {json.dumps(orders[0], indent=2)}")
    assert response.status_code == 200
    print("✓ Get orders passed\n")

def test_update_portfolio():
    """Test updating portfolio state"""
    print("Testing portfolio update...")
    portfolio = {
        "strategy_name": "SPXL",
        "cash": 85000.00,
        "initial_cash": 100000.00,
        "invested": True
    }
    response = requests.post(f"{API_URL}/portfolio", json=portfolio)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✓ Portfolio update passed\n")

def test_create_position():
    """Test creating a position"""
    print("Testing position creation...")
    position = {
        "strategy_name": "SPXL",
        "symbol": "SPXL",
        "quantity": 100,
        "avg_price": 150.50,
        "current_price": 152.00
    }
    response = requests.post(f"{API_URL}/positions", json=position)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✓ Position creation passed\n")

def test_get_portfolio():
    """Test getting portfolio state"""
    print("Testing get portfolio...")
    response = requests.get(f"{API_URL}/portfolio/SPXL")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    assert response.status_code == 200
    print("✓ Get portfolio passed\n")

def run_all_tests():
    """Run all tests"""
    print("=" * 50)
    print("EfficientFrontier API Test Suite")
    print("=" * 50 + "\n")

    try:
        test_health()
        test_create_order()
        test_get_orders()
        test_update_portfolio()
        test_create_position()
        test_get_portfolio()

        print("=" * 50)
        print("✓ All tests passed!")
        print("=" * 50)
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        raise

if __name__ == "__main__":
    run_all_tests()
