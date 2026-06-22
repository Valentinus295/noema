"""Noema Backtesting Engine — validates trading edge before risking real money."""

from noema.backtest.engine import BacktestEngine, BacktestResult
from noema.backtest.metrics import compute_metrics, PerformanceMetrics

__all__ = ["BacktestEngine", "BacktestResult", "compute_metrics", "PerformanceMetrics"]
