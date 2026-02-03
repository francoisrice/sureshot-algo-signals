import logging
import json
import numpy as np
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from .Portfolio import Portfolio
from .Polygon import PolygonClient
from .BacktestingPriceCache import BacktestingPriceCache

logger = logging.getLogger(__name__)


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
        cache_dir: str = ".price_cache"
    ):
        """
        Initialize backtest engine

        Args:
            strategy_name: Name of the strategy being tested
            initial_cash: Starting cash amount
            use_cache: Whether to use price data caching
            cache_dir: Directory for cache files
        """
        self.strategy_name = strategy_name
        self.initial_cash = initial_cash
        self.portfolio = Portfolio(cash=initial_cash)
        self.polygon_client = PolygonClient()
        self.use_cache = use_cache
        self.price_cache = BacktestingPriceCache(cache_dir) if use_cache else None

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
        """
        Get historical data with caching support

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Timeframe

        Returns:
            List of price data
        """
        # Try cache first
        if self.use_cache and self.price_cache:
            cached_data = self.price_cache.get(symbol, start_date, end_date, timeframe)
            if cached_data:
                return cached_data

        # Fetch from API
        logger.info(f"Fetching {symbol} data from {start_date.date()} to {end_date.date()}")
        data = self.polygon_client.get_historical_data(symbol, start_date, end_date, timeframe)

        # Cache the data
        if self.use_cache and self.price_cache and data:
            self.price_cache.set(symbol, start_date, end_date, timeframe, data)

        return data

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
        """
        Record portfolio equity at a point in time

        Args:
            date: Current date
            symbol_prices: Dictionary of symbol -> current price
        """
        # Calculate total equity
        total_equity = self.portfolio.cash

        if api_url:
            positions_response = requests.get(f"{api_url}/positions?{self.strategy_name}")
            positions_response.raise_for_status()
            positions = positions_response.json()
            for pos in positions:
                if pos['symbol'] in symbol_prices:
                    total_equity += pos['quantity'] * symbol_prices[pos['symbol']]
        else:
            for symbol, shares in self.portfolio.positions.items():
                if symbol in symbol_prices:
                    total_equity += shares * symbol_prices[symbol]

        self.equity_curve.append((date, total_equity))

        # Calculate daily return
        if len(self.equity_curve) > 1:
            prev_equity = self.equity_curve[-2][1]
            daily_return = (total_equity - prev_equity) / prev_equity
            self.daily_returns.append(daily_return)

    def calculate_metrics(self, api_url: str = None) -> Dict:
        """
        Calculate comprehensive backtest metrics

        Args:
            api_url: Base URL of the MultiStrategyAPI

        Returns:
            Dictionary of performance metrics
        """

        # Fetch orders from API
        try:
            orders_response = requests.get(f"{api_url}/orders")
            orders_response.raise_for_status()
            orders = orders_response.json()
        except Exception as e:
            logger.error(f"Failed to fetch orders from API: {e}")
            return {}

        # Fetch portfolio state for final value
        try:
            portfolio_response = requests.get(f"{api_url}/portfolio/{self.strategy_name}")
            portfolio_response.raise_for_status()
            portfolio_state = portfolio_response.json()
        except Exception as e:
            logger.error(f"Failed to fetch portfolio state from API: {e}")
            return {}

        # Sort orders by id (chronological order)
        orders = sorted(orders, key=lambda x: x['id'])

        # Get portfolio values
        initial_cash = portfolio_state['initial_cash']
        final_value = portfolio_state['total_value']
        total_return = final_value - initial_cash
        total_return_pct = (total_return / initial_cash) * 100 if initial_cash > 0 else 0

        # Pair BUY and SELL orders to calculate P&L for each round trip
        buy_orders = [o for o in orders if o['order_type'] == 'BUY']
        sell_orders = [o for o in orders if o['order_type'] == 'SELL']

        # Calculate P&L for each sell by matching with preceding buy
        trades = []
        for i, sell in enumerate(sell_orders):
            if i < len(buy_orders):
                buy = buy_orders[i]
                pnl = sell['order_value'] - buy['order_value']
                pnl_pct = (pnl / buy['order_value']) * 100
                trades.append({
                    'buy_value': buy['order_value'],
                    'sell_value': sell['order_value'],
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })

        # Separate winning and losing trades
        winning_trades = [rt for rt in trades if rt['pnl'] > 0]
        losing_trades = [rt for rt in trades if rt['pnl'] < 0]
        total_trades = len(trades)

        # Win/Loss statistics
        num_wins = len(winning_trades)
        num_losses = len(losing_trades)
        win_rate = (num_wins / total_trades * 100) if total_trades > 0 else 0
        loss_rate = (num_losses / total_trades * 100) if total_trades > 0 else 0

        avg_win = np.mean([rt['pnl_pct'] for rt in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([rt['pnl_pct'] for rt in losing_trades]) if losing_trades else 0

        # Expectancy (average return per trade over 100 trades)
        if total_trades > 0:
            expectancy = (win_rate / 100 * avg_win) + (loss_rate / 100 * avg_loss)
        else:
            expectancy = 0

        # Annualized return (CAGR)
        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days
            years = days / 365.25
            if years > 0:
                cagr = (((final_value / initial_cash) ** (1 / years)) - 1) * 100
            else:
                cagr = 0
        else:
            cagr = 0

        if self.daily_returns:
            avg_daily_return = np.mean(self.daily_returns)
            std_daily_return = np.std(self.daily_returns)
            if std_daily_return > 0:
                sharpe_ratio = (avg_daily_return / std_daily_return) * np.sqrt(252)
            else:
                sharpe_ratio = 0
        
        # Calculate returns from round trips for Sharpe/Sortino
        # trade_returns = [rt['pnl_pct'] / 100 for rt in trades]  # Convert to decimal
        # Sharpe Ratio annualized
        # if trade_returns:
        #     avg_return = np.mean(trade_returns)
        #     std_return = np.std(trade_returns)
        #     trades_per_year = max(1, total_trades / max(1, years)) if self.start_date and self.end_date else 1
        #     if std_return > 0:
        #         sharpe_ratio = (avg_return / std_return) * np.sqrt(trades_per_year)
            # else:
            #     sharpe_ratio = 0
        else:
            sharpe_ratio = 0
            avg_return = 0

        # Sortino Ratio (downside deviation)
        if self.daily_returns:
            downside_returns = [r for r in self.daily_returns if r < 0]
        # if trade_returns:
        #     downside_returns = [r for r in trade_returns if r < 0]
            if downside_returns:
                downside_std = np.std(downside_returns)
                # trades_per_year = max(1, total_trades / max(1, years)) if self.start_date and self.end_date else 1
                if downside_std > 0:
                    sortino_ratio = (avg_daily_return / downside_std) * np.sqrt(252)
                    # sortino_ratio = (avg_return / downside_std) * np.sqrt(trades_per_year)
                else:
                    sortino_ratio = 0
            else:
                sortino_ratio = float('inf') if avg_daily_return > 0 else 0
        else:
            sortino_ratio = 0

        # Maximum Drawdown from equity curve (if available) or from round trips
        max_drawdown = 0
        if self.equity_curve:
            peak = self.equity_curve[0][1]
            for date, equity in self.equity_curve:
                if equity > peak:
                    peak = equity
                drawdown = ((peak - equity) / peak) * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        else:
            # Estimate from round trip returns
            cumulative = initial_cash
            peak = initial_cash
            for rt in trades:
                cumulative += rt['pnl']
                if cumulative > peak:
                    peak = cumulative
                drawdown = ((peak - cumulative) / peak) * 100 if peak > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        # Kelly Criterion
        if avg_loss != 0 and avg_win != 0:
            kelly = ((win_rate) / abs(avg_loss)) - ((loss_rate) / abs(avg_win))
        else:
            kelly = 0

        metrics = {
            'strategy_name': self.strategy_name,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'initial_cash': initial_cash,
            'final_value': final_value,
            'total_return': total_return,
            'total_return_pct': total_return_pct,
            'cagr': cagr,
            'total_trades': total_trades,
            'num_wins': num_wins,
            'num_losses': num_losses,
            'win_rate': win_rate,
            'loss_rate': loss_rate,
            'avg_win_pct': avg_win,
            'avg_loss_pct': avg_loss,
            'expectancy': expectancy,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'max_drawdown': max_drawdown,
            'kelly_criterion': kelly
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
        print(f"Total Number of Orders: {r['total_trades']}")
        print(f"Winning Trades: {r['num_wins']}")
        print(f"Losing Trades: {r['num_losses']}")
        print(f"Win Rate: {r['win_rate']:.2f}%")
        print(f"Loss Rate: {r['loss_rate']:.2f}%")
        print(f"Average Win Percentage: {r['avg_win_pct']:.2f}%")
        print(f"Average Loss Percentage: {r['avg_loss_pct']:.2f}%")
        print(f"Expectancy (100 trades): {r['expectancy']:.2f}%")
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
