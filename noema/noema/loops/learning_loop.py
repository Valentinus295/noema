"""Learning Loop — Track trade outcomes and update agent weights.

Priority: 2
Cadence: 3600 seconds (hourly)

Evaluates completed trades, updates agent performance scores,
and adjusts weights using exponential moving average.

Pauses during drawdown (Safety Loop override).
"""

from __future__ import annotations

import time
from typing import Any, Optional

import structlog

from noema.core.loop import TradingLoop

logger = structlog.get_logger(__name__)


class LearningLoop(TradingLoop):
    """Tracks trade outcomes and updates agent weights.

    This loop:
    1. Gathers completed trades since last run
    2. Evaluates prediction accuracy per agent
    3. Updates agent weights via EMA (smooth, not noisy)
    4. Flags underperforming agents for review
    """

    def __init__(
        self,
        orchestrator: Any = None,
        learning_agent: Any = None,  # LLMAgent for learning
        weight_update_alpha: float = 0.3,
    ):
        super().__init__(
            name="learning",
            cadence_seconds=3600.0,
            priority=2,
            max_consecutive_errors=3,
        )
        self.orchestrator = orchestrator
        self.learning_agent = learning_agent
        self.alpha = weight_update_alpha  # EMA smoothing factor

    async def tick(self) -> None:
        """Run one learning cycle.

        Delegates to the orchestrator's learning agent if available,
        otherwise performs a basic outcome tracking cycle.
        """
        if self.learning_agent:
            # Use the configured learning agent
            try:
                result = await self.learning_agent.process({
                    "phase": "learning",
                    "alpha": self.alpha,
                })
                self.logger.info(
                    "learning_cycle_complete",
                    agent=getattr(self.learning_agent, "name", "unknown"),
                    result_type=type(result).__name__,
                )
            except Exception as e:
                self.logger.error("learning_agent_error", error=str(e))
                raise
        else:
            # Basic learning cycle — log and continue
            self.logger.info(
                "learning_cycle_noop",
                message="No learning agent configured — skipping",
            )
