# SureshotSDK Tests

Comprehensive test suite for the SureshotSDK components using pytest.

## Test Structure

- `test_sma.py` - Tests for the Simple Moving Average (SMA) indicator
- `test_portfolio.py` - Tests for Portfolio management functionality
- `test_polygon_client.py` - Tests for the Polygon API client

## Setup

Install test dependencies:

```bash
cd automation/SureshotSDK
pip install -r requirements-test.txt
```

## Running Tests

Run all tests:
```bash
pytest
```

Run tests with coverage:
```bash
pytest --cov=. --cov-report=html
```

Run specific test file:
```bash
pytest tests/test_sma.py
pytest tests/test_portfolio.py
pytest tests/test_polygon_client.py
```

Run tests with verbose output:
```bash
pytest -v
```

Run specific test class or function:
```bash
pytest tests/test_sma.py::TestSMABasicFunctionality
pytest tests/test_portfolio.py::TestPortfolioBuyOperations::test_buy_all_success
```

## Test Categories

Tests are organized by markers:
- `unit` - Unit tests for individual components
- `integration` - Integration tests with external dependencies
- `slow` - Tests that take longer to run

Run tests by marker:
```bash
pytest -m unit
pytest -m integration
```

## Test Coverage

### SMA Tests
- Basic functionality (initialization, updates, calculations)
- Polygon API integration (mocked)
- Edge cases (zero prices, negative values, large periods)
- Rolling window behavior

### Portfolio Tests
- Initialization and reset
- Buy operations (buy_all, buy specific shares)
- Sell operations (sell_all, sell specific shares)
- Multiple positions management
- Value calculations
- Error handling

### PolygonClient Tests
- Initialization (API key, environment, Vault)
- Current price fetching
- Historical data retrieval
- OHLCV data formatting
- Close prices extraction
- Last quote fetching
- Market status checking
- Session management
- Error handling

## Notes

- All tests use mocked external dependencies (Polygon API)
- No actual API calls are made during testing
- Tests are designed to be fast and deterministic
