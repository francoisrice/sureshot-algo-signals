"""
Comprehensive test suite for the PolygonClient class
Tests API integration, data fetching, and error handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import requests
import sys
import os

# Add parent's parent directory to path so we can import SureshotSDK as a package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from SureshotSDK.Polygon.client import PolygonClient


class TestPolygonClientInitialization:
    """Test PolygonClient initialization"""

    def test_initialization_with_api_key(self):
        """Test initialization with provided API key"""
        client = PolygonClient(api_key='test_key_123')
        assert client.api_key == 'test_key_123'
        assert client.base_url == 'https://api.polygon.io'

    @patch.dict(os.environ, {'POLYGON_API_KEY': 'env_key_456'})
    def test_initialization_from_environment(self):
        """Test initialization from environment variable"""
        client = PolygonClient()
        assert client.api_key == 'env_key_456'

    @patch.dict(os.environ, {}, clear=True)
    def test_initialization_without_api_key_raises_error(self):
        """Test initialization raises error without API key"""
        with pytest.raises(ValueError, match="POLYGON_API_KEY not found"):
            PolygonClient()

    @patch('SureshotSDK.Polygon.client.get_polygon_api_key_from_vault')
    def test_initialization_with_vault(self, mock_vault):
        """Test initialization with Vault"""
        mock_vault.return_value = 'vault_key_789'

        client = PolygonClient(use_vault=True)
        print(client.api_key)
        assert client.api_key == 'vault_key_789'

    @patch('SureshotSDK.Polygon.client.get_polygon_api_key_from_vault')
    @patch.dict(os.environ, {'POLYGON_API_KEY': 'env_key_backup'})
    def test_initialization_vault_fallback_to_env(self, mock_vault):
        """Test initialization falls back to env if Vault fails"""
        mock_vault.side_effect = Exception("Vault error")

        client = PolygonClient(use_vault=True)
        print(client.api_key)
        assert client.api_key == 'env_key_backup'


class TestPolygonClientGetCurrentPrice:
    """Test get_current_price method"""

    @patch('requests.Session.get')
    def test_get_current_price_success(self, mock_get):
        """Test successful current price fetch"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': {'p': 450.75}
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        price = client.get_current_price('SPY')

        assert price == 450.75
        mock_get.assert_called_once()

    @patch('requests.Session.get')
    def test_get_current_price_no_results(self, mock_get):
        """Test current price fetch with no results"""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'ERROR'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        price = client.get_current_price('INVALID')

        assert price is None

    @patch('requests.Session.get')
    def test_get_current_price_api_error(self, mock_get):
        """Test current price fetch handles API errors"""
        mock_get.side_effect = requests.RequestException("API Error")

        client = PolygonClient(api_key='test_key')
        price = client.get_current_price('SPY')

        assert price is None

    @patch('requests.Session.get')
    def test_get_current_price_invalid_json(self, mock_get):
        """Test current price fetch handles invalid JSON"""
        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        price = client.get_current_price('SPY')

        assert price is None


class TestPolygonClientGetHistoricalData:
    """Test get_historical_data method"""

    @patch('requests.Session.get')
    def test_get_historical_data_success(self, mock_get):
        """Test successful historical data fetch"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [
                {'t': 1640995200000, 'o': 99.0, 'h': 101.0, 'l': 98.0, 'c': 100.0, 'v': 1000},
                {'t': 1641081600000, 'o': 100.0, 'h': 103.0, 'l': 99.0, 'c': 102.0, 'v': 1100},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        data = client.get_historical_data('SPY', start_date, end_date, timeframe='1d')

        assert len(data) == 2
        assert data[0]['c'] == 100.0
        assert data[1]['c'] == 102.0

    @patch('requests.Session.get')
    @pytest.mark.parametrize("timeframe,expected_multiplier,expected_timespan", [
        ('1d', 1, 'day'),
        ('1h', 1, 'hour'),
        ('5m', 5, 'minute'),
        ('15m', 15, 'minute'),
        ('30m', 30, 'minute'),
        ('1m', 1, 'minute'),
    ])
    def test_get_historical_data_timeframes(self, mock_get, timeframe, expected_multiplier, expected_timespan):
        """Test historical data with different timeframes"""
        mock_response = Mock()
        mock_response.json.return_value = {'results': []}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        client.get_historical_data('SPY', start_date, end_date, timeframe=timeframe)

        # Verify the URL contains correct multiplier and timespan
        call_args = mock_get.call_args
        url = call_args[0][0]
        assert f'/range/{expected_multiplier}/{expected_timespan}/' in url

    @patch('requests.Session.get')
    def test_get_historical_data_empty_results(self, mock_get):
        """Test historical data with empty results"""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'NO_DATA'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        data = client.get_historical_data('SPY', start_date, end_date)

        assert data == []

    @patch('requests.Session.get')
    def test_get_historical_data_api_error(self, mock_get):
        """Test historical data handles API errors"""
        mock_get.side_effect = requests.RequestException("API Error")

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        data = client.get_historical_data('SPY', start_date, end_date)

        assert data == []


class TestPolygonClientGetOHLCVData:
    """Test get_ohlcv_data method"""

    @patch('requests.Session.get')
    def test_get_ohlcv_data_success(self, mock_get):
        """Test successful OHLCV data fetch"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [
                {'t': 1640995200000, 'o': 99.0, 'h': 101.0, 'l': 98.0, 'c': 100.0, 'v': 1000},
                {'t': 1641081600000, 'o': 100.0, 'h': 103.0, 'l': 99.0, 'c': 102.0, 'v': 1100},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        data = client.get_ohlcv_data('SPY', start_date, end_date)

        assert len(data) == 2
        # Check first candle
        timestamp, open_p, high, low, close, volume = data[0]
        assert isinstance(timestamp, datetime)
        assert open_p == 99.0
        assert high == 101.0
        assert low == 98.0
        assert close == 100.0
        assert volume == 1000

    @patch('requests.Session.get')
    def test_get_ohlcv_data_empty(self, mock_get):
        """Test OHLCV data with empty results"""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'NO_DATA'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        data = client.get_ohlcv_data('SPY', start_date, end_date)

        assert data == []


class TestPolygonClientGetClosePrices:
    """Test get_close_prices method"""

    @patch('requests.Session.get')
    def test_get_close_prices_success(self, mock_get):
        """Test successful close prices fetch"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [
                {'t': 1640995200000, 'o': 99.0, 'h': 101.0, 'l': 98.0, 'c': 100.0, 'v': 1000},
                {'t': 1641081600000, 'o': 100.0, 'h': 103.0, 'l': 99.0, 'c': 102.0, 'v': 1100},
                {'t': 1641168000000, 'o': 102.0, 'h': 105.0, 'l': 101.0, 'c': 104.0, 'v': 1200},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 5)

        prices = client.get_close_prices('SPY', start_date, end_date)

        assert prices == [100.0, 102.0, 104.0]

    @patch('requests.Session.get')
    def test_get_close_prices_empty(self, mock_get):
        """Test close prices with empty results"""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'NO_DATA'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 3)

        prices = client.get_close_prices('SPY', start_date, end_date)

        assert prices == []

    @patch('requests.Session.get')
    def test_get_close_prices_missing_close(self, mock_get):
        """Test close prices handles missing 'c' field"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [
                {'t': 1640995200000, 'o': 99.0, 'h': 101.0, 'l': 98.0, 'c': 100.0, 'v': 1000},
                {'t': 1641081600000, 'o': 100.0, 'h': 103.0, 'l': 99.0, 'v': 1100},  # Missing 'c'
                {'t': 1641168000000, 'o': 102.0, 'h': 105.0, 'l': 101.0, 'c': 104.0, 'v': 1200},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        start_date = datetime(2022, 1, 1)
        end_date = datetime(2022, 1, 5)

        prices = client.get_close_prices('SPY', start_date, end_date)

        assert prices == [100.0, 104.0]  # Skips entry without 'c'


class TestPolygonClientGetLastQuote:
    """Test get_last_quote method"""

    @patch('requests.Session.get')
    def test_get_last_quote_success(self, mock_get):
        """Test successful last quote fetch"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': {
                'T': 'SPY',
                'X': 4,
                'p': 450.75,
                'P': 4,
                's': 1,
                'S': 1
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        quote = client.get_last_quote('SPY')

        assert quote is not None
        assert quote['T'] == 'SPY'
        assert quote['p'] == 450.75

    @patch('requests.Session.get')
    def test_get_last_quote_no_results(self, mock_get):
        """Test last quote with no results"""
        mock_response = Mock()
        mock_response.json.return_value = {'status': 'ERROR'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        quote = client.get_last_quote('INVALID')

        assert quote is None

    @patch('requests.Session.get')
    def test_get_last_quote_api_error(self, mock_get):
        """Test last quote handles API errors"""
        mock_get.side_effect = requests.RequestException("API Error")

        client = PolygonClient(api_key='test_key')
        quote = client.get_last_quote('SPY')

        assert quote is None


class TestPolygonClientIsMarketOpen:
    """Test is_market_open method"""

    @patch('requests.Session.get')
    def test_is_market_open_true(self, mock_get):
        """Test market is open"""
        mock_response = Mock()
        mock_response.json.return_value = {'market': 'open'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        is_open = client.is_market_open()

        assert is_open is True

    @patch('requests.Session.get')
    def test_is_market_open_false(self, mock_get):
        """Test market is closed"""
        mock_response = Mock()
        mock_response.json.return_value = {'market': 'closed'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        client = PolygonClient(api_key='test_key')
        is_open = client.is_market_open()

        assert is_open is False

    @patch('requests.Session.get')
    @patch('SureshotSDK.Polygon.client.datetime')
    def test_is_market_open_fallback_weekday(self, mock_datetime, mock_get):
        """Test market open fallback logic for weekday"""
        mock_get.side_effect = requests.RequestException("API Error")

        # Mock weekday (Monday) at 10 AM
        mock_now = Mock()
        mock_now.weekday.return_value = 0  # Monday
        mock_now.hour = 10
        mock_datetime.now.return_value = mock_now

        client = PolygonClient(api_key='test_key')
        is_open = client.is_market_open()

        assert is_open is True

    @patch('requests.Session.get')
    @patch('SureshotSDK.Polygon.client.datetime')
    def test_is_market_open_fallback_weekend(self, mock_datetime, mock_get):
        """Test market open fallback logic for weekend"""
        mock_get.side_effect = requests.RequestException("API Error")

        # Mock weekend (Saturday)
        mock_now = Mock()
        mock_now.weekday.return_value = 5  # Saturday
        mock_now.hour = 10
        mock_datetime.now.return_value = mock_now

        client = PolygonClient(api_key='test_key')
        is_open = client.is_market_open()

        assert is_open is False

    @patch('requests.Session.get')
    @patch('SureshotSDK.Polygon.client.datetime')
    def test_is_market_open_fallback_outside_hours(self, mock_datetime, mock_get):
        """Test market open fallback logic outside hours"""
        mock_get.side_effect = requests.RequestException("API Error")

        # Mock weekday at 8 AM (before market opens)
        mock_now = Mock()
        mock_now.weekday.return_value = 0  # Monday
        mock_now.hour = 8
        mock_datetime.now.return_value = mock_now

        client = PolygonClient(api_key='test_key')
        is_open = client.is_market_open()

        assert is_open is False


class TestPolygonClientSessionManagement:
    """Test session management"""

    def test_session_created(self):
        """Test that session is created on initialization"""
        client = PolygonClient(api_key='test_key')
        assert hasattr(client, 'session')
        assert isinstance(client.session, requests.Session)

    def test_session_cleanup(self):
        """Test session is closed on deletion"""
        client = PolygonClient(api_key='test_key')
        mock_session = Mock()
        client.session = mock_session

        del client

        mock_session.close.assert_called_once()
