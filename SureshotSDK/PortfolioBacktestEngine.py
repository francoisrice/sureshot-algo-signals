"""
Refactored Portfolio Backtest Engine

Multi-strategy portfolio backtesting with:
- Multi-resolution support (daily and intraday)
- Dynamic capital allocation
- Per-strategy rebalancing frequencies
- Flexible strategy architecture
"""

import logging
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date, time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from collections import defaultdict

from .Portfolio import Portfolio
from .Polygon import PolygonClient
from .BacktestingPriceCache import BacktestingPriceCache
from .IntradayDataManager import IntradayDataManager
from .BacktestEngine import Trade
from .strategies.BaseStrategy import BaseStrategy, BarData

logger = logging.getLogger(__name__)


class PortfolioBacktestEngine:
    """
    Advanced multi-strategy portfolio backtesting engine

    Supports:
    - Multiple strategy types (monthly, intraday, options)
    - Dynamic capital allocation based on performance
    - Multi-resolution data processing
    - Per-strategy rebalancing frequencies
    """

    def __init__(
        self,
        portfolio_name: str,
        strategies: List[BaseStrategy],
        initial_cash: float = 100000,
        use_cache: bool = True,
        cache_dir: str = ".price_cache",
        rebalance_lookback_days: int = 90
    ):
        """
        Initialize portfolio backtest engine

        Args:
            portfolio_name: Name of the portfolio
            strategies: List of strategy instances (BaseStrategy subclasses)
            initial_cash: Starting cash amount for entire portfolio
            use_cache: Whether to use price data caching
            cache_dir: Directory for cache files
            rebalance_lookback_days: Days to look back for performance scoring
        """
        self.portfolio_name = portfolio_name
        self.strategies = strategies
        self.initial_cash = initial_cash
        self.use_cache = use_cache
        self.rebalance_lookback_days = rebalance_lookback_days

        # Data managers
        self.price_cache = BacktestingPriceCache(cache_dir) if use_cache else None
        self.intraday_manager = IntradayDataManager()
        self.polygon_client = PolygonClient()

        # Shared portfolio
        self.portfolio = Portfolio(cash=initial_cash)

        # Strategy tracking
        self.strategy_positions: Dict[str, Dict[str, float]] = {}  # strategy -> {symbol: shares}
        self.strategy_equity: Dict[str, List[float]] = defaultdict(list)  # For performance tracking

        # Backtest state
        self.start_date: Optional[datetime] = None
        self.end_date: Optional[datetime] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_returns: List[float] = []

        # Results
        self.results: Optional[Dict] = None

        logger.info(
            f"PortfolioBacktestEngine initialized: '{portfolio_name}' "
            f"with {len(strategies)} strategies, ${initial_cash:,.0f} capital"
        )

    def run(
        self,
        start_date: datetime,
        end_date: datetime,
        initial_allocation_method: str = 'equal_weight'
    ):
        """
        Run multi-strategy portfolio backtest

        Args:
            start_date: Backtest start date
            end_date: Backtest end date
            initial_allocation_method: 'equal_weight' or 'risk_parity'
        """
        self.start_date = start_date
        self.end_date = end_date

        logger.info(f"=" * 80)
        logger.info(f"Starting portfolio backtest: {self.portfolio_name}")
        logger.info(f"Period: {start_date.date()} to {end_date.date()}")
        logger.info(f"Initial allocation: {initial_allocation_method}")
        logger.info(f"=" * 80)

        # Initialize all strategies
        self._initialize_strategies(start_date, initial_allocation_method)

        # Get all trading dates
        all_trading_dates = self._get_trading_dates(start_date, end_date)

        logger.info(f"Processing {len(all_trading_dates)} trading days...")

        # Main backtest loop
        for current_date in all_trading_dates:
            self._process_trading_day(current_date)

        # Close all open positions at end
        self._close_all_positions(all_trading_dates[-1])

        logger.info("Portfolio backtest execution completed")

        # Calculate metrics
        self.calculate_metrics()
        self.print_results()
        self.save_results()

        return self.results

    def _initialize_strategies(self, start_date: datetime, allocation_method: str):
        """
        Initialize all strategies with capital allocation

        Args:
            start_date: Backtest start date
            allocation_method: Allocation method
        """
        logger.info(f"\nInitializing {len(self.strategies)} strategies...")

        # Initial capital allocation
        if allocation_method == 'equal_weight':
            weights = self._allocate_equal_weight()
        elif allocation_method == 'risk_parity':
            weights = self._allocate_risk_parity()
        else:
            raise ValueError(f"Unknown allocation method: {allocation_method}")

        # Initialize each strategy
        for strategy in self.strategies:
            allocated_capital = self.initial_cash * weights.get(strategy.name, 0.0)

            logger.info(f"  [{strategy.name}] Allocation: ${allocated_capital:,.0f} ({weights[strategy.name]:.1%})")

            strategy.initialize(start_date, allocated_capital)
            strategy.mark_rebalanced(start_date, weights[strategy.name], allocated_capital)

            # Initialize position tracking
            self.strategy_positions[strategy.name] = {}

    def _get_trading_dates(self, start_date: datetime, end_date: datetime) -> List[date]:
        """
        Get all trading dates in the backtest period

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of trading dates
        """
        # Fetch SPY data to get trading calendar
        spy_data = self.get_historical_data('SPY', start_date, end_date, '1d')

        if not spy_data:
            logger.error("Could not fetch trading calendar")
            return []

        trading_dates = [datetime.fromtimestamp(bar['t'] / 1000).date() for bar in spy_data]
        return sorted(set(trading_dates))

    def _process_trading_day(self, current_date: date):
        """
        Process a single trading day

        Args:
            current_date: Trading date
        """
        current_datetime = datetime.combine(current_date, datetime.min.time())

        # Check if we should rebalance capital
        self._check_and_rebalance(current_datetime)

        # Fetch daily bars for all required symbols
        daily_bars = self._fetch_daily_bars(current_date)

        # Process daily bars for all strategies
        for strategy in self.strategies:
            signal = strategy.on_bar(current_datetime, daily_bars)

            if signal:
                self._execute_trade(signal, strategy, current_datetime)

        # Process intraday data for strategies that need it
        self._process_intraday_strategies(current_date, daily_bars)

        # Record equity for the day
        self._record_equity(current_datetime, daily_bars)

    def _fetch_daily_bars(self, current_date: date) -> Dict[str, BarData]:
        """
        Fetch daily bars for all required symbols

        Args:
            current_date: Trading date

        Returns:
            Dictionary of {symbol: BarData}
        """
        # Get all unique symbols needed
        all_symbols = set()
        for strategy in self.strategies:
            all_symbols.update(strategy.get_required_symbols())

        # Fetch data for each symbol
        bars = {}
        start_dt = datetime.combine(current_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)

        for symbol in all_symbols:
            data = self.get_historical_data(symbol, start_dt, end_dt, '1d')

            if data:
                bar = data[0]  # Should only be one bar for the day
                bars[symbol] = BarData(
                    timestamp=datetime.fromtimestamp(bar['t'] / 1000),
                    open=float(bar['o']),
                    high=float(bar['h']),
                    low=float(bar['l']),
                    close=float(bar['c']),
                    volume=int(bar['v'])
                )

        return bars

    def _process_intraday_strategies(self, current_date: date, daily_bars: Dict[str, BarData]):
        """
        Process intraday data for strategies that require it

        Args:
            current_date: Trading date
            daily_bars: Daily bars (for fallback)
        """
        # Find strategies that need intraday data
        intraday_strategies = [s for s in self.strategies if s.requires_intraday_data()]

        if not intraday_strategies:
            return

        # Get unique symbols needed for intraday
        intraday_symbols = set()
        for strategy in intraday_strategies:
            intraday_symbols.update(strategy.get_required_symbols())

        # Fetch minute bars for each symbol
        minute_data_by_symbol = {}
        for symbol in intraday_symbols:
            minute_bars = self.intraday_manager.get_minute_bars(symbol, current_date)
            if minute_bars:
                minute_data_by_symbol[symbol] = minute_bars

        if not minute_data_by_symbol:
            logger.warning(f"No intraday data available for {current_date}")
            return

        # Get all unique timestamps across all symbols
        all_timestamps = set()
        for bars in minute_data_by_symbol.values():
            for bar in bars:
                all_timestamps.add(bar['t'])

        all_timestamps = sorted(all_timestamps)

        # Process each minute bar
        for timestamp_ms in all_timestamps:
            current_datetime = datetime.fromtimestamp(timestamp_ms / 1000)

            # Build BarData dict for this timestamp
            minute_bars = {}
            for symbol, bars in minute_data_by_symbol.items():
                # Find bar for this timestamp
                matching_bars = [b for b in bars if b['t'] == timestamp_ms]
                if matching_bars:
                    bar = matching_bars[0]
                    minute_bars[symbol] = BarData(
                        timestamp=current_datetime,
                        open=float(bar['o']),
                        high=float(bar['h']),
                        low=float(bar['l']),
                        close=float(bar['c']),
                        volume=int(bar['v'])
                    )

            # Process minute bar for each intraday strategy
            for strategy in intraday_strategies:
                signal = strategy.on_minute_bar(current_datetime, minute_bars)

                if signal:
                    self._execute_trade(signal, strategy, current_datetime)

    def _execute_trade(self, signal: Dict, strategy: BaseStrategy, current_datetime: datetime):
        """
        Execute a trade signal

        Args:
            signal: Trade signal dictionary
            strategy: Strategy that generated the signal
            current_datetime: Current datetime
        """
        action = signal.get('action')
        symbol = signal.get('symbol')
        quantity = signal.get('quantity', 0)
        price = signal.get('price', 0)
        reason = signal.get('reason', '')

        if action == 'BUY':
            self._execute_buy(current_datetime, strategy, symbol, price, quantity, reason)
        elif action == 'SELL':
            self._execute_sell(current_datetime, strategy, symbol, price, quantity, reason)
        elif action in ['SELL_OPTION', 'BUY_OPTION', 'ASSIGNED_PUT', 'ASSIGNED_CALL', 'EXPIRED']:
            # Option-specific actions
            self._execute_option_trade(current_datetime, strategy, signal)
        else:
            logger.warning(f"Unknown action: {action}")

    def _execute_buy(
        self,
        date: datetime,
        strategy: BaseStrategy,
        symbol: str,
        price: float,
        quantity: int,
        reason: str
    ):
        """Execute a buy order"""
        value = quantity * price

        # Check if we have enough cash
        if self.portfolio.cash >= value:
            # Proceed with the requested quantity
            actual_quantity = quantity
            actual_value = value
        elif self.portfolio.cash >= price:
            # Adjust quantity to what we can afford
            actual_quantity = int(self.portfolio.cash / price)
            actual_value = actual_quantity * price

            logger.warning(
                f"{date.date()} [{strategy.name}] Adjusted position: "
                f"Requested {quantity} shares (${value:.2f}), "
                f"but only have ${self.portfolio.cash:.2f}. "
                f"Buying {actual_quantity} shares instead (${actual_value:.2f})"
            )
        else:
            # Can't even afford 1 share
            logger.warning(
                f"{date.date()} [{strategy.name}] Insufficient cash for BUY: "
                f"Need ${value:.2f}, have ${self.portfolio.cash:.2f}. "
                f"Cannot afford even 1 share @ ${price:.2f}"
            )
            return

        # Execute the trade
        self.portfolio.cash -= actual_value
        self.portfolio.positions[symbol] = self.portfolio.positions.get(symbol, 0) + actual_quantity
        self.portfolio.invested = True

        # Track strategy position
        self.strategy_positions[strategy.name][symbol] = actual_quantity

        # Create trade record
        trade = Trade(date, symbol, 'BUY', actual_quantity, price, actual_value)
        trade.strategy = strategy.name
        trade.reason = reason
        self.trades.append(trade)

        # Update strategy state
        strategy.update_state(
            is_in_position=True,
            position_size=actual_quantity,
            entry_price=price,
            entry_date=date
        )

        logger.info(
            f"{date.date()} [{strategy.name}] BUY {actual_quantity} {symbol} "
            f"@ ${price:.2f} = ${actual_value:.2f} ({reason})"
        )

    def _execute_sell(
        self,
        date: datetime,
        strategy: BaseStrategy,
        symbol: str,
        price: float,
        quantity: int,
        reason: str
    ):
        """Execute a sell order"""
        if strategy.name not in self.strategy_positions:
            logger.warning(f"[{strategy.name}] No positions to sell")
            return

        if symbol not in self.strategy_positions[strategy.name]:
            logger.warning(f"[{strategy.name}] No position in {symbol}")
            return

        shares = self.strategy_positions[strategy.name][symbol]
        actual_quantity = min(quantity, shares)
        proceeds = actual_quantity * price

        # Update portfolio
        self.portfolio.positions[symbol] -= actual_quantity
        if self.portfolio.positions[symbol] == 0:
            del self.portfolio.positions[symbol]
        self.portfolio.cash += proceeds
        self.portfolio.invested = len(self.portfolio.positions) > 0

        # Update strategy position
        if actual_quantity == shares:
            del self.strategy_positions[strategy.name][symbol]
        else:
            self.strategy_positions[strategy.name][symbol] -= actual_quantity

        # Create trade record
        trade = Trade(date, symbol, 'SELL', actual_quantity, price, proceeds)
        trade.strategy = strategy.name
        trade.reason = reason

        # Calculate P&L
        for t in reversed(self.trades):
            if (t.symbol == symbol and t.action == 'BUY' and
                hasattr(t, 'strategy') and t.strategy == strategy.name):
                cost_basis = t.price * actual_quantity
                trade.pnl = proceeds - cost_basis
                trade.pnl_percent = (trade.pnl / cost_basis) * 100 if cost_basis > 0 else 0
                break

        self.trades.append(trade)

        # Update strategy state
        is_still_in_position = len(self.strategy_positions.get(strategy.name, {})) > 0
        strategy.update_state(
            is_in_position=is_still_in_position,
            position_size=self.strategy_positions.get(strategy.name, {}).get(symbol, 0)
        )

        logger.info(
            f"{date.date()} [{strategy.name}] SELL {actual_quantity} {symbol} "
            f"@ ${price:.2f} = ${proceeds:.2f} "
            f"(P&L: ${trade.pnl:.2f}, {trade.pnl_percent:.2f}%) ({reason})"
        )

    def _execute_option_trade(self, date: datetime, strategy: BaseStrategy, signal: Dict):
        """
        Execute option trade (simplified simulation)

        Args:
            date: Trade date
            strategy: Strategy instance
            signal: Trade signal with option details
        """
        action = signal['action']

        if action == 'SELL_OPTION':
            # Selling option - collect premium
            premium = signal.get('premium', 0)
            contracts = signal.get('contracts', 0)
            total_premium = premium * contracts * 100  # 100 shares per contract

            self.portfolio.cash += total_premium

            trade = Trade(date, signal['symbol'], 'SELL_OPTION', contracts, premium, total_premium)
            trade.strategy = strategy.name
            trade.reason = signal.get('reason', '')
            self.trades.append(trade)

            strategy.update_state(is_in_position=True, position_size=contracts)

            logger.info(
                f"{date.date()} [{strategy.name}] SELL {contracts} {signal['option_type']} "
                f"${signal['strike']:.2f} for ${total_premium:.2f} premium"
            )

        elif action == 'BUY_OPTION':
            # Buying back option
            premium = signal.get('premium', 0)
            contracts = signal.get('contracts', 0)
            total_cost = premium * contracts * 100

            self.portfolio.cash -= total_cost

            trade = Trade(date, signal['symbol'], 'BUY_OPTION', contracts, premium, total_cost)
            trade.strategy = strategy.name
            trade.reason = signal.get('reason', '')

            # Calculate P&L from option trade
            for t in reversed(self.trades):
                if (t.symbol == signal['symbol'] and t.action == 'SELL_OPTION' and
                    hasattr(t, 'strategy') and t.strategy == strategy.name):
                    trade.pnl = t.value - total_cost
                    trade.pnl_percent = (trade.pnl / t.value) * 100 if t.value > 0 else 0
                    break

            self.trades.append(trade)
            strategy.update_state(is_in_position=False, position_size=0)

            logger.info(
                f"{date.date()} [{strategy.name}] BUY {contracts} option for ${total_cost:.2f} "
                f"(P&L: ${trade.pnl:.2f}, {trade.pnl_percent:.2f}%)"
            )

        elif action in ['ASSIGNED_PUT', 'ASSIGNED_CALL', 'EXPIRED']:
            # Option assignment or expiration
            trade = Trade(date, signal['symbol'], action, 0, 0, 0)
            trade.strategy = strategy.name
            trade.reason = signal.get('reason', '')
            self.trades.append(trade)

            strategy.update_state(is_in_position=False, position_size=0)

            logger.info(f"{date.date()} [{strategy.name}] {action}: {signal.get('reason', '')}")

    def _check_and_rebalance(self, current_date: datetime):
        """
        Check if capital should be reallocated between strategies

        Args:
            current_date: Current date
        """
        # Identify strategies that can be rebalanced
        rebalanceable = [s for s in self.strategies if s.can_rebalance(current_date)]

        if not rebalanceable:
            return  # No strategies available for rebalancing

        # Calculate allocation scores for rebalanceable strategies
        scores = {}
        for strategy in rebalanceable:
            score = strategy.get_allocation_score(self.rebalance_lookback_days)
            scores[strategy.name] = max(0.0, score)

        total_score = sum(scores.values())

        if total_score == 0:
            # Equal weight if no performance data
            for strategy in rebalanceable:
                scores[strategy.name] = 1.0
            total_score = len(rebalanceable)

        # Calculate new weights (only for rebalanceable strategies)
        # Calculate how much capital is locked in non-rebalanceable strategies
        locked_capital = 0.0
        for strategy in self.strategies:
            if strategy not in rebalanceable:
                locked_capital += strategy.state.allocated_capital

        available_capital = self.portfolio.cash + locked_capital

        # Allocate available capital to rebalanceable strategies
        for strategy in rebalanceable:
            new_weight = scores[strategy.name] / total_score if total_score > 0 else 0
            new_allocation = available_capital * new_weight

            # Mark as rebalanced
            strategy.mark_rebalanced(current_date, new_weight, new_allocation)

            logger.debug(
                f"[{strategy.name}] Rebalanced: {new_weight:.2%} allocation, "
                f"${new_allocation:,.0f} capital"
            )

    def _record_equity(self, date: datetime, daily_bars: Dict[str, BarData]):
        """
        Record portfolio equity for the day

        Args:
            date: Current date
            daily_bars: Daily bars for position valuation
        """
        total_equity = self.portfolio.cash

        # Add value of all positions
        for symbol, shares in self.portfolio.positions.items():
            if symbol in daily_bars:
                price = daily_bars[symbol].close
                total_equity += shares * price

        self.equity_curve.append((date, total_equity))

        # Calculate daily return
        if len(self.equity_curve) > 1:
            prev_equity = self.equity_curve[-2][1]
            if prev_equity > 0:
                daily_return = (total_equity - prev_equity) / prev_equity
                self.daily_returns.append(daily_return)

        # Record equity per strategy
        for strategy in self.strategies:
            strategy_equity = strategy.state.allocated_capital

            # Add value of strategy positions
            if strategy.name in self.strategy_positions:
                for symbol, shares in self.strategy_positions[strategy.name].items():
                    if symbol in daily_bars:
                        price = daily_bars[symbol].close
                        strategy_equity += shares * price - strategy.state.allocated_capital

            strategy.record_equity(strategy_equity)

    def _close_all_positions(self, final_date: date):
        """
        Close all open positions at end of backtest

        Args:
            final_date: Final trading date
        """
        logger.info("\nClosing all open positions...")

        final_datetime = datetime.combine(final_date, datetime.min.time())

        # Fetch final prices
        final_bars = self._fetch_daily_bars(final_date)

        for strategy in self.strategies:
            if strategy.state.is_in_position:
                if strategy.name in self.strategy_positions:
                    for symbol, shares in list(self.strategy_positions[strategy.name].items()):
                        if symbol in final_bars:
                            price = final_bars[symbol].close
                            self._execute_sell(
                                final_datetime,
                                strategy,
                                symbol,
                                price,
                                shares,
                                "End of backtest"
                            )

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

        data = self.polygon_client.get_historical_data(symbol, start_date, end_date, timeframe)

        if self.use_cache and self.price_cache and data:
            self.price_cache.set(symbol, start_date, end_date, timeframe, data)

        return data if data else []

    def _allocate_equal_weight(self) -> Dict[str, float]:
        """Allocate capital equally across all strategies"""
        equal_weight = 1.0 / len(self.strategies)
        return {strategy.name: equal_weight for strategy in self.strategies}

    def _allocate_risk_parity(self) -> Dict[str, float]:
        """Allocate capital using risk parity (equal risk contribution)"""
        # For initial allocation, use equal weight
        # In live rebalancing, this would use historical volatility
        return self._allocate_equal_weight()

    def calculate_metrics(self) -> Dict:
        """Calculate comprehensive portfolio metrics"""
        if not self.equity_curve:
            logger.error("No equity data to calculate metrics")
            return {}

        final_value = self.equity_curve[-1][1]
        total_return = final_value - self.initial_cash
        total_return_pct = (total_return / self.initial_cash) * 100

        # Trade statistics
        winning_trades = [t for t in self.trades if t.action in ['SELL', 'BUY_OPTION'] and hasattr(t, 'pnl') and t.pnl and t.pnl > 0]
        losing_trades = [t for t in self.trades if t.action in ['SELL', 'BUY_OPTION'] and hasattr(t, 'pnl') and t.pnl and t.pnl < 0]
        total_trades = len(winning_trades) + len(losing_trades)

        num_wins = len(winning_trades)
        num_losses = len(losing_trades)
        win_rate = (num_wins / total_trades * 100) if total_trades > 0 else 0
        loss_rate = (num_losses / total_trades * 100) if total_trades > 0 else 0

        avg_win = np.mean([t.pnl_percent for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl_percent for t in losing_trades]) if losing_trades else 0

        # Expectancy
        expectancy = ((1 + (avg_win / 100)) ** (win_rate/100)) * ((1 - (abs(avg_loss)/ 100)) ** (loss_rate/100)) * 100 if total_trades > 0 else 0

        # CAGR
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
            kelly = (win_rate / (abs(avg_loss)/100)) - (loss_rate / (avg_win / 100))
        else:
            kelly = 0

        metrics = {
            'portfolio_name': self.portfolio_name,
            'num_strategies': len(self.strategies),
            'strategy_weights': {s.name: s.state.current_weight for s in self.strategies},
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

        print(f"\n{'STRATEGY WEIGHTS (FINAL)':-^80}")
        for name, weight in r['strategy_weights'].items():
            print(f"{name}: {weight:.2%}")

        print(f"\n{'PERFORMANCE METRICS':-^80}")
        print(f"Total Return: ${r['total_return']:,.2f} ({r['total_return_pct']:.2f}%)")
        print(f"CAGR: {r['cagr']:.2f}%")

        print(f"\n{'TRADE STATISTICS':-^80}")
        print(f"Total Trades: {r['total_trades']}")
        print(f"Winning Trades: {r['num_wins']}")
        print(f"Losing Trades: {r['num_losses']}")
        print(f"Win Rate: {r['win_rate']:.2f}%")
        print(f"Loss Rate: {r['loss_rate']:.2f}%")
        print(f"Average Win: {r['avg_win_pct']:.2f}%")
        print(f"Average Loss: {r['avg_loss_pct']:.2f}%")
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
        results_with_metadata['backtest_completed'] = datetime.now().isoformat()

        with open(filepath, 'w') as f:
            json.dump(results_with_metadata, f, indent=2)

        logger.info(f"Results saved to {filepath}")
        print(f"\nResults saved to: {filepath}")
