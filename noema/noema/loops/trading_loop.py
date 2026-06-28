"""Trading Loop — Core OODA cycle.

Priority: 1
Cadence: 60 seconds (configurable)

Runs the main trading cycle: Data → Analysis → Decision → Execution.
Delegates to ModernOrchestrator.run_cycle() for each configured symbol.

Can be paused by Safety Loop (priority 0) when kill-switches fire.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from noema.core.loop import TradingLoop

logger = structlog.get_logger(__name__)


class TradingCycleLoop(TradingLoop):
    """Main trading OODA loop.

    Wraps the existing orchestrator.run_cycle() in a managed loop
    with health tracking, pause/resume, and priority scheduling.
    """

    def __init__(
        self,
        orchestrator: Any,  # ModernOrchestrator
        symbols: list[str] | None = None,
        cadence_seconds: float = 60.0,
    ):
        super().__init__(
            name="trading",
            cadence_seconds=cadence_seconds,
            priority=1,
            max_consecutive_errors=5,
        )
        self.orchestrator = orchestrator
        self.symbols = symbols or []

    async def tick(self) -> None:
        """Run one trading cycle for all symbols."""
        for symbol in self.symbols:
            try:
                metrics = await self.orchestrator.run_cycle(symbol)
                self.logger.info(
                    "trading_cycle_complete",
                    symbol=symbol,
                    decision=metrics.decision,
                    latency_ms=round(metrics.total_latency_ms, 1),
                )
            except Exception as e:
                self.logger.error(
                    "trading_cycle_error",
                    symbol=symbol,
                    error=str(e),
                )
                raise  # Let base class track consecutive errors
