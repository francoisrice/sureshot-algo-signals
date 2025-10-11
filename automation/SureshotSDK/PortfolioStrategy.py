class PortfolioStrategy:
    def __init__(self):
        self.trading_strategies = {}
        self.capital = 0

    def add_trading_strategy(self, strategy):
        self.trading_strategies[strategy.get_name()] = strategy

    def get_trading_strategies(self):
        return self.trading_strategies
    
    def get_trading_strategy(self, name):
        return self.trading_strategies.get(name, None)
    
    def set_assets(self, assets):
        self.assets = assets

    def set_capital(self, capital):
        self.capital = capital

    def get_assets(self):
        return self.assets

    def get_capital(self):
        return self.capital

    def allocate(self):
        pass

    def rebalance(self):
        pass
