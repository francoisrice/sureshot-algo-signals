class SMA:
    """
    Simple Moving Average indicator class for SureshotSDK.

    Calculates the simple moving average of closing prices over a specified period.
    Compatible with candle data from pull_candles.py PolygonMiddleware.
    """

    def __init__(self, symbol, period=20):
        """
        Initialize SMA indicator.

        Args:
            symbol (str): The symbol to track (e.g., 'SPY', 'AAPL', 'MSFT')
            period (int): Number of periods for the moving average (default: 20)
        """
        self.symbol = symbol
        self.period = period
        self.prices = []
        self.currentSMA = None

    def update(self, candles):
        """
        Update the SMA with new candle data.

        Args:
            candles (list or dict): Candle data from PolygonMiddleware.fetch_candles()
                Expected format from Polygon API:
                {
                    "results": [
                        {
                            "o": open_price,
                            "c": close_price,
                            "h": high_price,
                            "l": low_price,
                            "v": volume,
                            "t": timestamp
                        }, ...
                    ]
                }
        """
        if isinstance(candles, dict) and 'results' in candles:
            # Handle Polygon API response format
            candle_data = candles['results']
        elif isinstance(candles, list):
            # Handle direct list of candles
            candle_data = candles
        else:
            raise ValueError("Invalid candle data format")

        # Extract closing prices and add to our price history
        for candle in candle_data:
            if isinstance(candle, dict) and 'c' in candle:
                self.prices.append(float(candle['c']))
            elif hasattr(candle, 'close'):
                self.prices.append(float(candle.close))
            else:
                raise ValueError("Cannot extract closing price from candle data")

        # Keep only the most recent 'period' prices
        if len(self.prices) > self.period:
            self.prices = self.prices[-self.period:]

        # Calculate SMA if we have enough data
        if len(self.prices) >= self.period:
            self.currentSMA = sum(self.prices[-self.period:]) / self.period

    def add_price(self, price):
        """
        Add a single price to the SMA calculation.

        Args:
            price (float): The price to add
        """
        self.prices.append(float(price))

        # Keep only the most recent 'period' prices
        if len(self.prices) > self.period:
            self.prices = self.prices[-self.period:]

        # Calculate SMA if we have enough data
        if len(self.prices) >= self.period:
            self.currentSMA = sum(self.prices[-self.period:]) / self.period

    def getValue(self):
        """
        Get the current SMA value.

        Returns:
            float: Current SMA value, or None if insufficient data
        """
        return self.currentSMA

    def get_value(self):
        """
        Alias for getValue() for consistency.

        Returns:
            float: Current SMA value, or None if insufficient data
        """
        return self.getValue()

    def is_ready(self):
        """
        Check if the SMA has enough data to provide a valid value.

        Returns:
            bool: True if SMA is ready, False otherwise
        """
        return len(self.prices) >= self.period

    def get_period(self):
        """
        Get the period used for the SMA calculation.

        Returns:
            int: The period
        """
        return self.period

    def get_symbol(self):
        """
        Get the symbol this SMA is tracking.

        Returns:
            str: The symbol
        """
        return self.symbol

    def reset(self):
        """
        Reset the SMA indicator, clearing all price history.
        """
        self.prices = []
        self.currentSMA = None

    def __str__(self):
        """
        String representation of the SMA.

        Returns:
            str: String description of the SMA
        """
        status = "ready" if self.is_ready() else f"needs {self.period - len(self.prices)} more prices"
        return f"SMA({self.symbol}, period={self.period}, value={self.currentSMA}, {status})"

    def __repr__(self):
        """
        String representation of the SMA for debugging.

        Returns:
            str: String representation
        """
        return self.__str__()[]