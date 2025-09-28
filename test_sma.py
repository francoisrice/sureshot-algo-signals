#!/usr/bin/env python3
"""
Simple test script to verify SMA class functionality with sample candle data.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'SureshotSDK'))

from SMA import SMA

def test_sma_with_polygon_format():
    """Test SMA with Polygon API response format."""
    print("Testing SMA with Polygon API format...")

    # Sample Polygon API response format
    sample_candles = {
        "results": [
            {"c": 100.0, "o": 99.0, "h": 101.0, "l": 98.0, "v": 1000, "t": 1640995200000},
            {"c": 102.0, "o": 100.0, "h": 103.0, "l": 99.0, "v": 1100, "t": 1641081600000},
            {"c": 101.0, "o": 102.0, "h": 104.0, "l": 100.0, "v": 1200, "t": 1641168000000},
            {"c": 103.0, "o": 101.0, "h": 105.0, "l": 100.0, "v": 1300, "t": 1641254400000},
            {"c": 104.0, "o": 103.0, "h": 106.0, "l": 102.0, "v": 1400, "t": 1641340800000},
        ]
    }

    # Create SMA with 3-period for quick testing
    sma = SMA('SPY', period=3)
    print(f"Created: {sma}")

    # Update with candle data
    sma.update(sample_candles)
    print(f"After update: {sma}")
    print(f"SMA value: {sma.getValue()}")

    # Expected SMA for last 3 prices (101, 103, 104) = 102.67
    expected = (101.0 + 103.0 + 104.0) / 3
    actual = sma.getValue()
    print(f"Expected: {expected:.2f}, Actual: {actual:.2f}")

    return abs(expected - actual) < 0.01

def test_sma_with_individual_prices():
    """Test SMA with individual price updates."""
    print("\nTesting SMA with individual prices...")

    sma = SMA('SPXL', period=4)
    prices = [100, 102, 98, 104, 106]

    for price in prices:
        sma.add_price(price)
        print(f"Added {price}: {sma}")

    # Expected SMA for last 4 prices (102, 98, 104, 106) = 102.5
    expected = (102 + 98 + 104 + 106) / 4
    actual = sma.getValue()
    print(f"Expected: {expected}, Actual: {actual}")

    return abs(expected - actual) < 0.01

def test_sma_insufficient_data():
    """Test SMA behavior with insufficient data."""
    print("\nTesting SMA with insufficient data...")

    sma = SMA('TEST', period=5)
    sma.add_price(100)
    sma.add_price(102)

    print(f"SMA with 2 prices (needs 5): {sma}")
    print(f"getValue() returns: {sma.getValue()}")
    print(f"is_ready(): {sma.is_ready()}")

    return sma.getValue() is None and not sma.is_ready()

if __name__ == "__main__":
    print("SMA Class Test Suite")
    print("=" * 50)

    test1 = test_sma_with_polygon_format()
    test2 = test_sma_with_individual_prices()
    test3 = test_sma_insufficient_data()

    print("\n" + "=" * 50)
    print("Test Results:")
    print(f"Polygon format test: {'PASS' if test1 else 'FAIL'}")
    print(f"Individual prices test: {'PASS' if test2 else 'FAIL'}")
    print(f"Insufficient data test: {'PASS' if test3 else 'FAIL'}")

    if all([test1, test2, test3]):
        print("\nAll tests PASSED! SMA class is working correctly.")
    else:
        print("\nSome tests FAILED. Please check the implementation.")