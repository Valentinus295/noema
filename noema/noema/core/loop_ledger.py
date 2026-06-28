"""Loop Ledger — Dashboard-ready loop health metrics.

Tracks and exposes loop health metrics for Grafana/dashboard consumption
and Prometheus export.

Design reference: research-loop-systems.md §9.3
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from noema.core.loop_manager import LoopManager

logger = structlog.get_logger(__name__)


class LoopLedger:
    """Tracks and exposes loop health metrics for monitoring.

    Usage::

        ledger = LoopLedger(loop_manager)
        dashboard_data = ledger.get_dashboard_data()
    """

    def __init__(self, loop_manager: LoopManager) -> None:
        self.manager = loop_manager

    def get_dashboard_data(self) -> dict[str, Any]:
        """Return data for Grafana/dashboard consumption.

        Returns a dict with per-loop health metrics and a timestamp.
        """
        report = self.manager.health_report()
        return {
            "loops": {
                name: {
                    "state": health["state"],
                    "tick_count": health["tick_count"],
                    "error_count": health["error_count"],
                    "consecutive_errors": health["consecutive_errors"],
                    "avg_tick_ms": health["avg_tick_ms"],
                    "drift_ms": health["drift_ms"],
                    "last_error": health["last_error"],
                    "uptime_seconds": health["uptime_seconds"],
                }
                for name, health in report.items()
            },
            "summary": self._build_summary(report),
            "timestamp": time.time(),
        }

    def _build_summary(self, report: dict[str, Any]) -> dict[str, Any]:
        """Build an aggregate summary of all loop health."""
        total_loops = len(report)
        running = sum(1 for h in report.values() if h["state"] == "running")
        errored = sum(1 for h in report.values() if h["state"] == "errored")
        halted = sum(1 for h in report.values() if h["state"] == "halted")
        paused = sum(1 for h in report.values() if h["state"] == "paused")
        total_errors = sum(h["error_count"] for h in report.values())
        total_ticks = sum(h["tick_count"] for h in report.values())

        return {
            "total_loops": total_loops,
            "running": running,
            "errored": errored,
            "halted": halted,
            "paused": paused,
            "total_errors": total_errors,
            "total_ticks": total_ticks,
            "overall_health": "healthy" if errored == 0 and halted == 0 else "degraded",
        }
