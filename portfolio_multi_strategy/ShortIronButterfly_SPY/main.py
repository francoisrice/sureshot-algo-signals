"""
Short Iron Butterfly Strategy on SPY (Plasma Blade)

Strategy Logic:
1. Sell Put 1 strike above ATM, Sell Call 1 strike below ATM
   - If price is within $0.20 of a strike, sell both at that strike (straddle)
2. Buy Put 10 strikes OTM (protective wing)
3. Buy Call 10 strikes OTM (protective wing)
4. Close at 10% of max profit (premium received)
5. Let losers ride (no stop-loss by default)
6. One trade per day, entered in the morning (v1)

Modes:
- LIVE: Connects to portfolio API, trades via IBKR
- BACKTEST: Uses intraday backtesting engine with Black-Scholes pricing
- OPTIMIZATION: Runs in optimization framework
"""

import SureshotSDK
from SureshotSDK import TradingStrategy
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import logging
import os
from typing import Optional, NamedTuple

ET = ZoneInfo("America/New_York")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

STRATEGY_NAME = "ShortIronButterfly_SPY"
TRADING_SYMBOL = "SPY"
STRIKE_WIDTH = 1          # $1 SPY strike intervals
WING_WIDTH = 10           # Number of strikes OTM for protective wings
ATM_SNAP_THRESHOLD = 0.20 # If price is within $0.20 of a strike, use that strike for both legs
TAKE_PROFIT_PERCENT = 0.10 # Close at 10% of max profit
RISK_FREE_RATE = 0.045
DEFAULT_VOLATILITY = 0.16
DTE_DAYS = 1               # 0DTE / next-day expiration for daily butterfly

TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")
API_URL = os.getenv("API_URL", "http://localhost:8000")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
ENTRY_WINDOW_END = time(10, 0)  # v1: enter in first 30 minutes

# ============================================================================
# IRON BUTTERFLY POSITION
# ============================================================================

class IronButterflyPosition(NamedTuple):
    short_put_strike: float
    short_call_strike: float
    long_put_strike: float
    long_call_strike: float
    short_put_premium: float
    short_call_premium: float
    long_put_premium: float
    long_call_premium: float
    net_credit: float
    entry_date: datetime
    expiration_date: datetime

# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class ShortIronButterflySPY(TradingStrategy):

    name = STRATEGY_NAME
    tradingSymbol = TRADING_SYMBOL

    def __init__(self):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.trading_mode = TRADING_MODE
        self.timeframe = '1m'

        self.position: Optional[IronButterflyPosition] = None
        self.completedTrade = False
        self.current_trading_date = None

        self.price_history = []
        self.volatility_lookback = 30

    def _get_current_datetime(self, passed_datetime=None):
        if passed_datetime is not None:
            return passed_datetime
        return SureshotSDK.get_system_time()

    def initialize(self):
        logger.info(f"Initializing {self.name} for LIVE trading")

    def backtest_initialize(self, start_date, end_date):
        self.set_start_date(start_date)
        self.set_end_date(end_date)
        logger.info(f"Initialized {self.name} for backtesting")

    def reset_daily_state(self, current_date):
        self.completedTrade = False
        self.position = None
        current_datetime = self._get_current_datetime(current_date)
        self.current_trading_date = current_datetime.date() if isinstance(current_datetime, datetime) else current_datetime

    def calculate_volatility(self) -> float:
        if len(self.price_history) < 2:
            return DEFAULT_VOLATILITY

        import numpy as np
        prices = np.array(self.price_history)
        log_returns = np.diff(np.log(prices))
        if len(log_returns) == 0:
            return DEFAULT_VOLATILITY

        daily_vol = np.std(log_returns)
        annual_vol = daily_vol * np.sqrt(252)

        if np.isnan(annual_vol) or annual_vol <= 0 or annual_vol > 2.0:
            return DEFAULT_VOLATILITY
        return annual_vol

    def _nearest_strike(self, price: float) -> float:
        return round(price / STRIKE_WIDTH) * STRIKE_WIDTH

    def _price_option(self, underlying: float, strike: float, dte_years: float, vol: float, option_type: str) -> float:
        try:
            from SureshotSDK.options.BlackScholes import calculate_call_price, calculate_put_price
            if option_type == 'call':
                return calculate_call_price(underlying, strike, dte_years, RISK_FREE_RATE, vol)
            else:
                return calculate_put_price(underlying, strike, dte_years, RISK_FREE_RATE, vol)
        except Exception:
            intrinsic = max(0, underlying - strike) if option_type == 'call' else max(0, strike - underlying)
            time_value = underlying * vol * (dte_years ** 0.5) * 0.4
            return intrinsic + time_value

    def open_iron_butterfly(self, underlying_price: float, current_datetime: datetime):
        nearest = self._nearest_strike(underlying_price)
        distance_to_nearest = abs(underlying_price - nearest)

        if distance_to_nearest <= ATM_SNAP_THRESHOLD:
            short_put_strike = nearest
            short_call_strike = nearest
        else:
            if underlying_price > nearest:
                short_put_strike = nearest + STRIKE_WIDTH
                short_call_strike = nearest
            else:
                short_put_strike = nearest
                short_call_strike = nearest - STRIKE_WIDTH

        long_put_strike = short_put_strike - (WING_WIDTH * STRIKE_WIDTH)
        long_call_strike = short_call_strike + (WING_WIDTH * STRIKE_WIDTH)

        vol = self.calculate_volatility()
        from SureshotSDK.options.BlackScholes import days_to_years
        dte_years = days_to_years(DTE_DAYS) if DTE_DAYS > 0 else 1 / 365.0

        short_put_prem = self._price_option(underlying_price, short_put_strike, dte_years, vol, 'put')
        short_call_prem = self._price_option(underlying_price, short_call_strike, dte_years, vol, 'call')
        long_put_prem = self._price_option(underlying_price, long_put_strike, dte_years, vol, 'put')
        long_call_prem = self._price_option(underlying_price, long_call_strike, dte_years, vol, 'call')

        net_credit = (short_put_prem + short_call_prem) - (long_put_prem + long_call_prem)

        self.position = IronButterflyPosition(
            short_put_strike=short_put_strike,
            short_call_strike=short_call_strike,
            long_put_strike=long_put_strike,
            long_call_strike=long_call_strike,
            short_put_premium=short_put_prem,
            short_call_premium=short_call_prem,
            long_put_premium=long_put_prem,
            long_call_premium=long_call_prem,
            net_credit=net_credit,
            entry_date=current_datetime,
            expiration_date=current_datetime + timedelta(days=DTE_DAYS),
        )

        logger.info(
            f"Opened Iron Butterfly: "
            f"Short P{short_put_strike}/C{short_call_strike}, "
            f"Long P{long_put_strike}/C{long_call_strike}, "
            f"Net Credit: ${net_credit:.2f}"
        )

        self.buy_all(self.tradingSymbol, 1)

    def _current_position_value(self, underlying_price: float, current_datetime: datetime) -> float:
        if self.position is None:
            return 0.0

        remaining = (self.position.expiration_date - current_datetime).total_seconds() / (365.25 * 24 * 3600)
        remaining = max(remaining, 1 / (365.25 * 24 * 60))

        vol = self.calculate_volatility()

        sp = self._price_option(underlying_price, self.position.short_put_strike, remaining, vol, 'put')
        sc = self._price_option(underlying_price, self.position.short_call_strike, remaining, vol, 'call')
        lp = self._price_option(underlying_price, self.position.long_put_strike, remaining, vol, 'put')
        lc = self._price_option(underlying_price, self.position.long_call_strike, remaining, vol, 'call')

        current_cost_to_close = (sp + sc) - (lp + lc)
        return current_cost_to_close

    def on_minute_bar(self, bar: dict, current_datetime: datetime = None):
        current_datetime = self._get_current_datetime(current_datetime)
        self.current_date = current_datetime
        current_time = current_datetime.time()
        current_date = current_datetime.date()

        if self.current_trading_date != current_date:
            self.reset_daily_state(current_datetime)

        if not (MARKET_OPEN <= current_time < MARKET_CLOSE):
            return

        price = bar['c']

        self.price_history.append(price)
        if len(self.price_history) > self.volatility_lookback * 390:
            self.price_history = self.price_history[-(self.volatility_lookback * 390):]

        if self.completedTrade:
            return

        if self.position is None:
            if current_time < ENTRY_WINDOW_END:
                self.open_iron_butterfly(price, current_datetime)
            else:
                self.completedTrade = True
            return

        cost_to_close = self._current_position_value(price, current_datetime)
        profit = self.position.net_credit - cost_to_close
        profit_pct = profit / self.position.net_credit if self.position.net_credit > 0 else 0

        if profit_pct >= TAKE_PROFIT_PERCENT:
            logger.info(
                f"Take profit: {profit_pct*100:.1f}% of max credit "
                f"(${profit:.2f} of ${self.position.net_credit:.2f})"
            )
            self._record_trade_close(profit)
            return

        if current_time >= time(15, 55):
            logger.info(f"End of day close: P&L ${profit:.2f} ({profit_pct*100:.1f}%)")
            self._record_trade_close(profit)

    def _record_trade_close(self, profit: float):
        self.sell_all(self.tradingSymbol)
        self.position = None
        self.completedTrade = True

    def on_data(self, price=None, current_date=None):
        logger.warning("Iron Butterfly strategy requires minute data. Use on_minute_bar() instead.")

    def run(self):
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main(strategy: ShortIronButterflySPY):
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True

    while strategy.running:
        try:
            now_et = datetime.now(ET)
            current_time = now_et.time()

            if not (MARKET_OPEN <= current_time < MARKET_CLOSE):
                logger.debug(f"Outside market hours ({current_time} ET) — sleeping 60s")
                strategy.idle_seconds(60)
                continue

            bar = strategy.real_time_price_fetcher(strategy.tradingSymbol)
            if bar:
                strategy.on_minute_bar(bar, now_et)
            else:
                logger.warning(f"No bar returned for {strategy.tradingSymbol}")

            strategy.idle_seconds(60)

        except KeyboardInterrupt:
            logger.info("Stopping strategy...")
            strategy.running = False
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            strategy.idle_seconds(60)


if __name__ == "__main__":
    strategy = ShortIronButterflySPY()

    if TRADING_MODE == "BACKTEST":
        logger.info("Strategy initialized for BACKTEST mode")
        logger.info("Run via: python backtest.py")
    elif TRADING_MODE == "LIVE" and TRADING_MODE == "PAPER":
        strategy.initialize()
        main(strategy)
    elif TRADING_MODE == "OPTIMIZATION":
        logger.info("Strategy initialized for OPTIMIZATION mode")
    else:
        logger.error(f"Unknown TRADING_MODE: {TRADING_MODE}")
