import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Callable
from .BacktestEngine import BacktestEngine
from .SMA import SMA

logger = logging.getLogger(__name__)


class BacktestRunner:
    """
    Runner for backtesting portfolio strategies
    Designed to work with existing TradingStrategy implementations
    """

    def __init__(
        self,
        strategy_name: str,
        start_date: datetime,
        end_date: datetime,
        initial_cash: float = 100000,
        use_cache: bool = True
    ):
        """
        Initialize backtest runner

        Args:
            strategy_name: Name of the strategy
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_cash: Starting cash amount
            use_cache: Whether to use price data caching
        """
        self.strategy_name = strategy_name
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash

        # Initialize backtest engine
        self.engine = BacktestEngine(
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            use_cache=use_cache
        )

        self.engine.start_date = start_date
        self.engine.end_date = end_date

        logger.info(f"BacktestRunner initialized: {strategy_name} from {start_date.date()} to {end_date.date()}")

    def run(
        self,
        trading_symbol: str,
        indicator_symbol: str,
        sma_period: int = 252,
        max_mid_month_loss: float = 0.05,
        on_tick: Optional[Callable] = None
    ):
        """
        Run backtest for a strategy similar to IncredibleLeverageSPXL

        Args:
            trading_symbol: Symbol to trade (e.g., 'SPXL')
            indicator_symbol: Symbol for SMA indicator (e.g., 'SPY')
            sma_period: SMA period (default 252 days)
            max_mid_month_loss: Maximum mid-month loss threshold
            on_tick: Optional custom tick handler
        """
        logger.info(f"Starting backtest for {self.strategy_name}")
        logger.info(f"Trading: {trading_symbol}, Indicator: {indicator_symbol} ({sma_period}-day SMA)")

        # Initialize SMA indicator
        sma = SMA(indicator_symbol, period=sma_period, timeframe='1d')
        warmup_start = self.start_date - timedelta(days=sma_period * 2)
        sma.initialize(warmup_start)

        # Fetch historical data for both symbols
        logger.info("Fetching historical data...")
        indicator_data = self.engine.get_historical_data(
            indicator_symbol, self.start_date, self.end_date, '1d'
        )
        trading_data = self.engine.get_historical_data(
            trading_symbol, self.start_date, self.end_date, '1d'
        )

        if not indicator_data or not trading_data:
            logger.error("Failed to fetch historical data")
            return None

        # Create lookup for trading prices by date
        trading_prices = {}
        for candle in trading_data:
            date = datetime.fromtimestamp(candle['t'] / 1000).date()
            trading_prices[date] = candle['c']

        logger.info(f"Processing {len(indicator_data)} trading days...")

        # Process each day
        previous_close = None
        previous_close_above_sma = False

        for i, candle in enumerate(indicator_data):
            # Get current date and indicator price
            current_date = datetime.fromtimestamp(candle['t'] / 1000)
            indicator_price = candle['c']

            # Update SMA with indicator price
            sma.Update(indicator_price)

            if not sma.is_ready():
                continue

            sma_value = sma.get_value()

            # Get trading price for this date
            date_key = current_date.date()
            if date_key not in trading_prices:
                continue

            trading_price = trading_prices[date_key]

            # Record current equity
            self.engine.record_equity(current_date, {trading_symbol: trading_price})

            # Use custom tick handler if provided
            if on_tick:
                on_tick(
                    self.engine,
                    current_date,
                    trading_symbol,
                    trading_price,
                    sma_value,
                    previous_close,
                    previous_close_above_sma
                )
            else:
                # Default strategy logic (IncredibleLeverageSPXL pattern)
                self._default_strategy_logic(
                    current_date,
                    trading_symbol,
                    trading_price,
                    sma_value,
                    indicator_price,
                    max_mid_month_loss,
                    previous_close,
                    previous_close_above_sma
                )

            # Update previous values
            previous_close = indicator_price
            previous_close_above_sma = indicator_price > sma_value

        logger.info("Backtest execution completed")

        # Calculate and display results
        logger.info("Calculating metrics...")
        self.engine.calculate_metrics()
        self.engine.print_results()
        self.engine.save_results()

        return self.engine.results

    def _default_strategy_logic(
        self,
        current_date: datetime,
        trading_symbol: str,
        trading_price: float,
        sma_value: float,
        indicator_price: float,
        max_mid_month_loss: float,
        previous_close: Optional[float],
        previous_close_above_sma: bool
    ):
        """
        Default strategy logic based on IncredibleLeverageSPXL

        Args:
            current_date: Current date
            trading_symbol: Symbol being traded
            trading_price: Current trading price
            sma_value: Current SMA value
            indicator_price: Current indicator price
            max_mid_month_loss: Maximum mid-month loss threshold
            previous_close: Previous close price
            previous_close_above_sma: Whether previous close was above SMA
        """
        # Check if we have a position
        has_position = trading_symbol in self.engine.portfolio.positions

        # Mid-Month Stop Loss: Exit if price drops more than X% below SMA
        if has_position:
            if indicator_price < sma_value * (1 - max_mid_month_loss):
                logger.info(f"{current_date.date()} Mid-month stop loss triggered: {indicator_price:.2f} < {sma_value * (1 - max_mid_month_loss):.2f}")
                self.engine.execute_sell(current_date, trading_symbol, trading_price)
                return

        # Month-end logic
        if self._is_month_end(current_date):
            if has_position:
                # Exit if price is below SMA at month end
                if indicator_price < sma_value:
                    logger.info(f"{current_date.date()} Month-end exit: {indicator_price:.2f} < {sma_value:.2f}")
                    self.engine.execute_sell(current_date, trading_symbol, trading_price)
            else:
                # Entry condition: price above SMA and previous close also above SMA
                if previous_close and indicator_price > sma_value and previous_close_above_sma:
                    logger.info(f"{current_date.date()} Month-end entry: {indicator_price:.2f} > {sma_value:.2f}")
                    self.engine.execute_buy(current_date, trading_symbol, trading_price)

    def _is_month_end(self, date: datetime) -> bool:
        """
        Check if date is at month end (last trading day of the month)

        Args:
            date: Date to check

        Returns:
            True if month end, False otherwise
        """
        # Simple heuristic: consider last 5 days of month as "month end"
        # More sophisticated logic could check actual trading days
        next_day = date + timedelta(days=1)
        return date.month != next_day.month or date.day >= 25

    def get_equity_curve(self):
        """
        Get the equity curve from the backtest

        Returns:
            List of (date, equity) tuples
        """
        return self.engine.equity_curve

    def get_trades(self):
        """
        Get all trades executed during backtest

        Returns:
            List of Trade objects
        """
        return self.engine.trades

    def get_results(self):
        """
        Get backtest results

        Returns:
            Dictionary of metrics
        """
        return self.engine.results
