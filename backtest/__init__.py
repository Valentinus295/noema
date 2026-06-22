"""VMPM Backtesting Engine — validates trading edge before risking real money."""

from vmpm.backtest.engine import BacktestEngine, BacktestResult
from vmpm.backtest.metrics import compute_metrics, PerformanceMetrics

__all__ = ["BacktestEngine", "BacktestResult", "compute_metrics", "PerformanceMetrics"]
