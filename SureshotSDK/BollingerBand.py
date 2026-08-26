from collections import deque
from datetime import datetime, timedelta
import logging
import statistics
from typing import Dict, Optional
from .HistoricalDataClient import HistoricalDataClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BollingerBand:
    def __init__(self, symbol: str, period: int = 20, stddev: float = 2.0, timeframe: str = '1d'):
        """
        Bollinger Band indicator

        Plots a moving average (middle band) with upper/lower bands offset
        by a multiple of the rolling population standard deviation, so the
        bands widen and narrow with volatility. Commonly used to spot
        breakouts (price closing outside a band).

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            period: Number of periods for the moving average / stddev window
            stddev: Number of standard deviations for the upper/lower bands
            timeframe: Timeframe for data ('1d', '1h', '15m', etc.)
        """
        self.symbol = symbol
        self.period = period
        self.stddev = stddev
        self.timeframe = timeframe
        self.prices = deque(maxlen=period)
        self.middle_band: Optional[float] = None
        self.upper_band: Optional[float] = None
        self.lower_band: Optional[float] = None
        self.is_initialized = False
        self.data_client = HistoricalDataClient()

    def initialize(self, start_date: Optional[datetime] = None):
        """
        Initialize the Bollinger Band with historical data

        Args:
            start_date: Optional start date for historical data warmup
        """
        try:
            if start_date is None:
                # Default to enough historical data to warm up the indicator
                end_date = datetime.now()
                start_date = end_date - timedelta(days=self.period * 2)
            else:
                end_date = start_date + timedelta(days=self.period * 2)

            # Fetch historical data using Polygon client
            close_prices = self.data_client.get_close_prices(
                self.symbol, start_date, end_date, self.timeframe
            )

            if not close_prices:
                raise ValueError(f"No historical data available for {self.symbol}")

            # Warm up the rolling window with historical closes
            for close_price in close_prices:
                self.prices.append(float(close_price))
            self._calculate_bands()

            self.is_initialized = True

        except Exception as e:
            logger.error(f" Could not initialize BollingerBand with historical data: {e}")
            # Fall back to manual initialization
            self.is_initialized = True

    def Update(self, price: float):
        """
        Update the Bollinger Band with a new price

        Args:
            price: New price to add to the calculation
        """
        self.prices.append(price)
        self._calculate_bands()

    def _calculate_bands(self):
        """Calculate the middle/upper/lower bands from the rolling window"""
        if len(self.prices) == 0:
            return

        window = list(self.prices)
        self.middle_band = sum(window) / len(window)
        # Population stddev (divide by N) matches the standard Bollinger Band definition
        std = statistics.pstdev(window) if len(window) >= 2 else 0.0
        self.upper_band = self.middle_band + (self.stddev * std)
        self.lower_band = self.middle_band - (self.stddev * std)

    def get_upper_band(self) -> Optional[float]:
        """Get the current upper band value"""
        return self.upper_band

    def get_lower_band(self) -> Optional[float]:
        """Get the current lower band value"""
        return self.lower_band

    def get_middle_band(self) -> Optional[float]:
        """Get the current middle band (moving average) value"""
        return self.middle_band

    def get_value(self) -> Dict[str, Optional[float]]:
        """
        Get the current band values

        Returns:
            Dict with 'upper', 'middle', 'lower' keys
        """
        return {
            'upper': self.upper_band,
            'middle': self.middle_band,
            'lower': self.lower_band,
        }

    def is_ready(self) -> bool:
        """
        Check if the Bollinger Band has enough data to produce valid values

        Returns:
            True if ready, False otherwise
        """
        return len(self.prices) >= self.period

    def reset(self):
        """Reset the Bollinger Band indicator"""
        self.prices.clear()
        self.middle_band = None
        self.upper_band = None
        self.lower_band = None
        self.is_initialized = False

    def get_current_price(self) -> Optional[float]:
        """
        Get the current price using Polygon client

        Returns:
            Current price or None if unavailable
        """
        return self.data_client.get_current_price(self.symbol)

    def __repr__(self) -> str:
        return (
            f"BollingerBand(symbol={self.symbol}, period={self.period}, stddev={self.stddev}, "
            f"upper={self.upper_band}, middle={self.middle_band}, lower={self.lower_band})"
        )
