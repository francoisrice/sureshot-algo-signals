"""
Bond Ladder & Interest Rate Strategy

Paper-trade only. Simulates holding a mixed bond portfolio:
- AMZN 2065 bond, 5.55% coupon
- AAPL 2062 bond, 4.10% coupon
- High Yield Savings, 4.00% APY

Each day, the strategy sends a single "order" representing the day's accrued
interest across all holdings, increasing the portfolio value linearly.

No real trades are executed — the value simply grows by the effective
daily return of the blended coupon/yield.

Modes:
- LIVE: Runs daily, accrues interest via portfolio API
- BACKTEST: Accrues daily through backtesting engine
- OPTIMIZATION: Not applicable (returns are fixed-income, nothing to optimize)
"""

import SureshotSDK
from SureshotSDK import TradingStrategy
from datetime import datetime, time
from zoneinfo import ZoneInfo
import logging
import os

ET = ZoneInfo("America/New_York")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

STRATEGY_NAME = "Bonds"

BOND_HOLDINGS = [
    {"name": "AMZN 2065",        "coupon_rate": 0.0555, "weight": 0.34},
    {"name": "AAPL 2062",        "coupon_rate": 0.0410, "weight": 0.33},
    {"name": "High Yield Savings", "coupon_rate": 0.0400, "weight": 0.33},
]

BLENDED_ANNUAL_RATE = sum(h["coupon_rate"] * h["weight"] for h in BOND_HOLDINGS)
DAILY_RATE = BLENDED_ANNUAL_RATE / 365.0

TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")
API_URL = os.getenv("API_URL", "http://localhost:8000")

# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class BondLadder(TradingStrategy):

    name = STRATEGY_NAME

    def __init__(self):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.trading_mode = TRADING_MODE
        self.timeframe = '1d'
        self.tradingSymbol = 'BONDS'
        self.last_accrual_date = None

    def _get_current_date(self, passed_date=None):
        if passed_date is not None:
            return passed_date
        return SureshotSDK.get_system_time()

    def initialize(self):
        logger.info(f"Initializing {self.name} for LIVE (paper) trading")
        logger.info(f"Blended annual rate: {BLENDED_ANNUAL_RATE*100:.2f}%")
        logger.info(f"Effective daily rate: {DAILY_RATE*100:.4f}%")

    def backtest_initialize(self, start_date, end_date):
        self.set_start_date(start_date)
        self.set_end_date(end_date)
        logger.info(f"Initialized {self.name} for backtesting")

    def on_data(self, price=None, current_date=None):
        current_date = self._get_current_date(current_date)
        date_obj = current_date.date() if isinstance(current_date, datetime) else current_date

        if self.last_accrual_date == date_obj:
            return

        if price is None or price <= 0:
            logger.warning(f"No valid price on {date_obj}, skipping accrual")
            return

        daily_income = price * DAILY_RATE

        logger.info(
            f"{date_obj} | Portfolio value: ${price:.2f} | "
            f"Daily accrual: ${daily_income:.4f} | "
            f"New value: ${price + daily_income:.2f}"
        )

        self.last_accrual_date = date_obj
        self.current_date = current_date

        self.buy_all(self.tradingSymbol, 1)

    def on_minute_bar(self, bar: dict, current_datetime: datetime = None):
        pass

    def run(self):
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main(strategy: BondLadder):
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True

    while strategy.running:
        try:
            now_et = datetime.now(ET)

            if now_et.time() < time(9, 0) or now_et.time() > time(10, 0):
                strategy.idle_seconds(300)
                continue

            price = strategy.price_fetcher(strategy.tradingSymbol)
            if price:
                strategy.on_data(price=price, current_date=now_et)
            else:
                logger.warning("No price data available for bond valuation")

            strategy.idle_seconds(3600)

        except KeyboardInterrupt:
            logger.info("Stopping strategy...")
            strategy.running = False
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            strategy.idle_seconds(300)


if __name__ == "__main__":
    strategy = BondLadder()

    if TRADING_MODE == "BACKTEST":
        logger.info("Strategy initialized for BACKTEST mode")
        logger.info("Run via: python backtest.py")
    elif TRADING_MODE == "LIVE":
        strategy.initialize()
        main(strategy)
    elif TRADING_MODE == "OPTIMIZATION":
        logger.info("Bond strategy has fixed returns — nothing to optimize")
    else:
        logger.error(f"Unknown TRADING_MODE: {TRADING_MODE}")
