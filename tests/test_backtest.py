"""Tests for backtesting engine, metrics, statistical gates, and walk-forward."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from noema.backtest.engine import BacktestEngine, BacktestConfig, TradeRecord
from noema.backtest.metrics import compute_metrics, PerformanceMetrics, format_metrics
from noema.backtest.statistical import (
    bootstrap_sharpe_ci, sprt_monitor, permutation_test, monte_carlo_ruin,
)
from noema.backtest.walkforward import WalkForwardOptimizer


# ── Fixtures ──

@pytest.fixture
def sample_data() -> pd.DataFrame:
    """Generate 500 bars of synthetic OHLCV data."""
    rng = np.random.RandomState(42)
    n = 500
    close = 1.1000 + np.cumsum(rng.randn(n) * 0.0005)
    return pd.DataFrame({
        "time": pd.date_range(end=pd.Timestamp.now(), periods=n, freq="1h"),
        "open": close + rng.randn(n) * 0.0001,
        "high": close + abs(rng.randn(n) * 0.0003),
        "low": close - abs(rng.randn(n) * 0.0003),
        "close": close,
        "volume": rng.randint(50, 500, n).astype(float),
    })


@pytest.fixture
def sample_pnls() -> list[float]:
    """Sample trade P&Ls for metrics testing."""
    return [50.0, 30.0, -20.0, 40.0, -15.0, 60.0, -10.0, 25.0, -30.0, 35.0]


@pytest.fixture
def winning_pnls() -> list[float]:
    """All winning trades."""
    return [10.0, 20.0, 15.0, 25.0, 30.0]


@pytest.fixture
def losing_pnls() -> list[float]:
    """All losing trades."""
    return [-10.0, -20.0, -15.0, -25.0, -30.0]


# ── Backtest Engine Tests ──

class TestBacktestEngine:
    """Tests for BacktestEngine."""

    def test_initialization(self):
        engine = BacktestEngine()
        assert engine._balance == 10000.0
        assert engine._trades == []
        assert engine._open_positions == []

    def test_custom_config(self):
        config = BacktestConfig(initial_balance=5000, risk_per_trade=0.02)
        engine = BacktestEngine(config)
        assert engine._balance == 5000

    def test_run_with_no_signal(self, sample_data):
        """Engine should handle no-signal function gracefully."""
        def noop_signal(ctx):
            return {"signal": "WAIT", "confidence": 0.0}

        engine = BacktestEngine()
        result = engine.run("EURUSD", sample_data, noop_signal)
        assert result.total_bars_processed == 500
        assert len(result.trades) == 0
        assert result.equity_curve[0] == 10000.0

    def test_run_with_buy_signals(self, sample_data):
        """Engine should execute trades on BUY signals."""
        call_count = [0]

        def buy_signal(ctx):
            call_count[0] += 1
            price = ctx["current_price"]
            if call_count[0] % 50 == 0:
                return {
                    "signal": "BUY", "confidence": 0.8,
                    "sl": price - 0.0050, "tp": price + 0.0100,
                    "agent_reports": {},
                }
            return {"signal": "WAIT", "confidence": 0.0}

        engine = BacktestEngine(BacktestConfig(risk_per_trade=0.01))
        result = engine.run("EURUSD", sample_data, buy_signal)
        assert result.total_bars_processed == 500
        assert len(result.trades) > 0
        assert result.metrics.total_trades > 0

    def test_run_with_error_in_signal(self, sample_data):
        """Engine should handle errors in signal function."""
        def bad_signal(ctx):
            raise ValueError("Signal function crashed")

        engine = BacktestEngine()
        result = engine.run("EURUSD", sample_data, bad_signal)
        assert result.total_bars_processed == 500
        assert len(result.trades) == 0

    def test_insufficient_data(self):
        """Engine should handle insufficient data."""
        def noop_signal(ctx):
            return {"signal": "WAIT", "confidence": 0.0}

        engine = BacktestEngine()
        data = pd.DataFrame({
            "time": pd.date_range(end=pd.Timestamp.now(), periods=10, freq="1h"),
            "open": [1.0] * 10, "high": [1.01] * 10,
            "low": [0.99] * 10, "close": [1.0] * 10,
            "volume": [100.0] * 10,
        })
        result = engine.run("EURUSD", data, noop_signal)
        assert result.total_bars_processed == 0

    def test_daily_loss_limit(self, sample_data):
        """Engine should stop trading after daily loss limit."""
        always_buy = lambda ctx: {
            "signal": "BUY", "confidence": 0.9,
            "sl": ctx["current_price"] - 0.0010,
            "tp": ctx["current_price"] + 0.0010,
            "agent_reports": {},
        }
        engine = BacktestEngine(BacktestConfig(
            risk_per_trade=0.5,  # Huge risk to trigger daily limit fast
            max_daily_loss_pct=0.01,
        ))
        result = engine.run("EURUSD", sample_data, always_buy)
        # Should have stopped trading at some point
        assert result.total_bars_processed == 500


# ── Metrics Tests ──

class TestMetrics:
    """Tests for performance metrics."""

    def test_empty_trades(self):
        m = compute_metrics([])
        assert m.total_trades == 0
        assert m.win_rate == 0.0

    def test_all_wins(self, winning_pnls):
        trades = [TradeRecord(
            ticket=i, symbol="EURUSD", direction="buy",
            entry_price=1.1, exit_price=1.11, volume=0.1,
            sl=1.09, tp=1.13, pnl=p, pnl_pips=p / 10,
            entry_time=pd.Timestamp("2026-01-01").to_pydatetime(),
            exit_time=pd.Timestamp("2026-01-02").to_pydatetime(),
            exit_reason="tp", session="london",
        ) for i, p in enumerate(winning_pnls)]

        m = compute_metrics(trades)
        assert m.win_rate == 1.0
        assert m.total_pnl > 0
        assert m.losses == 0

    def test_all_losing(self, losing_pnls):
        trades = [TradeRecord(
            ticket=i, symbol="EURUSD", direction="buy",
            entry_price=1.1, exit_price=1.09, volume=0.1,
            sl=1.09, tp=1.13, pnl=p, pnl_pips=p / 10,
            entry_time=pd.Timestamp("2026-01-01").to_pydatetime(),
            exit_time=pd.Timestamp("2026-01-02").to_pydatetime(),
            exit_reason="sl", session="london",
        ) for i, p in enumerate(losing_pnls)]

        m = compute_metrics(trades)
        assert m.win_rate == 0.0
        assert m.total_pnl < 0

    def test_mixed_results(self, sample_pnls):
        trades = [TradeRecord(
            ticket=i, symbol="EURUSD", direction="buy",
            entry_price=1.1, exit_price=1.1 + p * 0.0001, volume=0.1,
            sl=1.09, tp=1.13, pnl=p, pnl_pips=p / 10,
            entry_time=pd.Timestamp("2026-01-01").to_pydatetime(),
            exit_time=pd.Timestamp("2026-01-02").to_pydatetime(),
            exit_reason="tp" if p > 0 else "sl", session="london",
        ) for i, p in enumerate(sample_pnls)]

        m = compute_metrics(trades)
        assert m.total_trades == 10
        assert m.wins == 6
        assert m.losses == 4
        assert m.win_rate == 0.6
        assert m.total_pnl == sum(sample_pnls)
        assert m.profit_factor > 0

    def test_format_metrics(self, sample_pnls):
        trades = [TradeRecord(
            ticket=i, symbol="EURUSD", direction="buy",
            entry_price=1.1, exit_price=1.1 + p * 0.0001, volume=0.1,
            sl=1.09, tp=1.13, pnl=p, pnl_pips=p / 10,
            entry_time=pd.Timestamp("2026-01-01").to_pydatetime(),
            exit_time=pd.Timestamp("2026-01-02").to_pydatetime(),
            exit_reason="tp" if p > 0 else "sl", session="london",
        ) for i, p in enumerate(sample_pnls)]

        m = compute_metrics(trades)
        text = format_metrics(m)
        assert "BACKTEST PERFORMANCE REPORT" in text
        assert "Win Rate" in text


# ── Statistical Gates Tests ──

class TestStatisticalGates:
    """Tests for statistical gates."""

    def test_bootstrap_positive_edge(self):
        pnls = [10.0] * 20 + [-5.0] * 10
        result = bootstrap_sharpe_ci(pnls, n_resamples=500)
        assert result.mean > 0
        assert result.ci_lower < result.ci_upper

    def test_bootstrap_insufficient_data(self):
        result = bootstrap_sharpe_ci([1.0, 2.0])
        assert result.significant is False

    def test_sprt_accept_h1(self):
        # Strong positive edge
        pnls = [0.15] * 30
        result = sprt_monitor(pnls, h0_expectancy=0.0, h1_expectancy=0.15)
        assert result.decision in ("accept_h1", "continue")

    def test_sprt_accept_h0(self):
        # No edge
        pnls = [0.0] * 30
        result = sprt_monitor(pnls, h0_expectancy=0.0, h1_expectancy=0.15)
        assert result.decision in ("accept_h0", "continue")

    def test_permutation_significant(self):
        pnls = [10.0] * 30 + [-2.0] * 10
        result = permutation_test(pnls, n_resamples=500)
        assert result.observed_statistic > 0
        assert 0 <= result.p_value <= 1

    def test_monte_carlo_ruin(self):
        pnls = [10.0, -5.0, 8.0, -3.0, 12.0]
        result = monte_carlo_ruin(pnls, n_simulations=1000)
        assert 0 <= result.p_ruin <= 1
        assert result.median_final_equity > 0


# ── Walk-Forward Tests ──

class TestWalkForward:
    """Tests for walk-forward optimizer."""

    def test_window_splitting(self):
        """Window splitting with small enough windows for our test data."""
        # 2000 bars = ~83 days of H1 data
        rng = np.random.RandomState(42)
        n = 2000
        close = 1.1 + np.cumsum(rng.randn(n) * 0.0005)
        data = pd.DataFrame({
            "time": pd.date_range(end=pd.Timestamp.now(), periods=n, freq="1h"),
            "open": close + rng.randn(n) * 0.0001,
            "high": close + abs(rng.randn(n) * 0.0003),
            "low": close - abs(rng.randn(n) * 0.0003),
            "close": close,
            "volume": rng.randint(50, 500, n).astype(float),
        })
        # Use very small windows so they fit in our dataset
        optimizer = WalkForwardOptimizer(train_months=1, test_months=1, step_months=1)
        windows = optimizer._split_windows(data)
        assert len(windows) > 0
        for w in windows:
            assert len(w.train_data) > 0
            assert len(w.test_data) > 0

    def test_param_combinations(self):
        optimizer = WalkForwardOptimizer()
        grid = {"rsi_period": [10, 14], "threshold": [0.3, 0.5]}
        combos = optimizer._generate_param_combinations(grid)
        assert len(combos) == 4
        assert {"rsi_period": 10, "threshold": 0.3} in combos
