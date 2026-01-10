import logging
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from collections import defaultdict
from .Portfolio import Portfolio
from .Polygon import PolygonClient
from .BacktestingPriceCache import BacktestingPriceCache
from .SMA import SMA
from .BacktestEngine import Trade

logger = logging.getLogger(__name__)
logger.level = logging.DEBUG

class StrategyConfig:
    """Configuration for a single strategy in the portfolio"""

    def __init__(
        self,
        name: str,
        trading_symbol: str,
        indicator_symbol: str,
        sma_period: int = 252,
        max_mid_month_loss: float = 0.05
    ):
        self.name = name
        self.trading_symbol = trading_symbol
        self.indicator_symbol = indicator_symbol
        self.sma_period = sma_period
        self.max_mid_month_loss = max_mid_month_loss
        self.weight = 0.0  # Will be set by optimization


class PortfolioBacktestEngine:
    """
    Backtesting engine for multi-strategy portfolios with shared capital pool
    """

    def __init__(
        self,
        portfolio_name: str,
        strategies: List[StrategyConfig],
        initial_cash: float = 100000,
        use_cache: bool = True,
        cache_dir: str = ".price_cache"
    ):
        """
        Initialize portfolio backtest engine

        Args:
            portfolio_name: Name of the portfolio
            strategies: List of strategy configurations
            initial_cash: Starting cash amount for entire portfolio
            use_cache: Whether to use price data caching
            cache_dir: Directory for cache files
        """
        self.portfolio_name = portfolio_name
        self.strategies = strategies
        self.initial_cash = initial_cash
        self.use_cache = use_cache
        self.price_cache = BacktestingPriceCache(cache_dir) if use_cache else None

        # Shared portfolio across all strategies
        self.portfolio = Portfolio(cash=initial_cash)
        self.polygon_client = PolygonClient()

        # Strategy-specific state
        self.smas = {}  # strategy_name -> SMA
        self.strategy_positions = {}  # strategy_name -> {symbol: shares}
        self.strategy_cash_allocated = {}  # strategy_name -> allocated cash
        self.strategy_previous_close = {}  # strategy_name -> previous close price
        self.strategy_previous_close_above_sma = {}  # strategy_name -> bool

        # Backtest state
        self.start_date = None
        self.end_date = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_returns: List[float] = []
        self.strategy_equity_curves = defaultdict(list)  # strategy_name -> [(date, equity)]

        # Results
        self.results = None

        logger.info(f"PortfolioBacktestEngine initialized for '{portfolio_name}' with {len(strategies)} strategies")

    def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = '1d'
    ) -> List[Dict]:
        """Get historical data with caching support"""
        if self.use_cache and self.price_cache:
            cached_data = self.price_cache.get(symbol, start_date, end_date, timeframe)
            if cached_data:
                return cached_data

        logger.info(f"Fetching {symbol} data from {start_date.date()} to {end_date.date()}")
        data = self.polygon_client.get_historical_data(symbol, start_date, end_date, timeframe)

        if self.use_cache and self.price_cache and data:
            self.price_cache.set(symbol, start_date, end_date, timeframe, data)

        return data

    def allocate_capital_efficient_frontier(self, historical_returns: pd.DataFrame) -> Dict[str, float]:
        """
        Allocate capital using efficient frontier optimization

        Args:
            historical_returns: DataFrame of daily returns for each strategy

        Returns:
            Dictionary of strategy_name -> weight (0-1)
        """
        try:
            from portfolio_IL_efficientfrontier.EfficientFrontier.calc_efficientfrontier import (
                compute_log_returns_cov,
                compute_ABC,
                compute_global_minimum_variance_portfolio
            )

            # Use log returns and covariance
            log_returns, cov_matrix = compute_log_returns_cov(historical_returns)
            market_components = compute_ABC(log_returns, cov_matrix)

            # Get minimum variance portfolio weights
            weights_array, _ = compute_global_minimum_variance_portfolio(market_components)
            weights = weights_array.flatten()

            # Create weight dictionary
            weight_dict = {}
            for i, strategy in enumerate(self.strategies):
                weight_dict[strategy.name] = float(weights[i])

            logger.info("Efficient Frontier Weights:")
            for name, weight in weight_dict.items():
                logger.info(f"  {name}: {weight:.2%}")

            return weight_dict

        except Exception as e:
            logger.warning(f"Efficient frontier optimization failed: {e}. Using equal weights.")
            # Fallback to equal weights
            equal_weight = 1.0 / len(self.strategies)
            return {strategy.name: equal_weight for strategy in self.strategies}

    def allocate_capital_equal_weight(self) -> Dict[str, float]:
        """Allocate capital equally across all strategies"""
        equal_weight = 1.0 / len(self.strategies)
        return {strategy.name: equal_weight for strategy in self.strategies}

    def execute_buy(
        self,
        date: datetime,
        strategy_name: str,
        symbol: str,
        price: float,
        allocated_cash: float
    ) -> Optional[Trade]:
        """Execute a buy order for a specific strategy"""
        shares_to_buy = allocated_cash // price

        if shares_to_buy > 0 and self.portfolio.cash >= shares_to_buy * price:
            value = shares_to_buy * price
            self.portfolio.cash -= value
            self.portfolio.positions[symbol] = self.portfolio.positions.get(symbol, 0) + shares_to_buy
            self.portfolio.invested = True

            # Track strategy position
            if strategy_name not in self.strategy_positions:
                self.strategy_positions[strategy_name] = {}
            self.strategy_positions[strategy_name][symbol] = shares_to_buy

            trade = Trade(date, symbol, 'BUY', shares_to_buy, price, value)
            trade.strategy = strategy_name
            self.trades.append(trade)

            logger.info(f"{date.date()} [{strategy_name}] BUY {shares_to_buy} {symbol} @ ${price:.2f} = ${value:.2f}")
            return trade

        return None

    def execute_sell(self, date: datetime, strategy_name: str, symbol: str, price: float) -> Optional[Trade]:
        """Execute a sell order for a specific strategy"""
        if strategy_name not in self.strategy_positions:
            return None

        if symbol not in self.strategy_positions[strategy_name]:
            return None

        shares = self.strategy_positions[strategy_name][symbol]
        proceeds = shares * price

        # Update portfolio
        self.portfolio.positions[symbol] -= shares
        if self.portfolio.positions[symbol] == 0:
            del self.portfolio.positions[symbol]
        self.portfolio.cash += proceeds
        self.portfolio.invested = len(self.portfolio.positions) > 0

        # Clear strategy position
        del self.strategy_positions[strategy_name][symbol]

        # Calculate P&L
        trade = Trade(date, symbol, 'SELL', shares, price, proceeds)
        trade.strategy = strategy_name

        # Find last buy for this strategy
        last_buy = None
        for t in reversed(self.trades):
            if t.symbol == symbol and t.action == 'BUY' and hasattr(t, 'strategy') and t.strategy == strategy_name:
                last_buy = t
                break

        if last_buy:
            trade.pnl = proceeds - last_buy.value
            trade.pnl_percent = (trade.pnl / last_buy.value) * 100

        self.trades.append(trade)
        logger.info(f"{date.date()} [{strategy_name}] SELL {shares} {symbol} @ ${price:.2f} = ${proceeds:.2f} (P&L: ${trade.pnl:.2f}, {trade.pnl_percent:.2f}%)")
        return trade

    def run(self, start_date: datetime, end_date: datetime, optimization_method: str = 'efficient_frontier'):
        """
        Run backtest for the entire portfolio

        Args:
            start_date: Backtest start date
            end_date: Backtest end date
            optimization_method: 'efficient_frontier' or 'equal_weight'
        """
        self.start_date = start_date
        self.end_date = end_date

        logger.info(f"Starting portfolio backtest: {self.portfolio_name}")
        logger.info(f"Period: {start_date.date()} to {end_date.date()}")
        logger.info(f"Optimization: {optimization_method}")

        # Initialize SMAs for all strategies
        for strategy in self.strategies:
            warmup_start = start_date - timedelta(days=strategy.sma_period * 2)
            sma = SMA(strategy.indicator_symbol, period=strategy.sma_period, timeframe='1d')
            sma.initialize(warmup_start)
            logger.debug(f"[{strategy.name}] SMA: {sma.sma_value}")
            self.smas[strategy.name] = sma
            self.strategy_previous_close[strategy.name] = None
            self.strategy_previous_close_above_sma[strategy.name] = False

        # Fetch historical data for all symbols (for efficient frontier)
        logger.info("Fetching historical data for optimization...")
        strategy_returns = {}

        for strategy in self.strategies:
            data = self.get_historical_data(strategy.trading_symbol, start_date, end_date, '1d')
            if data:
                prices = [candle['c'] for candle in data]
                returns = pd.Series(prices).pct_change().dropna()
                strategy_returns[strategy.name] = returns

        # Allocate capital using chosen method
        if optimization_method == 'efficient_frontier' and len(strategy_returns) > 0:
            returns_df = pd.DataFrame(strategy_returns)
            weights = self.allocate_capital_efficient_frontier(returns_df)
        else:
            weights = self.allocate_capital_equal_weight()

        # Set weights and allocate cash
        for strategy in self.strategies:
            strategy.weight = weights.get(strategy.name, 0.0)
            self.strategy_cash_allocated[strategy.name] = self.initial_cash * strategy.weight

        # Get all unique trading and indicator symbols
        all_symbols = set()
        for strategy in self.strategies:
            all_symbols.add(strategy.trading_symbol)
            all_symbols.add(strategy.indicator_symbol)

        # Fetch historical data for all symbols
        historical_data = {}
        for symbol in all_symbols:
            data = self.get_historical_data(symbol, start_date, end_date, '1d')
            if data:
                historical_data[symbol] = {datetime.fromtimestamp(c['t'] / 1000).date(): c['c'] for c in data}

        # Get all trading dates
        all_dates = set()
        for data in historical_data.values():
            all_dates.update(data.keys())
        all_dates = sorted(all_dates)

        logger.info(f"Processing {len(all_dates)} trading days...")

        # Process each trading day
        for current_date_key in all_dates:
            current_datetime = datetime.combine(current_date_key, datetime.min.time())

            # Process each strategy
            for strategy in self.strategies:
                # Get indicator price and update SMA
                if strategy.indicator_symbol not in historical_data:
                    continue
                if current_date_key not in historical_data[strategy.indicator_symbol]:
                    continue

                indicator_price = historical_data[strategy.indicator_symbol][current_date_key]
                sma = self.smas[strategy.name]
                sma.Update(indicator_price)

                if not sma.is_ready():
                    continue

                sma_value = sma.get_value()

                # Get trading price
                if strategy.trading_symbol not in historical_data:
                    continue
                if current_date_key not in historical_data[strategy.trading_symbol]:
                    continue

                trading_price = historical_data[strategy.trading_symbol][current_date_key]

                # Check if strategy has position
                has_position = (
                    strategy.name in self.strategy_positions and
                    strategy.trading_symbol in self.strategy_positions[strategy.name]
                )

                # Mid-Month Stop Loss
                if has_position:
                    if indicator_price < sma_value * (1 - strategy.max_mid_month_loss):
                        logger.info(f"{current_date_key} [{strategy.name}] Mid-month stop loss triggered")
                        logger.debug(f"{current_date_key} [{strategy.name}] SMA: {sma_value}")
                        logger.debug(f"{current_date_key} [{strategy.name}] Indicator price: {indicator_price}")
                        self.execute_sell(current_datetime, strategy.name, strategy.trading_symbol, trading_price)
                        continue

                # Month-end logic
                if self._is_month_end(current_datetime):
                    logger.debug(f"{current_date_key} [{strategy.name}] SMA: {sma_value}")
                    logger.debug(f"{current_date_key} [{strategy.name}] Indicator price: {indicator_price}")
                    if has_position:
                        # Exit if below SMA
                        if indicator_price < sma_value:
                            logger.info(f"{current_date_key} [{strategy.name}] Month-end exit")
                            self.execute_sell(current_datetime, strategy.name, strategy.trading_symbol, trading_price)
                    else:
                        # Entry condition
                        prev_close = self.strategy_previous_close[strategy.name]
                        logger.debug(f"{current_date_key} [{strategy.name}] Prev Close: {prev_close}")
                        prev_above_sma = self.strategy_previous_close_above_sma[strategy.name]
                        logger.debug(f"{current_date_key} [{strategy.name}] Prev Close over SMA: {prev_above_sma}")

                        if prev_close and indicator_price > sma_value and prev_above_sma:
                            logger.info(f"{current_date_key} [{strategy.name}] Month-end entry")
                            allocated_cash = self.strategy_cash_allocated[strategy.name]
                            self.execute_buy(current_datetime, strategy.name, strategy.trading_symbol, trading_price, allocated_cash)

                # Update strategy state
                self.strategy_previous_close[strategy.name] = indicator_price
                self.strategy_previous_close_above_sma[strategy.name] = indicator_price > sma_value

            # Record equity for the day
            self._record_equity(current_datetime, historical_data, current_date_key)

        # Close all positions
        for strategy in self.strategies:
            has_position = (
                    strategy.name in self.strategy_positions and
                    strategy.trading_symbol in self.strategy_positions[strategy.name]
                )
            trading_price = historical_data[strategy.trading_symbol][all_dates[-1]]
            if has_position:
                self.execute_sell(datetime.combine(all_dates[-1], datetime.min.time()), strategy.name, strategy.trading_symbol, trading_price)

        logger.info("Portfolio backtest execution completed")

        # Calculate metrics
        self.calculate_metrics()
        self.print_results()
        self.save_results()

        return self.results

    def _is_month_end(self, date: datetime) -> bool:
        # Get the last calendar day of the month
        # Move to the first day of next month, then subtract one day
        if date.month == 12:
            next_month = date.replace(year=date.year + 1, month=1, day=1)
        else:
            next_month = date.replace(month=date.month + 1, day=1)

        last_day_of_month = next_month - timedelta(days=1)

        # Walk backwards from the last day to find the last weekday (Mon-Fri)
        last_trading_day = last_day_of_month
        while last_trading_day.weekday() >= 5:  # 5=Saturday, 6=Sunday
            last_trading_day -= timedelta(days=1)

        # Check if the given date matches the last trading day
        return date.date() == last_trading_day.date()

    def _record_equity(self, date: datetime, historical_data: Dict, current_date_key):
        """Record portfolio equity"""
        total_equity = self.portfolio.cash

        # Add value of all positions
        for symbol, shares in self.portfolio.positions.items():
            if symbol in historical_data and current_date_key in historical_data[symbol]:
                price = historical_data[symbol][current_date_key]
                total_equity += shares * price

        self.equity_curve.append((date, total_equity))

        # Calculate daily return
        if len(self.equity_curve) > 1:
            prev_equity = self.equity_curve[-2][1]
            if prev_equity > 0:
                daily_return = (total_equity - prev_equity) / prev_equity
                self.daily_returns.append(daily_return)

    def calculate_metrics(self) -> Dict:
        """Calculate comprehensive portfolio metrics"""
        if not self.equity_curve:
            logger.error("No equity data to calculate metrics")
            return {}

        final_value = self.equity_curve[-1][1]
        total_return = final_value - self.initial_cash
        total_return_pct = (total_return / self.initial_cash) * 100

        # Separate trades by strategy
        strategy_trades = defaultdict(list)
        for trade in self.trades:
            if hasattr(trade, 'strategy'):
                strategy_trades[trade.strategy].append(trade)

        # Overall trade statistics
        winning_trades = [t for t in self.trades if t.action == 'SELL' and t.pnl and t.pnl > 0]
        losing_trades = [t for t in self.trades if t.action == 'SELL' and t.pnl and t.pnl < 0]
        total_trades = len(winning_trades) + len(losing_trades)

        num_wins = len(winning_trades)
        num_losses = len(losing_trades)
        win_rate = (num_wins / total_trades * 100) if total_trades > 0 else 0
        loss_rate = (num_losses / total_trades * 100) if total_trades > 0 else 0

        avg_win = np.mean([t.pnl_percent for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl_percent for t in losing_trades]) if losing_trades else 0

        expectancy = ((1 + (avg_win / 100)) ** (win_rate/100)) * ((1 - (avg_loss/ 100)) ** (loss_rate/100)) * 100 if total_trades > 0 else 0

        # Annualized return
        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days
            years = days / 365.25
            if years > 0:
                cagr = (((final_value / self.initial_cash) ** (1 / years)) - 1) * 100
            else:
                cagr = 0
        else:
            cagr = 0

        # Risk metrics
        if self.daily_returns:
            avg_daily_return = np.mean(self.daily_returns)
            std_daily_return = np.std(self.daily_returns)
            sharpe_ratio = (avg_daily_return / std_daily_return) * np.sqrt(252) if std_daily_return > 0 else 0

            downside_returns = [r for r in self.daily_returns if r < 0]
            if downside_returns:
                downside_std = np.std(downside_returns)
                sortino_ratio = (avg_daily_return / downside_std) * np.sqrt(252) if downside_std > 0 else 0
            else:
                sortino_ratio = 0
        else:
            sharpe_ratio = 0
            sortino_ratio = 0

        # Maximum Drawdown
        max_drawdown = 0
        peak = self.equity_curve[0][1]
        for date, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            drawdown = ((peak - equity) / peak) * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # Kelly Criterion
        if avg_loss != 0 and avg_win != 0:
            # kelly = (win_rate / 100) - ((loss_rate / 100) / abs(avg_loss / avg_win)) ?
            kelly = (win_rate  / (abs(avg_loss)/100)) - (loss_rate / (avg_win / 100))
        else:
            kelly = 0

        metrics = {
            'portfolio_name': self.portfolio_name,
            'num_strategies': len(self.strategies),
            'strategy_weights': {s.name: s.weight for s in self.strategies},
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'initial_cash': self.initial_cash,
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
        """Pretty print portfolio backtest results"""
        if not self.results:
            logger.error("No results to print")
            return

        r = self.results

        print("\n" + "=" * 80)
        print(f"PORTFOLIO BACKTEST RESULTS: {r['portfolio_name']}")
        print("=" * 80)
        print(f"\nPeriod: {r['start_date'][:10]} to {r['end_date'][:10]}")
        print(f"Number of Strategies: {r['num_strategies']}")
        print(f"Initial Capital: ${r['initial_cash']:,.2f}")
        print(f"Final Value: ${r['final_value']:,.2f}")

        print(f"\n{'STRATEGY WEIGHTS':-^80}")
        for name, weight in r['strategy_weights'].items():
            print(f"{name}: {weight:.2%}")

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
        print(f"Expectancy: {r['expectancy']:.2f}%")

        print(f"\n{'RISK METRICS':-^80}")
        print(f"Sharpe Ratio: {r['sharpe_ratio']:.3f}")
        print(f"Sortino Ratio: {r['sortino_ratio']:.3f}")
        print(f"Maximum Drawdown: {r['max_drawdown']:.2f}%")
        print(f"Kelly Criterion: {r['kelly_criterion']:.3f}")
        print("=" * 80 + "\n")

    def save_results(self, output_dir: str = "backtest_results"):
        """Save results to JSON file"""
        if not self.results:
            logger.error("No results to save")
            return

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.portfolio_name}_{timestamp}.json"
        filepath = output_path / filename

        results_with_metadata = self.results.copy()
        results_with_metadata['backtest_started'] = self.start_date.isoformat() if self.start_date else None
        results_with_metadata['backtest_completed'] = datetime.now().isoformat()

        with open(filepath, 'w') as f:
            json.dump(results_with_metadata, f, indent=2)

        logger.info(f"Results saved to {filepath}")
        print(f"\nResults saved to: {filepath}")
