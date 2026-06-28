"""Calibration Loop — Measure prediction accuracy and recalibrate thresholds.

Priority: 2
Cadence: 86400 seconds (daily)

Measures prediction accuracy using Brier score, recalibrates
confidence thresholds, and adjusts agent weights based on
longer-term performance data.

Uses the fixed Brier score implementation for calibration tracking.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from noema.core.loop import TradingLoop

logger = structlog.get_logger(__name__)


class CalibrationLoop(TradingLoop):
    """Daily calibration of prediction accuracy and thresholds.

    This loop:
    1. Gathers prediction/outcome pairs from the past 24h
    2. Computes Brier scores per agent
    3. Recalibrates confidence thresholds
    4. Updates agent weights with longer-term smoothing
    """

    def __init__(
        self,
        orchestrator: Any = None,
        min_sample_size: int = 10,
    ):
        super().__init__(
            name="calibration",
            cadence_seconds=86400.0,
            priority=2,
            max_consecutive_errors=2,  # Calibration errors are concerning
        )
        self.orchestrator = orchestrator
        self.min_sample_size = min_sample_size

    async def tick(self) -> None:
        """Run one calibration cycle.

        Evaluates prediction accuracy and recalibrates thresholds.
        Skips if insufficient sample size.
        """
        self.logger.info("calibration_cycle_start")

        # If orchestrator has a learning agent, delegate calibration
        if self.orchestrator and hasattr(self.orchestrator, "_learning_agent"):
            learning_agent = self.orchestrator._learning_agent
            if learning_agent:
                try:
                    result = await learning_agent.process({
                        "phase": "calibration",
                        "min_sample_size": self.min_sample_size,
                    })
                    self.logger.info(
                        "calibration_cycle_complete",
                        result_type=type(result).__name__,
                    )
                    return
                except Exception as e:
                    self.logger.error("calibration_agent_error", error=str(e))
                    raise

        # Basic calibration — log metrics
        self.logger.info(
            "calibration_cycle_noop",
            message="No calibration agent configured — recording cycle",
        )
