from SureshotSDK import SMA, TradingStrategy

class IncredibleLeverageSPXL(TradingStrategy):

    def __init__(self):
        super().__init__()
        self.set_name("Incredible Leverage SPXL")
        self.set_description("A #longterm strategy that uses SPXL for leveraged exposure to the #S&P500. Exits when month-end price closes below the 252-day SMA or tick price drops more than X% below SMA mid-month.")
        self.set_parameters({
            "MaximumMidMonthLoss": 0.05,
        })
        self.universe = ['SPXL']
        # self.symbol = Asset("SPY")
        self.indicator = SMA('SPY', period=252)

    def on_start(self):
        self.data = self.subscribe(self.universe)

    def on_tick(self):
        if 'SPXL' not in self.data:
            return

        current_price = self.data['SPXL'].getPrice()
        current_date = self.data['SPXL'].getDate()
        sma_price = self.indicator.getValue() # How does this work with real-time data?

        # Mid Month Stop Loss
        if current_price < sma_price * (1 - self.get_parameter("MaximumMidMonthLoss")):
            self.sell_all(self.symbol)

        if self.is_month_end(current_date):
            # Exit Condition
            if self.portfolio.getPosition(self.symbol):
                if current_price < sma_price:
                    self.sell_all(self.symbol)

            else:
                # Entry Condition
                if self.previous_close:
                    if current_price > sma_price and self.previousCloseAboveSMA:
                        self.buy(self.symbol, quantity=100)

            # Must store algorithm state; but not in memory; must be persistent and accessible after failure

    def backtest_on_start(self):
        self.log("Starting Incredible Leverage SPXL Strategy")
        self.allocate_initial_capital()

    def backtest_on_stop(self):
        self.log("Stopping Incredible Leverage SPXL Strategy")
        self.sell_all(self.leveraged_asset)

    def allocate_initial_capital(self):
        total_capital = self.get_capital()
        leverage_factor = self.get_parameter("leverage_factor")
        allocation = total_capital * leverage_factor
        self.buy(self.leveraged_asset, allocation)    

    def rebalance(self):
        total_capital = self.get_capital()
        leverage_factor = self.get_parameter("leverage_factor")
        allocation = total_capital * leverage_factor
        self.sell_all(self.leveraged_asset)
        self.buy(self.leveraged_asset, allocation)
        self.log("Rebalanced portfolio to maintain leverage factor of {}".format(leverage_factor))

    