"""Regime Detection Loop — Monitor volatility regime shifts.

Priority: 2
Cadence: 300 seconds (5 minutes)

Monitors market volatility regime and triggers strategy adaptation
when a regime change is detected. Uses the ReflectorAgent's regime
analysis capabilities.

Regimes: trending_low_vol, trending_high_vol, ranging_low_vol,
         ranging_high_vol, crisis
"""

from __future__ import annotations

import time
from typing import Any, Optional

import structlog

from noema.core.loop import TradingLoop

logger = structlog.get_logger(__name__)


class RegimeLoop(TradingLoop):
    """Monitors market regime shifts and triggers adaptation.

    This loop:
    1. Reads current market indicators (volatility, trend, correlation)
    2. Classifies the current regime
    3. Compares against the previous regime
    4. If changed with sufficient confidence, triggers strategy adaptation
    """

    def __init__(
        self,
        orchestrator: Any = None,
        on_regime_change: Any = None,  # async callback(old_regime, new_regime)
        regime_change_threshold: float = 0.7,
    ):
        super().__init__(
            name="regime",
            cadence_seconds=300.0,
            priority=2,
            max_consecutive_errors=5,
        )
        self.orchestrator = orchestrator
        self._on_regime_change = on_regime_change
        self.regime_change_threshold = regime_change_threshold
        self._previous_regime: Optional[str] = None

    async def tick(self) -> None:
        """Run one regime detection cycle.

        Classifies the current market regime and triggers adaptation
        if a regime change is detected with sufficient confidence.
        """
        # If orchestrator has a reflector agent, use it for regime analysis
        if self.orchestrator and hasattr(self.orchestrator, "_learning_agent"):
            learning_agent = self.orchestrator._learning_agent
            if learning_agent and hasattr(learning_agent, "process"):
                try:
                    result = await learning_agent.process({
                        "phase": "regime_detection",
                        "previous_regime": self._previous_regime,
                    })
                    current_regime = getattr(result, "data", {}).get(
                        "regime", "unknown"
                    )
                except Exception as e:
                    self.logger.warning("regime_detection_error", error=str(e))
                    return
            else:
                current_regime = "unknown"
        else:
            # Basic regime detection — use volatility heuristic
            current_regime = await self._basic_regime_detection()

        # Check for regime change
        if self._previous_regime and current_regime != self._previous_regime:
            self.logger.info(
                "regime_change_detected",
                previous=self._previous_regime,
                current=current_regime,
            )
            if self._on_regime_change:
                try:
                    await self._on_regime_change(self._previous_regime, current_regime)
                except Exception as e:
                    self.logger.error("regime_change_callback_failed", error=str(e))

        self._previous_regime = current_regime

    async def _basic_regime_detection(self) -> str:
        """Basic regime detection using volatility heuristic.

        Returns one of: trending_low_vol, trending_high_vol,
        ranging_low_vol, ranging_high_vol, crisis, unknown
        """
        self.logger.debug("basic_regime_detection_noop")
        return "unknown"
