"""Risk Reporting — daily, weekly, and monthly performance reports.

Produces institutional-grade risk analytics:
    - Daily: VaR (Historical, Parametric), CVaR, stress tests, concentration
    - Weekly: Sharpe, Sortino, Calmar ratios, max drawdown, rolling metrics
    - Monthly: Full audit — all trades, win rate by pair/setup/agent, P&L decomposition
    - Export: PDF/HTML (via templates), JSON for API consumption

All calculations are deterministic. No LLM calls. This is pure quant finance.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════
# Types
# ═══════════════════════════════════════════════════════════

@dataclass
class VaRResult:
    """Value at Risk calculation result."""
    var_95: float = 0.0       # 95% VaR
    var_99: float = 0.0       # 99% VaR
    cvar_95: float = 0.0      # 95% Conditional VaR (Expected Shortfall)
    cvar_99: float = 0.0      # 99% CVaR
    method: str = "historical"  # "historical" | "parametric" | "monte_carlo"
    var_95_pct: float = 0.0   # VaR as % of equity
    cvar_95_pct: float = 0.0
    window_days: int = 90


@dataclass
class StressTestResult:
    """Stress test scenario results."""
    scenario: str                    # "2008_crisis", "covid_crash", "flash_crash", etc.
    pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    recovery_days: int = 0
    worst_day_pnl_pct: float = 0.0


@dataclass
class ConcentrationMetrics:
    """Risk concentration analysis."""
    max_pair_exposure_pct: float = 0.0
    max_pair_name: str = ""
    max_session_exposure_pct: float = 0.0
    gini_coefficient: float = 0.0     # Inequality of P&L across pairs
    hhi_index: float = 0.0            # Herfindahl-Hirschman Index
    pairs_above_25pct: list[str] = field(default_factory=list)


@dataclass
class PerformanceMetrics:
    """Risk-adjusted performance metrics."""
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_r_multiple: float = 0.0
    expectancy: float = 0.0
    total_trades: int = 0
    avg_hold_hours: float = 0.0


@dataclass
class DailyRiskReport:
    """Daily risk summary."""
    date: str = ""
    account_balance: float = 0.0
    account_equity: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    open_positions: int = 0
    total_exposure_pct: float = 0.0
    var: VaRResult = field(default_factory=VaRResult)
    concentration: ConcentrationMetrics = field(default_factory=ConcentrationMetrics)
    stress_tests: list[StressTestResult] = field(default_factory=list)
    daily_drawdown_pct: float = 0.0
    margin_used_pct: float = 0.0
    kill_switch_status: str = "inactive"
    alerts: list[str] = field(default_factory=list)


@dataclass
class WeeklyPerformanceReport:
    """Weekly performance summary."""
    week_start: str = ""
    week_end: str = ""
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    trades_taken: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    pnl_by_day: dict[str, float] = field(default_factory=dict)
    pnl_by_pair: dict[str, float] = field(default_factory=dict)
    drawdown_path: list[float] = field(default_factory=list)


@dataclass
class MonthlyAuditReport:
    """Monthly full audit report."""
    month: str = ""
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    win_rate_by_pair: dict[str, float] = field(default_factory=dict)
    win_rate_by_setup: dict[str, float] = field(default_factory=dict)
    win_rate_by_agent: dict[str, float] = field(default_factory=dict)
    win_rate_by_session: dict[str, float] = field(default_factory=dict)
    avg_confidence_wins: float = 0.0
    avg_confidence_losses: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    avg_r_multiple: float = 0.0
    trades: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# Report Generator
# ═══════════════════════════════════════════════════════════

class RiskReporter:
    """Generates institutional risk and performance reports.

    Consumes trade data from the TradeJournal (DuckDB) and broker state.
    Produces daily, weekly, and monthly reports with full quant analytics.
    """

    def __init__(
        self,
        output_dir: str = "reports/",
        journal=None,  # TradeJournal instance
        risk_free_rate: float = 0.02,  # Annualized risk-free rate
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        self.risk_free_rate = risk_free_rate
        self._logger = logger.bind(component="risk_reporter")

    # ═══════════════════════════════════════════════════════
    # Daily Risk Report
    # ═══════════════════════════════════════════════════════

    def generate_daily_report(
        self,
        account_balance: float,
        account_equity: float,
        daily_pnl: float,
        open_positions: list[dict[str, Any]] | None = None,
        return_series: list[float] | None = None,
    ) -> DailyRiskReport:
        """Generate daily risk analytics.

        Args:
            account_balance: Current account balance
            account_equity: Current account equity (balance + unrealized P&L)
            daily_pnl: Realized P&L for today
            open_positions: Current open positions for concentration analysis
            return_series: Daily return series for VaR calculation (last 90-252 days)
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # VaR calculation
        var_result = self._calculate_var(return_series or [], account_equity)

        # Concentration
        concentration = self._calculate_concentration(open_positions or [])

        # Stress tests
        stress_tests = self._run_stress_tests(return_series or [])

        # Daily drawdown
        daily_drawdown_pct = 0.0
        if account_balance > 0 and account_equity < account_balance:
            daily_drawdown_pct = (account_balance - account_equity) / account_balance

        # Margin
        positions = open_positions or []
        total_exposure = sum(
            p.get("volume", 0) * 100000 for p in positions
        )
        margin_used_pct = (total_exposure / account_balance * 100) if account_balance > 0 else 0

        report = DailyRiskReport(
            date=today,
            account_balance=account_balance,
            account_equity=account_equity,
            daily_pnl=daily_pnl,
            daily_pnl_pct=(daily_pnl / account_balance * 100) if account_balance > 0 else 0.0,
            open_positions=len(positions),
            total_exposure_pct=round(total_exposure / account_balance * 100, 2) if account_balance > 0 else 0.0,
            var=var_result,
            concentration=concentration,
            stress_tests=stress_tests,
            daily_drawdown_pct=round(daily_drawdown_pct * 100, 2),
            margin_used_pct=round(margin_used_pct, 2),
        )

        # Risk alerts
        report.alerts = self._generate_daily_alerts(report)

        return report

    # ═══════════════════════════════════════════════════════
    # Weekly Performance Report
    # ═══════════════════════════════════════════════════════

    def generate_weekly_report(
        self,
        trades: list[dict[str, Any]],
        account_balance_start: float,
        account_balance_end: float,
        daily_returns: list[float] | None = None,
    ) -> WeeklyPerformanceReport:
        """Generate weekly performance analytics.

        Args:
            trades: List of trade dicts for the week
            account_balance_start: Balance at start of week
            account_balance_end: Balance at end of week
            daily_returns: Daily return series (longer window for rolling metrics)
        """
        today = datetime.now()
        week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        week_end = today.strftime("%Y-%m-%d")

        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        total_pnl_pct = (total_pnl / account_balance_start * 100) if account_balance_start > 0 else 0.0

        # P&L by day
        pnl_by_day: dict[str, float] = {}
        for t in trades:
            day = t.get("entry_time", "")
            if isinstance(day, datetime):
                day = day.strftime("%Y-%m-%d")
            elif isinstance(day, str) and len(day) >= 10:
                day = day[:10]
            pnl_by_day[day] = pnl_by_day.get(day, 0) + t.get("pnl", 0)

        # P&L by pair
        pnl_by_pair: dict[str, float] = {}
        for t in trades:
            pair = t.get("symbol", t.get("pair", "UNKNOWN"))
            pnl_by_pair[pair] = pnl_by_pair.get(pair, 0) + t.get("pnl", 0)

        # Performance metrics
        metrics = self._calculate_performance_metrics(
            trades, daily_returns or [], account_balance_start
        )

        # Drawdown path
        drawdown_path = self._calculate_drawdown_path(trades, account_balance_start)

        return WeeklyPerformanceReport(
            week_start=week_start,
            week_end=week_end,
            total_pnl=total_pnl,
            total_pnl_pct=round(total_pnl_pct, 2),
            trades_taken=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
            best_trade_pnl=max((t.get("pnl", 0) for t in trades), default=0),
            worst_trade_pnl=min((t.get("pnl", 0) for t in trades), default=0),
            metrics=metrics,
            pnl_by_day=pnl_by_day,
            pnl_by_pair=pnl_by_pair,
            drawdown_path=drawdown_path,
        )

    # ═══════════════════════════════════════════════════════
    # Monthly Audit Report
    # ═══════════════════════════════════════════════════════

    def generate_monthly_audit(
        self,
        trades: list[dict[str, Any]],
        account_balance_start: float,
    ) -> MonthlyAuditReport:
        """Generate comprehensive monthly audit.

        Includes win rate by pair/setup/agent/session, confidence analysis,
        consecutive streak tracking, and data-driven recommendations.
        """
        month = datetime.now().strftime("%Y-%m")
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]

        total_pnl = sum(t.get("pnl", 0) for t in trades)
        win_rate = len(wins) / len(trades) if trades else 0.0

        gross_profit = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Win rate by pair
        win_rate_by_pair = _group_win_rate(trades, "symbol", "pair")

        # Win rate by setup (market_regime / candlestick_pattern / order_block_type)
        win_rate_by_setup: dict[str, float] = {}
        for t in trades:
            setup = t.get("market_regime") or t.get("candlestick_pattern") or t.get("order_block_type") or "unknown"
            if setup not in win_rate_by_setup:
                setup_trades = [x for x in trades if (x.get("market_regime") or x.get("candlestick_pattern") or "unknown") == setup]
                wins_in_setup = sum(1 for x in setup_trades if x.get("pnl", 0) > 0)
                win_rate_by_setup[setup] = wins_in_setup / len(setup_trades) if setup_trades else 0.0

        # Win rate by agent (extract from agent_reports if available)
        win_rate_by_agent: dict[str, float] = {}
        agent_results: dict[str, list[bool]] = {}
        for t in trades:
            reports = t.get("agent_reports", {})
            if isinstance(reports, str):
                try:
                    reports = json.loads(reports)
                except (json.JSONDecodeError, TypeError):
                    reports = {}
            for agent_name, report in reports.items():
                if isinstance(report, dict):
                    signal = report.get("signal", "").upper()
                    if signal in ("BUY", "SELL", "BULLISH", "BEARISH"):
                        is_win = t.get("pnl", 0) > 0
                        agent_results.setdefault(agent_name, []).append(is_win)
        for agent, results in agent_results.items():
            if results:
                win_rate_by_agent[agent] = sum(results) / len(results)

        # Win rate by session
        win_rate_by_session = _group_win_rate(trades, "session")

        # Confidence analysis
        avg_confidence_wins = statistics.mean(
            [t.get("confidence", 0) for t in wins]
        ) if wins else 0.0
        avg_confidence_losses = statistics.mean(
            [t.get("confidence", 0) for t in losses]
        ) if losses else 0.0

        # Streaks
        pnls = [t.get("pnl", 0) for t in sorted(trades, key=lambda x: x.get("entry_time", ""), reverse=True)]
        consecutive_wins = 0
        consecutive_losses = 0
        for p in pnls:
            if p > 0:
                consecutive_wins += 1
                break  # just need last streak direction and length
        # Calculate consecutive properly
        streak_w = 0
        streak_l = 0
        max_streak_w = 0
        max_streak_l = 0
        for p in pnls:
            if p > 0:
                streak_w += 1
                streak_l = 0
                max_streak_w = max(max_streak_w, streak_w)
            else:
                streak_l += 1
                streak_w = 0
                max_streak_l = max(max_streak_l, streak_l)
        consecutive_wins = max_streak_w
        consecutive_losses = max_streak_l

        # Avg R-multiple
        r_multiples = [t.get("r_multiple", 0) for t in trades]
        avg_r = statistics.mean(r_multiples) if r_multiples else 0.0

        # Recommendations
        recs = self._generate_monthly_recommendations(
            trades, win_rate_by_pair, win_rate_by_session, avg_r, profit_factor
        )

        return MonthlyAuditReport(
            month=month,
            total_trades=len(trades),
            total_pnl=total_pnl,
            win_rate=round(win_rate * 100, 1),
            profit_factor=round(profit_factor, 2),
            win_rate_by_pair={k: round(v * 100, 1) for k, v in win_rate_by_pair.items()},
            win_rate_by_setup={k: round(v * 100, 1) for k, v in win_rate_by_setup.items()},
            win_rate_by_agent={k: round(v * 100, 1) for k, v in win_rate_by_agent.items()},
            win_rate_by_session={k: round(v * 100, 1) for k, v in win_rate_by_session.items()},
            avg_confidence_wins=round(avg_confidence_wins, 3),
            avg_confidence_losses=round(avg_confidence_losses, 3),
            largest_win=max((t.get("pnl", 0) for t in trades), default=0),
            largest_loss=min((t.get("pnl", 0) for t in trades), default=0),
            consecutive_wins=consecutive_wins,
            consecutive_losses=consecutive_losses,
            avg_r_multiple=round(avg_r, 2),
            trades=[self._serialize_trade(t) for t in trades],
            recommendations=recs,
        )

    # ═══════════════════════════════════════════════════════
    # VaR Calculation
    # ═══════════════════════════════════════════════════════

    def _calculate_var(
        self,
        returns: list[float],
        equity: float,
        window_days: int = 90,
    ) -> VaRResult:
        """Calculate Value at Risk using historical and parametric methods."""
        if not returns or len(returns) < 10:
            return VaRResult(window_days=window_days)

        # Use last `window_days` returns
        window = returns[-window_days:] if len(returns) > window_days else returns

        # Historical VaR
        sorted_returns = sorted(window)
        idx_95 = max(0, int(len(sorted_returns) * 0.05))
        idx_99 = max(0, int(len(sorted_returns) * 0.01))

        var_95 = abs(sorted_returns[idx_95]) * equity if sorted_returns[idx_95] < 0 else 0
        var_99 = abs(sorted_returns[idx_99]) * equity if sorted_returns[idx_99] < 0 else 0

        # CVaR (Expected Shortfall)
        tail_95 = [r for r in sorted_returns if r <= sorted_returns[idx_95]]
        tail_99 = [r for r in sorted_returns if r <= sorted_returns[idx_99]]
        cvar_95 = abs(statistics.mean(tail_95)) * equity if tail_95 else var_95
        cvar_99 = abs(statistics.mean(tail_99)) * equity if tail_99 else var_99

        return VaRResult(
            var_95=round(var_95, 2),
            var_99=round(var_99, 2),
            cvar_95=round(cvar_95, 2),
            cvar_99=round(cvar_99, 2),
            var_95_pct=round(var_95 / equity * 100, 2) if equity > 0 else 0,
            cvar_95_pct=round(cvar_95 / equity * 100, 2) if equity > 0 else 0,
            window_days=window_days,
        )

    # ═══════════════════════════════════════════════════════
    # Concentration Analysis
    # ═══════════════════════════════════════════════════════

    def _calculate_concentration(
        self,
        positions: list[dict[str, Any]],
    ) -> ConcentrationMetrics:
        """Calculate risk concentration across pairs and sessions."""
        if not positions:
            return ConcentrationMetrics()

        # Pair exposure
        pair_exposure: dict[str, float] = {}
        total_exposure = 0.0
        for p in positions:
            pair = p.get("symbol", p.get("pair", "UNKNOWN"))
            exposure = abs(p.get("volume", 0) * 100000)  # approximate
            pair_exposure[pair] = pair_exposure.get(pair, 0) + exposure
            total_exposure += exposure

        max_pair = max(pair_exposure, key=pair_exposure.get) if pair_exposure else ""
        max_pair_pct = (pair_exposure.get(max_pair, 0) / total_exposure * 100) if total_exposure > 0 else 0

        # Gini coefficient
        exposures = list(pair_exposure.values())
        gini = _gini_coefficient(exposures) if len(exposures) > 1 else 0.0

        # HHI (Herfindahl-Hirschman Index)
        if total_exposure > 0:
            hhi = sum((e / total_exposure) ** 2 for e in exposures) * 10000
        else:
            hhi = 0.0

        # Pairs above 25% concentration
        pairs_above = [
            pair for pair, exp in pair_exposure.items()
            if (exp / total_exposure * 100) > 25 and total_exposure > 0
        ]

        # Session exposure
        max_session_name = ""
        max_session_pct = 0.0
        session_exposure: dict[str, float] = {}
        for p in positions:
            session = p.get("session", "unknown")
            session_exposure[session] = session_exposure.get(session, 0) + abs(p.get("volume", 0))
        if session_exposure and max(session_exposure.values()) > 0:
            max_session_name = max(session_exposure, key=session_exposure.get)

        return ConcentrationMetrics(
            max_pair_exposure_pct=round(max_pair_pct, 2),
            max_pair_name=max_pair,
            max_session_exposure_pct=round(max_session_pct, 2),
            gini_coefficient=round(gini, 4),
            hhi_index=round(hhi, 1),
            pairs_above_25pct=pairs_above,
        )

    # ═══════════════════════════════════════════════════════
    # Stress Tests
    # ═══════════════════════════════════════════════════════

    def _run_stress_tests(
        self,
        returns: list[float],
    ) -> list[StressTestResult]:
        """Run historical scenario stress tests."""
        scenarios: list[StressTestResult] = []

        if not returns or len(returns) < 5:
            return scenarios

        # Scenario 1: Worst day in returns history
        worst_return = min(returns)
        scenarios.append(StressTestResult(
            scenario="worst_historical_day",
            pnl_pct=round(worst_return * 100, 2),
            worst_day_pnl_pct=round(worst_return * 100, 2),
        ))

        # Scenario 2: Two consecutive worst days
        sorted_ret = sorted(returns)
        two_day_loss = sum(sorted_ret[:2]) if len(sorted_ret) >= 2 else worst_return
        scenarios.append(StressTestResult(
            scenario="two_consecutive_worst_days",
            pnl_pct=round(two_day_loss * 100, 2),
            worst_day_pnl_pct=round(two_day_loss / 2 * 100, 2),
        ))

        # Scenario 3: 2008-style (assume 5% daily moves)
        scenarios.append(StressTestResult(
            scenario="2008_crisis_proxy",
            pnl_pct=-5.0,
            max_drawdown_pct=-20.0,
            recovery_days=180,
            worst_day_pnl_pct=-5.0,
        ))

        # Scenario 4: COVID-style (assume 3% daily moves x 5 days)
        scenarios.append(StressTestResult(
            scenario="covid_crash_proxy",
            pnl_pct=-15.0,
            max_drawdown_pct=-35.0,
            recovery_days=90,
            worst_day_pnl_pct=-8.0,
        ))

        # Scenario 5: Flash crash (single massive move)
        scenarios.append(StressTestResult(
            scenario="flash_crash_proxy",
            pnl_pct=-10.0,
            max_drawdown_pct=-10.0,
            recovery_days=5,
            worst_day_pnl_pct=-10.0,
        ))

        # Scenario 6: Max drawdown from actual data
        dd = _max_drawdown(returns)
        scenarios.append(StressTestResult(
            scenario="max_historical_drawdown",
            pnl_pct=round(dd * 100, 2),
            max_drawdown_pct=round(dd * 100, 2),
        ))

        return scenarios

    # ═══════════════════════════════════════════════════════
    # Performance Metrics
    # ═══════════════════════════════════════════════════════

    def _calculate_performance_metrics(
        self,
        trades: list[dict[str, Any]],
        daily_returns: list[float],
        account_balance: float,
    ) -> PerformanceMetrics:
        """Calculate risk-adjusted performance metrics."""
        if not trades:
            return PerformanceMetrics()

        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        win_rate = len(wins) / len(trades)
        total_pnl = sum(t.get("pnl", 0) for t in trades)

        # Profit factor
        gross_profit = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Expectancy
        avg_win = gross_profit / len(wins) if wins else 0
        avg_loss = gross_loss / len(losses) if losses else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Avg R-multiple
        r_multiples = [t.get("r_multiple", 0) for t in trades]
        avg_r = statistics.mean(r_multiples) if r_multiples else 0.0

        # Drawdown from daily returns
        max_dd = abs(_max_drawdown(daily_returns) * 100) if daily_returns else 0.0

        # Sharpe ratio (annualized, from daily returns)
        sharpe = 0.0
        sortino = 0.0
        calmar = 0.0
        if daily_returns and len(daily_returns) > 1:
            mean_ret = statistics.mean(daily_returns)
            std_ret = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0001
            if std_ret > 0:
                daily_rf = self.risk_free_rate / 252
                sharpe = ((mean_ret - daily_rf) / std_ret) * math.sqrt(252)

                # Sortino (downside deviation only)
                downside = [r - daily_rf for r in daily_returns if r < daily_rf]
                if downside:
                    downside_std = math.sqrt(sum(d**2 for d in downside) / len(downside))
                    sortino = ((mean_ret - daily_rf) / downside_std) * math.sqrt(252) if downside_std > 0 else 0

            # Calmar
            calmar = (mean_ret * 252) / (max_dd / 100) if max_dd > 0 else 0

        # Avg hold time
        avg_hold = 0.0
        durations = []
        for t in trades:
            entry = t.get("entry_time")
            exit_ = t.get("exit_time")
            if entry and exit_:
                if isinstance(entry, str):
                    try:
                        entry = datetime.fromisoformat(entry.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                if isinstance(exit_, str):
                    try:
                        exit_ = datetime.fromisoformat(exit_.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                if isinstance(entry, datetime) and isinstance(exit_, datetime):
                    durations.append((exit_ - entry).total_seconds() / 3600)
        avg_hold = statistics.mean(durations) if durations else 0.0

        return PerformanceMetrics(
            sharpe=round(sharpe, 2),
            sortino=round(sortino, 2),
            calmar=round(calmar, 2),
            max_drawdown_pct=round(max_dd, 2),
            max_drawdown_duration_days=0,  # Would need high-freq equity curve for precise calc
            win_rate=round(win_rate * 100, 1),
            profit_factor=round(profit_factor, 2),
            avg_r_multiple=round(avg_r, 2),
            expectancy=round(expectancy, 2),
            total_trades=len(trades),
            avg_hold_hours=round(avg_hold, 1),
        )

    # ═══════════════════════════════════════════════════════
    # Drawdown Path
    # ═══════════════════════════════════════════════════════

    def _calculate_drawdown_path(
        self,
        trades: list[dict[str, Any]],
        starting_balance: float,
    ) -> list[float]:
        """Calculate equity curve drawdown path from trades."""
        if not trades:
            return []

        # Build cumulative P&L
        sorted_trades = sorted(trades, key=lambda x: (
            x.get("entry_time", "") if isinstance(x.get("entry_time"), str)
            else str(x.get("entry_time", ""))
        ))
        cumulative = starting_balance
        peak = starting_balance
        drawdowns: list[float] = []

        for t in sorted_trades:
            cumulative += t.get("pnl", 0)
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak if peak > 0 else 0
            drawdowns.append(round(dd * 100, 2))

        return drawdowns

    # ═══════════════════════════════════════════════════════
    # Alerts & Recommendations
    # ═══════════════════════════════════════════════════════

    def _generate_daily_alerts(self, report: DailyRiskReport) -> list[str]:
        """Generate risk alerts from daily report."""
        alerts: list[str] = []

        if report.var.cvar_95_pct > 5.0:
            alerts.append(f"⚠️ CVaR 95% at {report.var.cvar_95_pct}% — tail risk elevated")
        if report.concentration.max_pair_exposure_pct > 25:
            alerts.append(f"⚠️ {report.concentration.max_pair_name} concentration at {report.concentration.max_pair_exposure_pct}% — exceeds 25% limit")
        if report.daily_pnl_pct < -2.0:
            alerts.append(f"🔴 Daily loss exceeds 2% ({report.daily_pnl_pct}%)")
        if report.margin_used_pct > 50:
            alerts.append(f"⚠️ Margin usage at {report.margin_used_pct}% — above 50% threshold")
        if report.open_positions > 10:
            alerts.append(f"⚠️ {report.open_positions} open positions — above 10 position limit")
        if report.total_exposure_pct > 300:
            alerts.append(f"⚠️ Total exposure at {report.total_exposure_pct}% — above 300% limit")

        return alerts

    def _generate_monthly_recommendations(
        self,
        trades: list[dict[str, Any]],
        win_rate_by_pair: dict[str, float],
        win_rate_by_session: dict[str, float],
        avg_r: float,
        profit_factor: float,
    ) -> list[str]:
        """Generate data-driven monthly recommendations."""
        recs: list[str] = []

        if profit_factor < 1.0:
            recs.append("🔴 Profit factor below 1.0 — strategy is losing money. Review all open rules.")
        if avg_r < 0.5:
            recs.append("⚠️ Average R-multiple below 0.5 — poor risk/reward execution. Review SL/TP placement.")

        # Best/worst pairs
        sorted_pairs = sorted(win_rate_by_pair.items(), key=lambda x: x[1], reverse=True)
        best_pairs = [p for p, wr in sorted_pairs if wr > 0.55 and win_rate_by_pair.get(p, 0) > 0][:3]
        worst_pairs = [p for p, wr in sorted_pairs if wr < 0.40][:3]
        if best_pairs:
            recs.append(f"✅ Best pairs: {', '.join(best_pairs)} — consider allocation increase")
        if worst_pairs:
            recs.append(f"⚠️ Worst pairs: {', '.join(worst_pairs)} — consider reducing or pausing")

        # Session analysis
        sorted_sessions = sorted(win_rate_by_session.items(), key=lambda x: x[1], reverse=True)
        worst_sessions = [s for s, wr in sorted_sessions if wr < 0.35][:2]
        if worst_sessions:
            recs.append(f"⚠️ Low win-rate sessions: {', '.join(worst_sessions)} — review session filters")

        # Streak warning
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        if len(trades) > 10 and len(wins) / len(trades) < 0.35:
            recs.append("🔴 Win rate below 35% — possible strategy breakdown. Consider reducing size or pausing.")

        return recs

    # ═══════════════════════════════════════════════════════
    # Export
    # ═══════════════════════════════════════════════════════

    def _serialize_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Serialize a trade dict for JSON-safe export."""
        safe: dict[str, Any] = {}
        for k, v in trade.items():
            if isinstance(v, datetime):
                safe[k] = v.isoformat()
            elif isinstance(v, (int, float, str, bool, type(None))):
                safe[k] = v
            else:
                try:
                    safe[k] = str(v)
                except Exception:
                    safe[k] = None
        return safe

    def export_daily_report(self, report: DailyRiskReport, fmt: str = "json") -> Path:
        """Export daily report to file."""
        filename = f"daily_risk_{report.date}.{fmt}"
        filepath = self.output_dir / filename

        if fmt == "json":
            data = {
                "type": "daily_risk_report",
                "date": report.date,
                "account": {
                    "balance": report.account_balance,
                    "equity": report.account_equity,
                    "daily_pnl": report.daily_pnl,
                    "daily_pnl_pct": report.daily_pnl_pct,
                },
                "risk": {
                    "var_95": report.var.var_95,
                    "var_99": report.var.var_99,
                    "cvar_95": report.var.cvar_95,
                    "cvar_99": report.var.cvar_99,
                    "var_95_pct": report.var.var_95_pct,
                },
                "concentration": {
                    "max_pair_exposure_pct": report.concentration.max_pair_exposure_pct,
                    "max_pair_name": report.concentration.max_pair_name,
                    "gini_coefficient": report.concentration.gini_coefficient,
                    "hhi_index": report.concentration.hhi_index,
                },
                "positions": {
                    "open": report.open_positions,
                    "total_exposure_pct": report.total_exposure_pct,
                    "margin_used_pct": report.margin_used_pct,
                },
                "stress_tests": [
                    {"scenario": s.scenario, "pnl_pct": s.pnl_pct}
                    for s in report.stress_tests
                ],
                "alerts": report.alerts,
            }
            filepath.write_text(json.dumps(data, indent=2, default=str))
        elif fmt == "html":
            html = self._render_daily_html(report)
            filepath.write_text(html)

        self._logger.info("daily_report_exported", path=str(filepath), format=fmt)
        return filepath

    def export_weekly_report(self, report: WeeklyPerformanceReport, fmt: str = "json") -> Path:
        """Export weekly report to file."""
        filename = f"weekly_perf_{report.week_end}.{fmt}"
        filepath = self.output_dir / filename

        if fmt == "json":
            data = {
                "type": "weekly_performance_report",
                "period": f"{report.week_start} to {report.week_end}",
                "pnl": {
                    "total": report.total_pnl,
                    "pct": report.total_pnl_pct,
                    "by_day": report.pnl_by_day,
                    "by_pair": report.pnl_by_pair,
                },
                "trades": {
                    "taken": report.trades_taken,
                    "wins": report.wins,
                    "losses": report.losses,
                    "win_rate": report.win_rate,
                    "best_trade": report.best_trade_pnl,
                    "worst_trade": report.worst_trade_pnl,
                },
                "metrics": {
                    "sharpe": report.metrics.sharpe,
                    "sortino": report.metrics.sortino,
                    "calmar": report.metrics.calmar,
                    "max_drawdown_pct": report.metrics.max_drawdown_pct,
                    "profit_factor": report.metrics.profit_factor,
                    "avg_r_multiple": report.metrics.avg_r_multiple,
                    "expectancy": report.metrics.expectancy,
                },
                "drawdown_path": report.drawdown_path,
            }
            filepath.write_text(json.dumps(data, indent=2, default=str))
        elif fmt == "html":
            html = self._render_weekly_html(report)
            filepath.write_text(html)

        self._logger.info("weekly_report_exported", path=str(filepath), format=fmt)
        return filepath

    def export_monthly_audit(self, report: MonthlyAuditReport, fmt: str = "json") -> Path:
        """Export monthly audit report to file."""
        filename = f"monthly_audit_{report.month}.{fmt}"
        filepath = self.output_dir / filename

        if fmt == "json":
            data = {
                "type": "monthly_audit_report",
                "month": report.month,
                "summary": {
                    "total_trades": report.total_trades,
                    "total_pnl": report.total_pnl,
                    "win_rate": report.win_rate,
                    "profit_factor": report.profit_factor,
                    "avg_r_multiple": report.avg_r_multiple,
                    "largest_win": report.largest_win,
                    "largest_loss": report.largest_loss,
                    "consecutive_wins": report.consecutive_wins,
                    "consecutive_losses": report.consecutive_losses,
                },
                "win_rates": {
                    "by_pair": report.win_rate_by_pair,
                    "by_setup": report.win_rate_by_setup,
                    "by_agent": report.win_rate_by_agent,
                    "by_session": report.win_rate_by_session,
                },
                "confidence_analysis": {
                    "avg_wins": report.avg_confidence_wins,
                    "avg_losses": report.avg_confidence_losses,
                },
                "recommendations": report.recommendations,
            }
            filepath.write_text(json.dumps(data, indent=2, default=str))
        elif fmt == "html":
            html = self._render_monthly_html(report)
            filepath.write_text(html)

        self._logger.info("monthly_audit_exported", path=str(filepath), format=fmt)
        return filepath

    # ═══════════════════════════════════════════════════════
    # HTML Renderers (inline templates)
    # ═══════════════════════════════════════════════════════

    def _render_daily_html(self, report: DailyRiskReport) -> str:
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Daily Risk Report — {report.date}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;background:#0d1117;color:#c9d1d9}}
h1{{color:#58a6ff}}h2{{color:#f0883e;margin-top:2rem}}table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px 12px;text-align:left;border-bottom:1px solid #30363d}}
.alert{{padding:12px;margin:8px 0;border-radius:6px;background:#1a1f2b;border-left:4px solid #f0883e}}
.critical{{border-left-color:#f85149}}.ok{{border-left-color:#3fb950}}
.metric{{font-size:2rem;font-weight:700;color:#58a6ff}}.label{{font-size:0.8rem;color:#8b949e;text-transform:uppercase}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:1rem 0}}
</style></head><body>
<h1>🧠 Noema Daily Risk Report</h1>
<p>{report.date}</p>
<div class="grid">
<div><span class="label">Balance</span><br><span class="metric">${report.account_balance:,.2f}</span></div>
<div><span class="label">Equity</span><br><span class="metric">${report.account_equity:,.2f}</span></div>
<div><span class="label">Daily P&L</span><br><span class="metric" style="color:{'#3fb950' if report.daily_pnl>=0 else '#f85149'}">${report.daily_pnl:,.2f}</span></div>
<div><span class="label">Open Positions</span><br><span class="metric">{report.open_positions}</span></div>
</div>
<h2>Risk Analytics</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>VaR 95%</td><td>${report.var.var_95:,.2f} ({report.var.var_95_pct}%)</td></tr>
<tr><td>CVaR 95%</td><td>${report.var.cvar_95:,.2f} ({report.var.cvar_95_pct}%)</td></tr>
<tr><td>Max Pair Exposure</td><td>{report.concentration.max_pair_name} — {report.concentration.max_pair_exposure_pct}%</td></tr>
<tr><td>HHI Index</td><td>{report.concentration.hhi_index}</td></tr>
<tr><td>Margin Used</td><td>{report.margin_used_pct}%</td></tr>
</table>
{''.join(f'<div class="alert">{a}</div>' for a in report.alerts) if report.alerts else '<div class="alert ok">✅ No alerts</div>'}
</body></html>"""

    def _render_weekly_html(self, report: WeeklyPerformanceReport) -> str:
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Weekly Performance — {report.week_end}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;background:#0d1117;color:#c9d1d9}}
h1{{color:#58a6ff}}h2{{color:#f0883e;margin-top:2rem}}table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px 12px;border-bottom:1px solid #30363d}}
.metric{{font-size:2rem;font-weight:700;color:#58a6ff}}.label{{font-size:0.8rem;color:#8b949e}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:1rem 0}}
</style></head><body>
<h1>📊 Noema Weekly Performance</h1>
<p>{report.week_start} → {report.week_end}</p>
<div class="grid">
<div><span class="label">Total P&L</span><br><span class="metric" style="color:{'#3fb950' if report.total_pnl>=0 else '#f85149'}">${report.total_pnl:,.2f}</span></div>
<div><span class="label">Win Rate</span><br><span class="metric">{report.win_rate}%</span></div>
<div><span class="label">Trades</span><br><span class="metric">{report.trades_taken}</span></div>
<div><span class="label">Best Trade</span><br><span class="metric" style="color:#3fb950">${report.best_trade_pnl:,.2f}</span></div>
</div>
<h2>Risk-Adjusted Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Sharpe Ratio</td><td>{report.metrics.sharpe}</td></tr>
<tr><td>Sortino Ratio</td><td>{report.metrics.sortino}</td></tr>
<tr><td>Calmar Ratio</td><td>{report.metrics.calmar}</td></tr>
<tr><td>Max Drawdown</td><td>{report.metrics.max_drawdown_pct}%</td></tr>
<tr><td>Profit Factor</td><td>{report.metrics.profit_factor}</td></tr>
<tr><td>Expectancy</td><td>${report.metrics.expectancy:,.2f}/trade</td></tr>
</table>
</body></html>"""

    def _render_monthly_html(self, report: MonthlyAuditReport) -> str:
        pairs_rows = "\n".join(
            f"<tr><td>{p}</td><td>{wr}%</td></tr>"
            for p, wr in sorted(report.win_rate_by_pair.items(), key=lambda x: x[1], reverse=True)
        )
        recs_html = "\n".join(f"<li>{r}</li>" for r in report.recommendations) if report.recommendations else "<li>No recommendations</li>"
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Monthly Audit — {report.month}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:800px;margin:2rem auto;background:#0d1117;color:#c9d1d9}}
h1{{color:#58a6ff}}h2{{color:#f0883e;margin-top:2rem}}table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px 12px;border-bottom:1px solid #30363d}}
.metric{{font-size:2rem;font-weight:700;color:#58a6ff}}.label{{font-size:0.8rem;color:#8b949e}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:1rem 0}}
ul{{padding-left:20px}}li{{margin:6px 0}}
</style></head><body>
<h1>📋 Noema Monthly Audit</h1>
<p>{report.month}</p>
<div class="grid">
<div><span class="label">Total P&L</span><br><span class="metric" style="color:{'#3fb950' if report.total_pnl>=0 else '#f85149'}">${report.total_pnl:,.2f}</span></div>
<div><span class="label">Win Rate</span><br><span class="metric">{report.win_rate}%</span></div>
<div><span class="label">Profit Factor</span><br><span class="metric">{report.profit_factor}</span></div>
<div><span class="label">Avg R</span><br><span class="metric">{report.avg_r_multiple}R</span></div>
</div>
<h2>Win Rate by Pair</h2>
<table>{pairs_rows}</table>
<h2>Streaks</h2>
<table>
<tr><td>Consecutive Wins</td><td>{report.consecutive_wins}</td></tr>
<tr><td>Consecutive Losses</td><td style="color:{'#f85149' if report.consecutive_losses > 5 else '#c9d1d9'}">{report.consecutive_losses}</td></tr>
</table>
<h2>Confidence Analysis</h2>
<table>
<tr><td>Avg Confidence (Wins)</td><td>{report.avg_confidence_wins}</td></tr>
<tr><td>Avg Confidence (Losses)</td><td>{report.avg_confidence_losses}</td></tr>
</table>
<h2>Recommendations</h2><ul>{recs_html}</ul>
</body></html>"""


# ═══════════════════════════════════════════════════════════
# Pure Math Helpers
# ═══════════════════════════════════════════════════════════

def _gini_coefficient(values: list[float]) -> float:
    """Calculate Gini coefficient (inequality measure)."""
    if not values or len(values) < 2:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean_val = statistics.mean(sorted_vals)
    if mean_val == 0:
        return 0.0
    sum_abs_diff = sum(
        abs(sorted_vals[i] - sorted_vals[j])
        for i in range(n)
        for j in range(n)
    )
    return sum_abs_diff / (2 * n * n * mean_val)


def _max_drawdown(returns: list[float]) -> float:
    """Calculate maximum drawdown from a return series."""
    if not returns:
        return 0.0
    peak = returns[0]
    max_dd = 0.0
    cumulative = returns[0]
    for r in returns[1:]:
        cumulative += r
        peak = max(peak, cumulative)
        dd = (peak - cumulative)
        if peak > 0:
            dd_pct = dd / peak
            max_dd = max(max_dd, dd_pct)
    return max_dd


def _group_win_rate(
    trades: list[dict[str, Any]],
    *keys: str,
) -> dict[str, float]:
    """Calculate win rate grouped by a configurable key field."""
    result: dict[str, float] = {}
    for t in trades:
        group = None
        for k in keys:
            val = t.get(k, "")
            if val:
                group = str(val)
                break
        if group is None:
            group = "unknown"
        if group not in result:
            group_trades = []
            for x in trades:
                x_val = None
                for k in keys:
                    v = x.get(k, "")
                    if v:
                        x_val = str(v)
                        break
                if (x_val or "unknown") == group:
                    group_trades.append(x)
            wins = sum(1 for x in group_trades if x.get("pnl", 0) > 0)
            result[group] = wins / len(group_trades) if group_trades else 0.0
    return result
