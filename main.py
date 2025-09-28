#!/usr/bin/env python3
"""
Main script to run IncredibleLeverageSPXL strategy with daily candle updates.

This script:
- Instantiates the IncredibleLeverageSPXL strategy
- Fetches daily candles for SPXL and SPY
- Updates the SMA indicator with new data
- Runs the strategy's on_tick method
- Schedules execution once per day at market close
- Runs indefinitely until Ctrl+C is pressed
- Uses non-blocking execution with asyncio
"""

import asyncio
import signal
import sys
import logging
from datetime import datetime, time, timedelta
from typing import Optional

from IncredibleLeverageSPXL import IncredibleLeverageSPXL
from pull_candles import PolygonMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('strategy.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class StrategyRunner:
    """Main strategy runner that manages daily execution."""

    def __init__(self):
        self.strategy = None
        self.polygon_client = None
        self.running = True
        self.last_execution_date = None

        # 1 hr before market close time (3:00 PM ET)
        self.execution_time = time(20, 0, 0)  # 20:00 UTC (3:00 PM ET)

    async def initialize(self):
        """Initialize the strategy and data sources."""
        try:
            logger.info("Initializing IncredibleLeverageSPXL strategy...")
            self.strategy = IncredibleLeverageSPXL()

            logger.info("Initializing Polygon API client...")
            self.polygon_client = PolygonMiddleware()

            # Initialize the strategy
            self.strategy.on_start()
            logger.info("Strategy initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise

    async def fetch_daily_candles(self, symbol: str, days_back: int = 1) -> Optional[dict]:
        """
        Fetch daily candles for a symbol.

        Args:
            symbol: The stock symbol to fetch
            days_back: Number of days back to fetch (default: 1)

        Returns:
            dict: Candle data from Polygon API or None if failed
        """
        try:
            # TODO: Add condition to avoid fetching on weekends/holidays
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

            logger.info(f"Fetching daily candles for {symbol} from {start_date} to {end_date}")

            candles = self.polygon_client.fetch_candles(
                symbol=symbol,
                multiplier=1,
                timespan='day',
                startDate=start_date,
                endDate=end_date
            )

            if candles and 'results' in candles and candles['results']:
                logger.info(f"Fetched {len(candles['results'])} candles for {symbol}")
                return candles
            else:
                logger.warning(f"No candle data received for {symbol}")
                return None

        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            return None

    async def update_strategy_data(self):
        """Update the strategy with latest candle data."""
        try:
            # Fetch candles for SPY (for SMA calculation)
            spy_candles = await self.fetch_daily_candles('SPY', days_back=300)  # Fetch enough for 252-day SMA
            if spy_candles:
                # Update the SMA indicator with SPY data
                self.strategy.indicator.update(spy_candles)
                logger.info(f"Updated SMA with SPY data. Current SMA: {self.strategy.indicator.getValue()}")

            # Fetch current SPXL data for strategy execution
            spxl_candles = await self.fetch_daily_candles('SPXL', days_back=1)
            if spxl_candles and 'results' in spxl_candles and spxl_candles['results']:
                latest_candle = spxl_candles['results'][-1]

                # Mock the data structure expected by strategy
                # This would need to be adapted based on actual data interface
                self.strategy.data = {
                    'SPXL': MockAssetData(latest_candle)
                }

                logger.info(f"Updated SPXL data. Price: ${latest_candle['c']}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error updating strategy data: {e}")
            return False

    async def execute_daily_strategy(self):
        """Execute the strategy's daily logic."""
        try:
            current_date = datetime.now().strftime('%Y-%m-%d')

            if self.last_execution_date == current_date:
                logger.debug(f"Strategy already executed today ({current_date})")
                return

            logger.info(f"Executing daily strategy for {current_date}")

            # Update strategy data
            if await self.update_strategy_data():
                # Execute strategy logic
                self.strategy.on_tick()
                self.last_execution_date = current_date
                logger.info("Daily strategy execution completed")
            else:
                logger.warning("Failed to update strategy data, skipping execution")

        except Exception as e:
            logger.error(f"Error during strategy execution: {e}")

    async def calculate_next_execution_delay(self) -> float:
        """
        Calculate seconds until next execution time.

        Returns:
            float: Seconds to wait until next execution
        """
        now = datetime.now()
        today_execution = datetime.combine(now.date(), self.execution_time)

        # If we've passed today's execution time, schedule for tomorrow
        if now >= today_execution:
            next_execution = today_execution + timedelta(days=1)
        else:
            next_execution = today_execution

        delay = (next_execution - now).total_seconds()
        logger.info(f"Next execution scheduled for {next_execution} (in {delay/3600:.1f} hours)")
        return delay

    async def run_strategy_loop(self):
        """Main strategy execution loop."""
        logger.info("Starting strategy execution loop...")

        while self.running:
            try:
                # Execute strategy immediately on first run, then daily
                if self.last_execution_date is None:
                    await self.execute_daily_strategy()

                # Calculate time until next execution
                delay = await self.calculate_next_execution_delay()

                # Wait until next execution time, checking periodically for shutdown
                check_interval = min(300, delay)  # Check every 5 minutes or less
                while delay > 0 and self.running:
                    wait_time = min(check_interval, delay)
                    await asyncio.sleep(wait_time)
                    delay -= wait_time

                # Execute daily strategy if still running
                if self.running:
                    await self.execute_daily_strategy()

            except asyncio.CancelledError:
                logger.info("Strategy loop cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in strategy loop: {e}")
                # Wait a bit before retrying to avoid rapid failures
                await asyncio.sleep(60)

    def shutdown(self):
        """Gracefully shutdown the strategy runner."""
        logger.info("Shutting down strategy runner...")
        self.running = False
        if self.strategy:
            try:
                self.strategy.on_stop()
            except Exception as e:
                logger.error(f"Error during strategy shutdown: {e}")


class MockAssetData:
    """Mock asset data class to interface with strategy."""

    def __init__(self, candle_data):
        self.candle = candle_data

    def getPrice(self):
        """Return the closing price."""
        return self.candle['c']

    def getDate(self):
        """Return the candle timestamp as datetime."""
        return datetime.fromtimestamp(self.candle['t'] / 1000)


async def main():
    """Main entry point."""
    runner = StrategyRunner()

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        runner.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize the strategy
        await runner.initialize()

        # Start the main strategy loop
        await runner.run_strategy_loop()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1
    finally:
        runner.shutdown()
        logger.info("Strategy runner stopped")

    return 0


if __name__ == "__main__":
    try:
        # Run the async main function
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nGracefully shutting down...")
        sys.exit(0)