"""
Opening Range Breakout (ORB) Strategy with Daily Stock Scanner

Strategy Logic:
1. Daily scan: Find highest volume stock with >10% ATR and price >$5
2. Calculate opening range: first 5 minutes of trading day
3. Entry: Breakout of opening range high (long) or low (short)
4. Exit: Take-profit (30% ATR) OR stop-loss (50% ATR) OR end of day
5. Position sizing: Risk 1% of portfolio per trade

Modes:
- LIVE: Connects to portfolio API, trades via IBKR
- BACKTEST: Uses intraday backtesting engine
- OPTIMIZATION: Runs in optimization framework
"""

import SureshotSDK
from SureshotSDK import TradingStrategy
from datetime import datetime, time, timedelta
import logging
import os
from typing import Optional
from .scanner import StockScanner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

STRATEGY_NAME = "ORB_HighVolume"
ATR_PERIOD = 14
OPENING_RANGE_MINUTES = 5
OPTIMIZATION_TAKE_PROFIT_ATR_DISTANCE = 0.3  # 30% of ATR
OPTIMIZATION_STOP_LOSS_ATR_DISTANCE = 0.5    # 50% of ATR
STOP_LOSS_RISK_SIZE = 0.01      # Risk 1% per trade
MIN_STOCK_PRICE = 5.0
MIN_ATR_PERCENT = 10.0
LEVERAGE = 4.0

# Trading mode
TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")

# Portfolio API URL
API_URL = os.getenv("API_URL", "http://localhost:8000")

# Backtest settings
# BACKTEST_START_DATE = (2025, 1, 1)
# BACKTEST_END_DATE = (2025, 12, 31)
# BACKTEST_INITIAL_CASH = 100000

# Market hours (ET)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
OPENING_RANGE_END = time(9, 35)  # 5 minutes after open

# Rebalance frequency: Scan for new stock every N days when not in position
REBALANCE_FREQUENCY_DAYS = 1

# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class ORBStrategy(TradingStrategy):
    """
    Opening Range Breakout strategy with daily stock scanning
    """

    name = STRATEGY_NAME

    def __init__(self):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.trading_mode = TRADING_MODE

        # Stock scanner
        self.scanner = StockScanner(
            min_price=MIN_STOCK_PRICE,
            min_atr_percent=MIN_ATR_PERCENT,
            atr_period=ATR_PERIOD
        )

        # Current trading symbol (changes based on scan)
        self.trading_symbol = None

        # ATR indicator (will be reset when symbol changes)
        self.atr = None

        # Opening range tracking
        self.opening_range_high = None
        self.opening_range_low = None
        self.opening_range_calculated = False

        # Position tracking
        self.entry_price = None
        self.take_profit_price = None
        self.stop_loss_price = None
        self.position_direction = None  # 'LONG' or 'SHORT'

        # Date tracking
        self.current_trading_date = None
        self.last_scan_date = None
        self.last_rebalance_date = None

    def _get_current_datetime(self, passed_datetime=None):
        """
        Get current datetime for strategy logic

        Args:
            passed_datetime: Datetime passed from backtesting engine (None in LIVE mode)

        Returns:
            datetime: Current datetime (simulated in backtest, real in live)
        """
        if passed_datetime is not None:
            return passed_datetime
        return SureshotSDK.get_system_time()

    def initialize(self):
        """Initialize for LIVE trading"""
        logger.info(f"Initializing {self.name} for LIVE trading")
        self.scan_for_stock()

    def backtest_initialize(self,start_date,end_date):
        """Initialize for BACKTEST mode"""
        self.set_start_date(start_date)
        self.set_end_date(end_date)

        logger.info(f"Initialized {self.name} for backtesting")

    def scan_for_stock(self, current_date=None):
        """
        Scan for best stock to trade

        Args:
            current_date: Current date (passed in backtest mode, None in LIVE mode)
        """
        logger.info("Scanning for best stock candidate...")

        top_symbol = self.scanner.get_top_candidate(current_date=current_date)

        if top_symbol:
            if top_symbol != self.trading_symbol:
                logger.info(f"Selected new symbol: {top_symbol} (was: {self.trading_symbol})")
                self.trading_symbol = top_symbol

                # Reset ATR for new symbol
                self.atr = SureshotSDK.ATR(self.trading_symbol, ATR_PERIOD)

            # Use passed date if available, otherwise get current date
            current_datetime = self._get_current_datetime(current_date)
            self.last_scan_date = current_datetime.date() if isinstance(current_datetime, datetime) else current_datetime
        else:
            # logger.warning("No suitable stock found in scan. Using SPY as fallback.")
            # self.trading_symbol = "SPY"
            # self.atr = SureshotSDK.ATR("SPY", ATR_PERIOD)
            logger.warning("No suitable stock found in scan.")
            self.trading_symbol = None
            self.atr = None

    def should_rebalance(self, current_date) -> bool:
        """
        Check if should scan for new stock

        Only rebalance when:
        1. Not in a position
        2. N days have passed since last rebalance
        """
        if self.invested:
            return False

        if not self.last_rebalance_date:
            return True

        days_since_rebalance = (current_date - self.last_rebalance_date).days
        return days_since_rebalance >= REBALANCE_FREQUENCY_DAYS

    def reset_daily_state(self, current_date=None):
        """
        Reset state for new trading day

        Args:
            current_date: Current date (passed in backtest mode, None in LIVE mode)
        """
        self.opening_range_high = None
        self.opening_range_low = None
        self.opening_range_calculated = False

        # Get current date (use passed date in backtest, real date in live)
        current_datetime = self._get_current_datetime(current_date)
        date_obj = current_datetime.date() if isinstance(current_datetime, datetime) else current_datetime

        # Check if should scan for new stock
        if self.should_rebalance(date_obj):
            self.scan_for_stock(current_date)
            self.last_rebalance_date = date_obj

    def is_market_open_time(self, current_time: time) -> bool:
        """Check if within market hours"""
        return MARKET_OPEN <= current_time < MARKET_CLOSE

    def is_opening_range_period(self, current_time: time) -> bool:
        """Check if currently in opening range calculation period"""
        return MARKET_OPEN <= current_time < OPENING_RANGE_END

    def calculate_opening_range(self, bars: list):
        """Calculate opening range from first 5 minutes"""
        if len(bars) == 0:
            return

        highs = [bar['high'] for bar in bars]
        lows = [bar['low'] for bar in bars]

        self.opening_range_high = max(highs)
        self.opening_range_low = min(lows)
        self.opening_range_calculated = True

        logger.info(f"Opening range for {self.trading_symbol}: High ${self.opening_range_high:.2f}, Low ${self.opening_range_low:.2f}")

    def calculate_position_size(self, price: float, atr_value: float) -> int:
        """Calculate position size based on 1% risk"""
        if not self.portfolio or atr_value == 0:
            return 0

        risk_amount = self.portfolio.cash * STOP_LOSS_RISK_SIZE
        stop_distance = atr_value * OPTIMIZATION_STOP_LOSS_ATR_DISTANCE
        shares = int(risk_amount / stop_distance) if stop_distance > 0 else 0

        return shares

    def on_minute_bar(self, bar: dict, current_datetime: datetime = None):
        """
        Process minute bar data

        Args:
            bar: Minute bar data dictionary
            current_datetime: Current datetime (passed by backtesting engine, None in LIVE mode)
        """
        # Get current datetime (use passed datetime in backtest, real time in live)
        current_datetime = self._get_current_datetime(current_datetime)
        current_time = current_datetime.time()
        current_date = current_datetime.date()

        # Check if new trading day
        if self.current_trading_date != current_date:
            self.current_trading_date = current_date
            self.reset_daily_state(current_datetime)

        # Skip if outside market hours
        if not self.is_market_open_time(current_time):
            return

        # Skip if no trading symbol selected
        if not self.trading_symbol:
            return

        price = bar['close']
        high = bar['high']
        low = bar['low']

        # Update ATR
        if self.atr:
            self.atr.Update(high, low, price)
            atr_value = self.atr.get_value()
        else:
            logger.warning("ATR not initialized")
            return

        # During opening range: collect data
        if self.is_opening_range_period(current_time):
            if not hasattr(self, 'opening_bars'):
                self.opening_bars = []
            self.opening_bars.append(bar)
            return

        # Calculate opening range if not yet done
        if not self.opening_range_calculated and hasattr(self, 'opening_bars'):
            self.calculate_opening_range(self.opening_bars)
            del self.opening_bars

        # Skip if opening range not calculated
        if not self.opening_range_calculated:
            return

        # Position management
        if self.invested:
            # Check exit conditions
            if self.position_direction == 'LONG':
                if price >= self.take_profit_price:
                    logger.info(f"Take profit hit for {self.trading_symbol}: ${price:.2f} >= ${self.take_profit_price:.2f}")
                    self.sell_all(self.trading_symbol)
                    return
                elif price <= self.stop_loss_price:
                    logger.info(f"Stop loss hit for {self.trading_symbol}: ${price:.2f} <= ${self.stop_loss_price:.2f}")
                    self.sell_all(self.trading_symbol)
                    return
            if self.position_direction == 'SHORT':
                if price <= self.take_profit_price:
                    logger.info(f"Take profit hit for {self.trading_symbol}: ${price:.2f} <= ${self.take_profit_price:.2f}")
                    self.sell_all(self.trading_symbol)
                    return
                elif price >= self.stop_loss_price:
                    logger.info(f"Stop loss hit for {self.trading_symbol}: ${price:.2f} >= ${self.stop_loss_price:.2f}")
                    self.sell_all(self.trading_symbol)
                    return

            # End of day exit
            if current_time >= time(15, 59):
                logger.info(f"End of day exit for {self.trading_symbol}")
                self.sell_all(self.trading_symbol)
                return
        else:
            # Entry logic: Long breakout
            if high > self.opening_range_high:
                logger.info(f"Long breakout for {self.trading_symbol}: ${high:.2f} > ${self.opening_range_high:.2f}")

                position_size = self.calculate_position_size(price, atr_value)

                if position_size > 0:
                    self.entry_price = price
                    self.position_direction = 'LONG'
                    self.take_profit_price = price + (atr_value * OPTIMIZATION_TAKE_PROFIT_ATR_DISTANCE)
                    self.stop_loss_price = price - (atr_value * OPTIMIZATION_STOP_LOSS_ATR_DISTANCE)

                    logger.info(f"Entering LONG {self.trading_symbol}: {position_size} shares @ ${price:.2f}")
                    logger.info(f"Take Profit: ${self.take_profit_price:.2f}, Stop Loss: ${self.stop_loss_price:.2f}")

                    self.buy_all(self.trading_symbol)
            
            elif low < self.opening_range_low:
                logger.info(f"Short breakout for {self.trading_symbol}: ${low:.2f} < ${self.opening_range_low:.2f}")

                position_size = self.calculate_position_size(price, atr_value)

                if position_size != 0:
                    self.entry_price = price
                    self.position_direction = 'SHORT'
                    self.take_profit_price = price - (atr_value * OPTIMIZATION_TAKE_PROFIT_ATR_DISTANCE)
                    self.stop_loss_price = price + (atr_value * OPTIMIZATION_STOP_LOSS_ATR_DISTANCE)

                    logger.info(f"Entering SHORT {self.trading_symbol}: -{position_size} shares @ ${price:.2f}")
                    logger.info(f"Take Profit: ${self.take_profit_price:.2f}, Stop Loss: ${self.stop_loss_price:.2f}")

                    self.sell_short_all(self.trading_symbol)


    def on_data(self, price=None, current_date=None):
        """
        Daily data handler (for backtesting frameworks that provide daily data)

        Args:
            price: Current price (not used for ORB)
            current_date: Current date (passed by backtesting engine, None in LIVE mode)
        """
        logger.warning("ORB strategy requires minute data. Use on_minute_bar() instead.")

    def run(self):
        """Run strategy"""
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")
        logger.info(f"Current symbol: {self.trading_symbol}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main(strategy: ORBStrategy):
    """Main loop for LIVE trading"""
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True

    logger.warning("ORB strategy requires minute bar streaming")
    logger.warning("Integration with minute bar provider needed for LIVE mode")

    while strategy.running:
        try:
            logger.info(f"Monitoring {strategy.trading_symbol}...")
            strategy.idle_seconds(60)

        except KeyboardInterrupt:
            logger.info("Stopping strategy...")
            strategy.running = False
            break


if __name__ == "__main__":
    strategy = ORBStrategy()

    if TRADING_MODE == "BACKTEST":
        logger.info("Strategy initialized for BACKTEST mode")
        logger.info("Run via: python backtest.py")
    elif TRADING_MODE == "LIVE":
        strategy.initialize()
        main(strategy)
    elif TRADING_MODE == "OPTIMIZATION":
        logger.info("Strategy initialized for OPTIMIZATION mode")
    else:
        logger.error(f"Unknown TRADING_MODE: {TRADING_MODE}")
