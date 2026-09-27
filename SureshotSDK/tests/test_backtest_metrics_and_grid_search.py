"""
Unit tests for fixed backtest metrics (Sortino, Max Drawdown, Kelly, Trade Matching)
and GridSearch optimization.
"""

import json
import pytest
import numpy as np
from datetime import datetime

from SureshotSDK.BacktestEngine import (
    BacktestEngine,
    MAX_RISK_ADJUSTED_RATIO,
    geometric_expectancy_pct,
)
from SureshotSDK.optimization import GridSearch


def test_sortino_ratio_downside_deviation():
    engine = BacktestEngine(strategy_name="TestStrategy", initial_cash=100000)
    engine.daily_returns = [0.01, -0.01, 0.02, -0.02, 0.01]

    # Calculate expected Sortino:
    # returns: 0.01, -0.01, 0.02, -0.02, 0.01 -> mean = 0.002
    # downside diffs: 0.0, -0.01, 0.0, -0.02, 0.0
    # squared: 0.0, 0.0001, 0.0, 0.0004, 0.0 -> sum = 0.0005, mean = 0.0001
    # downside_std = sqrt(0.0001) = 0.01
    # Sortino = (0.002 / 0.01) * sqrt(252) = 0.2 * 15.874507866387544 = 3.1749015732775087
    metrics = engine.calculate_metrics()
    expectedSortino = (0.002 / 0.01) * np.sqrt(252)
    assert abs(metrics['sortino_ratio'] - expectedSortino) < 1e-4


def test_max_drawdown_calculation():
    engine = BacktestEngine(strategy_name="TestStrategy", initial_cash=100000)
    engine.equity_curve = [
        (datetime(2026, 1, 1), 100000.0),
        (datetime(2026, 1, 2), 120000.0),  # peak = 120,000
        (datetime(2026, 1, 3), 108000.0),  # dd = (120,000 - 108,000) / 120,000 = 10%
        (datetime(2026, 1, 4), 114000.0),  # dd = 5%
        (datetime(2026, 1, 5), 102000.0),  # dd = (120,000 - 102,000) / 120,000 = 15%
        (datetime(2026, 1, 6), 130000.0),  # new peak = 130,000
        (datetime(2026, 1, 7), 123500.0),  # dd = (130,000 - 123,500) / 130,000 = 5%
    ]
    metrics = engine.calculate_metrics()
    assert abs(metrics['max_drawdown'] - 15.0) < 1e-4


def test_sortino_capped_when_no_downside_returns():
    """No losing day makes Sortino unbounded; it must stay finite and JSON-serialisable."""
    engine = BacktestEngine(strategy_name="TestStrategy", initial_cash=100000)
    engine.daily_returns = [0.01, 0.02, 0.005]

    metrics = engine.calculate_metrics()

    assert metrics['sortino_ratio'] == MAX_RISK_ADJUSTED_RATIO
    assert "Infinity" not in json.dumps(metrics)


def test_drawdown_measured_from_initial_cash():
    """A curve that never recovers past its opening mark still draws down from initial capital."""
    engine = BacktestEngine(strategy_name="TestStrategy", initial_cash=100000)
    engine.equity_curve = [
        (datetime(2026, 1, 2), 90000.0),
        (datetime(2026, 1, 3), 80000.0),
    ]

    metrics = engine.calculate_metrics()
    assert abs(metrics['max_drawdown'] - 20.0) < 1e-4


def test_metrics_are_plain_floats():
    engine = BacktestEngine(strategy_name="TestStrategy", initial_cash=100000)
    engine.daily_returns = [0.01, -0.01, 0.02]
    engine.equity_curve = [(datetime(2026, 1, 2), 101000.0), (datetime(2026, 1, 3), 99000.0)]

    metrics = engine.calculate_metrics()
    for key in ('sharpe_ratio', 'sortino_ratio', 'max_drawdown', 'kelly_criterion'):
        assert type(metrics[key]) is float, f"{key} is {type(metrics[key])}"


def test_geometric_expectancy_penalises_volatility_drag():
    """+50%/-40% alternating averages to +5% arithmetically but compounds to a loss."""
    assert abs(geometric_expectancy_pct([50, -40, 50, -40, 50, -40]) - (-5.13)) < 0.01


def test_geometric_expectancy_floors_at_total_loss():
    assert geometric_expectancy_pct([20, -100, 30]) == -100.0
    assert geometric_expectancy_pct([20, -120, 30]) == -100.0
    assert geometric_expectancy_pct([]) == 0.0


def test_grid_search_generation_and_optimization():
    gridSearch = GridSearch()
    paramRanges = {
        "stop_loss": (0.05, 0.20, 0.05),
        "target": (1.0, 2.0, 1.0)
    }
    grid = gridSearch.generate_grid(paramRanges)
    # stop_loss: 0.05, 0.10, 0.15, 0.20 (4)
    # target: 1.0, 2.0 (2)
    # total points = 4 * 2 = 8
    assert len(grid) == 8

    def evaluate(params):
        sl = params['stop_loss']
        tgt = params['target']
        score = -(sl - 0.10) ** 2 - (tgt - 2.0) ** 2
        return {'score': score, 'total_return': score}, score

    bestParams, bestObj, bestMetrics = gridSearch.optimize(
        initial_params={'stop_loss': 0.05, 'target': 1.0},
        param_ranges=paramRanges,
        evaluate_fn=evaluate
    )
    assert abs(bestParams['stop_loss'] - 0.10) < 1e-4
    assert abs(bestParams['target'] - 2.0) < 1e-4
    assert abs(bestObj - 0.0) < 1e-4
    assert len(gridSearch.all_results) == 8
