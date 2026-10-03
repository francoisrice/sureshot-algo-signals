import logging
import json
import numpy as np
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from .Portfolio import Portfolio
from .HistoricalDataClient import HistoricalDataClient

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
# Caps Sharpe/Sortino when there is no downside volatility; inf breaks JSON and optimizers
MAX_RISK_ADJUSTED_RATIO = 10.0


def annualized_ratio(mean_return: float, deviation: float) -> float:
    if deviation <= 0:
        return MAX_RISK_ADJUSTED_RATIO if mean_return > 0 else 0.0
    ratio = (mean_return / deviation) * np.sqrt(TRADING_DAYS_PER_YEAR)
    return float(np.clip(ratio, -MAX_RISK_ADJUSTED_RATIO, MAX_RISK_ADJUSTED_RATIO))


def downside_deviation(returns: List[float]) -> float:
    """Root-mean-square of the negative returns, averaged over the full series (MAR = 0)"""
    return float(np.sqrt(np.mean([min(r, 0.0) ** 2 for r in returns])))


def geometric_expectancy_pct(trade_return_pcts: List[float]) -> float:
    """Per-trade geometric mean return; arithmetic averaging overstates compounded growth"""
    if not trade_return_pcts:
        return 0.0
    growthFactors = [1.0 + pct / 100.0 for pct in trade_return_pcts]
    if any(factor <= 0 for factor in growthFactors):
        return -100.0
    compounded = float(np.prod(growthFactors))
    return (compounded ** (1.0 / len(growthFactors)) - 1.0) * 100.0


def max_drawdown_pct(equity_values: List[float], starting_equity: float) -> float:
    peak = starting_equity
    maxDrawdown = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        if peak > 0:
            maxDrawdown = max(maxDrawdown, ((peak - equity) / peak) * 100.0)
    return maxDrawdown


class Trade:
    """Represents a single trade execution"""

    def __init__(self, date: datetime, symbol: str, action: str, quantity: float, price: float, value: float):
        self.date = date
        self.symbol = symbol
        self.action = action  # 'BUY' or 'SELL'
        self.quantity = quantity
        self.price = price
        self.value = value
        self.pnl = None  # Will be set on exit
        self.pnl_percent = None


class BacktestEngine:
    """
    Backtesting engine for portfolio strategies
    """

    def __init__(
        self,
        strategy_name: str,
        initial_cash: float = 100000,
        use_cache: bool = True,
        data_root: Optional[str] = None
    ):
        """
        Initialize backtest engine

        Args:
            strategy_name: Name of the strategy being tested
            initial_cash: Starting cash amount
            use_cache: Whether to read bars from the shared data store (DATA_ROOT)
            data_root: Shared data store root; None uses $DATA_ROOT, then ../data
        """
        self.strategy_name = strategy_name
        self.initial_cash = initial_cash
        self.portfolio = Portfolio(cash=initial_cash)
        self.use_cache = use_cache
        self.data_client = HistoricalDataClient(data_root=data_root, use_market_store=use_cache)

        # Backtest state
        self.start_date = None
        self.end_date = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_returns: List[float] = []

        # Results
        self.results = None

        logger.info(f"BacktestEngine initialized for '{strategy_name}' with ${initial_cash:,.2f}")

    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = '1d'
    ) -> List[Dict]:
        """Split-adjusted bars from the shared data store, filling gaps from the providers"""
        return self.data_client.get_historical_data(symbol, start_date, end_date, timeframe)

    def execute_buy(self, date: datetime, symbol: str, price: float) -> Optional[Trade]:
        """
        Execute a buy order

        Args:
            date: Trade date
            symbol: Stock symbol
            price: Purchase price

        Returns:
            Trade object if successful, None otherwise
        """
        shares = self.portfolio.buy_all(symbol, price)
        if shares > 0:
            value = shares * price
            trade = Trade(date, symbol, 'BUY', shares, price, value)
            self.trades.append(trade)
            logger.info(f"{date.date()} BUY {shares} {symbol} @ ${price:.2f} = ${value:.2f}")
            return trade
        return None

    def execute_sell(self, date: datetime, symbol: str, price: float) -> Optional[Trade]:
        """
        Execute a sell order

        Args:
            date: Trade date
            symbol: Stock symbol
            price: Sale price

        Returns:
            Trade object if successful, None otherwise
        """
        if symbol not in self.portfolio.positions:
            return None

        shares = self.portfolio.positions[symbol]
        proceeds = self.portfolio.sell_all(symbol, price)

        if proceeds > 0:
            trade = Trade(date, symbol, 'SELL', shares, price, proceeds)

            # Calculate P&L from last buy
            last_buy = None
            for t in reversed(self.trades):
                if t.symbol == symbol and t.action == 'BUY':
                    last_buy = t
                    break

            if last_buy:
                trade.pnl = proceeds - last_buy.value
                trade.pnl_percent = (trade.pnl / last_buy.value) * 100

            self.trades.append(trade)
            logger.info(f"{date.date()} SELL {shares} {symbol} @ ${price:.2f} = ${proceeds:.2f} (P&L: ${trade.pnl:.2f}, {trade.pnl_percent:.2f}%)")
            return trade
        return None

    def record_equity(self, date: datetime, symbol_prices: Dict[str, float], api_url: str = None):
        totalEquity = self.portfolio.cash

        if api_url:
            try:
                portfolioResponse = requests.get(f"{api_url}/portfolio/{self.strategy_name}")
                if portfolioResponse.status_code == 200:
                    totalEquity = portfolioResponse.json().get('cash', 0.0)
            except Exception as e:
                logger.error(f"Failed to fetch portfolio cash in record_equity: {e}")

            try:
                positionsResponse = requests.get(f"{api_url}/positions", params={"strategy_name": self.strategy_name})
                if positionsResponse.status_code == 200:
                    positionsData = positionsResponse.json()
                    for pos in positionsData:
                        symbol = pos['symbol']
                        quantity = pos['quantity']
                        avgPrice = pos.get('avg_price', 0.0)
                        curPrice = symbol_prices.get(symbol, pos.get('current_price', avgPrice))
                        if quantity > 0:
                            totalEquity += quantity * curPrice
                        elif quantity < 0:
                            totalEquity += abs(quantity) * (2.0 * avgPrice - curPrice)
            except Exception as e:
                logger.error(f"Failed to fetch positions in record_equity: {e}")
        else:
            for symbol, shares in self.portfolio.positions.items():
                if symbol in symbol_prices:
                    curPrice = symbol_prices[symbol]
                    if shares > 0:
                        totalEquity += shares * curPrice
                    elif shares < 0:
                        avgPrice = self.portfolio.avgPrices.get(symbol, curPrice)
                        totalEquity += abs(shares) * (2.0 * avgPrice - curPrice)

        self.equity_curve.append((date, totalEquity))

        if len(self.equity_curve) > 1:
            prevEquity = self.equity_curve[-2][1]
            if prevEquity > 0:
                dailyReturn = (totalEquity - prevEquity) / prevEquity
                self.daily_returns.append(dailyReturn)

    def calculate_metrics(self, api_url: str = None) -> Dict:
        orders = []
        initialCash = self.initial_cash
        finalValue = self.portfolio.cash

        if api_url:
            try:
                ordersResponse = requests.get(f"{api_url}/orders", params={"strategy_name": self.strategy_name, "limit": 100000})
                ordersResponse.raise_for_status()
                orders = ordersResponse.json()
            except Exception as e:
                logger.error(f"Failed to fetch orders from API: {e}")
                return {}

            try:
                portfolioResponse = requests.get(f"{api_url}/portfolio/{self.strategy_name}")
                portfolioResponse.raise_for_status()
                portfolioState = portfolioResponse.json()
                initialCash = portfolioState['initial_cash']
                finalValue = portfolioState['total_value']
            except Exception as e:
                logger.error(f"Failed to fetch portfolio state from API: {e}")
                return {}
        else:
            if self.equity_curve:
                finalValue = self.equity_curve[-1][1]

        totalReturn = finalValue - initialCash
        totalReturnPct = (totalReturn / initialCash) * 100.0 if initialCash > 0 else 0.0

        orders = sorted(orders, key=lambda x: x['id'])

        trades = []
        if api_url and orders:
            ordersBySymbol: Dict[str, List[Dict]] = {}
            for o in orders:
                sym = o['symbol']
                ordersBySymbol.setdefault(sym, []).append(o)

            for sym, symOrders in ordersBySymbol.items():
                openLots: List[Dict[str, Any]] = []

                for order in symOrders:
                    orderType = order['order_type']
                    orderQty = order['quantity']
                    orderPrice = order['price']
                    if not orderPrice or orderPrice <= 0:
                        continue

                    absQty = abs(orderQty)
                    if absQty <= 0:
                        continue

                    if orderQty < 0:
                        orderSide = 'SHORT' if orderType == 'SELL' else 'COVER'
                    else:
                        orderSide = 'LONG' if orderType == 'BUY' else 'SELL'

                    if not openLots:
                        side = 'SHORT' if orderSide in ('SHORT', 'SELL') and orderType == 'SELL' else 'LONG'
                        openLots.append({'qty': absQty, 'price': orderPrice, 'side': side})
                        continue

                    currSide = openLots[0]['side']
                    isClosing = (currSide == 'LONG' and orderSide in ('SELL', 'SHORT') and orderType == 'SELL') or                                 (currSide == 'SHORT' and orderSide in ('COVER', 'LONG') and orderType == 'BUY')

                    if isClosing:
                        remainingCloseQty = absQty
                        while openLots and remainingCloseQty > 0:
                            lot = openLots[0]
                            matchedQty = min(lot['qty'], remainingCloseQty)
                            entryPrice = lot['price']

                            if currSide == 'LONG':
                                pnl = (orderPrice - entryPrice) * matchedQty
                                pnlPct = ((orderPrice - entryPrice) / entryPrice) * 100.0 if entryPrice > 0 else 0.0
                            else:
                                pnl = (entryPrice - orderPrice) * matchedQty
                                pnlPct = ((entryPrice - orderPrice) / entryPrice) * 100.0 if entryPrice > 0 else 0.0

                            trades.append({
                                'symbol': sym,
                                'side': currSide,
                                'quantity': matchedQty,
                                'entry_price': entryPrice,
                                'exit_price': orderPrice,
                                'pnl': pnl,
                                'pnl_pct': pnlPct
                            })

                            lot['qty'] -= matchedQty
                            remainingCloseQty -= matchedQty
                            if lot['qty'] <= 1e-6:
                                openLots.pop(0)

                        if remainingCloseQty > 1e-6:
                            newSide = 'SHORT' if currSide == 'LONG' else 'LONG'
                            openLots.append({'qty': remainingCloseQty, 'price': orderPrice, 'side': newSide})
                    else:
                        openLots.append({'qty': absQty, 'price': orderPrice, 'side': currSide})
        elif self.trades:
            for t in self.trades:
                if hasattr(t, 'pnl') and t.pnl is not None:
                    trades.append({
                        'symbol': t.symbol,
                        'pnl': t.pnl,
                        'pnl_pct': getattr(t, 'pnl_percent', 0.0)
                    })

        winningTrades = [rt for rt in trades if rt['pnl'] > 0]
        losingTrades = [rt for rt in trades if rt['pnl'] < 0]
        totalTrades = len(trades)

        numWins = len(winningTrades)
        numLosses = len(losingTrades)
        winRate = (numWins / totalTrades * 100.0) if totalTrades > 0 else 0.0
        lossRate = (numLosses / totalTrades * 100.0) if totalTrades > 0 else 0.0

        avgWin = float(np.mean([rt['pnl_pct'] for rt in winningTrades])) if winningTrades else 0.0
        avgLoss = float(np.mean([rt['pnl_pct'] for rt in losingTrades])) if losingTrades else 0.0

        expectancy = geometric_expectancy_pct([rt['pnl_pct'] for rt in trades])

        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days
            years = days / 365.25
            if years > 0 and initialCash > 0:
                if finalValue <= 0:
                    cagr = -100.0
                else:
                    cagr = (((finalValue / initialCash) ** (1.0 / years)) - 1.0) * 100.0
            else:
                cagr = 0.0
        else:
            cagr = 0.0

        if self.daily_returns:
            avgDailyReturn = float(np.mean(self.daily_returns))
            stdDailyReturn = float(np.std(self.daily_returns, ddof=1)) if len(self.daily_returns) > 1 else 0.0
            sharpeRatio = annualized_ratio(avgDailyReturn, stdDailyReturn)
            sortinoRatio = annualized_ratio(avgDailyReturn, downside_deviation(self.daily_returns))
        else:
            sharpeRatio = 0.0
            sortinoRatio = 0.0

        if self.equity_curve:
            maxDrawdown = max_drawdown_pct([equity for _, equity in self.equity_curve], initialCash)
        elif trades:
            cumulative = initialCash
            equitySteps = []
            for rt in trades:
                cumulative += rt['pnl']
                equitySteps.append(cumulative)
            maxDrawdown = max_drawdown_pct(equitySteps, initialCash)
        else:
            maxDrawdown = 0.0

        if avgLoss != 0 and avgWin != 0:
            p = winRate / 100.0
            q = lossRate / 100.0
            b = abs(avgWin) / abs(avgLoss)
            kellyCriterion = (b * p - q) / b
        elif numWins > 0 and numLosses == 0:
            kellyCriterion = 1.0
        else:
            kellyCriterion = 0.0

        metrics = {
            'strategy_name': self.strategy_name,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'initial_cash': initialCash,
            'final_value': finalValue,
            'total_return': totalReturn,
            'total_return_pct': totalReturnPct,
            'cagr': cagr,
            'total_trades': totalTrades,
            'num_wins': numWins,
            'num_losses': numLosses,
            'win_rate': winRate,
            'loss_rate': lossRate,
            'avg_win_pct': avgWin,
            'avg_loss_pct': avgLoss,
            'expectancy': expectancy,
            'sharpe_ratio': float(sharpeRatio),
            'sortino_ratio': float(sortinoRatio),
            'max_drawdown': float(maxDrawdown),
            'kelly_criterion': float(kellyCriterion)
        }

        self.results = metrics
        return metrics

    def print_results(self):
        """Pretty print backtest results to console"""
        if not self.results:
            logger.error("No results to print. Run calculate_metrics() first.")
            return

        r = self.results

        print("\n" + "=" * 80)
        print(f"BACKTEST RESULTS: {r['strategy_name']}")
        print("=" * 80)
        print(f"\nPeriod: {r['start_date'][:10]} to {r['end_date'][:10]}")
        print(f"Initial Capital: ${r['initial_cash']:,.2f}")
        print(f"Final Value: ${r['final_value']:,.2f}")
        print(f"\n{'PERFORMANCE METRICS':-^80}")
        print(f"Total Return: ${r['total_return']:,.2f} ({r['total_return_pct']:.2f}%)")
        print(f"Compounding Annualized Return (CAGR): {r['cagr']:.2f}%")
        print(f"\n{'TRADE STATISTICS':-^80}")
        print(f"Total Round-Trip Trades: {r['total_trades']}")
        print(f"Winning Trades: {r['num_wins']}")
        print(f"Losing Trades: {r['num_losses']}")
        print(f"Win Rate: {r['win_rate']:.2f}%")
        print(f"Loss Rate: {r['loss_rate']:.2f}%")
        print(f"Average Win Percentage: {r['avg_win_pct']:.2f}%")
        print(f"Average Loss Percentage: {r['avg_loss_pct']:.2f}%")
        print(f"Expectancy (geometric): {r['expectancy']:.2f}%")
        print(f"\n{'RISK METRICS':-^80}")
        print(f"Sharpe Ratio: {r['sharpe_ratio']:.3f}")
        print(f"Sortino Ratio: {r['sortino_ratio']:.3f}")
        print(f"Maximum Drawdown: {r['max_drawdown']:.2f}%")
        print(f"Kelly Criterion: {r['kelly_criterion']:.3f}")
        print("=" * 80 + "\n")

    def save_results(self, output_dir: str = "backtest_results"):
        """
        Save backtest results to JSON file

        Args:
            output_dir: Directory to save results
        """
        if not self.results:
            logger.error("No results to save. Run calculate_metrics() first.")
            return

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        # Generate filename with strategy name and timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.strategy_name}_{timestamp}.json"
        filepath = output_path / filename

        # Add metadata
        results_with_metadata = self.results.copy()
        results_with_metadata['backtest_started'] = self.start_date.isoformat() if self.start_date else None
        results_with_metadata['backtest_completed'] = datetime.now().isoformat()

        # Save to JSON
        with open(filepath, 'w') as f:
            json.dump(results_with_metadata, f, indent=2)

        logger.info(f"Results saved to {filepath}")
        print(f"\nResults saved to: {filepath}")

    def reset(self):
        """Reset backtest state"""
        self.portfolio.reset(self.initial_cash)
        self.trades = []
        self.equity_curve = []
        self.daily_returns = []
        self.results = None
        self.start_date = None
        self.end_date = None
