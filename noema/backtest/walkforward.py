"""Walk-forward optimization framework.

Splits data into train/test windows, optimizes parameters on train,
validates on test. Uses expanding or rolling windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class WalkForwardWindow:
    """A single walk-forward window."""
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    test_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    best_params: dict[str, Any] = field(default_factory=dict)
    test_metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class WalkForwardResult:
    """Complete walk-forward optimization result."""
    windows: list[WalkForwardWindow]
    out_of_sample_sharpe: float
    out_of_sample_win_rate: float
    out_of_sample_pnl: float
    is_consistent: bool  # True if most windows are profitable


class WalkForwardOptimizer:
    """Walk-forward optimization engine.

    Splits data into train/test periods, optimizes strategy parameters
    on training data, and validates on unseen test data.
    """

    def __init__(
        self,
        train_months: int = 6,
        test_months: int = 2,
        step_months: int = 2,
    ) -> None:
        self.train_months = train_months
        self.test_months = test_months
        self.step_months = step_months

    def optimize(
        self,
        data: pd.DataFrame,
        backtest_fn: Callable[[pd.DataFrame, dict[str, Any]], float],
        param_grid: dict[str, list[Any]],
        symbol: str = "EURUSD",
    ) -> WalkForwardResult:
        """Run walk-forward optimization.

        Args:
            data: Full OHLCV dataset
            backtest_fn: Function(train_data, params) -> Sharpe ratio
            param_grid: Dict of param_name -> list of values to try
            symbol: Trading pair
        """
        windows = self._split_windows(data)

        logger.info("walk_forward_start", n_windows=len(windows), symbol=symbol)

        all_test_pnls = []
        all_test_win_rates = []

        for i, window in enumerate(windows):
            logger.debug("optimizing_window", i=i, train_bars=len(window.train_data),
                         test_bars=len(window.test_data))

            # Grid search on training data
            best_sharpe = -float("inf")
            best_params = {}

            for params in self._generate_param_combinations(param_grid):
                try:
                    sharpe = backtest_fn(window.train_data, params)
                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_params = params
                except Exception as exc:
                    logger.debug("param_combo_failed", params=params, error=str(exc))
                    continue

            window.best_params = best_params

            # Validate on test data
            try:
                test_sharpe = backtest_fn(window.test_data, best_params)
                window.test_metrics = {"sharpe": test_sharpe}
                all_test_pnls.append(test_sharpe)
            except Exception as exc:
                logger.debug("test_failed", error=str(exc))
                window.test_metrics = {"sharpe": 0.0}
                all_test_pnls.append(0.0)

        # Aggregate out-of-sample results
        oos_sharpe = sum(all_test_pnls) / len(all_test_pnls) if all_test_pnls else 0.0
        profitable_windows = sum(1 for s in all_test_pnls if s > 0)
        is_consistent = profitable_windows > len(all_test_pnls) * 0.5

        return WalkForwardResult(
            windows=windows,
            out_of_sample_sharpe=oos_sharpe,
            out_of_sample_win_rate=profitable_windows / len(all_test_pnls) if all_test_pnls else 0.0,
            out_of_sample_pnl=sum(all_test_pnls),
            is_consistent=is_consistent,
        )

    def _split_windows(self, data: pd.DataFrame) -> list[WalkForwardWindow]:
        """Split data into train/test windows."""
        windows = []
        n = len(data)
        train_bars = self.train_months * 21 * 24  # approximate H1 bars
        test_bars = self.test_months * 21 * 24
        step_bars = self.step_months * 21 * 24

        start = 0
        while start + train_bars + test_bars <= n:
            train_end = start + train_bars
            test_start = train_end
            test_end = min(test_start + test_bars, n)

            windows.append(WalkForwardWindow(
                train_start=start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                train_data=data.iloc[start:train_end].copy(),
                test_data=data.iloc[test_start:test_end].copy(),
            ))

            start += step_bars

        return windows

    def _generate_param_combinations(
        self, param_grid: dict[str, list[Any]]
    ) -> list[dict[str, Any]]:
        """Generate all combinations of parameters."""
        if not param_grid:
            return [{}]

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        combinations = [{}]
        for key, vals in zip(keys, values):
            new_combinations = []
            for combo in combinations:
                for val in vals:
                    new_combo = {**combo, key: val}
                    new_combinations.append(new_combo)
            combinations = new_combinations

        return combinations
