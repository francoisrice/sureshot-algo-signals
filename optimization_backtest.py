"""
Optimization Backtest Script

Performs gradient descent optimization across strategy parameters.
Parameters to optimize are prefixed with OPTIMIZATION_ in the strategy file.
"""

import os
import re
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Callable, Any

from SureshotSDK.optimization.multipoint_hill_climbing import MultipointHillClimbing

# ============================================================================
# OPTIMIZATION CONFIGURATION
# ============================================================================

# Strategy to optimize
PORTFOLIO = "portfolio_multi_strategy"
STRATEGY = "IncredibleLeverage_SPXL"
STRATEGY_FILE = f"{PORTFOLIO}/{STRATEGY}/main.py"

# Parameter ranges: (min, max, step)
# These must match OPTIMIZATION_ prefixed variables in the strategy file
OPTIMIZATION_MAX_MID_MONTH_LOSS = (0.01, 1.0, 0.01)

# Gradient descent settings
PORTFOLIO_API_URL = "http://localhost:8000"
MAX_ITERATIONS = 1000
STEP_REDUCTION_FACTOR = 0.5
MIN_STEP_SIZE = 0.01  # Stop if objective change < this
NUM_STARTING_POINTS = 4  # Number of starting points for multipoint search

# Results output files
RESULTS_DIR = "optimization_results"
RESULTS_JSON = f"{RESULTS_DIR}/optimization_results.json"
RESULTS_TXT = f"{RESULTS_DIR}/optimization_log.txt"


# ============================================================================
# OBJECTIVE FUNCTION
# ============================================================================

def default_objective(metrics: Dict) -> float:
    """
    Default objective function: Sortino * CAGR * Kelly

    Args:
        metrics: Dictionary of backtest metrics

    Returns:
        Objective value to maximize
    """
    sortino = metrics.get('sortino_ratio', 0)
    cagr = metrics.get('cagr', 0)
    kelly = metrics.get('kelly_criterion', 0)

    # Handle edge cases
    if sortino == float('inf'):
        sortino = 10  # Cap infinite sortino
    if sortino < 0:
        sortino = 0
    if kelly < 0:
        kelly = 0

    return sortino * cagr * kelly


# Set the objective function (can be overridden)
OBJECTIVE_FUNCTION: Callable[[Dict], float] = default_objective


# ============================================================================
# RESULTS FILE HANDLING
# ============================================================================

class ResultsLogger:
    """Handles logging optimization results to JSON and TXT files"""

    def __init__(self, json_path: str, txt_path: str):
        self.json_path = json_path
        self.txt_path = txt_path
        self.results: List[Dict] = []

        # Ensure directory exists
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize/clear the text file with header
        with open(self.txt_path, 'w') as f:
            f.write(f"Optimization Log - Started {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n\n")

    def log_run(self, iteration: int, params: Dict, metrics: Dict, objective: float):
        """Log a single optimization run"""
        result = {
            'timestamp': datetime.now().isoformat(),
            'iteration': iteration,
            'parameters': params,
            'objective_value': objective,
            'metrics': {
                'sharpe_ratio': metrics.get('sharpe_ratio', 0),
                'sortino_ratio': metrics.get('sortino_ratio', 0),
                'cagr': metrics.get('cagr', 0),
                'kelly_criterion': metrics.get('kelly_criterion', 0),
                'total_return_pct': metrics.get('total_return_pct', 0),
                'max_drawdown': metrics.get('max_drawdown', 0),
                'win_rate': metrics.get('win_rate', 0),
                'total_trades': metrics.get('total_trades', 0),
            },
            'raw_metrics': metrics
        }
        self.results.append(result)

        # Append to text file
        params_str = ", ".join(f"{k}={v:.4f}" for k, v in params.items())
        with open(self.txt_path, 'a') as f:
            f.write(f"[{iteration:03d}] {params_str} | objective={objective:.6f}\n")

        # Save JSON (overwrite with complete results)
        self._save_json()

    def _save_json(self):
        """Save all results to JSON file"""
        with open(self.json_path, 'w') as f:
            json.dump(self.results, f, indent=2)

    def log_final_summary(self, best_params: Dict, best_objective: float, best_metrics: Dict):
        """Log final optimization summary"""
        with open(self.txt_path, 'a') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write("OPTIMIZATION COMPLETE\n")
            f.write("=" * 80 + "\n")
            f.write(f"Best objective: {best_objective:.6f}\n")
            f.write(f"Best parameters:\n")
            for k, v in best_params.items():
                f.write(f"  {k} = {v:.4f}\n")
            f.write(f"\nBest metrics:\n")
            f.write(f"  Sortino Ratio: {best_metrics.get('sortino_ratio', 0):.4f}\n")
            f.write(f"  CAGR: {best_metrics.get('cagr', 0):.4f}%\n")
            f.write(f"  Kelly Criterion: {best_metrics.get('kelly_criterion', 0):.4f}\n")
            f.write(f"  Total Return: {best_metrics.get('total_return_pct', 0):.2f}%\n")
            f.write(f"  Max Drawdown: {best_metrics.get('max_drawdown', 0):.2f}%\n")
            f.write(f"  Win Rate: {best_metrics.get('win_rate', 0):.2f}%\n")


# ============================================================================
# PARAMETER DISCOVERY AND MODIFICATION
# ============================================================================

def discover_optimization_params(strategy_file: str) -> Dict[str, float]:
    """
    Discover OPTIMIZATION_ prefixed parameters in strategy file

    Returns:
        Dictionary of parameter names to current values
    """
    params = {}
    pattern = r'^(OPTIMIZATION_\w+)\s*=\s*([\d.]+)'

    with open(strategy_file, 'r') as f:
        for line in f:
            match = re.match(pattern, line.strip())
            if match:
                param_name = match.group(1)
                param_value = float(match.group(2))
                params[param_name] = param_value

    return params


def get_param_ranges() -> Dict[str, Tuple[float, float, float]]:
    """
    Get parameter ranges defined in this file

    Returns:
        Dictionary of parameter names to (min, max, step) tuples
    """
    ranges = {}

    # Get all OPTIMIZATION_ variables from this module's globals
    for name, value in globals().items():
        if name.startswith('OPTIMIZATION_') and isinstance(value, tuple) and len(value) == 3:
            ranges[name] = value

    return ranges


def update_strategy_params(strategy_file: str, params: Dict[str, float]):
    """
    Update OPTIMIZATION_ parameters in strategy file

    Args:
        strategy_file: Path to strategy file
        params: Dictionary of parameter names to new values
    """
    with open(strategy_file, 'r') as f:
        content = f.read()

    for param_name, param_value in params.items():
        # Pattern to match the parameter assignment
        pattern = rf'^({param_name}\s*=\s*)[\d.]+(.*)$'
        replacement = rf'\g<1>{param_value}\2'
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    with open(strategy_file, 'w') as f:
        f.write(content)


def restore_strategy_params(strategy_file: str, original_params: Dict[str, float]):
    """Restore original parameter values"""
    update_strategy_params(strategy_file, original_params)


# ============================================================================
# BACKTEST EXECUTION
# ============================================================================

def run_backtest() -> Dict:
    """
    Run backtest.py and return metrics

    Returns:
        Dictionary of backtest metrics
    """
    # Run backtest.py as subprocess
    result = subprocess.run(
        ['.venv/bin/python', 'backtest.py'],
        capture_output=True,
        text=True,
        env={**os.environ, 'PYTHONPATH': '.'}
    )

    if result.returncode != 0:
        print(f"Backtest failed: {result.stderr}")
        return {}

    # Find the most recent results file
    results_dir = Path('backtest_results')
    if not results_dir.exists():
        print("No backtest_results directory found")
        return {}

    result_files = sorted(results_dir.glob(f'{STRATEGY}_*.json'), reverse=True)
    if not result_files:
        print("No result files found")
        return {}

    with open(result_files[0], 'r') as f:
        metrics = json.load(f)

    return metrics


# ============================================================================
# OPTIMIZATION WRAPPER
# ============================================================================

class BacktestOptimizer:
    """Wrapper that integrates backtest execution with optimization"""

    def __init__(self, strategy_file: str, logger: ResultsLogger):
        self.strategy_file = strategy_file
        self.logger = logger
        self.iteration = 0

    def evaluate(self, params: Dict[str, float]) -> Tuple[Dict, float]:
        """
        Evaluate parameters by running backtest

        Args:
            params: Parameter values to evaluate

        Returns:
            Tuple of (metrics, objective_value)
        """
        update_strategy_params(self.strategy_file, params)
        metrics = run_backtest()

        if not metrics:
            return {}, 0.0

        objective = OBJECTIVE_FUNCTION(metrics)

        # Log this run
        self.logger.log_run(self.iteration, params, metrics, objective)

        return metrics, objective

    def on_iteration(self, iteration: int, params: Dict, objective: float, metrics: Dict):
        """Callback for iteration logging"""
        self.iteration = iteration
        print(f"\n{'='*40}")
        print(f"Iteration {iteration + 1}")
        print(f"{'='*40}")
        print(f"Current params: {params}")
        print(f"Current objective: {objective:.6f}")
        print(f"  Sortino: {metrics.get('sortino_ratio', 0):.4f}")
        print(f"  CAGR: {metrics.get('cagr', 0):.4f}%")
        print(f"  Kelly: {metrics.get('kelly_criterion', 0):.4f}")

    def on_gradient_step(
        self, param_name: str, old_val: float, new_val: float,
        old_obj: float, new_obj: float, gradient: float
    ):
        """Callback for gradient step logging"""
        print(f"  {param_name}: {old_val:.4f} -> {new_val:.4f}, "
              f"objective: {old_obj:.4f} -> {new_obj:.4f}, "
              f"gradient: {gradient:.6f}")


def optimize():
    """Run gradient descent optimization"""
    print("=" * 80)
    print("OPTIMIZATION BACKTEST")
    print("=" * 80)
    print(f"Strategy: {PORTFOLIO}/{STRATEGY}")
    print(f"Min Step Size: {MIN_STEP_SIZE}")
    print(f"Step Reduction Factor: {STEP_REDUCTION_FACTOR}")
    print(f"Max Iterations: {MAX_ITERATIONS}")
    print(f"Starting Points: {NUM_STARTING_POINTS}")
    print("=" * 80)

    # Initialize results logger
    logger = ResultsLogger(RESULTS_JSON, RESULTS_TXT)

    # Discover parameters in strategy file
    original_params = discover_optimization_params(STRATEGY_FILE)
    print(f"\nDiscovered parameters: {original_params}")

    # Get parameter ranges
    param_ranges = get_param_ranges()
    print(f"Parameter ranges: {param_ranges}")

    # Validate that discovered params have ranges defined
    for param in original_params:
        if param not in param_ranges:
            print(f"WARNING: No range defined for {param}")

    # Initialize optimizer
    optimizer = MultipointHillClimbing(
        api_url=PORTFOLIO_API_URL,
        max_iterations=MAX_ITERATIONS,
        min_step_size=MIN_STEP_SIZE,
        step_reduction_factor=STEP_REDUCTION_FACTOR,
        num_points=NUM_STARTING_POINTS
    )

    # Create backtest evaluator
    evaluator = BacktestOptimizer(STRATEGY_FILE, logger)
    optimizer.on_iteration = evaluator.on_iteration
    optimizer.on_gradient_step = evaluator.on_gradient_step

    try:
        # Run optimization
        best_params, best_objective, best_metrics = optimizer.optimize(
            original_params,
            param_ranges,
            evaluator.evaluate
        )

    finally:
        # Restore original parameters
        print("\nRestoring original parameters...")
        restore_strategy_params(STRATEGY_FILE, original_params)

    # Log final summary
    logger.log_final_summary(best_params, best_objective, best_metrics)

    # Print final results
    print("\n" + "=" * 80)
    print("OPTIMIZATION COMPLETE")
    print("=" * 80)
    print(f"Best objective: {best_objective:.6f}")
    print(f"Best parameters: {best_params}")
    print(f"\nBest metrics:")
    print(f"  Sortino Ratio: {best_metrics.get('sortino_ratio', 0):.4f}")
    print(f"  CAGR: {best_metrics.get('cagr', 0):.4f}%")
    print(f"  Kelly Criterion: {best_metrics.get('kelly_criterion', 0):.4f}")
    print(f"  Total Return: {best_metrics.get('total_return_pct', 0):.2f}%")
    print(f"  Max Drawdown: {best_metrics.get('max_drawdown', 0):.2f}%")
    print(f"  Win Rate: {best_metrics.get('win_rate', 0):.2f}%")
    print(f"\nResults saved to:")
    print(f"  JSON: {RESULTS_JSON}")
    print(f"  Log:  {RESULTS_TXT}")
    print("=" * 80)

    return best_params, best_metrics


if __name__ == "__main__":
    optimize()
