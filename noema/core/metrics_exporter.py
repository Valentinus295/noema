"""
Noema Metrics Exporter — enriched Prometheus metrics for dashboard.

Extends noema.core.metrics with:
- Agent call counters (per agent, per phase)
- LLM call gauges (concurrent, total, error rate)
- Position/exposure gauges
- Trade P&L histograms
- Pipeline latency histograms (per phase)
- Kill-switch activation counter

All metrics are exported via Prometheus scraping endpoint (:8000/metrics).
Dashboard (Grafana) consumes these for real-time monitoring.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    from prometheus_client import (
        Counter, Gauge, Histogram, Enum,
        generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════
# Metric Definitions
# ══════════════════════════════════════════════════════════════════════

if PROMETHEUS_AVAILABLE:
    # ── Agent Metrics ────────────────────────────────────────────
    AGENT_CALLS = Counter(
        "noema_agent_calls_total",
        "Total agent execution calls",
        ["agent", "phase", "status"],  # status: success, error, timeout
    )

    AGENT_LATENCY = Histogram(
        "noema_agent_latency_seconds",
        "Agent execution latency",
        ["agent", "phase"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    )

    AGENT_CONFIDENCE = Histogram(
        "noema_agent_confidence",
        "Agent confidence distribution (0.0-1.0)",
        ["agent"],
        buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    )

    AGENT_SIGNAL_DISTRIBUTION = Counter(
        "noema_agent_signals_total",
        "Agent signal distribution",
        ["agent", "signal"],  # BULLISH, BEARISH, NEUTRAL, ERROR
    )

    # ── LLM Metrics ──────────────────────────────────────────────
    LLM_CALLS_TOTAL = Counter(
        "noema_llm_calls_total",
        "Total LLM API calls",
        ["agent", "model", "tier", "status"],  # status: success, error, timeout, cache_hit
    )

    LLM_LATENCY_SECONDS = Histogram(
        "noema_llm_latency_seconds",
        "LLM API call latency",
        ["agent", "model"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0],
    )

    LLM_TOKENS_TOTAL = Counter(
        "noema_llm_tokens_total",
        "Total LLM tokens consumed",
        ["agent", "type"],  # type: prompt, completion
    )

    LLM_CONCURRENT = Gauge(
        "noema_llm_concurrent_calls",
        "Currently in-flight LLM calls",
        ["agent"],
    )

    LLM_ERROR_RATE = Gauge(
        "noema_llm_error_rate",
        "Rolling LLM error rate (0.0-1.0)",
        ["agent"],
    )

    LLM_COST_USD = Counter(
        "noema_llm_cost_usd_total",
        "Estimated LLM cost in USD",
        ["agent", "model"],
    )

    # ── Pipeline Metrics ─────────────────────────────────────────
    PIPELINE_PHASE_LATENCY = Histogram(
        "noema_pipeline_phase_latency_seconds",
        "Pipeline phase execution time",
        ["phase"],  # data, analysis, decision, execution, learning
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    )

    PIPELINE_CYCLE_LATENCY = Histogram(
        "noema_pipeline_cycle_latency_seconds",
        "Full pipeline cycle time per symbol",
        ["symbol"],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],
    )

    PIPELINE_CYCLE_COUNT = Counter(
        "noema_pipeline_cycles_total",
        "Total pipeline cycles executed",
        ["symbol"],
    )

    PIPELINE_ERROR_COUNT = Counter(
        "noema_pipeline_errors_total",
        "Pipeline execution errors",
        ["symbol", "phase"],
    )

    # ── Trade Metrics ────────────────────────────────────────────
    TRADE_DECISIONS = Counter(
        "noema_trade_decisions_total",
        "Total trade decisions made",
        ["symbol", "decision"],  # BUY, SELL, NO_TRADE
    )

    TRADE_PNL_HISTOGRAM = Histogram(
        "noema_trade_pnl_pct",
        "Trade P&L distribution (%)",
        ["symbol", "direction"],
        buckets=[-5.0, -3.0, -2.0, -1.0, -0.5, -0.25, -0.1, 0.0,
                 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
    )

    TRADE_HOLD_TIME = Histogram(
        "noema_trade_hold_time_seconds",
        "Trade hold time distribution",
        ["symbol", "outcome"],
        buckets=[60, 300, 900, 1800, 3600, 7200, 14400, 28800,
                 86400, 172800, 604800],
    )

    # ── Position / Risk Metrics ──────────────────────────────────
    OPEN_POSITIONS_GAUGE = Gauge(
        "noema_open_positions",
        "Number of currently open positions",
        ["symbol"],
    )

    ACCOUNT_EXPOSURE = Gauge(
        "noema_account_exposure_pct",
        "Current account exposure (%)",
    )

    DAILY_PNL_PCT = Gauge(
        "noema_daily_pnl_pct",
        "Day's P&L as % of account",
    )

    WEEKLY_PNL_PCT = Gauge(
        "noema_weekly_pnl_pct",
        "Week's P&L as % of account",
    )

    MAX_DRAWDOWN = Gauge(
        "noema_max_drawdown_pct",
        "Maximum drawdown from peak (%)",
    )

    CURRENT_DRAWDOWN = Gauge(
        "noema_current_drawdown_pct",
        "Current drawdown from peak (%)",
    )

    WIN_RATE = Gauge(
        "noema_win_rate",
        "Rolling win rate (0.0-1.0)",
    )

    SHARPE_RATIO = Gauge(
        "noema_sharpe_ratio",
        "Rolling Sharpe ratio",
    )

    # ── Kill Switch Metrics ──────────────────────────────────────
    KILL_SWITCH_ACTIVATIONS = Counter(
        "noema_kill_switch_activations_total",
        "Total kill-switch activations",
        ["reason", "symbol"],
    )

    KILL_SWITCH_ACTIVE = Gauge(
        "noema_kill_switch_active",
        "Whether kill-switch is currently active (1=active, 0=inactive)",
    )

    # ── Phase 1.5: News Blackout Metrics ───────────────────────
    NEWS_BLACKOUT_ACTIVE = Gauge(
        "noema_news_blackout_active",
        "News blackout active per pair (1=blackout, 0=trading)",
        ["pair"],
    )

    EVENT_IMPACT_TRIGGERED = Counter(
        "noema_event_impact_triggered_total",
        "Total event impact triggers",
        ["event_name", "pair"],
    )

    DAILY_LOSS_LIMIT_PCT = Gauge(
        "noema_daily_loss_limit_remaining_pct",
        "Remaining loss limit for the day (%)",
    )

    # ── System / Connection Metrics ──────────────────────────────
    MT5_PING_MS = Histogram(
        "noema_mt5_ping_ms",
        "MT5 connection ping latency",
        buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
    )

    REDIS_CONNECTED = Gauge(
        "noema_redis_connected",
        "Redis connection status (1=connected, 0=disconnected)",
    )

    POSTGRES_CONNECTED = Gauge(
        "noema_postgres_connected",
        "PostgreSQL connection status (1=connected, 0=disconnected)",
    )

    CACHE_HIT_RATE = Gauge(
        "noema_cache_hit_rate",
        "LLM cache hit rate (0.0-1.0)",
    )

    MEMORY_USAGE_BYTES = Gauge(
        "noema_memory_usage_bytes",
        "Process memory usage (RSS)",
    )


# ══════════════════════════════════════════════════════════════════════
# Metrics Collector
# ══════════════════════════════════════════════════════════════════════

@dataclass
class MetricsSnapshot:
    """Snapshot of current system metrics for import into the dashboard."""
    timestamp: float = field(default_factory=time.time)
    open_positions: int = 0
    account_exposure_pct: float = 0.0
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    daily_loss_remaining_pct: float = 3.0
    kill_switch_active: bool = False
    mt5_connected: bool = False
    redis_connected: bool = False
    postgres_connected: bool = False
    cache_hit_rate: float = 0.0
    pipeline_running: bool = False
    total_cycles: int = 0
    total_trades: int = 0
    total_llm_calls: int = 0
    total_errors: int = 0


class MetricsExporter:
    """Enriched metrics collection and export for Noema.

    Tracks everything needed for the Grafana dashboard:
    - Agent performance (calls, latency, confidence, signals)
    - LLM usage (tokens, cost, latency, errors)
    - Pipeline health (phase latencies, cycles, errors)
    - Trade performance (P&L, win rate, Sharpe, drawdown)
    - Risk state (exposure, kill-switch, loss limits)
    - System health (connections, memory)

    Usage:
        exporter = MetricsExporter()
        exporter.record_agent_call("market-structure", "analysis", "success", 0.025, 0.85, "BULLISH")
        exporter.record_llm_call("thesis", "nemotron-3-super", "standard", "success", 1.5, 350, 150)
        exporter.record_trade_pnl("EURUSD", "buy", 0.35)
        exporter.update_snapshot(open_positions=2, daily_pnl=1.5)
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and PROMETHEUS_AVAILABLE
        self._start_time = time.time()
        self._snapshot = MetricsSnapshot()

        # Rolling counters for rate calculation
        self._llm_stats: dict[str, dict[str, int]] = {}  # agent → {total, errors}
        self._trade_outcomes: list[float] = []  # recent P&L %

        if not self.enabled:
            logger.info("metrics_exporter_disabled", reason="prometheus not installed")

    # ── Agent Tracking ──────────────────────────────────────────────

    def record_agent_call(
        self,
        agent: str,
        phase: str,
        status: str,  # "success", "error", "timeout"
        latency_seconds: float,
        confidence: float = 0.0,
        signal: str = "NEUTRAL",
    ) -> None:
        """Record an agent execution call with full metadata."""
        if not self.enabled:
            return
        AGENT_CALLS.labels(agent=agent, phase=phase, status=status).inc()
        AGENT_LATENCY.labels(agent=agent, phase=phase).observe(latency_seconds)
        AGENT_CONFIDENCE.labels(agent=agent).observe(confidence)
        AGENT_SIGNAL_DISTRIBUTION.labels(agent=agent, signal=signal).inc()

    # ── LLM Tracking ────────────────────────────────────────────────

    def record_llm_call(
        self,
        agent: str,
        model: str,
        tier: str,
        status: str,  # "success", "error", "timeout", "cache_hit"
        latency_seconds: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Record an LLM API call with token usage and latency."""
        if not self.enabled:
            return
        LLM_CALLS_TOTAL.labels(agent=agent, model=model, tier=tier, status=status).inc()
        LLM_LATENCY_SECONDS.labels(agent=agent, model=model).observe(latency_seconds)
        LLM_TOKENS_TOTAL.labels(agent=agent, type="prompt").inc(prompt_tokens)
        LLM_TOKENS_TOTAL.labels(agent=agent, type="completion").inc(completion_tokens)

        # Track rolling error rate
        if agent not in self._llm_stats:
            self._llm_stats[agent] = {"total": 0, "errors": 0}
        self._llm_stats[agent]["total"] += 1
        if status == "error":
            self._llm_stats[agent]["errors"] += 1
        total = self._llm_stats[agent]["total"]
        errors = self._llm_stats[agent]["errors"]
        LLM_ERROR_RATE.labels(agent=agent).set(errors / total if total > 0 else 0)

    def record_llm_cost(
        self,
        agent: str,
        model: str,
        cost_usd: float,
    ) -> None:
        """Record estimated LLM cost."""
        if not self.enabled:
            return
        if cost_usd > 0:
            LLM_COST_USD.labels(agent=agent, model=model).inc(cost_usd)

    def set_llm_concurrent(self, agent: str, count: int) -> None:
        """Track in-flight LLM calls."""
        if not self.enabled:
            return
        LLM_CONCURRENT.labels(agent=agent).set(count)

    # ── Pipeline Tracking ───────────────────────────────────────────

    def record_pipeline_phase(self, phase: str, latency_seconds: float) -> None:
        """Record pipeline phase execution time."""
        if not self.enabled:
            return
        PIPELINE_PHASE_LATENCY.labels(phase=phase).observe(latency_seconds)

    def record_pipeline_cycle(
        self,
        symbol: str,
        latency_seconds: float,
        error: bool = False,
        error_phase: str = "",
    ) -> None:
        """Record a complete pipeline cycle."""
        if not self.enabled:
            return
        PIPELINE_CYCLE_LATENCY.labels(symbol=symbol).observe(latency_seconds)
        PIPELINE_CYCLE_COUNT.labels(symbol=symbol).inc()
        if error:
            PIPELINE_ERROR_COUNT.labels(symbol=symbol, phase=error_phase).inc()
        self._snapshot.total_cycles += 1

    # ── Trade Tracking ──────────────────────────────────────────────

    def record_trade_decision(self, symbol: str, decision: str) -> None:
        """Record a trade decision (BUY/SELL/NO_TRADE)."""
        if not self.enabled:
            return
        TRADE_DECISIONS.labels(symbol=symbol, decision=decision).inc()
        if decision != "NO_TRADE":
            self._snapshot.total_trades += 1

    def record_trade_pnl(
        self,
        symbol: str,
        direction: str,
        pnl_pct: float,
        hold_time_seconds: float = 0,
        outcome: str = "win",
    ) -> None:
        """Record trade P&L for histogram and outcome tracking."""
        if not self.enabled:
            return
        TRADE_PNL_HISTOGRAM.labels(symbol=symbol, direction=direction).observe(pnl_pct)
        if hold_time_seconds > 0:
            TRADE_HOLD_TIME.labels(symbol=symbol, outcome=outcome).observe(hold_time_seconds)

        # Update rolling win rate
        self._trade_outcomes.append(1.0 if pnl_pct > 0 else 0.0)
        if len(self._trade_outcomes) > 500:
            self._trade_outcomes = self._trade_outcomes[-500:]
        if self._trade_outcomes:
            wr = sum(self._trade_outcomes) / len(self._trade_outcomes)
            WIN_RATE.set(wr)

    # ── Position / Risk Tracking ────────────────────────────────────

    def update_positions(
        self,
        positions: dict[str, int],  # symbol → count
    ) -> None:
        """Update open position gauges per symbol."""
        if not self.enabled:
            return
        for symbol, count in positions.items():
            OPEN_POSITIONS_GAUGE.labels(symbol=symbol).set(count)
        total = sum(positions.values())
        self._snapshot.open_positions = total

    def update_exposure(self, exposure_pct: float) -> None:
        """Update account exposure gauge."""
        if not self.enabled:
            return
        ACCOUNT_EXPOSURE.set(exposure_pct)
        self._snapshot.account_exposure_pct = exposure_pct

    def update_daily_pnl(self, pnl_pct: float) -> None:
        """Update daily P&L gauge."""
        if not self.enabled:
            return
        DAILY_PNL_PCT.set(pnl_pct)
        self._snapshot.daily_pnl_pct = pnl_pct

    def update_weekly_pnl(self, pnl_pct: float) -> None:
        """Update weekly P&L gauge."""
        if not self.enabled:
            return
        WEEKLY_PNL_PCT.set(pnl_pct)
        self._snapshot.weekly_pnl_pct = pnl_pct

    def update_drawdown(self, current_pct: float, max_pct: float) -> None:
        """Update drawdown gauges."""
        if not self.enabled:
            return
        CURRENT_DRAWDOWN.set(current_pct)
        MAX_DRAWDOWN.set(max_pct)
        self._snapshot.current_drawdown_pct = current_pct
        self._snapshot.max_drawdown_pct = max_pct

    def update_sharpe(self, sharpe: float) -> None:
        """Update rolling Sharpe ratio."""
        if not self.enabled:
            return
        SHARPE_RATIO.set(sharpe)
        self._snapshot.sharpe_ratio = sharpe

    # ── Kill Switch Tracking ────────────────────────────────────────

    def set_news_blackout_active(self, active: bool, pair: str = "system") -> None:
        """Set the news blackout Prometheus gauge (Phase 1.5).

        Called by EventAnalyst→Guardian when blackout is activated/deactivated.
        COO condition #3.
        """
        if not self.enabled:
            return
        NEWS_BLACKOUT_ACTIVE.labels(pair=pair).set(1 if active else 0)

    def record_event_impact_triggered(
        self, event_name: str = "", pair: str = "", blocked: bool = True
    ) -> None:
        """Record an event impact trigger (Phase 1.5).

        Tracks when a high-impact economic event triggers trading halts.
        """
        if not self.enabled:
            return
        if blocked and event_name:
            EVENT_IMPACT_TRIGGERED.labels(event_name=event_name, pair=pair).inc()

    def record_kill_switch(self, reason: str, symbol: str = "") -> None:
        """Record a kill-switch activation."""
        if not self.enabled:
            return
        KILL_SWITCH_ACTIVATIONS.labels(reason=reason, symbol=symbol or "system").inc()

    def set_kill_switch_active(self, active: bool) -> None:
        """Set kill-switch active state."""
        if not self.enabled:
            return
        KILL_SWITCH_ACTIVE.set(1 if active else 0)
        self._snapshot.kill_switch_active = active

    def update_daily_loss_remaining(self, remaining_pct: float) -> None:
        """Update remaining daily loss limit."""
        if not self.enabled:
            return
        DAILY_LOSS_LIMIT_PCT.set(remaining_pct)
        self._snapshot.daily_loss_remaining_pct = remaining_pct

    # ── Connection / System Tracking ────────────────────────────────

    def set_mt5_connected(self, connected: bool, ping_ms: float = 0.0) -> None:
        """Update MT5 connection status."""
        if not self.enabled:
            return
        if ping_ms > 0:
            MT5_PING_MS.observe(ping_ms)
        self._snapshot.mt5_connected = connected

    def set_redis_connected(self, connected: bool) -> None:
        """Update Redis connection status."""
        if not self.enabled:
            return
        REDIS_CONNECTED.set(1 if connected else 0)
        self._snapshot.redis_connected = connected

    def set_postgres_connected(self, connected: bool) -> None:
        """Update PostgreSQL connection status."""
        if not self.enabled:
            return
        POSTGRES_CONNECTED.set(1 if connected else 0)
        self._snapshot.postgres_connected = connected

    def update_cache_hit_rate(self, hit_rate: float) -> None:
        """Update LLM cache hit rate."""
        if not self.enabled:
            return
        CACHE_HIT_RATE.set(hit_rate)
        self._snapshot.cache_hit_rate = hit_rate

    def update_memory_usage(self) -> None:
        """Update process memory usage from OS."""
        if not self.enabled:
            return
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # ru_maxrss is in KB on Linux
            MEMORY_USAGE_BYTES.set(rss * 1024)
        except Exception:
            pass

    def record_latency(self, metric_name: str, value_s: float, labels: dict[str, str] | None = None) -> None:
        """Record generic latency value (exported for pipeline use)."""
        if not self.enabled:
            return
        # Use the existing pipeline phase latency histogram
        phase = labels.get("phase", metric_name) if labels else metric_name
        PIPELINE_PHASE_LATENCY.labels(phase=phase).observe(value_s)

    # ── Snapshot (for dashboard API) ─────────────────────────────────

    def get_snapshot(self) -> MetricsSnapshot:
        """Return current metrics snapshot for dashboard consumption."""
        self.update_memory_usage()
        return self._snapshot

    def get_snapshot_dict(self) -> dict[str, Any]:
        """Return snapshot as plain dict for JSON serialization."""
        snap = self.get_snapshot()
        return {
            "timestamp": snap.timestamp,
            "open_positions": snap.open_positions,
            "account_exposure_pct": snap.account_exposure_pct,
            "daily_pnl_pct": snap.daily_pnl_pct,
            "weekly_pnl_pct": snap.weekly_pnl_pct,
            "win_rate": snap.win_rate,
            "sharpe_ratio": snap.sharpe_ratio,
            "max_drawdown_pct": snap.max_drawdown_pct,
            "current_drawdown_pct": snap.current_drawdown_pct,
            "daily_loss_remaining_pct": snap.daily_loss_remaining_pct,
            "kill_switch_active": snap.kill_switch_active,
            "mt5_connected": snap.mt5_connected,
            "redis_connected": snap.redis_connected,
            "postgres_connected": snap.postgres_connected,
            "cache_hit_rate": snap.cache_hit_rate,
            "pipeline_running": snap.pipeline_running,
            "total_cycles": snap.total_cycles,
            "total_trades": snap.total_trades,
            "total_llm_calls": snap.total_llm_calls,
            "total_errors": snap.total_errors,
            "uptime_seconds": time.time() - self._start_time,
        }

    # ── Prometheus Export ────────────────────────────────────────────

    def get_metrics_page(self) -> tuple[bytes, str]:
        """Return Prometheus metrics page for scraping."""
        if not self.enabled:
            return b"# Prometheus not available\n", "text/plain"
        self.update_memory_usage()
        return generate_latest(), CONTENT_TYPE_LATEST
