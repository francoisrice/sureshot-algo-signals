import SureshotSDK
from SureshotSDK import Scheduler, Portfolio
from datetime import timedelta
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ilSPXLScheduler(Scheduler):

    name = "IncredibleLeverage_SPXL"
    signalSymbol = "SPY"
    positionSymbol = "SPXL"

    def __init__(self, max_loss=0.05):
        super().__init__(portfolio=None, strategy_name=self.name)
        self.max_loss = max_loss
        self.timeframe = '1d'
        self.sma = SureshotSDK.SMA(self.signalSymbol, 252, self.timeframe)

    def initialize(self):
        # self.portfolio
        # self.cash , from portfolio algorithm
        self.sma.initialize()

    def backtest_initialize(self):
        self.set_start_date(2010, 1, 1)  # Set Start Date
        self.set_end_date(2024, 12, 31)    # Set End Date
        self.set_cash(100000)           # Set Strategy Cash

        self.signalSymbol = "SPY"
        self.positionSymbol = "SPXL"

        self.previous_close = None
        self.previousCloseAboveSMA = False

        # Warm up the SMA with historical data
        self.sma.initialize(self.start_date)
        
    def is_end_of_month(self, current_date):
        next_day = current_date + timedelta(days=1)
        return next_day.day == 1

    def on_data(self, price=None):

        if not price:
            logger.warning("No price data available.")
            return

        # Get current month's close and SMA
        current_date = SureshotSDK.get_system_time()
        self.sma.Update(price)
        current_sma = self.sma.get_value()

        # Mid Month Stop-Loss
        if self.invested:
            if price < (current_sma * (1 - self.max_loss)):
                self.sell_all(self.positionSymbol)

        if self.is_end_of_month(current_date):

            if self.invested:
                if price < current_sma:
                    self.sell_all(self.positionSymbol)

            else:
                if self.previous_close:
                    if price > current_sma and self.previousCloseAboveSMA:
                        self.buy_all(self.positionSymbol)

            self.previous_close = price
            if price > current_sma:
                self.previousCloseAboveSMA = True
            else:
                self.previousCloseAboveSMA = False

    def run(self):
        logger.info("Scheduler is running...")

def main(ss: ilSPXLScheduler):

    logger.info(f"Starting {ss.name} strategy monitoring...")

    ss.running = True
    while ss.running:
        try:
            # When scheduled for next candle, fetch price
            price = ss.price_fetcher(ss.signalSymbol)
            logger.debug(f"Fetched price for {ss.signalSymbol}: {price}")

            # Pass price into strategy
            ss.on_data(price)

            # Sleep for 60 seconds before next check
            ss.idle_seconds(60)

        except KeyboardInterrupt:
            logger.info("Stopping strategy...")
            ss.running = False
            break
        except Exception as e:
            logger.error(f"Error in strategy loop: {e}")
            # Sleep before retrying on error
            ss.idle_seconds(60)


if __name__ == "__main__":
    ss = ilSPXLScheduler(max_loss=0.05)
    main(ss)