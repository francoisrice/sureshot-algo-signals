"""
Capital Allocation Logic for Multi-Strategy Portfolio

Handles dynamic reallocation of capital across strategies based on:
- Risk-adjusted performance (Sharpe ratio)
- Recent returns
- Maximum drawdown
- Per-strategy position locks
"""

import logging
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import numpy as np

from .models import PortfolioState, Order, AllocationHistory

logger = logging.getLogger(__name__)


class CapitalAllocator:
    """
    Manages dynamic capital allocation across multiple strategies
    """

    def __init__(
        self,
        lookback_days: int = 90,
        min_allocation_pct: float = 0.10,  # Minimum 10% per strategy
        max_allocation_pct: float = 0.50   # Maximum 50% per strategy
    ):
        """
        Initialize capital allocator

        Args:
            lookback_days: Days to look back for performance calculation
            min_allocation_pct: Minimum allocation percentage per strategy
            max_allocation_pct: Maximum allocation percentage per strategy
        """
        self.lookback_days = lookback_days
        self.min_allocation_pct = min_allocation_pct
        self.max_allocation_pct = max_allocation_pct

    def calculate_strategy_performance(
        self,
        db: Session,
        strategy_name: str,
        lookback_days: int = None
    ) -> Dict[str, float]:
        """
        Calculate risk-adjusted performance metrics for a strategy

        Args:
            db: Database session
            strategy_name: Name of the strategy
            lookback_days: Optional override for lookback period

        Returns:
            Dict with returns, sharpe, drawdown, score
        """
        lookback = lookback_days or self.lookback_days
        cutoff_date = datetime.utcnow() - timedelta(days=lookback)

        # Get recent orders for this strategy
        orders = db.query(Order).filter(
            Order.strategy_name == strategy_name,
            Order.timestamp >= cutoff_date,
            Order.status == "EXECUTED"
        ).order_by(Order.timestamp).all()

        if len(orders) < 2:
            # Not enough data, return neutral score
            return {
                'returns': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'score': 1.0  # Neutral score
            }

        # Calculate equity curve from orders
        equity = []
        current_equity = 0

        for order in orders:
            if order.order_type == "BUY":
                current_equity -= order.order_value
            else:  # SELL
                current_equity += order.order_value
            equity.append(current_equity)

        if len(equity) == 0:
            return {
                'returns': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'score': 1.0
            }

        equity_array = np.array(equity)

        # Calculate returns
        total_return = equity_array[-1] if len(equity_array) > 0 else 0.0
        returns_pct = (total_return / abs(equity_array[0])) * 100 if equity_array[0] != 0 else 0.0

        # Calculate daily returns for Sharpe
        daily_returns = np.diff(equity_array) / np.abs(equity_array[:-1])
        daily_returns = daily_returns[np.isfinite(daily_returns)]  # Remove inf/nan

        if len(daily_returns) > 1:
            sharpe_ratio = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252) if np.std(daily_returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Calculate maximum drawdown
        running_max = np.maximum.accumulate(equity_array)
        drawdown = (equity_array - running_max) / running_max
        max_drawdown = abs(np.min(drawdown)) * 100 if len(drawdown) > 0 else 0.0

        # Calculate composite score
        # Higher Sharpe = better, Higher returns = better, Lower drawdown = better
        score = (
            (1.0 + sharpe_ratio) *  # Sharpe contribution
            (1.0 + returns_pct / 100.0) *  # Returns contribution
            (1.0 / (1.0 + max_drawdown / 100.0))  # Drawdown penalty
        )

        score = max(0.0, score)  # Ensure non-negative

        return {
            'returns': total_return,
            'returns_pct': returns_pct,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'score': score
        }

    def allocate_capital(
        self,
        db: Session,
        total_capital: float,
        strategies: List[str],
        method: str = "risk_adjusted"
    ) -> Dict[str, float]:
        """
        Allocate capital across strategies

        Args:
            db: Database session
            total_capital: Total capital to allocate
            strategies: List of strategy names
            method: Allocation method - "equal_weight" or "risk_adjusted"

        Returns:
            Dict mapping strategy names to allocated capital
        """
        if method == "equal_weight":
            allocation_per_strategy = total_capital / len(strategies)
            return {strategy: allocation_per_strategy for strategy in strategies}

        elif method == "risk_adjusted":
            # Get performance scores for each strategy
            scores = {}
            for strategy in strategies:
                # Check if strategy has locked position
                state = db.query(PortfolioState).filter(
                    PortfolioState.strategy_name == strategy
                ).first()

                if state and state.position_locked:
                    # Strategy locked, keep current allocation
                    scores[strategy] = state.allocated_capital
                    logger.info(f"Strategy {strategy} is locked with position, keeping allocation ${state.allocated_capital:,.2f}")
                else:
                    # Strategy available for reallocation
                    perf = self.calculate_strategy_performance(db, strategy)
                    scores[strategy] = perf['score']
                    logger.info(f"Strategy {strategy} score: {perf['score']:.3f} (Sharpe: {perf['sharpe_ratio']:.2f}, Return: {perf['returns_pct']:.1f}%)")

            # Calculate total available capital (excluding locked strategies)
            locked_capital = sum(
                amount for strategy, amount in scores.items()
                if isinstance(amount, (int, float)) and amount > 0
            )
            available_capital = total_capital - locked_capital

            # Get unlocked strategies
            unlocked_strategies = [
                s for s in strategies
                if not isinstance(scores[s], (int, float)) or scores[s] == 0
            ]

            if len(unlocked_strategies) == 0:
                # All strategies locked, return current allocations
                return scores

            # Allocate available capital based on scores
            unlocked_scores = {s: scores[s] for s in unlocked_strategies}
            total_score = sum(unlocked_scores.values())

            allocations = {}

            if total_score > 0:
                for strategy in strategies:
                    if strategy in unlocked_strategies:
                        # Calculate proportional allocation
                        allocation_pct = unlocked_scores[strategy] / total_score

                        # Apply min/max constraints
                        allocation_pct = max(self.min_allocation_pct, min(self.max_allocation_pct, allocation_pct))

                        allocations[strategy] = available_capital * allocation_pct
                    else:
                        # Keep locked allocation
                        allocations[strategy] = scores[strategy]
            else:
                # No valid scores, equal weight for unlocked strategies
                allocation_per_strategy = available_capital / len(unlocked_strategies)
                for strategy in strategies:
                    if strategy in unlocked_strategies:
                        allocations[strategy] = allocation_per_strategy
                    else:
                        allocations[strategy] = scores[strategy]

            logger.info(f"Capital allocation: {allocations}")
            return allocations

        else:
            raise ValueError(f"Unknown allocation method: {method}")

    def rebalance_portfolio(
        self,
        db: Session,
        total_capital: float,
        strategies: List[str],
        method: str = "risk_adjusted"
    ) -> Dict[str, Dict[str, float]]:
        """
        Rebalance portfolio allocations and update database

        Args:
            db: Database session
            total_capital: Total capital available
            strategies: List of strategy names
            method: Allocation method

        Returns:
            Dict with allocation details per strategy
        """
        allocations = self.allocate_capital(db, total_capital, strategies, method)

        # Update portfolio states
        allocation_details = {}
        for strategy, allocated in allocations.items():
            state = db.query(PortfolioState).filter(
                PortfolioState.strategy_name == strategy
            ).first()

            if state:
                old_allocation = state.allocated_capital
                state.allocated_capital = allocated
                state.last_updated = datetime.utcnow()
                db.commit()

                allocation_details[strategy] = {
                    'allocated': allocated,
                    'previous': old_allocation,
                    'change': allocated - old_allocation,
                    'locked': state.position_locked
                }
            else:
                logger.warning(f"No portfolio state found for strategy: {strategy}")

        # Record allocation history
        history = AllocationHistory(
            timestamp=datetime.utcnow(),
            total_capital=total_capital,
            allocations=allocation_details,
            rebalance_reason=f"Scheduled rebalance using {method}"
        )
        db.add(history)
        db.commit()

        logger.info(f"Portfolio rebalanced: {allocation_details}")
        return allocation_details
