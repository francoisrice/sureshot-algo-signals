"""
Grid Search Optimization

Performs exhaustive grid search optimization across defined parameter ranges.
"""

from itertools import product
from typing import Dict, List, Tuple, Callable, Any, Optional
import requests


class GridSearch:
    """
    Exhaustive Grid Search optimizer.
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        max_iterations: Optional[int] = None
    ):
        self.api_url = api_url
        self.max_iterations = max_iterations
        self.all_results: List[Dict[str, Any]] = []

        self.on_iteration: Optional[Callable[[int, Dict, float, Dict], None]] = None
        self.on_gradient_step: Optional[Callable] = None

    def clear_orders(self):
        try:
            requests.delete(f"{self.api_url}/orders/clear", timeout=10)
        except Exception:
            pass

    def generate_grid(
        self,
        param_ranges: Dict[str, Tuple[float, float, float]]
    ) -> List[Dict[str, float]]:
        paramNames = list(param_ranges.keys())
        paramValueLists = []

        for name in paramNames:
            minVal, maxVal, step = param_ranges[name]
            if step <= 0 or minVal > maxVal:
                paramValueLists.append([minVal])
                continue

            numSteps = int(round((maxVal - minVal) / step)) + 1
            vals = [round(minVal + i * step, 6) for i in range(numSteps)]
            vals = [v for v in vals if v <= maxVal + 1e-9]
            if not vals:
                vals = [minVal]
            paramValueLists.append(vals)

        combinations = list(product(*paramValueLists))
        grid = [dict(zip(paramNames, combo)) for combo in combinations]

        if self.max_iterations and len(grid) > self.max_iterations:
            grid = grid[:self.max_iterations]

        return grid

    def optimize(
        self,
        initial_params: Dict[str, float],
        param_ranges: Dict[str, Tuple[float, float, float]],
        evaluate_fn: Callable[[Dict[str, float]], Tuple[Dict, float]]
    ) -> Tuple[Dict[str, float], float, Dict]:
        grid = self.generate_grid(param_ranges)
        self.all_results = []

        globalBestObjective = float('-inf')
        globalBestParams = initial_params.copy() if initial_params else {}
        globalBestMetrics = {}

        for iteration, params in enumerate(grid):
            metrics, objective = evaluate_fn(params)
            self.clear_orders()

            resultEntry = {
                'iteration': iteration,
                'parameters': params,
                'objective_value': objective,
                'metrics': metrics
            }
            self.all_results.append(resultEntry)

            if self.on_iteration:
                self.on_iteration(iteration, params, objective, metrics)

            if not metrics:
                continue  # failed backtest: never let its placeholder objective win

            if objective > globalBestObjective:
                globalBestObjective = objective
                globalBestParams = params.copy()
                globalBestMetrics = metrics.copy() if isinstance(metrics, dict) else metrics

        return globalBestParams, globalBestObjective, globalBestMetrics
