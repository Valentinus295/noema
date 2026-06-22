"""
Noema Health Check — system status endpoint for dashboard and Prometheus.

Provides:
- Agent health (all 17 agents, state, last execution time)
- Infrastructure health (Redis, PostgreSQL, MT5, NIM)
- Pipeline status (current phase, last cycle time, error count)
- Kill-switch state
- Uptime and version info

Consumed by:
- Dashboard (Grafana) via /health endpoint
- Prometheus blackbox exporter for alerting
- Kubernetes/health-check probes (liveness + readiness)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class AgentHealth:
    """Health status for a single agent."""
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_execution_at: float = 0.0
    last_execution_latency_ms: float = 0.0
    last_signal: str = "NEUTRAL"
    total_calls: int = 0
    total_errors: int = 0
    error_rate: float = 0.0


@dataclass
class ConnectionHealth:
    """Health status for an external connection."""
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    connected: bool = False
    ping_ms: float = 0.0
    last_checked_at: float = 0.0
    error_message: str = ""


@dataclass
class SystemHealth:
    """Complete system health snapshot."""
    # Meta
    timestamp: float = field(default_factory=time.time)
    version: str = "2.0.0"
    uptime_seconds: float = 0.0
    environment: str = "development"

    # Overall
    overall_status: HealthStatus = HealthStatus.UNKNOWN

    # Agents
    agents: list[AgentHealth] = field(default_factory=list)
    agents_healthy: int = 0
    agents_degraded: int = 0
    agents_unhealthy: int = 0

    # Connections
    connections: list[ConnectionHealth] = field(default_factory=list)

    # Pipeline
    pipeline_running: bool = False
    pipeline_current_phase: str = "idle"
    pipeline_last_cycle_ms: float = 0.0
    pipeline_total_cycles: int = 0
    pipeline_total_errors: int = 0

    # Kill-switch
    kill_switch_active: bool = False
    kill_switch_reason: str = ""

    # Trading
    open_positions: int = 0
    daily_pnl_pct: float = 0.0
    account_exposure_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict for HTTP responses."""
        return {
            "status": self.overall_status.value,
            "timestamp": self.timestamp,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "environment": self.environment,
            "agents": {
                "total": len(self.agents),
                "healthy": self.agents_healthy,
                "degraded": self.agents_degraded,
                "unhealthy": self.agents_unhealthy,
                "details": [
                    {
                        "name": a.name,
                        "status": a.status.value,
                        "last_execution_latency_ms": round(a.last_execution_latency_ms, 1),
                        "last_signal": a.last_signal,
                        "error_rate": round(a.error_rate, 4),
                        "total_calls": a.total_calls,
                    }
                    for a in self.agents
                ],
            },
            "connections": {
                c.name: {
                    "status": c.status.value,
                    "connected": c.connected,
                    "ping_ms": round(c.ping_ms, 1),
                    "error": c.error_message,
                }
                for c in self.connections
            },
            "pipeline": {
                "running": self.pipeline_running,
                "current_phase": self.pipeline_current_phase,
                "last_cycle_ms": round(self.pipeline_last_cycle_ms, 1),
                "total_cycles": self.pipeline_total_cycles,
                "total_errors": self.pipeline_total_errors,
            },
            "kill_switch": {
                "active": self.kill_switch_active,
                "reason": self.kill_switch_reason,
            },
            "trading": {
                "open_positions": self.open_positions,
                "daily_pnl_pct": round(self.daily_pnl_pct, 4),
                "account_exposure_pct": round(self.account_exposure_pct, 4),
            },
        }


class HealthChecker:
    """Collects and evaluates system health for dashboard and alerting.

    Usage:
        checker = HealthChecker(start_time=time.time())
        checker.update_agent("market-structure", HealthStatus.HEALTHY, 25.0, "BULLISH")
        health = checker.collect()  # Returns SystemHealth snapshot
    """

    def __init__(self, start_time: float | None = None):
        self._start_time = start_time or time.time()
        self._agent_health: dict[str, AgentHealth] = {}
        self._connections: dict[str, ConnectionHealth] = {}

        # Pipeline state
        self._pipeline_running = False
        self._pipeline_current_phase = "idle"
        self._pipeline_last_cycle_ms = 0.0
        self._pipeline_total_cycles = 0
        self._pipeline_total_errors = 0

        # Kill-switch
        self._kill_switch_active = False
        self._kill_switch_reason = ""

        # Trading
        self._open_positions = 0
        self._daily_pnl_pct = 0.0
        self._account_exposure_pct = 0.0

    # ── Agent Health ─────────────────────────────────────────────────

    def update_agent(
        self,
        name: str,
        status: HealthStatus,
        latency_ms: float = 0.0,
        signal: str = "NEUTRAL",
        error: bool = False,
    ) -> None:
        """Update health status for a specific agent."""
        if name not in self._agent_health:
            self._agent_health[name] = AgentHealth(name=name)
        agent = self._agent_health[name]
        agent.status = status
        agent.last_execution_at = time.time()
        agent.last_execution_latency_ms = latency_ms
        agent.last_signal = signal
        agent.total_calls += 1
        if error:
            agent.total_errors += 1
        agent.error_rate = (
            agent.total_errors / agent.total_calls
            if agent.total_calls > 0
            else 0.0
        )

    def update_agent_error(self, name: str, error_msg: str = "") -> None:
        """Mark an agent as having errored."""
        self.update_agent(name, HealthStatus.DEGRADED, error=True)
        logger.warning("agent_health_degraded", agent=name, error=error_msg)

    def ensure_all_agents(self, agent_names: list[str]) -> None:
        """Pre-register all expected agents so they appear in health checks."""
        for name in agent_names:
            if name not in self._agent_health:
                self._agent_health[name] = AgentHealth(name=name)

    # ── Connection Health ────────────────────────────────────────────

    def update_connection(
        self,
        name: str,
        connected: bool,
        ping_ms: float = 0.0,
        error_message: str = "",
    ) -> None:
        """Update health status for an external connection."""
        if name not in self._connections:
            self._connections[name] = ConnectionHealth(name=name)
        conn = self._connections[name]
        conn.connected = connected
        conn.ping_ms = ping_ms
        conn.last_checked_at = time.time()
        conn.error_message = error_message
        conn.status = HealthStatus.HEALTHY if connected else HealthStatus.UNHEALTHY

    async def check_postgres(self, dsn: str) -> None:
        """Check PostgreSQL connection health."""
        try:
            import asyncpg
            start = time.monotonic()
            conn = await asyncpg.connect(dsn, timeout=5)
            try:
                await conn.fetchval("SELECT 1")
                ping_ms = (time.monotonic() - start) * 1000
                self.update_connection("postgresql", True, ping_ms)
            finally:
                await conn.close()
        except Exception as e:
            self.update_connection("postgresql", False, error_message=str(e))

    async def check_redis(self, url: str) -> None:
        """Check Redis connection health."""
        try:
            import redis.asyncio as aioredis
            start = time.monotonic()
            r = aioredis.from_url(url, socket_connect_timeout=5)
            try:
                await r.ping()
                ping_ms = (time.monotonic() - start) * 1000
                self.update_connection("redis", True, ping_ms)
            finally:
                await r.aclose()  # type: ignore[attr-defined]
        except Exception as e:
            self.update_connection("redis", False, error_message=str(e))

    def check_mt5(self, connected: bool, ping_ms: float = 0.0) -> None:
        """Update MT5 connection health (checked by broker layer)."""
        self.update_connection("mt5", connected, ping_ms)

    def check_nim(self, connected: bool, latency_ms: float = 0.0) -> None:
        """Update NIM API health."""
        self.update_connection("nim_api", connected, latency_ms)

    # ── Pipeline / Trading State ─────────────────────────────────────

    def update_pipeline(
        self,
        running: bool = True,
        current_phase: str = "idle",
        last_cycle_ms: float = 0.0,
        total_cycles: int = 0,
        total_errors: int = 0,
    ) -> None:
        """Update pipeline state."""
        self._pipeline_running = running
        self._pipeline_current_phase = current_phase
        self._pipeline_last_cycle_ms = last_cycle_ms
        self._pipeline_total_cycles = total_cycles
        self._pipeline_total_errors = total_errors

    def update_kill_switch(self, active: bool, reason: str = "") -> None:
        """Update kill-switch state."""
        self._kill_switch_active = active
        self._kill_switch_reason = reason

    def update_trading(
        self,
        open_positions: int = 0,
        daily_pnl_pct: float = 0.0,
        account_exposure_pct: float = 0.0,
    ) -> None:
        """Update trading state."""
        self._open_positions = open_positions
        self._daily_pnl_pct = daily_pnl_pct
        self._account_exposure_pct = account_exposure_pct

    # ── Collect ──────────────────────────────────────────────────────

    def collect(self) -> SystemHealth:
        """Collect and evaluate complete system health snapshot."""
        # Count agent statuses
        agents = list(self._agent_health.values())
        healthy = sum(1 for a in agents if a.status == HealthStatus.HEALTHY)
        degraded = sum(1 for a in agents if a.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for a in agents if a.status == HealthStatus.UNHEALTHY)

        # Evaluate overall status
        connections = list(self._connections.values())
        connections_unhealthy = sum(1 for c in connections if c.status == HealthStatus.UNHEALTHY)

        if self._kill_switch_active:
            overall = HealthStatus.DEGRADED
        elif connections_unhealthy > 0 or unhealthy > 0:
            overall = HealthStatus.DEGRADED if connections_unhealthy < len(connections) else HealthStatus.UNHEALTHY
        elif degraded > 0:
            overall = HealthStatus.DEGRADED
        elif sum(1 for a in agents if a.status == HealthStatus.UNKNOWN) == len(agents):
            overall = HealthStatus.UNKNOWN
        else:
            overall = HealthStatus.HEALTHY

        return SystemHealth(
            timestamp=time.time(),
            uptime_seconds=time.time() - self._start_time,
            overall_status=overall,
            agents=agents,
            agents_healthy=healthy,
            agents_degraded=degraded,
            agents_unhealthy=unhealthy,
            connections=connections,
            pipeline_running=self._pipeline_running,
            pipeline_current_phase=self._pipeline_current_phase,
            pipeline_last_cycle_ms=self._pipeline_last_cycle_ms,
            pipeline_total_cycles=self._pipeline_total_cycles,
            pipeline_total_errors=self._pipeline_total_errors,
            kill_switch_active=self._kill_switch_active,
            kill_switch_reason=self._kill_switch_reason,
            open_positions=self._open_positions,
            daily_pnl_pct=self._daily_pnl_pct,
            account_exposure_pct=self._account_exposure_pct,
        )
