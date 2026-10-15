"""
ClusterBarrage — multi-leg Opening Range Breakout (ORB) on TQQQ

Multi-leg variant of Sidewinder: one leg enters 5, 10, 15, 20, 30 and 60 minutes after the open,
each risking 1/6 of Sidewinder's 1% (≈0.167% of capital). Every leg independently applies Sidewinder's rules with
its own N-minute opening range: long above the 9:30 open with the stop at the range low, short below
it with the stop at the range high, a 10x take-profit, and a 15:55 exit. Only the legs whose own stop
is crossed close. Longs and shorts can coexist, so the legs are netted into one TQQQ position.
"""

import SureshotSDK
from SureshotSDK import TradingStrategy
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import logging
import os
import requests
from typing import Optional

ET = ZoneInfo("America/New_York")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRATEGY_NAME = "ClusterBarrage"
TRADING_SYMBOL = "TQQQ"
LEG_ENTRY_MINUTES = (5, 10, 15, 20, 30, 60)
TOTAL_RISK_SIZE = 0.01
LEG_RISK_SIZE = TOTAL_RISK_SIZE / len(LEG_ENTRY_MINUTES)
TAKE_PROFIT_FACTOR = 10
LEVERAGE = 4.0

TRADING_MODE = os.getenv("TRADING_MODE", "LIVE")
API_URL = os.getenv("API_URL", "http://localhost:8000")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
END_OF_DAY_EXIT = time(15, 55)


def minutes_after_open(minutes: int) -> time:
    return (datetime.combine(datetime.min, MARKET_OPEN) + timedelta(minutes=minutes)).time()


FIRST_LEG_ENTRY_TIME = minutes_after_open(LEG_ENTRY_MINUTES[0])


@dataclass(eq=False)
class Leg:
    entryMinutes: int
    direction: str
    shares: int
    entryPrice: Optional[float]
    stopLossPrice: Optional[float]
    takeProfitPrice: Optional[float]

    @property
    def signedShares(self) -> int:
        return self.shares if self.direction == "LONG" else -self.shares

    def is_stop_crossed(self, price: float) -> bool:
        if self.stopLossPrice is None:
            return False
        if self.direction == "LONG":
            return price < self.stopLossPrice
        return price > self.stopLossPrice

    def is_take_profit_hit(self, price: float) -> bool:
        if self.takeProfitPrice is None:
            return False
        if self.direction == "LONG":
            return price >= self.takeProfitPrice
        return price <= self.takeProfitPrice


class ClusterBarrage(TradingStrategy):

    name = STRATEGY_NAME

    def __init__(self):
        super().__init__(portfolio=None, strategy_name=self.name, api_url=API_URL)
        self.trading_mode = TRADING_MODE
        self.tradingSymbol = TRADING_SYMBOL
        self.timeframe = '1m'
        self.currentTradingDate = None
        self.reset_daily_state(None)

    def reset_daily_state(self, tradingDate):
        self.currentTradingDate = tradingDate
        self.completedTrade = False
        self.dayOpen = None
        self.dayHigh = None
        self.dayLow = None
        self.openLegs: list[Leg] = []
        self.firedLegMinutes: set[int] = set()
        self.dailyCapital = None
        self.positionInSync = True

    def initialize(self):
        """Initialize for LIVE trading"""
        self.fetch_trading_mode()
        self.completedTrade = self.is_trade_completed_today()
        logger.info(f"Initializing {self.name} for LIVE trading")
        if self.completedTrade:
            logger.info("Trades already completed today — will not re-enter")
            return
        if self.invested:
            self.restore_open_position()

    def restore_open_position(self):
        """Pod restarted mid-day: leg TP/SL levels are lost, so hold the net position to the EOD exit only."""
        position = self.fetch_open_position(self.tradingSymbol)
        if not position:
            return
        quantity = int(position.get("quantity", 0))
        direction = "LONG" if quantity > 0 else "SHORT"
        self.currentTradingDate = SureshotSDK.get_system_time().date()
        self.openLegs = [Leg(0, direction, abs(quantity), position.get("avg_price"), None, None)]
        self.firedLegMinutes = set(LEG_ENTRY_MINUTES)
        logger.warning(
            f"Restored {direction} position on startup: qty={quantity} @ avg ${position.get('avg_price'):.2f} "
            f"— leg TP/SL unknown, EOD exit only, no new legs today"
        )

    def backtest_initialize(self, start_date, end_date):
        """Initialize for BACKTEST mode"""
        self.set_start_date(start_date)
        self.set_end_date(end_date)
        logger.info(f"Initialized {self.name} for backtesting")

    def fetch_capital(self) -> Optional[float]:
        if self.portfolio:
            return self.portfolio.cash
        try:
            response = requests.get(f"{self.api_url}/portfolio/{self.strategy_name}", timeout=5)
            return response.json()["cash"]
        except Exception as e:
            logger.error(f"Failed to fetch cash from API: {e}")
            return None

    def fetch_net_shares(self) -> Optional[int]:
        try:
            response = requests.get(
                f"{self.api_url}/positions",
                params={"strategy_name": self.strategy_name, "symbol": self.tradingSymbol},
                timeout=5
            )
            response.raise_for_status()
            positions = response.json()
            return int(positions[0]["quantity"]) if positions else 0
        except Exception as e:
            logger.error(f"Failed to fetch {self.tradingSymbol} position from API: {e}")
            return None

    def calculate_leg_size(self, price: float, stopLossPrice: float) -> int:
        if self.dailyCapital is None:
            self.dailyCapital = self.fetch_capital()
        if not self.dailyCapital:
            return 0
        riskPerShare = abs(price - stopLossPrice)
        if riskPerShare == 0:
            return 0
        legRiskAmount = self.dailyCapital * LEG_RISK_SIZE
        legLeverageCap = LEVERAGE * self.dailyCapital / price / len(LEG_ENTRY_MINUTES)
        return int(min(legRiskAmount / riskPerShare, legLeverageCap))

    def reconcile_position(self, price: float) -> bool:
        """Trade the difference between the open legs' net shares and the real position, reducing before opening."""
        actualShares = self.fetch_net_shares()
        if actualShares is None:
            return False
        targetShares = sum(leg.signedShares for leg in self.openLegs)
        deltaShares = targetShares - actualShares
        if deltaShares == 0:
            return True
        logger.info(f"Rebalancing {self.tradingSymbol}: {actualShares} -> {targetShares} @ ${price:.2f}")
        if deltaShares > 0:
            coverShares = min(deltaShares, max(-actualShares, 0))
            if coverShares and not self.close_short_all(self.tradingSymbol, price=price, quantity=coverShares):
                return False
            if deltaShares > coverShares:
                self.buy_all(self.tradingSymbol, deltaShares - coverShares, price=price)
        else:
            sellShares = min(-deltaShares, max(actualShares, 0))
            if sellShares and not self.sell_all(self.tradingSymbol, price=price, quantity=sellShares):
                return False
            if -deltaShares > sellShares:
                self.sell_short_all(self.tradingSymbol, -deltaShares - sellShares, price=price)
        return self.fetch_net_shares() == targetShares

    def close_exited_legs(self, price: float) -> bool:
        exitedLegs = []
        for leg in self.openLegs:
            if leg.is_stop_crossed(price):
                logger.info(f"Stop loss on {leg.entryMinutes}m {leg.direction} leg: ${price:.2f} crossed ${leg.stopLossPrice:.2f}")
                exitedLegs.append(leg)
            elif leg.is_take_profit_hit(price):
                logger.info(f"Take profit on {leg.entryMinutes}m {leg.direction} leg: ${price:.2f} reached ${leg.takeProfitPrice:.2f}")
                exitedLegs.append(leg)
        self.openLegs = [leg for leg in self.openLegs if leg not in exitedLegs]
        return bool(exitedLegs)

    def open_leg(self, entryMinutes: int, price: float) -> bool:
        self.firedLegMinutes.add(entryMinutes)
        if price > self.dayOpen:
            direction, stopLossPrice = "LONG", self.dayLow
        elif price < self.dayOpen:
            direction, stopLossPrice = "SHORT", self.dayHigh
        else:
            logger.info(f"{entryMinutes}m leg skipped: price equals the open")
            return False
        shares = self.calculate_leg_size(price, stopLossPrice)
        if shares <= 0:
            logger.info(f"{entryMinutes}m leg skipped: zero size")
            return False
        riskPerShare = abs(price - stopLossPrice)
        takeProfitPrice = price + TAKE_PROFIT_FACTOR * riskPerShare if direction == "LONG" else price - TAKE_PROFIT_FACTOR * riskPerShare
        self.openLegs.append(Leg(entryMinutes, direction, shares, price, stopLossPrice, takeProfitPrice))
        logger.info(
            f"Opened {entryMinutes}m {direction} leg: {shares} {self.tradingSymbol} @ ${price:.2f}, "
            f"TP ${takeProfitPrice:.2f}, SL ${stopLossPrice:.2f}"
        )
        return True

    def due_leg_minutes(self, currentTime: time) -> list[int]:
        return [
            entryMinutes for entryMinutes in LEG_ENTRY_MINUTES
            if entryMinutes not in self.firedLegMinutes and currentTime >= minutes_after_open(entryMinutes)
        ]

    def update_day_range(self, bar: dict, currentTime: time):
        if self.dayOpen is None:
            if currentTime >= FIRST_LEG_ENTRY_TIME:
                return
            self.dayOpen, self.dayHigh, self.dayLow = bar['o'], bar['h'], bar['l']
        self.dayHigh = max(self.dayHigh, bar['h'])
        self.dayLow = min(self.dayLow, bar['l'])

    def complete_day(self):
        self.completedTrade = True
        self.mark_trade_completed()

    def sync_position(self, price: float):
        self.positionInSync = self.reconcile_position(price)
        if not self.positionInSync:
            logger.error(f"{self.tradingSymbol} position out of sync with legs — will retry next bar")

    def on_minute_bar(self, bar: dict, current_datetime: datetime = None):
        currentDatetime = current_datetime or SureshotSDK.get_system_time()
        self.current_date = currentDatetime
        currentTime = currentDatetime.time()

        if self.currentTradingDate != currentDatetime.date():
            self.reset_daily_state(currentDatetime.date())

        if self.completedTrade or not (MARKET_OPEN <= currentTime < MARKET_CLOSE):
            return

        price = bar['c']

        if currentTime >= END_OF_DAY_EXIT:
            if self.openLegs:
                logger.info(f"End of day exit for {len(self.openLegs)} leg(s)")
                self.openLegs = []
            self.sync_position(price)
            if self.positionInSync:
                self.complete_day()
            return

        if self.dayOpen is not None:
            legsChanged = self.close_exited_legs(price)
            for entryMinutes in self.due_leg_minutes(currentTime):
                legsChanged = self.open_leg(entryMinutes, price) or legsChanged

            if legsChanged or not self.positionInSync:
                self.sync_position(price)

            if len(self.firedLegMinutes) == len(LEG_ENTRY_MINUTES) and not self.openLegs and self.positionInSync:
                self.complete_day()
                return
        elif self.due_leg_minutes(currentTime):
            logger.warning("Missed the opening range — no legs today")
            self.firedLegMinutes = set(LEG_ENTRY_MINUTES)

        self.update_day_range(bar, currentTime)

    def on_data(self, price=None, current_date=None):
        logger.warning("ORB strategy requires minute data. Use on_minute_bar() instead.")

    def run(self):
        logger.info(f"Strategy {self.name} is running in {self.trading_mode} mode...")
        logger.info(f"Current symbol: {self.tradingSymbol}")


def main(strategy: ClusterBarrage):
    """Main loop for LIVE trading — polls real-time price every 60 seconds during market hours."""
    logger.info(f"Starting {strategy.name} strategy monitoring...")
    logger.info(f"Trading Mode: {strategy.trading_mode}")
    logger.info(f"API URL: {strategy.api_url}")

    strategy.running = True

    while strategy.running:
        try:
            nowEt = datetime.now(ET)

            if not (MARKET_OPEN <= nowEt.time() < MARKET_CLOSE):
                strategy.idle_seconds(60)
                continue

            if strategy.completedTrade:
                if strategy._data_fetcher is not None:
                    logger.info("Trades complete — stopping data fetcher")
                    strategy._data_fetcher.close()
                    strategy._data_fetcher = None
                strategy.idle_seconds(60)
                continue

            bar = strategy.real_time_price_fetcher(strategy.tradingSymbol)
            if bar:
                strategy.on_minute_bar(bar, nowEt)
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
    strategy = ClusterBarrage()

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
