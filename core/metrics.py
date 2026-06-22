"""Prometheus metrics and monitoring for VMPM.

Tracks:
- Pipeline latency (per phase, per agent)
- LLM call metrics (latency, errors, cache hits)
- Trade metrics (win rate, P&L, drawdown)
- System health (MT5 connection, memory, uptime)
"""

from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Try to import prometheus_client, fall back to no-op if not available
try:
    from prometheus_client import (
        Counter, Gauge, Histogram, Info, CollectorRegistry,
        generate_latest, CONTENT_TYPE_LATEST,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client_not_installed", hint="pip install prometheus-client")


# ── Metrics Definitions ──────────────────────────────────────────────

if PROMETHEUS_AVAILABLE:
    # Pipeline metrics
    PIPELINE_LATENCY = Histogram(
        "vmpm_pipeline_latency_seconds",
        "Total pipeline execution time",
        ["symbol", "phase"],
        buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    )

    PIPELINE_DECISIONS = Counter(
        "vmpm_pipeline_decisions_total",
        "Pipeline trade decisions",
        ["symbol", "decision"],
    )

    # LLM metrics
    LLM_CALLS = Counter(
        "vmpm_llm_calls_total",
        "Total LLM API calls",
        ["agent", "tier", "status"],
    )

    LLM_LATENCY = Histogram(
        "vmpm_llm_latency_seconds",
        "LLM API call latency",
        ["agent", "tier"],
        buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    )

    LLM_CACHE = Counter(
        "vmpm_llm_cache_total",
        "LLM cache hits/misses",
        ["result"],  # hit or miss
    )

    # Trade metrics
    TRADES_OPENED = Counter(
        "vmpm_trades_opened_total",
        "Total trades opened",
        ["symbol", "direction"],
    )

    TRADES_CLOSED = Counter(
        "vmpm_trades_closed_total",
        "Total trades closed",
        ["symbol", "outcome"],  # win, loss, breakeven
    )

    TRADE_PNL = Gauge(
        "vmpm_trade_pnl",
        "Trade P&L",
        ["symbol", "trade_id"],
    )

    DAILY_PNL = Gauge(
        "vmpm_daily_pnl",
        "Daily P&L percentage",
    )

    OPEN_POSITIONS = Gauge(
        "vmpm_open_positions",
        "Number of open positions",
    )

    # System metrics
    MT5_CONNECTED = Gauge(
        "vmpm_mt5_connected",
        "MT5 connection status (1=connected, 0=disconnected)",
    )

    SYSTEM_UPTIME = Gauge(
        "vmpm_uptime_seconds",
        "System uptime in seconds",
    )

    SYSTEM_INFO = Info(
        "vmpm_system",
        "VMPM system information",
    )


# ── Metrics Collector ────────────────────────────────────────────────

class MetricsCollector:
    """Collects and exposes VMPM metrics for Prometheus scraping.

    Usage:
        metrics = MetricsCollector()
        metrics.record_pipeline_latency("EURUSD", "decision", 1.5)
        metrics.record_llm_call("thesis", "standard", 2.3, cache_hit=False)
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and PROMETHEUS_AVAILABLE
        self._start_time = time.time()

    def record_pipeline_latency(self, symbol: str, phase: str, latency_seconds: float) -> None:
        if self.enabled:
            PIPELINE_LATENCY.labels(symbol=symbol, phase=phase).observe(latency_seconds)

    def record_pipeline_decision(self, symbol: str, decision: str) -> None:
        if self.enabled:
            PIPELINE_DECISIONS.labels(symbol=symbol, decision=decision).inc()

    def record_llm_call(
        self,
        agent: str,
        tier: str,
        latency_seconds: float,
        cache_hit: bool = False,
        error: bool = False,
    ) -> None:
        if self.enabled:
            status = "error" if error else ("cache_hit" if cache_hit else "success")
            LLM_CALLS.labels(agent=agent, tier=tier, status=status).inc()
            if not cache_hit:
                LLM_LATENCY.labels(agent=agent, tier=tier).observe(latency_seconds)
            LLM_CACHE.labels(result="hit" if cache_hit else "miss").inc()

    def record_trade_opened(self, symbol: str, direction: str) -> None:
        if self.enabled:
            TRADES_OPENED.labels(symbol=symbol, direction=direction).inc()
            OPEN_POSITIONS.inc()

    def record_trade_closed(self, symbol: str, pnl: float, outcome: str) -> None:
        if self.enabled:
            TRADES_CLOSED.labels(symbol=symbol, outcome=outcome).inc()
            OPEN_POSITIONS.dec()
            DAILY_PNL.set(pnl)

    def set_mt5_connected(self, connected: bool) -> None:
        if self.enabled:
            MT5_CONNECTED.set(1 if connected else 0)

    def update_uptime(self) -> None:
        if self.enabled:
            SYSTEM_UPTIME.set(time.time() - self._start_time)

    def set_system_info(self, version: str, pairs: list[str]) -> None:
        if self.enabled:
            SYSTEM_INFO.info({
                "version": version,
                "pairs": ",".join(pairs),
                "python": "3.11+",
            })

    def get_metrics_page(self) -> tuple[bytes, str]:
        """Return Prometheus metrics page for scraping."""
        if not self.enabled:
            return b"# Prometheus not available\n", "text/plain"
        self.update_uptime()
        return generate_latest(), CONTENT_TYPE_LATEST
