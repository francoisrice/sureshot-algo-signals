import logging
import os
import requests
from typing import Dict, Optional
from datetime import datetime
from .Polygon import PolygonClient
from .ibkr.automation.client import IBKRClient

class Portfolio:
    def __init__(self, cash: float = 100000, strategy_name: str = None):
        """
        Portfolio management class for tracking positions and cash

        Args:
            cash: Initial cash amount
            strategy_name: Name of the strategy (for API tracking)
        """
        self.cash = cash
        self.initial_cash = cash
        self.positions = {}  # symbol -> shares
        self.positionValues = {}  # symbol -> current market value
        self.invested = False
        self.polygon_client = PolygonClient()
        self.ibkr_client = IBKRClient()
        self.logger = logging.getLogger(__name__)
        self.strategy_name = strategy_name
        self.api_url = os.getenv("API_URL")

    def buy_all(self, symbol: str, current_price: Optional[float] = None):
        """
        Buy as many shares as possible with available cash

        Args:
            symbol: Stock symbol to buy
            current_price: Current price of the stock (if known)

        Returns:
            Number of shares purchased
        """
        if current_price is None:
            current_price = self._get_current_price(symbol)

        if current_price is None or current_price <= 0:
            self.logger.error(f"Could not get valid price for {symbol}")
            return 0

        shares_to_buy = self.cash // current_price
        if shares_to_buy > 0:
            total_cost = shares_to_buy * current_price
            self.positions[symbol] = self.positions.get(symbol, 0) + shares_to_buy
            self.positionValues[symbol] = self.positions[symbol] * current_price
            self.cash -= total_cost
            self.invested = len(self.positions) > 0
            self.logger.info(f"Bought {shares_to_buy} shares of {symbol} at ${current_price:.2f}")
            return shares_to_buy

        return 0

    def sell_all(self, symbol: str, current_price: Optional[float] = None):
        """
        Sell all shares of a given symbol

        Args:
            symbol: Stock symbol to sell
            current_price: Current price of the stock (if known)

        Returns:
            Total proceeds from sale
        """

        # if self.liveTrading:
        #     # do this
        # else:
        #     # paper Trading


        if symbol not in self.positions or self.positions[symbol] == 0:
            return 0

        if current_price is None:
            current_price = self._get_current_price(symbol)

        if current_price is None or current_price <= 0:
            self.logger.error(f"Could not get valid price for {symbol} : Current price: {str(current_price)}")
            return 0

        # Only share maximum of shares allowed by for TradingStrategy by the PortfolioStrategy
        sharesToSell = self.positions[symbol]

        totalProceeds = sharesToSell * current_price

        del self.positions[symbol]
        if symbol in self.positionValues:
            del self.positionValues[symbol]

        # Update cash and positions in the database
        self.cash += totalProceeds
        self.invested = len(self.positions) > 0

        self.logger.info(f"Sold {sharesToSell} shares of {symbol} at ${current_price:.2f}")
        return totalProceeds

    def buy(self, symbol: str, shares: float, current_price: Optional[float] = None):
        """
        Buy a specific number of shares

        Args:
            symbol: Stock symbol
            shares: Number of shares to buy
            current_price: Current price per share

        Returns:
            True if purchase successful, False otherwise
        """
        if current_price is None:
            current_price = self._get_current_price(symbol)

        if current_price is None or current_price <= 0:
            return False

        total_cost = shares * current_price
        if total_cost <= self.cash:
            self.positions[symbol] = self.positions.get(symbol, 0) + shares
            self.positionValues[symbol] = self.positions[symbol] * current_price
            self.cash -= total_cost
            self.invested = len(self.positions) > 0
            return True
        return False

    def sell(self, symbol: str, shares: float, current_price: Optional[float] = None):
        """
        Sell a specific number of shares

        Args:
            symbol: Stock symbol
            shares: Number of shares to sell
            current_price: Current price per share

        Returns:
            True if sale successful, False otherwise
        """
        if symbol not in self.positions or self.positions[symbol] < shares:
            return False

        if current_price is None:
            current_price = self._get_current_price(symbol)

        if current_price is None or current_price <= 0:
            return False

        total_proceeds = shares * current_price
        self.positions[symbol] -= shares

        if self.positions[symbol] == 0:
            del self.positions[symbol]
            if symbol in self.positionValues:
                del self.positionValues[symbol]
        else:
            self.positionValues[symbol] = self.positions[symbol] * current_price

        self.cash += total_proceeds
        self.invested = len(self.positions) > 0
        return True

    def get_total_value(self) -> float:
        """
        Get total portfolio value (cash + positions)

        Returns:
            Total portfolio value
        """
        total_position_value = 0
        for symbol, shares in self.positions.items():
            current_price = self._get_current_price(symbol)
            if current_price:
                total_position_value += shares * current_price
                self.positionValues[symbol] = shares * current_price

        return self.cash + total_position_value

    def get_positions(self) -> Dict[str, float]:
        """
        Get current positions

        Returns:
            Dictionary of symbol -> shares
        """
        return self.positions.copy()

    def get_cash(self) -> float:
        """
        Get current cash balance

        Returns:
            Current cash amount
        """
        return self.cash

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price using Polygon client

        Args:
            symbol: Stock symbol

        Returns:
            Current price or None if unavailable
        """
        try:
            return self.polygon_client.get_current_price(symbol)
        except Exception as e:
            self.logger.error(f"Error fetching current price for {symbol}: {e}")
            return None

    def reset(self, cash: float = 100000):
        """
        Reset portfolio to initial state

        Args:
            cash: New initial cash amount
        """
        self.cash = cash
        self.initial_cash = cash
        self.positions = {}
        self.positionValues = {}
        self.invested = False

    def __str__(self):
        """String representation of portfolio"""
        total_value = self.get_total_value()
        return f"Portfolio: Cash=${self.cash:.2f}, Positions={len(self.positions)}, Total Value=${total_value:.2f}"