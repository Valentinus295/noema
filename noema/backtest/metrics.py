"""Backtest performance metrics.

Computes Sharpe, Sortino, MaxDD, expectancy, profit factor,
win rate, and other metrics required by the statistical gates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PerformanceMetrics:
    """Complete backtest performance metrics."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    avg_rr: float = 0.0
    avg_bars_held: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    profit_per_bar: float = 0.0
    calmar_ratio: float = 0.0


def compute_metrics(trades: list, initial_balance: float = 10000.0) -> PerformanceMetrics:
    """Compute all performance metrics from a list of TradeRecord objects."""
    m = PerformanceMetrics()

    if not trades:
        return m

    pnls = [t.pnl for t in trades]
    m.total_trades = len(trades)
    m.wins = sum(1 for p in pnls if p > 0)
    m.losses = sum(1 for p in pnls if p <= 0)
    m.win_rate = m.wins / m.total_trades if m.total_trades > 0 else 0.0
    m.total_pnl = sum(pnls)
    m.total_pnl_pct = m.total_pnl / initial_balance * 100

    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p <= 0]

    m.avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    m.avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0
    m.best_trade = max(pnls) if pnls else 0.0
    m.worst_trade = min(pnls) if pnls else 0.0

    # Profit factor
    gross_profit = sum(win_pnls) if win_pnls else 0.0
    gross_loss = abs(sum(loss_pnls)) if loss_pnls else 0.0
    m.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy (average R-multiple)
    m.expectancy = (m.win_rate * m.avg_win) - ((1 - m.win_rate) * m.avg_loss)

    # Sharpe ratio (annualized, assuming H1 bars)
    if len(pnls) > 1:
        mean_ret = sum(pnls) / len(pnls)
        var = sum((p - mean_ret) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 1e-10
        # ~8760 H1 bars per year
        m.sharpe_ratio = (mean_ret / std) * math.sqrt(8760)
    else:
        m.sharpe_ratio = 0.0

    # Sortino ratio (downside deviation only)
    negative_pnls = [p for p in pnls if p < 0]
    if negative_pnls:
        downside_var = sum(p ** 2 for p in negative_pnls) / len(negative_pnls)
        downside_std = math.sqrt(downside_var) if downside_var > 0 else 1e-10
        mean_ret = sum(pnls) / len(pnls)
        m.sortino_ratio = (mean_ret / downside_std) * math.sqrt(8760)
    else:
        m.sortino_ratio = float("inf") if sum(pnls) > 0 else 0.0

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)
    m.max_drawdown = max_dd
    m.max_drawdown_pct = max_dd / initial_balance * 100

    # Calmar ratio
    m.calmar_ratio = m.total_pnl / max_dd if max_dd > 0 else float("inf")

    # Average bars held
    bars_held = []
    for t in trades:
        if hasattr(t, "entry_time") and hasattr(t, "exit_time"):
            delta = (t.exit_time - t.entry_time).total_seconds() / 3600
            bars_held.append(delta)
    m.avg_bars_held = sum(bars_held) / len(bars_held) if bars_held else 0.0

    # Profit per bar
    total_bars = sum(bars_held) if bars_held else 1.0
    m.profit_per_bar = m.total_pnl / total_bars if total_bars > 0 else 0.0

    return m


def format_metrics(m: PerformanceMetrics) -> str:
    """Format metrics as a readable string."""
    lines = [
        "=" * 50,
        "  BACKTEST PERFORMANCE REPORT",
        "=" * 50,
        f"  Total Trades:    {m.total_trades}",
        f"  Win Rate:        {m.win_rate:.1%} ({m.wins}W / {m.losses}L)",
        f"  Profit Factor:   {m.profit_factor:.2f}",
        f"  Expectancy:      ${m.expectancy:.2f}",
        f"  Total P&L:       ${m.total_pnl:,.2f} ({m.total_pnl_pct:.1f}%)",
        f"  Avg Win:         ${m.avg_win:.2f}",
        f"  Avg Loss:        ${m.avg_loss:.2f}",
        f"  Best Trade:      ${m.best_trade:.2f}",
        f"  Worst Trade:     ${m.worst_trade:.2f}",
        "-" * 50,
        f"  Sharpe Ratio:    {m.sharpe_ratio:.2f}",
        f"  Sortino Ratio:   {m.sortino_ratio:.2f}",
        f"  Max Drawdown:    ${m.max_drawdown:,.2f} ({m.max_drawdown_pct:.1f}%)",
        f"  Calmar Ratio:    {m.calmar_ratio:.2f}",
        f"  Avg Bars Held:   {m.avg_bars_held:.1f}h",
        f"  Profit/Bar:      ${m.profit_per_bar:.4f}",
        "=" * 50,
    ]
    return "\n".join(lines)
