"""
Multipoint Hill Climbing Optimization

Performs hill climbing optimization with support for multiple starting points
to avoid local optima.
"""

from itertools import product
import numpy as np
from typing import Dict, List, Tuple, Callable, Any, Optional


class MultipointHillClimbing:
    """
    Hill Climbing optimizer that supports multiple starting points.

    Args:
        will_add_later: Or maybe I never got to this?
    """

    def __init__(
        self,
        min_step_size: float = 0.01,
        step_reduction_factor: float = 0.5,
        max_iterations: int = 1000, # 50,
        num_points: int = 1,
        starting_position = "even-spaced" # "even-spaced" | "random"
    ):
        self.min_step_size = min_step_size
        self.step_reduction_factor = step_reduction_factor
        self.max_iterations = max_iterations
        self.num_points = num_points
        self.starting_position = starting_position

        # Callbacks
        self.on_iteration: Optional[Callable[[int, Dict, float, Dict], None]] = None
        self.on_gradient_step: Optional[Callable[[str, float, float, float, float, float], None]] = None

    def get_neighbors(self, 
                current_params: Dict[str, float], 
                param_ranges: Dict[str, Tuple[float, float, float]]
            ) -> List[Dict[str, float]]:
        
        neighbors = []
        for paramName, params in param_ranges.items():

            # Add nearest neighboar above
            neighbor = current_params.copy()
            currentParam = current_params[paramName] + params[2]
            currentParam = self.clip_param(currentParam, params[0], params[1])
            neighbor[paramName] = currentParam
            neighbors.append(neighbor)

            # Add nearest neighboar below
            neighbor = current_params.copy()
            currentParam = current_params[paramName] - params[2]
            currentParam = self.clip_param(currentParam, params[0], params[1])
            neighbor[paramName] = currentParam
            neighbors.append(neighbor)

        return neighbors

    def get_diagonal_neighbors(self, 
                current_params: Dict[str, float], 
                param_ranges: Dict[str, Tuple[float, float, float]]
            ) -> List[Dict[str, float]]:
        
        neighbors = []

        param_deltas = {}
        paramCount = len(param_ranges.items())
        for paramName, params in param_ranges.items():
            param_deltas[paramName] = [-params[2], 0, params[2]]

        all_deltas = product(*[param_deltas[paramName] for paramName, _ in param_ranges.items()])

        for delta in all_deltas:
            # Skip center point (all zeros)
            if all(d == 0 for d in delta):
                continue

            # neighbor = {}
            # for i, (paramName, params) in enumerate(param_ranges.items()):
            #     neighbor[paramName] = current_params[paramName] + delta[i]
            # currentParam = self.clip_param(currentParam, params[0], params[1])
            # neighbor[paramName] = currentParam
            # neighbors.append(neighbor)

        return neighbors

    def climb_step(
            self,
            current_params: Dict[str, float],
            param_ranges: Dict[str, Tuple[float, float, float]],
            evaluate_fn: Callable[[Dict[str, float]], Tuple[Dict, float]],
            history: Dict[Dict[str, float], Tuple[Dict, float]],
            current_metrics: Dict,
            current_objective: float,
        ) -> Tuple[Dict[str, float], float, Dict]:
        
        neighbors = self.get_neighbors(current_params, param_ranges)

        if not neighbors: # No valid neighbors, so reduce step size
            reducedStep = False
            for paramName, _ in param_ranges.items():
                min_val, max_val, step = param_ranges[paramName]
                if step > self.min_step_size:
                    reducedStep = True
                    step *= self.step_reduction_factor
                    param_ranges[paramName] = (min_val, max_val, step)
                    print(f"No valid neighbors. Reducing {paramName} step size to {str(step)} ...")
                
            if reducedStep:
                return self.climb_step(current_params, param_ranges, evaluate_fn, history, current_metrics, current_objective)
            else:
                print(f"Converged (no valid neighbors)")
                return current_params, current_metrics, current_objective, history

        bestParams = current_params.copy()
        bestMetrics = current_metrics.copy() if isinstance(current_metrics, dict) else current_metrics
        bestNeighborObjective = current_objective
        
        for neighbor_params in neighbors:
            metrics, objective = evaluate_fn(neighbor_params)
            history[str(neighbor_params)] = (metrics, objective)
            if not metrics:
                continue

            if objective > bestNeighborObjective:
                bestParams = neighbor_params
                bestNeighborObjective = objective
                bestMetrics = metrics

        if bestMetrics == current_metrics:
            # reduce step size
            reducedStep = False
            for paramName, _ in param_ranges.items():
                min_val, max_val, step = param_ranges[paramName]
                if step > self.min_step_size:
                    reducedStep = True
                    step *= self.step_reduction_factor
                    param_ranges[paramName] = (min_val, max_val, step)
                    print(f"Found local maximum. Reducing {paramName} step size to {str(step)} ...")

            if reducedStep:
                return self.climb_step(bestParams, param_ranges, evaluate_fn, history, current_metrics, current_objective)
            else:
                print(f"Converged at local maximum: {str(bestParams)}, {str(bestMetrics)}")

        return bestParams, param_ranges, bestMetrics, bestNeighborObjective, history

    def clip_param(self, value: float, min_val: float, max_val: float) -> float:
        """Clip parameter value to valid range"""
        return max(min_val, min(value, max_val))

    def generate_starting_points(
        self,
        initial_params: Dict[str, float],
        param_ranges: Dict[str, Tuple[float, float, float]]
    ) -> List[Dict[str, float]]:
        """
        Generate multiple starting points for multipoint optimization.

        Args:
            initial_params: Initial parameter values
            param_ranges: Parameter ranges (min, max, step)

        Returns:
            List of parameter dictionaries for each starting point
        """
        if self.num_points == 1:
            return [initial_params.copy()]


        if self.starting_position == "even-spaced":
            print(f"Using even spacing for starting points")
            if self.num_points != 2**len(initial_params.keys()):
                self.num_points = 2**len(initial_params.keys())
                print(f"Starting points must be 2^(# of parameters). Using {self.num_points} starting points.")

        starting_points = [initial_params.copy()]

        for i in range(1, self.num_points):
            point = {}
            for param_name, param_value in initial_params.items():
                if param_name in param_ranges:
                    min_val, max_val, step = param_ranges[param_name]

                    if self.starting_position == "even-spaced":
                        if param_name not in point:
                            value = (2*min_val+max_val)/3
                        else:
                            value = (min_val+2*max_val)/3
                        # Round to step size
                        value = round(value / step) * step
                        value = self.clip_param(value, min_val, max_val)
                        point[param_name] = value
                    else: 
                        # Generate random starting point within range if not specified 
                        random_value = np.random.uniform(min_val, max_val)
                        # Round to step size
                        random_value = round(random_value / step) * step
                        random_value = self.clip_param(random_value, min_val, max_val)
                        point[param_name] = random_value
                else:
                    point[param_name] = param_value
            starting_points.append(point)

        return starting_points

    def optimize_single_point(
        self,
        initial_params: Dict[str, float],
        param_ranges: Dict[str, Tuple[float, float, float]],
        evaluate_fn: Callable[[Dict[str, float]], Tuple[Dict, float]]
    ) -> Tuple[Dict[str, float], float, Dict]:
        """
        Run gradient descent from a single starting point.

        Args:
            initial_params: Starting parameter values
            param_ranges: Parameter ranges (min, max, step)
            evaluate_fn: Function that takes params and returns (metrics, objective)

        Returns:
            Tuple of (best_params, best_objective, best_metrics)
        """
        current_params = initial_params.copy()
        best_objective = float('-inf')
        best_params = current_params.copy()
        best_metrics = {}
        history = {}

        for iteration in range(self.max_iterations):
            # Evaluate current parameters
            # metrics, current_objective = evaluate_fn(current_params) # delete

            # delete
            # if not metrics:
            #     continue

            # Find the best neighbor
            # Return the params, metrics, and objective of the best neighbor
            
            # Evaluate current parameters
            newParams, newParamRanges, newBestMetrics, newBestObjective, history = self.climb_step(
                current_params, param_ranges, evaluate_fn, history, best_metrics, best_objective
            )

            # Callback for logging
            if self.on_iteration:
                self.on_iteration(iteration, current_params, newBestObjective, newBestMetrics)

            # Track best
            if newBestObjective > best_objective:
                best_objective = newBestObjective
                best_params = newParams.copy()
                best_metrics = newBestMetrics.copy() if isinstance(newBestMetrics, dict) else newBestMetrics

            if newParams == current_params:
                return best_params, best_objective, best_metrics
            else:
                current_params = newParams
                param_ranges = newParamRanges
                continue

        return best_params, best_objective, best_metrics

    def optimize(
        self,
        initial_params: Dict[str, float],
        param_ranges: Dict[str, Tuple[float, float, float]],
        evaluate_fn: Callable[[Dict[str, float]], Tuple[Dict, float]]
    ) -> Tuple[Dict[str, float], float, Dict]:
        """
        Run multipoint gradient descent optimization.

        Args:
            initial_params: Starting parameter values
            param_ranges: Parameter ranges (min, max, step)
            evaluate_fn: Function that takes params and returns (metrics, objective)

        Returns:
            Tuple of (best_params, best_objective, best_metrics)
        """
        starting_points = self.generate_starting_points(initial_params, param_ranges)

        global_best_objective = float('-inf')
        global_best_params = initial_params.copy()
        global_best_metrics = {}

        for _, start_params in enumerate(starting_points):
            best_params, best_objective, best_metrics = self.optimize_single_point(
                start_params, param_ranges, evaluate_fn
            )

            if best_objective > global_best_objective:
                global_best_objective = best_objective
                global_best_params = best_params
                global_best_metrics = best_metrics

        return global_best_params, global_best_objective, global_best_metrics


if __name__ == "__main__":
    # Example usage
    def mock_backtest(current_params: Dict[str, float]) -> Tuple[Dict, float]:
        """Dummy function - replace with actual backtest."""
        # Simple quadratic with optimum around SL=30, TP=90
        return {'x': current_params['x'], 'y': current_params['y']}, -(current_params['x'] * 100 - 30)**2 - (current_params['y'] * 100 - 90)**2 + 5000

    optimizer = MultipointHillClimbing(
        max_iterations=20,
        num_points=4
    )

    initial = {'x': 0.1, 'y': 0.9}
    ranges = {
        'x': (0.0, 1.0, 0.01),
        'y': (0.0, 1.0, 0.01)
    }

    best_params, best_obj, best_metrics = optimizer.optimize(
        initial, ranges, mock_backtest
    )
    print(f"Best params: {best_params}")
    print(f"Best objective: {best_obj}")
