"""Trading pipeline state machine for Noema.

Implements the 12-phase trading pipeline as a state machine.
Each phase must complete before advancing to the next.
The system can pause, wait, or reject at any phase.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class PipelineState(Enum):
    """States of the trading pipeline."""
    IDLE = "idle"
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"
    TREND_IDENTIFICATION = "trend_identification"
    MARKET_STRUCTURE = "market_structure"
    SUPPORT_RESISTANCE = "support_resistance"
    ORDER_BLOCK_ANALYSIS = "order_block_analysis"
    WAITING_FOR_PRICE = "waiting_for_price"
    PRICE_AT_ZONE = "price_at_zone"
    RSI_CONFIRMATION = "rsi_confirmation"
    CANDLESTICK_CONFIRMATION = "candlestick_confirmation"
    TRADE_VALIDATION = "trade_validation"
    RISK_MANAGEMENT = "risk_management"
    EXECUTION = "execution"
    TRADE_MANAGEMENT = "trade_management"
    POST_TRADE_LEARNING = "post_trade_learning"
    REJECTED = "rejected"
    COMPLETED = "completed"


# Valid state transitions
TRANSITIONS: dict[PipelineState, list[PipelineState]] = {
    PipelineState.IDLE: [PipelineState.FUNDAMENTAL_ANALYSIS],
    PipelineState.FUNDAMENTAL_ANALYSIS: [PipelineState.TREND_IDENTIFICATION, PipelineState.REJECTED],
    PipelineState.TREND_IDENTIFICATION: [PipelineState.MARKET_STRUCTURE, PipelineState.REJECTED],
    PipelineState.MARKET_STRUCTURE: [PipelineState.SUPPORT_RESISTANCE, PipelineState.REJECTED],
    PipelineState.SUPPORT_RESISTANCE: [PipelineState.ORDER_BLOCK_ANALYSIS, PipelineState.REJECTED],
    PipelineState.ORDER_BLOCK_ANALYSIS: [PipelineState.WAITING_FOR_PRICE, PipelineState.REJECTED],
    PipelineState.WAITING_FOR_PRICE: [PipelineState.PRICE_AT_ZONE, PipelineState.REJECTED],
    PipelineState.PRICE_AT_ZONE: [PipelineState.RSI_CONFIRMATION, PipelineState.REJECTED],
    PipelineState.RSI_CONFIRMATION: [PipelineState.CANDLESTICK_CONFIRMATION, PipelineState.WAITING_FOR_PRICE, PipelineState.REJECTED],
    PipelineState.CANDLESTICK_CONFIRMATION: [PipelineState.TRADE_VALIDATION, PipelineState.WAITING_FOR_PRICE, PipelineState.REJECTED],
    PipelineState.TRADE_VALIDATION: [PipelineState.RISK_MANAGEMENT, PipelineState.REJECTED],
    PipelineState.RISK_MANAGEMENT: [PipelineState.EXECUTION, PipelineState.REJECTED],
    PipelineState.EXECUTION: [PipelineState.TRADE_MANAGEMENT, PipelineState.COMPLETED],
    PipelineState.TRADE_MANAGEMENT: [PipelineState.POST_TRADE_LEARNING, PipelineState.COMPLETED],
    PipelineState.POST_TRADE_LEARNING: [PipelineState.COMPLETED],
    PipelineState.REJECTED: [PipelineState.IDLE],
    PipelineState.COMPLETED: [PipelineState.IDLE],
}


@dataclass
class PhaseResult:
    """Result from a pipeline phase."""
    phase: PipelineState
    success: bool
    signal: str = "NEUTRAL"          # BULLISH, BEARISH, NEUTRAL
    confidence: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    timestamp: float = field(default_factory=time.time)


class TradingPipeline:
    """State machine orchestrating the 12-phase Noema trading pipeline.

    Usage:
        pipeline = TradingPipeline()
        pipeline.advance(PhaseResult(...))
        pipeline.wait_for_price(zone_data)
        pipeline.reject("Fundamentals unclear")
    """

    def __init__(self) -> None:
        self.state = PipelineState.IDLE
        self._history: list[PhaseResult] = []
        self._trade_context: dict[str, Any] = {}
        self._logger = logger.bind(component="pipeline")

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def advance(self, result: PhaseResult) -> bool:
        """Attempt to advance to the next phase based on result.

        Returns True if transition was successful.
        """
        valid_next = TRANSITIONS.get(self.state, [])
        if not result.success:
            target = PipelineState.REJECTED
        else:
            target = valid_next[0] if valid_next else None

        if target is None or target not in valid_next:
            self._logger.warning(
                "invalid_transition",
                current=self.state.value,
                target=target.value if target else "None",
            )
            return False

        self._history.append(result)
        self._trade_context.update(result.data)
        old_state = self.state
        self.state = target
        self._logger.info(
            "pipeline_transition",
            from_state=old_state.value,
            to_state=target.value,
            signal=result.signal,
        )
        return True

    def wait_for_price(self, zone_data: dict[str, Any]) -> bool:
        """Transition to WAITING_FOR_PRICE state."""
        if self.state not in (PipelineState.WAITING_FOR_PRICE, PipelineState.RSI_CONFIRMATION, PipelineState.CANDLESTICK_CONFIRMATION):
            self._logger.warning("cannot_wait", current=self.state.value)
            return False
        self.state = PipelineState.WAITING_FOR_PRICE
        self._trade_context["waiting_zones"] = zone_data
        self._logger.info("waiting_for_price", zones=list(zone_data.keys()))
        return True

    def price_arrived(self, zone_data: dict[str, Any]) -> bool:
        """Transition from WAITING to PRICE_AT_ZONE."""
        if self.state != PipelineState.WAITING_FOR_PRICE:
            return False
        self.state = PipelineState.PRICE_AT_ZONE
        self._trade_context["arrival_zone"] = zone_data
        self._logger.info("price_arrived", zone=zone_data.get("zone_name", "unknown"))
        return True

    def reject(self, reason: str) -> None:
        """Reject the current trade setup."""
        self.state = PipelineState.REJECTED
        self._logger.info("trade_rejected", reason=reason)
        self._history.append(PhaseResult(
            phase=self.state,
            success=False,
            reasoning=reason,
        ))

    def reset(self) -> None:
        """Reset pipeline to IDLE for next trade."""
        self._logger.info(
            "pipeline_reset",
            phases_completed=len(self._history),
        )
        self.state = PipelineState.IDLE
        self._history.clear()
        self._trade_context.clear()

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    @property
    def context(self) -> dict[str, Any]:
        return self._trade_context.copy()

    @property
    def history(self) -> list[PhaseResult]:
        return self._history.copy()

    @property
    def is_active(self) -> bool:
        return self.state not in (PipelineState.IDLE, PipelineState.REJECTED, PipelineState.COMPLETED)

    def summary(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "phases_completed": len(self._history),
            "context_keys": list(self._trade_context.keys()),
            "is_active": self.is_active,
        }
