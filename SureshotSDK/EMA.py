from datetime import datetime, timedelta
import logging
from typing import Optional
from .HistoricalDataClient import HistoricalDataClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EMA:
    def __init__(self, symbol: str, period: int, timeframe: str = '1d', ema_value: float = 0):
        """
        Exponential Moving Average indicator

        Unlike SMA, EMA weights recent prices more heavily via a smoothing
        factor alpha = 2 / (period + 1), so it reacts faster to new price
        action than an SMA of the same period.

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            period: Number of periods for EMA calculation
            timeframe: Timeframe for data ('1d', '1h', '15m', etc.)
        """
        self.symbol = symbol
        self.period = period
        self.timeframe = timeframe
        self.alpha = 2 / (period + 1)
        self.ema_value = ema_value
        self.num_updates = 0
        self.is_initialized = False
        self.data_client = HistoricalDataClient()

    def initialize(self, start_date: Optional[datetime] = None):
        """
        Initialize the EMA with historical data

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

            # Warm up the EMA with historical closes, oldest first
            for close_price in close_prices:
                self.Update(float(close_price))

            self.is_initialized = True

        except Exception as e:
            logger.error(f" Could not initialize EMA with historical data: {e}")
            # Fall back to manual initialization
            self.is_initialized = True

    def Update(self, price: float):
        """
        Update the EMA with a new price

        Args:
            price: New price to add to the calculation
        """
        if self.num_updates == 0 and not self.ema_value:
            # Seed the EMA with the first observed price rather than 0,
            # so it doesn't take `period` updates to climb out of a bogus baseline
            self.ema_value = price
        else:
            self.ema_value = (price * self.alpha) + (self.ema_value * (1 - self.alpha))
        self.num_updates += 1

    def get_value(self) -> Optional[float]:
        """
        Get the current EMA value

        Returns:
            Current EMA value or None if not enough data
        """
        return self.ema_value

    def is_ready(self) -> bool:
        """
        Check if the EMA has enough data to produce valid values

        Returns:
            True if EMA is ready, False otherwise
        """
        return self.num_updates >= self.period

    def reset(self):
        """Reset the EMA indicator"""
        self.ema_value = 0
        self.num_updates = 0
        self.is_initialized = False

    def get_current_price(self) -> Optional[float]:
        """
        Get the current price using Polygon client

        Returns:
            Current price or None if unavailable
        """
        return self.data_client.get_current_price(self.symbol)

    def __repr__(self) -> str:
        return f"EMA(symbol={self.symbol}, period={self.period}, value={self.ema_value})"
