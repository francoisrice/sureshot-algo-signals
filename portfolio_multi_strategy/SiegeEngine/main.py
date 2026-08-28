"""
SiegeEngine — Volatility Decay Harvester (GLDM long / SHNY short)

Strategy Logic:
1. On start, LONG GLDM and SHORT SHNY at 3:1 by market value (beta-neutral gold exposure)
2. Hold until a manual exit or the stop-loss:
   - Close both legs if combined loss reaches 5% of capital at entry
   - P&L is checked once per trading day
3. Never auto-reinvest: once flat with any order history, stay out

Modes:
- LIVE: Connects to portfolio API, trades via IBKR
- PAPER: Connects to portfolio API, sends order entries to DB
- BACKTEST: Driven daily by BacktestRunner via on_data()
- OPTIMIZATION: Runs in optimization framework
"""

import SureshotSDK
from SureshotSDK import TradingStrategy
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional
import requests
import logging
import os

ET = ZoneInfo("America/New_York")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

STRATEGY_NAME = "SiegeEngine"
LONG_SYMBOL = "GLDM"
LEVERAGED_SYMBOL = "SHNY"
LEVERAGE_ETF_FACTOR = 3
OPTIMIZATION_STOP_LOSS_PERCENT = 0.05
TIMEFRAME = "1d"
DAILY_CHECK_TIME = time(15, 50)  # ET — single daily P&L check, before the 4:00pm pod scale-down

# Trading mode
TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")

# Portfolio API URL
API_URL = os.getenv("API_URL", "http://localhost:8000")

# ============================================================================
# STRATEGY IMPLEMENTATION
# ============================================================================

class SiegeEngine(TradingStrategy):
    """
    Long an ETF and short its leveraged counterpart to harvest volatility decay
    """

    name = STRATEGY_NAME
    positionSymbol = LONG_SYMBOL
    valuationSymbols = [LEVERAGED_SYMBOL]  # BacktestRunner values these in the equity curve too

    def __init__(self, stop_loss=OPTIMIZATION_STOP_LOSS_PERCENT):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.trading_mode = TRADING_MODE

        self.tradingSymbol = LONG_SYMBOL
        self.leveragedSymbol = LEVERAGED_SYMBOL
        self.timeframe = TIMEFRAME
        self.stopLossPercent = stop_loss

        self._reset_position_state()
        self.exitedPermanently = False
        self.lastProcessedDate = None
        self.leveragedPriceHistory = {}
        self.lastPrice = None
        self.lastLeveragedPrice = None

    def _reset_position_state(self):
        self.entryPrice = None
        self.leveragedEntryPrice = None
        self.longShares = 0
        self.shortShares = 0
        self.entryCapital = None

    def _get_current_datetime(self, passed_datetime=None):
        if passed_datetime is not None:
            return passed_datetime
        return SureshotSDK.get_system_time()

    def initialize(self):
        """Initialize for LIVE/PAPER trading"""
        self.fetch_trading_mode()
        logger.info(f"Initializing {self.name} for {self.trading_mode} trading")
        if self.invested:
            self._restore_position_state()

    def _restore_position_state(self):
        longPosition = self.fetch_open_position(self.tradingSymbol)
        shortPosition = self.fetch_open_position(self.leveragedSymbol)
        if not (longPosition and shortPosition):
            logger.error("Invested but could not restore both legs — stop-loss disabled until next restart")
            return
        self.longShares = longPosition.get("quantity", 0)
        self.shortShares = abs(shortPosition.get("quantity", 0))
        self.entryPrice = longPosition.get("avg_price")
        self.leveragedEntryPrice = shortPosition.get("avg_price")
        # Entry capital reconstructs exactly: both legs consumed cash at their entry basis
        remainingCash = self.fetch_portfolio_cash() or 0
        self.entryCapital = (
            remainingCash
            + self.longShares * self.entryPrice
            + self.shortShares * self.leveragedEntryPrice
        )
        logger.warning(
            f"Restored position on startup: LONG {self.longShares} {self.tradingSymbol} @ ${self.entryPrice:.2f}, "
            f"SHORT {self.shortShares} {self.leveragedSymbol} @ ${self.leveragedEntryPrice:.2f}, "
            f"entry capital ${self.entryCapital:.2f}"
        )

    def backtest_initialize(self, start_date, end_date):
        """Initialize for BACKTEST mode"""
        self.set_start_date(start_date)
        self.set_end_date(end_date)

        self._reset_position_state()
        self.exitedPermanently = False
        self.lastProcessedDate = None
        self.leveragedPriceHistory = self._load_daily_closes(self.leveragedSymbol, start_date, end_date)

        logger.info(f"Initialized {self.name} for backtesting")

    def _load_daily_closes(self, symbol: str, start_date: datetime, end_date: datetime) -> dict:
        if self.data_client is None:
            logger.error(f"No historical data client configured — cannot preload {symbol} prices")
            return {}
        try:
            bars = self.data_client.get_historical_data(symbol, start_date, end_date, TIMEFRAME)
            return {datetime.fromtimestamp(bar['t'] / 1000).date(): bar['c'] for bar in bars or []}
        except Exception as e:
            logger.error(f"Failed to preload daily closes for {symbol}: {e}")
            return {}

    def has_traded_before(self) -> bool:
        """Persistent manual-exit detection: any order history while flat means we exited"""
        if not (self.api_url and self.strategy_name):
            return False
        try:
            response = requests.get(
                f"{self.api_url}/orders",
                params={"strategy_name": self.strategy_name, "limit": 1},
                timeout=5
            )
            response.raise_for_status()
            return len(response.json()) > 0
        except Exception as e:
            logger.error(f"Failed to fetch order history: {e}")
            return True  # fail safe: never enter while history is unknown

    def fetch_portfolio_cash(self) -> Optional[float]:
        if self.portfolio:
            return self.portfolio.cash
        try:
            response = requests.get(f"{self.api_url}/portfolio/{self.strategy_name}", timeout=5)
            response.raise_for_status()
            return response.json()["cash"]
        except Exception as e:
            logger.error(f"Failed to fetch cash from API: {e}")
            return None

    def fetch_leveraged_price(self, currentDatetime: datetime) -> Optional[float]:
        if self.trading_mode in ("LIVE", "PAPER"):
            return self.price_fetcher(self.leveragedSymbol)
        return (
            self.leveragedPriceHistory.get(currentDatetime.date())
            or self.historical_price_fetcher(self.leveragedSymbol, currentDatetime)
        )

    def calculate_position_size(self, price: float, leveragedPrice: float) -> dict:
        """Split capital so long market value = LEVERAGE_ETF_FACTOR x short market value"""
        cash = self.fetch_portfolio_cash()
        if not cash or cash <= 0:
            return {"long": 0, "short": 0}

        shortCapital = cash / (LEVERAGE_ETF_FACTOR + 1)
        shortShares = int(shortCapital // leveragedPrice)
        longShares = int((shortShares * leveragedPrice * LEVERAGE_ETF_FACTOR) // price)

        return {"long": longShares, "short": shortShares}

    def combined_pnl(self, price: float, leveragedPrice: float) -> Optional[float]:
        if self.entryPrice is None or self.leveragedEntryPrice is None:
            return None
        longPnl = (price - self.entryPrice) * self.longShares
        shortPnl = (self.leveragedEntryPrice - leveragedPrice) * self.shortShares
        return longPnl + shortPnl

    def enter_position(self, price: float, leveragedPrice: float):
        positionSize = self.calculate_position_size(price, leveragedPrice)
        if positionSize["long"] <= 0 or positionSize["short"] <= 0:
            logger.warning(f"Position size came out empty: {positionSize} — not entering")
            return

        self.entryCapital = self.fetch_portfolio_cash()
        self.entryPrice = price
        self.leveragedEntryPrice = leveragedPrice
        self.longShares = positionSize["long"]
        self.shortShares = positionSize["short"]

        logger.info(
            f"Entering LONG {self.longShares} {self.tradingSymbol} @ ${price:.2f} and "
            f"SHORT {self.shortShares} {self.leveragedSymbol} @ ${leveragedPrice:.2f} "
            f"(capital ${self.entryCapital:,.2f})"
        )
        self.buy_all(self.tradingSymbol, self.longShares, price=price)
        self.sell_short_all(self.leveragedSymbol, self.shortShares, price=leveragedPrice)

    def exit_position(self, price: float, leveragedPrice: float) -> bool:
        longClosed = self.sell_all(self.tradingSymbol, price=price)
        shortClosed = self.close_short_all(self.leveragedSymbol, price=leveragedPrice)
        if longClosed and shortClosed:
            self._reset_position_state()
            self.exitedPermanently = True
            logger.info("Both legs closed — strategy will not re-enter")
            return True
        logger.error(f"Exit incomplete: long closed={longClosed}, short closed={shortClosed} — will retry")
        return False

    def _check_stop_loss(self, price: float, leveragedPrice: float) -> bool:
        """Returns False only when an exit attempt failed and should be retried"""
        pnl = self.combined_pnl(price, leveragedPrice)
        if pnl is None:
            logger.warning("Invested but entry state unknown — cannot evaluate stop-loss")
            return True
        stopLossThreshold = -self.stopLossPercent * (self.entryCapital or 0)
        if self.entryCapital and pnl <= stopLossThreshold:
            logger.info(
                f"Stop loss hit: combined P&L ${pnl:,.2f} <= ${stopLossThreshold:,.2f} "
                f"({self.stopLossPercent:.0%} of entry capital ${self.entryCapital:,.2f})"
            )
            return self.exit_position(price, leveragedPrice)
        logger.debug(f"Holding: combined P&L ${pnl:,.2f} (stop at ${stopLossThreshold:,.2f})")
        return True

    def on_data(self, price=None, current_date=None):
        """
        Daily processor for backtesting and live trading

        Args:
            price: Current price of the long symbol
            current_date: Current datetime (passed by backtesting engine, None in LIVE mode)
        """
        currentDatetime = self._get_current_datetime(current_date)
        self.current_date = currentDatetime
        currentDate = currentDatetime.date()

        if self.exitedPermanently:
            return
        if not price:
            logger.warning(f"No price data available for {self.tradingSymbol}.")
            return

        invested = self.invested
        if not invested and self.lastProcessedDate == currentDate:
            return  # entry decision already made today; only the stop-loss runs on every call

        leveragedPrice = self.fetch_leveraged_price(currentDatetime)
        if not leveragedPrice:
            logger.warning(f"No price data available for {self.leveragedSymbol}.")
            return

        self.lastPrice = price
        self.lastLeveragedPrice = leveragedPrice

        if invested:
            if self.entryPrice is None:
                self._restore_position_state()
            self._check_stop_loss(price, leveragedPrice)
        elif self.trading_mode in ("LIVE", "PAPER") and self.has_traded_before():
            # Dynamic per-day check, never latched: a transient flat reading from the
            # API must not permanently stop the strategy from monitoring its position
            logger.info("Flat with prior order history — treating as manual exit, not re-entering")
            self.lastProcessedDate = currentDate
        else:
            self.enter_position(price, leveragedPrice)
            self.lastProcessedDate = currentDate

    def on_minute_bar(self, bar: dict, current_datetime: datetime = None):
        logger.warning(f"{self.name} uses daily data. Use on_data() instead.")

    def backtest_close(self):
        """Close both legs at the end of a backtest"""
        if self.invested:
            self.sell_all(self.tradingSymbol, price=self.lastPrice)
            self.close_short_all(self.leveragedSymbol, price=self.lastLeveragedPrice)

    def run(self):
        """Run strategy"""
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")
        logger.info(f"Long: {self.tradingSymbol}, Short: {self.leveragedSymbol}")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def run_daily_check(strategy: SiegeEngine, nowEt: datetime) -> bool:
    """Fetch both symbol prices and evaluate entry/stop-loss. Returns False if the
    check could not run (no price) so the loop retries on the next minute."""
    logger.info(f"Running daily check for {nowEt.date()}")
    try:
        price = strategy.price_fetcher(strategy.tradingSymbol)
        if not price:
            logger.error(f"No price returned for {strategy.tradingSymbol} — will retry")
            return False
        strategy.on_data(price=price, current_date=nowEt)
        logger.info("Daily check complete")
        return True
    finally:
        if strategy._data_fetcher is not None:
            strategy._data_fetcher.close()
            strategy._data_fetcher = None


def main(strategy: SiegeEngine):
    """Idle in the pod all day; run one P&L check at DAILY_CHECK_TIME ET, then idle
    until the market-close CronJob scales the deployment down."""
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True
    lastCheckDate = None

    while strategy.running:
        try:
            nowEt = datetime.now(ET)
            checkDueToday = nowEt.weekday() < 5 and nowEt.time() >= DAILY_CHECK_TIME
            if checkDueToday and lastCheckDate != nowEt.date():
                if run_daily_check(strategy, nowEt):
                    lastCheckDate = nowEt.date()
            strategy.idle_seconds(60)
        except KeyboardInterrupt:
            logger.info("Stopping strategy...")
            strategy.running = False
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            strategy.idle_seconds(60)


if __name__ == "__main__":
    strategy = SiegeEngine()

    if TRADING_MODE == "BACKTEST":
        logger.info("Strategy initialized for BACKTEST mode")
        logger.info("Run via: python backtest.py")
    elif TRADING_MODE == "LIVE" or TRADING_MODE == "PAPER":
        strategy.initialize()
        main(strategy)
    elif TRADING_MODE == "OPTIMIZATION":
        logger.info("Strategy initialized for OPTIMIZATION mode")
    else:
        logger.error(f"Unknown TRADING_MODE: {TRADING_MODE}")
