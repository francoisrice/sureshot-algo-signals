import logging
from datetime import datetime, timedelta
from typing import Optional
from .BacktestEngine import BacktestEngine
from .Portfolio import Portfolio

import requests
import json

logger = logging.getLogger(__name__)


class BacktestRunner:
    """
    Runner for backtesting TradingStrategy implementations
    Works with any strategy that implements the on_data() interface
    """

    def __init__(
        self,
        strategy,
        start_date: datetime,
        end_date: datetime,
        initial_cash: float = 100000,
        use_cache: bool = True,
        cache_dir: str = ".backtest_cache"
    ):
        """
        Initialize backtest runner

        Args:
            strategy: TradingStrategy instance to backtest
            start_date: Start date for backtest
            end_date: End date for backtest
            initial_cash: Starting cash amount
            use_cache: Whether to use price data caching
            cache_dir: Directory for cache files
        """
        self.strategy = strategy
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash

        # Initialize backtest engine
        self.engine = BacktestEngine(
            strategy_name=strategy.name,
            initial_cash=initial_cash,
            use_cache=use_cache,
            cache_dir=cache_dir
        )

        self.engine.start_date = start_date
        self.engine.end_date = end_date

        # Give strategy access to the portfolio
        self.strategy.portfolio = self.engine.portfolio

        logger.info(
            f"BacktestRunner initialized: {strategy.name} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        # Initialize PortfolioAPI
        logger.info("PortfolioAPI initialized")
        init_response = requests.post(
            url=f"{self.strategy.api_url}/portfolio/initialize",
            headers={"Content-Type":"application/json"},
            data=json.dumps({
                "strategies": [strategy.name],
                "total_capital": self.initial_cash,
                "allocation_method": "equal_weight"
                })  
            )
        if init_response.status_code == 200:
            logger.info(f"Portfolio initialized: {init_response.text}")    
        else:
            logger.info(f"Failed to initialize PortfolioAPI: {init_response.status_code} {init_response.text}")

    def run(self):
        """
        Run backtest by calling strategy.on_data() for each bar

        Returns:
            Backtest results dictionary
        """
        logger.info(f"Starting backtest for {self.strategy.name}")

        # Get trading symbol from strategy (different strategies use different attribute names)
        trading_symbol = getattr(self.strategy, 'tradingSymbol', None) or getattr(self.strategy, 'signalSymbol', None) or getattr(self.strategy, 'positionSymbol', None)
        position_symbol = getattr(self.strategy, 'positionSymbol', None)
        if not trading_symbol:
            logger.error("Strategy must have 'tradingSymbol' or 'positionSymbol' attribute")
            return None

        logger.info(f"Trading Symbol: {trading_symbol}")
        logger.info(f"Position Symbol: {position_symbol}")

        # Fetch historical data
        logger.info("Fetching historical data...")
        data = self.engine.get_historical_data(
            trading_symbol, self.start_date, self.end_date, '1d'
        )

        if not data:
            logger.error("Failed to fetch historical data")
            return None

        logger.info(f"Processing {len(data)} trading days...")

        # Process each bar
        # TODO: Abstract this to its own function, to find it more easily 
        for i, candle in enumerate(data):
            # Get current date and price
            current_date = datetime.fromtimestamp(candle['t'] / 1000)
            current_price = candle['c']

            # Record current equity
            self.engine.record_equity(current_date, {position_symbol: current_price}, self.strategy.api_url)

            # Call strategy's on_data method with current price and date
            try:
                self.strategy.on_data(price=current_price, current_date=current_date)
            except Exception as e:
                logger.error(f"Error in strategy.on_data() on {current_date.date()}: {e}")
                continue

        logger.info("Backtest execution completed")
        self.strategy.backtest_close()

        # Calculate and display results
        logger.info("Calculating metrics...")
        self.engine.calculate_metrics(self.strategy.api_url)
        self.engine.print_results()
        self.engine.save_results()

        return self.engine.results

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
