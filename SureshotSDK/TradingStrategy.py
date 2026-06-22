import time
import logging
import signal
import os
import requests
from typing import Callable, Any, Optional
from datetime import datetime, timedelta
from .Portfolio import Portfolio
from .Polygon import PolygonClient

class TradingStrategy:
    def __init__(self, portfolio: Portfolio = None, strategy_name: str = None, api_url: str = None, timeframe: str = '1d'):
        self.tasks = []
        self.timeframe = timeframe
        self.running = False
        # self.portfolio = Portfolio()
        self.portfolio = portfolio
        self.start_date = None
        self.end_date = None
        self.polygon_client = PolygonClient() if os.getenv("POLYGON_API_KEY") else None
        self._data_fetcher = None 
        self.logger = logging.getLogger(__name__)
        self.strategy_name = strategy_name or getattr(self, 'name', None)
        self.api_url = api_url or os.getenv("API_URL")
        self.handle_shutdown_signals()

    def handle_shutdown_signals(self):
        signal.signal(signal.SIGTERM, self.shutdown_handler)
        signal.signal(signal.SIGINT, self.shutdown_handler)

    def shutdown_handler(self, signum, frame):
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        if self._data_fetcher is not None:
            self._data_fetcher.close()

    def idle_seconds(self, sleepDuration):
        for _ in range(sleepDuration):
            if not self.running:
                break
            time.sleep(1)

    def add_task(self, func: Callable, interval: int, *args, **kwargs):
        """Add a task to be executed at regular intervals

        Args:
            func: Function to execute
            interval: Interval in seconds between executions
            *args, **kwargs: Arguments to pass to the function
        """
        task = {
            'func': func,
            'interval': interval,
            'args': args,
            'kwargs': kwargs,
            'last_run': None,
            'next_run': datetime.now()
        }
        self.tasks.append(task)
        return len(self.tasks) - 1  # Return task ID

    def remove_task(self, task_id: int):
        """Remove a task by its ID"""
        if 0 <= task_id < len(self.tasks):
            self.tasks.pop(task_id)

    def run_once(self):
        """Execute all due tasks once"""
        now = datetime.now()
        for task in self.tasks:
            if now >= task['next_run']:
                try:
                    result = task['func'](*task['args'], **task['kwargs'])
                    task['last_run'] = now
                    task['next_run'] = now + timedelta(seconds=task['interval'])
                    print(f"Task executed at {now}: {task['func'].__name__}")
                except Exception as e:
                    print(f"Error executing task {task['func'].__name__}: {e}")

    def run(self, duration: Optional[int] = None):
        """Run the scheduler continuously

        Args:
            duration: Optional duration in seconds to run (None for infinite)
        """
        self.running = True
        start_time = datetime.now()

        print(f"Scheduler started at {start_time}")

        try:
            while self.running:
                self.run_once()
                time.sleep(1)  # Check every second

                if duration and (datetime.now() - start_time).seconds >= duration:
                    break

        except KeyboardInterrupt:
            print("\nScheduler stopped by user")
        finally:
            self.running = False
            print("Scheduler stopped")

    def backtest_close(self):
        """Close out position in BACKTEST mode"""
        if self.invested and hasattr(self,'positionSymbol'):
            self.sell_all(self.positionSymbol)
        if self.invested and hasattr(self,'tradingSymbol'):
            self.sell_all(self.tradingSymbol)

    def stop(self):
        """Stop the scheduler"""
        self.running = False

    def fetch_trading_mode(self) -> str:
        """Fetch trading mode from the API config and set self.trading_mode."""
        if not (self.api_url and self.strategy_name):
            self.logger.warning("Cannot fetch trading mode: api_url or strategy_name not set")
            return self.trading_mode
        try:
            response = requests.get(
                f"{self.api_url}/config/{self.strategy_name}/trading-mode",
                timeout=5
            )
            response.raise_for_status()
            mode = response.json()["trading_mode"]
            self.trading_mode = mode
            self.logger.info(f"Trading mode set from API: {mode}")
            return mode
        except Exception as e:
            fallback = os.getenv("TRADING_MODE", "PAPER")
            self.logger.error(f"Failed to fetch trading mode from API: {e} — falling back to env var: {fallback}")
            self.trading_mode = fallback
            return fallback

    def real_time_price_fetcher(self, symbol: str) -> Optional[dict]:
        try:
            if self._data_fetcher is None:
                from .DataFetcher import DataFetcherClient
                self._data_fetcher = DataFetcherClient()
            return self._data_fetcher.get_current_bar(symbol)
        except Exception as e:
            self.logger.error(f"Error fetching real-time bar for {symbol}: {e}")
            return None

    def price_fetcher(self, symbol: str) -> Optional[float]:
        """
        Fetch current price using Polygon client

        Args:
            symbol: Stock symbol to fetch price for

        Returns:
            Current price of the stock or None if unavailable
        """
        if self.polygon_client is None:
            bar = self.real_time_price_fetcher(symbol)
            return bar['c'] if bar else None
        try:
            price = self.polygon_client.get_current_price(symbol)
            if price is not None:
                self.logger.info(f"Fetched price for {symbol}: ${price:.2f}")
                return price
            else:
                self.logger.error(f"No price data available for {symbol}")
                return None
        except Exception as e:
            self.logger.error(f"Error fetching price for {symbol}: {e}")
            return None
        
    def historical_price_fetcher(self, symbol: str, date: datetime) -> Optional[float]:
        """
        Fetch historical price using Polygon client

        Args:
            symbol: Stock symbol to fetch price for
            date: Trading Date

        Returns:
            Current price of the stock or None if unavailable
        """
        try:
            price = self.polygon_client.get_historical_price(symbol, date, '1m')            
            if price is not None:
                self.logger.info(f"Fetched historical price for {symbol}: ${price:.2f}")
                return price
            else:
                self.logger.error(f"No historical price data available for {symbol}")
                return None
        except Exception as e:
            self.logger.error(f"Error fetching historical price for {symbol}: {e}")

        
    def set_start_date(self, start_date: datetime):
        """
        Set the start date for backtesting

        Args:
            year: Year
            month: Month
            day: Day
        """
        self.start_date = start_date

    def set_end_date(self, end_date: datetime):
        """
        Set the end date for backtesting

        Args:
            year: Year
            month: Month
            day: Day
        """
        self.end_date = end_date

    def set_cash(self, amount: float):
        """
        Set the initial cash amount

        Args:
            amount: Cash amount to set
        """
        self.portfolio.reset(amount)

    def buy_all(self, symbol: str, quantityOverride: int | None = None):
        """
        Buy all possible shares of a symbol with available cash

        Args:
            symbol: Stock symbol to buy
        """
        if self.trading_mode == "LIVE":
            current_price = self.price_fetcher(symbol)
        else:
            current_price = self.historical_price_fetcher(symbol, self.current_date)

        if not current_price:
            self.logger.error(f"Cannot buy {symbol}: no price available")
            return

        # If API is configured, use API-managed state
        if self.api_url and self.strategy_name:
            try:
                response = requests.post(
                    f"{self.api_url}/orders/buy_all",
                    json={
                        "strategy_name": self.strategy_name,
                        "symbol": symbol,
                        "price": current_price,
                        "quantity": quantityOverride
                    },
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                self.logger.info(
                    f"BUY_ALL: {data['quantity']} {symbol} @ ${data['price']:.2f}, "
                    f"Cash remaining: ${data['remaining_cash']:.2f}"
                )
            except Exception as e:
                self.logger.error(f"Failed to execute buy_all via API: {e}")
        else:
            # Fallback to local portfolio if no API
            if self.portfolio:
                self.portfolio.buy_all(symbol, current_price)
            else:
                self.logger.error("No API or Portfolio configured for buy_all")

    def sell_all(self, symbol: str):
        """
        Sell all shares of a symbol

        Args:
            symbol: Stock symbol to sell
        """
        if self.trading_mode == "LIVE":
            current_price = self.price_fetcher(symbol)
        else:
            current_price = self.historical_price_fetcher(symbol, self.current_date)

        if not current_price:
            self.logger.error(f"Cannot sell {symbol}: no price available")
            return

        # If API is configured, use API-managed state
        if self.api_url and self.strategy_name:
            try:
                response = requests.post(
                    f"{self.api_url}/orders/sell_all",
                    json={
                        "strategy_name": self.strategy_name,
                        "symbol": symbol,
                        "price": current_price
                    },
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                self.logger.info(
                    f"SELL_ALL: {data['quantity']} {symbol} @ ${data['price']:.2f}, "
                    f"Cash remaining: ${data['remaining_cash']:.2f}"
                )
            except Exception as e:
                self.logger.error(f"Failed to execute sell_all via API: {e}")
        else:
            # Fallback to local portfolio if no API
            if self.portfolio:
                self.portfolio.sell_all(symbol, current_price)
            else:
                self.logger.error("No API or Portfolio configured for sell_all")

    def sell_short_all(self, symbol: str, quantityOverride: int | None = None):
        """
        Sell short all shares of a symbol

        Args:
            symbol: Stock symbol to sell
        """
        if self.trading_mode == "LIVE":
            current_price = self.price_fetcher(symbol)
        else:
            current_price = self.historical_price_fetcher(symbol, self.current_date)

        if not current_price:
            self.logger.error(f"Cannot sell short {symbol}: no price available")
            return
        
        # If API is configured, use API-managed state
        if self.api_url and self.strategy_name:
            try:
                response = requests.post(
                    f"{self.api_url}/orders/sell_short_all",
                    json={
                        "strategy_name": self.strategy_name,
                        "symbol": symbol,
                        "price": current_price,
                        "quantity": quantityOverride
                    },
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                self.logger.info(
                    f"SELL_SHORT_ALL: {data['quantity']} {symbol} @ ${data['price']:.2f}, "
                    f"Cash remaining: ${data['remaining_cash']:.2f}"
                )
            except Exception as e:
                self.logger.error(f"Failed to execute sell_all via API: {e}")
        else:
            # Fallback to local portfolio if no API
            if self.portfolio:
                self.portfolio.sell_short_all(symbol, current_price)
            else:
                self.logger.error("No API or Portfolio configured for sell_short_all")

    def close_short_all(self, symbol: str):
        """
        Close all short shares of a symbol

        Args:
            symbol: Stock symbol to sell
        """
        if self.trading_mode == "LIVE":
            current_price = self.price_fetcher(symbol)
        else:
            current_price = self.historical_price_fetcher(symbol, self.current_date)

        if not current_price:
            self.logger.error(f"Cannot close short {symbol}: no price available")
            return

        # If API is configured, use API-managed state
        if self.api_url and self.strategy_name:
            try:
                response = requests.post(
                    f"{self.api_url}/orders/close_short_all",
                    json={
                        "strategy_name": self.strategy_name,
                        "symbol": symbol,
                        "price": current_price
                    },
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                self.logger.info(
                    f"CLOSE_SHORT_ALL: {data['quantity']} {symbol} @ ${data['price']:.2f}, "
                    f"Cash remaining: ${data['remaining_cash']:.2f}"
                )
            except Exception as e:
                self.logger.error(f"Failed to execute sell_all via API: {e}")
        else:
            # Fallback to local portfolio if no API
            if self.portfolio:
                self.portfolio.close_short_all(symbol, current_price)
            else:
                self.logger.error("No API or Portfolio configured for close_short_all")

    @property
    def invested(self):
        """
        Check if the strategy is currently invested

        Returns:
            bool: True if invested, False otherwise
        """
        # If API is configured, query API for invested status
        if self.api_url and self.strategy_name:
            try:
                response = requests.get(
                    f"{self.api_url}/portfolio/{self.strategy_name}/invested",
                    timeout=5
                )
                response.raise_for_status()
                data = response.json()
                return data.get("invested", False)
            except Exception as e:
                self.logger.error(f"Failed to query invested status from API: {e}")
                return False
        else:
            # Fallback to local portfolio if no API
            if self.portfolio:
                return self.portfolio.invested
            else:
                self.logger.error("No API or Portfolio configured for invested check")
                return False

    def is_trade_completed_today(self) -> bool:
        """Return True if a trade was already completed today (survives pod restarts via DB)."""
        if self.api_url and self.strategy_name:
            try:
                response = requests.get(
                    f"{self.api_url}/portfolio/{self.strategy_name}/completed",
                    timeout=5
                )
                response.raise_for_status()
                return response.json().get("completed_today", False)
            except Exception as e:
                self.logger.error(f"Failed to query completed status from API: {e}")
                return False
        return False

    def mark_trade_completed(self):
        """Persist today's trade completion to DB so restarts don't re-enter."""
        if self.api_url and self.strategy_name:
            try:
                response = requests.post(
                    f"{self.api_url}/portfolio/{self.strategy_name}/complete",
                    timeout=5
                )
                response.raise_for_status()
                self.logger.info("Trade marked complete in DB")
            except Exception as e:
                self.logger.error(f"Failed to mark trade complete via API: {e}")
