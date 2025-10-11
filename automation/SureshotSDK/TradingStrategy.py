class TradingStrategy:
    def __init__(self):
        self.name = ""
        self.description = ""
        self.parameters = {}

    def set_name(self, name):
        self.name = name

    def set_description(self, description):
        self.description = description

    def set_parameters(self, params):
        self.parameters = params

    def get_name(self):
        return self.name

    def get_description(self):
        return self.description

    def get_parameter(self, key):
        return self.parameters.get(key, None)

    def log(self, message):
        print("[{}] {}".format(self.get_name(), message))

    def buy(self, asset, amount):
        self.log("Buying {} of {}".format(amount, asset))

    def sell(self, asset, amount):
        self.log("Selling {} of {}".format(amount, asset))

    def sell_all(self, asset):
        # Which middleware to connect to? Should be handled here.
        # Middleware is based on Asset, Broker availability, etc.
        # There should be a perferred broker/middleware at any given time, until conditions change.

        # Sends a 'message' -> service takes the message and calls the API routes

        self.log("Selling all of {}".format(asset))

    def get_capital(self):
        return 10000  # Placeholder for actual capital retrieval

    def on_start(self):
        pass

    def on_tick(self):
        pass

    def on_stop(self):
        pass