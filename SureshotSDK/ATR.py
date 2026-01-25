from collections import deque
from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict
from .Polygon import PolygonClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ATR:
    """
    Average True Range (ATR) indicator

    ATR measures market volatility by decomposing the entire range of an asset price
    for a given period. It's commonly used for position sizing and setting stop-loss levels.

    True Range (TR) is the greatest of:
    1. Current High - Current Low
    2. abs(Current High - Previous Close)
    3. abs(Current Low - Previous Close)

    ATR is the moving average of TR over N periods.
    """

    def __init__(self, symbol: str, period: int = 14, timeframe: str = '1d'):
        """
        Initialize ATR indicator

        Args:
            symbol: Stock symbol (e.g., 'SPY')
            period: Number of periods for ATR calculation (default: 14)
            timeframe: Timeframe for data ('1d', '1h', '5m', etc.)
        """
        self.symbol = symbol
        self.period = period
        self.timeframe = timeframe
        self.true_ranges = deque(maxlen=period)
        self.atr_value = None
        self.previous_close = None
        self.is_initialized = False
        self.polygon_client = PolygonClient()

    def initialize(self, start_date: Optional[datetime] = None):
        """
        Initialize the ATR with historical data

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

            # Fetch historical OHLC data using Polygon client
            historical_data = self.polygon_client.get_historical_data(
                self.symbol, start_date, end_date, self.timeframe
            )

            if not historical_data:
                raise ValueError(f"No historical data available for {self.symbol}")

            # Warm up the ATR with historical bars
            for i, bar in enumerate(historical_data):
                high = float(bar['h'])
                low = float(bar['l'])
                close = float(bar['c'])

                if i == 0:
                    # First bar: TR = High - Low
                    tr = high - low
                else:
                    tr = self._calculate_true_range(high, low, self.previous_close)

                self.true_ranges.append(tr)
                self.previous_close = close

            self._calculate_atr()
            self.is_initialized = True
            logger.info(f"ATR initialized for {self.symbol} with {len(self.true_ranges)} periods")

        except Exception as e:
            logger.error(f"Could not initialize ATR with historical data: {e}")
            # Fall back to manual initialization
            self.is_initialized = True

    def _calculate_true_range(self, high: float, low: float, prev_close: Optional[float] = None) -> float:
        """
        Calculate True Range for a single bar

        Args:
            high: Current period high
            low: Current period low
            prev_close: Previous period close

        Returns:
            True Range value
        """
        if prev_close is None:
            return high - low

        return max(
            high - low,                    # Current range
            abs(high - prev_close),        # Gap up
            abs(low - prev_close)          # Gap down
        )

    def Update(self, high: float, low: float, close: float):
        """
        Update the ATR with a new OHLC bar

        Args:
            high: Current period high
            low: Current period low
            close: Current period close
        """
        tr = self._calculate_true_range(high, low, self.previous_close)
        self.true_ranges.append(tr)
        self.previous_close = close
        self._calculate_atr()

    def update_from_bar(self, bar: Dict):
        """
        Update the ATR from a bar dictionary

        Args:
            bar: Dictionary with 'h', 'l', 'c' keys
        """
        self.Update(float(bar['h']), float(bar['l']), float(bar['c']))

    def _calculate_atr(self):
        """Calculate the Average True Range"""
        if len(self.true_ranges) >= self.period:
            # Use Simple Moving Average for ATR
            self.atr_value = sum(list(self.true_ranges)[-self.period:]) / self.period
        elif len(self.true_ranges) > 0 and self.atr_value is not None:
            # Partial calculation before full warmup
            self.atr_value = sum(list(self.true_ranges)) / len(self.true_ranges)

    def get_value(self) -> Optional[float]:
        """
        Get the current ATR value

        Returns:
            Current ATR value or None if not enough data
        """
        return self.atr_value

    def is_ready(self) -> bool:
        """
        Check if the ATR has enough data to produce valid values

        Returns:
            True if ATR is ready, False otherwise
        """
        return self.atr_value is not None and len(self.true_ranges) >= self.period

    def reset(self):
        """Reset the ATR indicator"""
        self.true_ranges.clear()
        self.atr_value = None
        self.previous_close = None
        self.is_initialized = False

    def get_atr_percentage(self) -> Optional[float]:
        """
        Get ATR as a percentage of current price

        Returns:
            ATR as percentage of price, or None if not available
        """
        if self.atr_value is None or self.previous_close is None or self.previous_close == 0:
            return None
        return (self.atr_value / self.previous_close) * 100

    def __repr__(self) -> str:
        return f"ATR(symbol={self.symbol}, period={self.period}, value={self.atr_value:.2f if self.atr_value else 'N/A'})"
