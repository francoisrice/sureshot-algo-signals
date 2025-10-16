from collections import deque
from datetime import datetime, timedelta
import logging
from typing import Optional, Union
from .Polygon import PolygonClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SMA:
    def __init__(self, symbol: str, period: int, timeframe: str = '1d'):
        """
        Simple Moving Average indicator

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            period: Number of periods for SMA calculation
            timeframe: Timeframe for data ('1d', '1h', '5m', etc.)
        """
        self.symbol = symbol
        self.period = period
        self.timeframe = timeframe
        self.prices = deque(maxlen=period)
        self.sma_value = None
        self.is_initialized = False
        self.polygon_client = PolygonClient()

    def initialize(self, start_date: Optional[datetime] = None):
        """
        Initialize the SMA with historical data

        Args:
            start_date: Optional start date for historical data warmup
        """
        try:
            if start_date is None:
                # Default to enough historical data to warm up the indicator
                end_date = datetime.now()
                start_date = end_date - timedelta(days=self.period * 2)
            else:
                end_date = datetime.now()

            # Fetch historical data using Polygon client
            close_prices = self.polygon_client.get_close_prices(
                self.symbol, start_date, end_date, self.timeframe
            )

            if not close_prices:
                raise ValueError(f"No historical data available for {self.symbol}")

            # Warm up the SMA with historical closes
            for close_price in close_prices:
                self.prices.append(float(close_price))
                if len(self.prices) == self.period:
                    self._calculate_sma()

            self.is_initialized = True

        except Exception as e:
            logger.error(f" Could not initialize SMA with historical data: {e}")
            # Fall back to manual initialization
            self.is_initialized = True


    def Update(self, price: float):
        """
        Update the SMA with a new price

        Args:
            price: New price to add to the calculation
        """
        self.prices.append(price)
        if len(self.prices) >= self.period:
            self._calculate_sma()

    def _calculate_sma(self):
        """Calculate the Simple Moving Average"""
        if len(self.prices) >= self.period:
            self.sma_value = sum(list(self.prices)[-self.period:]) / self.period

    def get_value(self) -> Optional[float]:
        """
        Get the current SMA value

        Returns:
            Current SMA value or None if not enough data
        """
        return self.sma_value

    def is_ready(self) -> bool:
        """
        Check if the SMA has enough data to produce valid values

        Returns:
            True if SMA is ready, False otherwise
        """
        return len(self.prices) >= self.period and self.sma_value is not None

    def reset(self):
        """Reset the SMA indicator"""
        self.prices.clear()
        self.sma_value = None
        self.is_initialized = False

    def get_current_price(self) -> Optional[float]:
        """
        Get the current price using Polygon client

        Returns:
            Current price or None if unavailable
        """
        return self.polygon_client.get_current_price(self.symbol)