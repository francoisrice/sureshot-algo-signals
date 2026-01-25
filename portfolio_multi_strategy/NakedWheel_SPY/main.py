"""
Naked Wheel Strategy on SPY

Strategy Logic:
- Entry: Sell OTM puts (bullish) or calls (bearish) at ~1.6% OTM, 10+ DTE
- Exit: Take-profit (30% gain on premium) OR assignment at strike price
- Rebalance: When out of position AND 6 months since last rebalance
- Direction switches on assignment (put assignment -> sell calls, call assignment -> sell puts)

Options Income Strategy:
- Collect premium by selling options
- Switch direction based on assignment risk
- Conservative out-of-the-money strikes

Modes:
- LIVE: Connects to portfolio API and trades via IBKR
- BACKTEST: Uses backtesting engine with simulated options
- OPTIMIZATION: Runs in optimization framework
"""

import SureshotSDK
from SureshotSDK import TradingStrategy, Portfolio
from datetime import datetime, timedelta
import time
import logging
import os
from typing import Optional, NamedTuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

STRATEGY_NAME = "NakedWheel_SPY"
TRADING_SYMBOL = "SPY"
OTM_THRESHOLD = 0.016  # 1.6% out-of-the-money
MIN_DTE = 10  # Minimum days to expiration
TAKE_PROFIT_PERCENT = 0.3  # Take profit at 30% of premium
RISK_FREE_RATE = 0.045  # 4.5% risk-free rate
DEFAULT_VOLATILITY = 0.20  # 20% default volatility
TIMEFRAME = "1d"

# Rebalance frequency: 6 months
REBALANCE_FREQUENCY_DAYS = 180

# Trading mode
TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")

# Portfolio API URL
API_URL = os.getenv("API_URL", "http://localhost:8000")

# Backtest settings
BACKTEST_START_DATE = (2020, 1, 1)
BACKTEST_END_DATE = (2024, 12, 31)
BACKTEST_INITIAL_CASH = 100000

# ============================================================================
# OPTION CONTRACT
# ============================================================================

class OptionContract(NamedTuple):
    """Simulated option contract"""
    symbol: str
    strike_price: float
    expiration_date: datetime
    option_type: str  # 'PUT' or 'CALL'
    entry_price: float
    contracts: int


# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class NakedWheelSPY(TradingStrategy):
    """
    Naked Wheel strategy trading SPY options

    Sells out-of-the-money options to collect premium income.
    Switches between puts and calls based on assignment risk.
    """

    name = STRATEGY_NAME
    tradingSymbol = TRADING_SYMBOL

    def __init__(
        self,
        otm_threshold=OTM_THRESHOLD,
        min_dte=MIN_DTE,
        take_profit_percent=TAKE_PROFIT_PERCENT
    ):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.otm_threshold = otm_threshold
        self.min_dte = min_dte
        self.take_profit_percent = take_profit_percent
        self.timeframe = TIMEFRAME
        self.trading_mode = TRADING_MODE

        # Direction: 1 = sell puts (bullish), 0 = sell calls (bearish after assignment)
        self.direction = 1

        # Current option contract
        self.current_contract: Optional[OptionContract] = None

        # Price history for volatility calculation
        self.price_history = []
        self.volatility_lookback = 30  # days

        # Last rebalance tracking
        self.last_rebalance_date = None

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

    def initialize(self):
        """Initialize for LIVE trading"""
        logger.info(f"Initializing {self.name} for LIVE trading")
        logger.info(f"Trading Symbol: {self.tradingSymbol}")
        logger.info(f"OTM Threshold: {self.otm_threshold*100:.1f}%")
        logger.info(f"Min DTE: {self.min_dte}")

    def backtest_initialize(self):
        """Initialize for BACKTEST mode"""
        self.set_start_date(*BACKTEST_START_DATE)
        self.set_end_date(*BACKTEST_END_DATE)
        self.set_cash(BACKTEST_INITIAL_CASH)

        self.direction = 1
        self.current_contract = None
        self.price_history = []
        self.last_rebalance_date = None

        logger.info(f"Initialized {self.name} for backtesting")
        logger.info(f"Trading Symbol: {self.tradingSymbol}")
        logger.info(f"OTM Threshold: {self.otm_threshold*100:.1f}%")

    def can_rebalance(self, current_date) -> bool:
        """
        Check if strategy can be rebalanced

        Args:
            current_date: Current date

        Returns:
            True if can rebalance, False otherwise
        """
        if self.invested:
            return False

        if self.last_rebalance_date is None:
            return True

        days_since_rebalance = (current_date - self.last_rebalance_date).days
        return days_since_rebalance >= REBALANCE_FREQUENCY_DAYS

    def calculate_volatility(self) -> float:
        """
        Calculate historical volatility from price history

        Returns:
            Annualized volatility
        """
        if len(self.price_history) < 2:
            return DEFAULT_VOLATILITY

        import numpy as np

        # Calculate log returns
        prices = np.array(self.price_history)
        log_returns = np.diff(np.log(prices))

        if len(log_returns) == 0:
            return DEFAULT_VOLATILITY

        # Annualize: std * sqrt(252)
        daily_vol = np.std(log_returns)
        annual_vol = daily_vol * np.sqrt(252)

        # Use default if calculation fails or is unreasonable
        if np.isnan(annual_vol) or annual_vol <= 0 or annual_vol > 2.0:
            return DEFAULT_VOLATILITY

        return annual_vol

    def on_data(self, price=None, current_date=None):
        """
        Process price data and generate trading signals

        Called on each bar (daily in this case)

        Args:
            price: Current price of trading symbol
            current_date: Current date (passed by backtesting engine, None in LIVE mode)
        """
        if not price:
            logger.warning("No price data available.")
            return

        # Get current date
        current_date = self._get_current_date(current_date)

        # Track price history for volatility calculation
        self.price_history.append(price)
        if len(self.price_history) > self.volatility_lookback:
            self.price_history.pop(0)

        # Calculate historical volatility
        volatility = self.calculate_volatility()

        # If not in position, sell a new option
        if not self.invested:
            if self.can_rebalance(current_date):
                self.open_option_position(current_date, price, volatility)
                self.last_rebalance_date = current_date
        else:
            # If in position, check for exit conditions
            if self.current_contract is not None:
                self.check_exit_conditions(current_date, price, volatility)

    def open_option_position(self, current_date, underlying_price, volatility):
        """
        Open a new option position (sell put or call)

        Args:
            current_date: Current date
            underlying_price: Current price of underlying
            volatility: Historical volatility
        """
        # Calculate strike price based on direction
        if self.direction == 1:
            # Sell PUT (bullish)
            option_type = 'PUT'
            strike_price = underlying_price * (1 - self.otm_threshold)
        else:
            # Sell CALL (bearish)
            option_type = 'CALL'
            strike_price = underlying_price * (1 + self.otm_threshold)

        # Round strike to nearest 0.5
        strike_price = round(strike_price * 2) / 2

        # Calculate expiration date
        expiration_date = current_date + timedelta(days=self.min_dte)

        # Calculate option price using Black-Scholes
        try:
            from SureshotSDK.options.BlackScholes import (
                calculate_put_price,
                calculate_call_price,
                days_to_years
            )

            time_to_expiration = days_to_years(self.min_dte)

            if option_type == 'PUT':
                option_price = calculate_put_price(
                    underlying_price,
                    strike_price,
                    time_to_expiration,
                    RISK_FREE_RATE,
                    volatility
                )
            else:
                option_price = calculate_call_price(
                    underlying_price,
                    strike_price,
                    time_to_expiration,
                    RISK_FREE_RATE,
                    volatility
                )
        except ImportError:
            # Fallback if Black-Scholes not available
            logger.warning("Black-Scholes module not available, using simplified pricing")
            option_price = underlying_price * 0.02  # Simple 2% premium estimate

        # Calculate number of contracts
        # Each contract = 100 shares
        if self.portfolio:
            contracts = int(self.portfolio.cash / (strike_price * 100))
        else:
            contracts = 1

        if contracts == 0:
            logger.warning(f"Insufficient capital to sell options")
            return

        # Create contract
        self.current_contract = OptionContract(
            symbol=f"{self.tradingSymbol}_{option_type}_{strike_price}_{expiration_date.date()}",
            strike_price=strike_price,
            expiration_date=expiration_date,
            option_type=option_type,
            entry_price=option_price,
            contracts=contracts
        )

        logger.info(
            f"Selling {contracts} {option_type} contracts at ${strike_price:.2f} strike "
            f"for ${option_price:.2f} premium (expires {expiration_date.date()})"
        )

        # In a real implementation, this would execute the option trade
        # For now, we'll use buy_all to simulate taking a position
        # (In reality, selling options is a credit transaction)
        # self.buy_all(self.tradingSymbol)

    def check_exit_conditions(self, current_date, underlying_price, volatility):
        """
        Check if option position should be exited

        Args:
            current_date: Current date
            underlying_price: Current price of underlying
            volatility: Historical volatility
        """
        if self.current_contract is None:
            return

        # Calculate current option price
        days_to_exp = (self.current_contract.expiration_date - current_date).days
        time_to_exp = max(days_to_exp / 365.0, 0.001)  # Avoid division by zero

        if days_to_exp <= 0:
            # Option expired, check for assignment
            self.handle_expiration(current_date, underlying_price)
            return

        # Calculate current option value
        try:
            from SureshotSDK.options.BlackScholes import (
                calculate_put_price,
                calculate_call_price
            )

            if self.current_contract.option_type == 'PUT':
                current_price = calculate_put_price(
                    underlying_price,
                    self.current_contract.strike_price,
                    time_to_exp,
                    RISK_FREE_RATE,
                    volatility
                )
            else:
                current_price = calculate_call_price(
                    underlying_price,
                    self.current_contract.strike_price,
                    time_to_exp,
                    RISK_FREE_RATE,
                    volatility
                )
        except ImportError:
            # Fallback calculation
            current_price = max(0, abs(underlying_price - self.current_contract.strike_price) * 0.01)

        # Check for take-profit
        # We sold at entry_price, so profit means current_price is lower
        profit_target = self.current_contract.entry_price * (1 - self.take_profit_percent)

        if current_price <= profit_target:
            logger.info(
                f"Take-profit hit: Current ${current_price:.2f} <= Target ${profit_target:.2f}"
            )
            self.close_option_position(current_date, current_price, "Take-profit")
            return

        # Check for assignment risk (price crossing strike)
        if self.current_contract.option_type == 'PUT':
            if underlying_price <= self.current_contract.strike_price:
                logger.info(
                    f"PUT assignment risk: Price ${underlying_price:.2f} <= Strike ${self.current_contract.strike_price:.2f}"
                )
                # Switch to selling calls
                self.direction = 0
                self.close_option_position(current_date, current_price, "PUT assignment")
                return
        else:  # CALL
            if underlying_price >= self.current_contract.strike_price:
                logger.info(
                    f"CALL assignment risk: Price ${underlying_price:.2f} >= Strike ${self.current_contract.strike_price:.2f}"
                )
                # Switch to selling puts
                self.direction = 1
                self.close_option_position(current_date, current_price, "CALL assignment")
                return

    def handle_expiration(self, current_date, underlying_price):
        """
        Handle option expiration

        Args:
            current_date: Current date
            underlying_price: Current price of underlying
        """
        if self.current_contract is None:
            return

        logger.info(f"Option expired on {current_date.date()}")

        # Check if option expired in-the-money (ITM)
        if self.current_contract.option_type == 'PUT':
            if underlying_price < self.current_contract.strike_price:
                # PUT expired ITM - assignment
                logger.info("PUT assigned - switching to selling CALLs")
                self.direction = 0
        else:  # CALL
            if underlying_price > self.current_contract.strike_price:
                # CALL expired ITM - assignment
                logger.info("CALL assigned - switching to selling PUTs")
                self.direction = 1

        # Option expired - full premium captured or assignment occurred
        self.current_contract = None
        # self.sell_all(self.tradingSymbol)

    def close_option_position(self, current_date, current_price, reason):
        """
        Close the current option position

        Args:
            current_date: Current date
            current_price: Current option price
            reason: Reason for closing
        """
        logger.info(f"Closing option position: {reason}")

        # Calculate profit/loss
        if self.current_contract:
            profit = (self.current_contract.entry_price - current_price) * self.current_contract.contracts * 100
            logger.info(f"P&L: ${profit:.2f}")

        self.current_contract = None
        # self.sell_all(self.tradingSymbol)

    def run(self):
        """Run strategy (for LIVE mode)"""
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main(strategy: NakedWheelSPY):
    """
    Main loop for LIVE trading

    Fetches price data and calls strategy.on_data() continuously
    """
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"Trading Symbol: {strategy.tradingSymbol}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True
    while strategy.running:
        try:
            # Fetch current price
            price = strategy.price_fetcher(strategy.tradingSymbol)
            logger.debug(f"Fetched price for {strategy.tradingSymbol}: ${price:.2f}")

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
    strategy = NakedWheelSPY(
        otm_threshold=OTM_THRESHOLD,
        min_dte=MIN_DTE,
        take_profit_percent=TAKE_PROFIT_PERCENT
    )

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
