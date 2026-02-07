"""
Incredible Leverage SPXL Strategy

Strategy Logic:
- Entry: Month-end when SPY price > 252-day SMA and previous close also above SMA
- Exit: Month-end when SPY price < SMA OR mid-month stop-loss (5% below SMA)
- Position: SPXL (3x leveraged S&P 500 ETF)
- Indicator: SPY 252-day SMA

Modes:
- LIVE: Connects to portfolio API and trades via IBKR
- BACKTEST: Uses backtesting engine
- OPTIMIZATION: Runs in optimization framework
"""

import SureshotSDK
from SureshotSDK import TradingStrategy, Portfolio
from datetime import timedelta
import time
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

STRATEGY_NAME = "IncredibleLeverage_SPXL"
SIGNAL_SYMBOL = "SPY"
POSITION_SYMBOL = "SPXL"
SMA_PERIOD = 252
OPTIMIZATION_MAX_MID_MONTH_LOSS = 0.05
TIMEFRAME = "1d"

# Trading mode
TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")

# Portfolio API URL
API_URL = os.getenv("API_URL", "http://localhost:8000")
logger.info(f"API_URL: {API_URL}")

# Backtest settings
# BACKTEST_START_DATE = (2010, 1, 1)
# BACKTEST_END_DATE = (2024, 12, 31)
# BACKTEST_INITIAL_CASH = 100000

# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class IncredibleLeverageSPXL(TradingStrategy):
    """
    Incredible Leverage strategy trading SPXL based on SPY SMA
    """

    name = STRATEGY_NAME
    signalSymbol = SIGNAL_SYMBOL
    positionSymbol = POSITION_SYMBOL

    def __init__(self, max_loss=OPTIMIZATION_MAX_MID_MONTH_LOSS):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.max_loss = max_loss
        self.timeframe = TIMEFRAME
        self.sma = SureshotSDK.SMA(self.signalSymbol, SMA_PERIOD, self.timeframe)
        self.trading_mode = TRADING_MODE

        # State tracking
        self.previous_close = None
        self.previousCloseAboveSMA = False

    def initialize(self):
        """Initialize for LIVE trading"""
        self.sma.initialize()

    def backtest_initialize(self,start_date,end_date):
        """Initialize for BACKTEST mode"""
        self.set_start_date(start_date)
        self.set_end_date(end_date)

        self.signalSymbol = SIGNAL_SYMBOL
        self.positionSymbol = POSITION_SYMBOL

        self.previous_close = None
        self.previousCloseAboveSMA = False

        # Warm up the SMA with historical data
        try:
            self.sma.initialize(self.start_date-timedelta(days=self.period))
        except:
            self.sma.sma_value = 332.05

    def _get_current_date(self, passed_date=None):
        """
        Get current date for strategy logic

        Args:
            passed_date: Date passed from backtesting engine (None in LIVE mode)

        Returns:
            datetime: Current date (simulated in backtest, real in live)
        """
        if passed_date is not None:
            return passed_date
        return SureshotSDK.get_system_time()

    def is_end_of_month(self, current_date):
        """Check if current date is the last trading day of the month"""
        next_day = current_date + timedelta(days=1)
        return next_day.day == 1

    def on_data(self, price=None, current_date=None):
        """
        Process price data and generate trading signals

        Called on each bar (daily in this case)

        Args:
            price: Current price of signal symbol
            current_date: Current date (passed by backtesting engine, None in LIVE mode)
        """
        if not price:
            logger.warning("No price data available.")
            return

        # Get current date and update SMA
        self.current_date = self._get_current_date(current_date)
        self.sma.Update(price)
        current_sma = self.sma.get_value()
        if current_sma is None:
            current_sma = 0

        # Mid-month stop-loss check
        if self.invested:
            if price < (current_sma * (1 - self.max_loss)):
                logger.info(f"Mid-month stop-loss triggered: Price ${price:.2f} < SMA ${current_sma:.2f} * {1-self.max_loss}")
                self.sell_all(self.positionSymbol)

        # Month-end logic
        if self.is_end_of_month(self.current_date):
            if self.invested:
                # Exit if price below SMA
                if price < current_sma:
                    logger.info(f"Month-end exit: Price ${price:.2f} < SMA ${current_sma:.2f}")
                    self.sell_all(self.positionSymbol)
            else:
                # Entry signal: price > SMA AND previous close > SMA
                if self.previous_close:
                    if price > current_sma and self.previousCloseAboveSMA:
                        logger.info(f"Month-end entry: Price ${price:.2f} > SMA ${current_sma:.2f}")
                        self.buy_all(self.positionSymbol)

            # Update state for next month
            self.previous_close = price
            self.previousCloseAboveSMA = (price > current_sma)

    def run(self):
        """Run strategy (for LIVE mode)"""
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main(strategy: IncredibleLeverageSPXL):
    """
    Main loop for LIVE trading

    Fetches price data and calls strategy.on_data() continuously
    """
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"Signal Symbol: {strategy.signalSymbol}")
    logger.info(f"Position Symbol: {strategy.positionSymbol}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True
    while strategy.running:
        try:
            # Fetch current price
            price = strategy.price_fetcher(strategy.signalSymbol)
            logger.debug(f"Fetched price for {strategy.signalSymbol}: ${price:.2f}")

            # Pass price to strategy logic
            strategy.on_data(price)

            # Sleep for 60 seconds before next check
            strategy.idle_seconds(60)

        except KeyboardInterrupt:
            logger.info("Stopping strategy...")
            strategy.running = False
            break
        except Exception as e:
            logger.error(f"Error in strategy loop: {e}")
            # Sleep before retrying on error
            strategy.idle_seconds(60)


if __name__ == "__main__":
    strategy = IncredibleLeverageSPXL(max_loss=OPTIMIZATION_MAX_MID_MONTH_LOSS)

    if TRADING_MODE == "BACKTEST":
        # Backtest mode will be handled by backtest.py at repo root
        logger.info("Strategy initialized for BACKTEST mode")
        logger.info("Run via: python backtest.py")
    elif TRADING_MODE == "LIVE":
        # Live trading mode
        strategy.initialize()
        main(strategy)
    elif TRADING_MODE == "OPTIMIZATION":
        # Optimization mode
        logger.info("Strategy initialized for OPTIMIZATION mode")
        # Optimization framework will call strategy methods directly
    else:
        logger.error(f"Unknown TRADING_MODE: {TRADING_MODE}")
