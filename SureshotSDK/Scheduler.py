import time
import logging
from typing import Callable, Any, Optional
from datetime import datetime, timedelta
from .Portfolio import Portfolio
from .Polygon import PolygonClient

class Scheduler:
    def __init__(self):
        self.tasks = []
        self.running = False
        self.portfolio = Portfolio()
        self.start_date = None
        self.end_date = None
        self.polygon_client = PolygonClient()
        self.logger = logging.getLogger(__name__)

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

    def stop(self):
        """Stop the scheduler"""
        self.running = False

    def price_fetcher(self, symbol: str) -> Optional[float]:
        """
        Fetch current price using Polygon client

        Args:
            symbol: Stock symbol to fetch price for

        Returns:
            Current price of the stock or None if unavailable
        """
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

    def set_start_date(self, year: int, month: int, day: int):
        """
        Set the start date for backtesting

        Args:
            year: Year
            month: Month
            day: Day
        """
        self.start_date = datetime(year, month, day)

    def set_end_date(self, year: int, month: int, day: int):
        """
        Set the end date for backtesting

        Args:
            year: Year
            month: Month
            day: Day
        """
        self.end_date = datetime(year, month, day)

    def set_cash(self, amount: float):
        """
        Set the initial cash amount

        Args:
            amount: Cash amount to set
        """
        self.portfolio.reset(amount)

    def buy_all(self, symbol: str):
        """
        Buy all possible shares of a symbol with available cash

        Args:
            symbol: Stock symbol to buy
        """
        current_price = self.price_fetcher(symbol)
        self.portfolio.buy_all(symbol, current_price)

    def sell_all(self, symbol: str):
        """
        Sell all shares of a symbol

        Args:
            symbol: Stock symbol to sell
        """
        current_price = self.price_fetcher(symbol)
        self.portfolio.sell_all(symbol, current_price)
