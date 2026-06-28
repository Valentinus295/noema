"""Execution Agent — handles trade implementation.

Places orders, modifies orders, moves SL, partial close, close trades.
Uses the broker abstraction — works with MT5Broker, MT5LinuxBroker,
FBSBroker, and PaperBroker transparently.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.core.registry import AgentRegistry

logger = structlog.get_logger(__name__)


@AgentRegistry.register("execution", layer="execution", needs_broker=True)
class ExecutionAgent(DeterministicAgent):
    """Agent #14 — Trade implementation.

    Places orders, modifies orders, moves SL, partial close, close trades.
    Works through the broker abstraction — broker-agnostic.
    """

    name = "execution"
    role = "Trade Executor"
    priority = 0

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Execute a validated trade through the broker abstraction."""
        broker = context.get("broker")
        pair: str = context.get("pair", "EURUSD")
        direction: str = context.get("direction", "long")
        lot_size: float = context.get("lot_size", 0.01)
        stop_loss: float = context.get("stop_loss", 0.0)
        take_profit: float = context.get("take_profit", 0.0)
        magic: int = context.get("magic_number", 20260609)

        if broker is None:
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning="No broker connected",
            )

        # ── Get current tick via broker abstraction ──
        tick = None
        try:
            tick = broker.get_tick(pair)
        except Exception as exc:
            logger.warning("tick_fetch_failed", symbol=pair, error=str(exc))

        if tick is None:
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"No tick data for {pair}",
            )

        # ── Place order via broker abstraction ──
        order_type = "buy" if direction.lower() == "long" else "sell"

        try:
            result = broker.place_order(
                symbol=pair,
                order_type=order_type,
                volume=lot_size,
                sl=stop_loss,
                tp=take_profit,
                comment="Noema",
                magic=magic,
            )
        except Exception as exc:
            logger.error("order_placement_exception", symbol=pair, error=str(exc))
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"Order exception: {exc}",
            )

        if result and result.success:
            return AgentReport(
                agent_name=self.name,
                signal="EXECUTED",
                confidence=1.0,
                data={
                    "ticket": result.ticket,
                    "price": result.price,
                    "volume": result.volume,
                    "sl": stop_loss,
                    "tp": take_profit,
                    "pair": pair,
                    "direction": direction,
                },
                reasoning=f"Order executed: {direction.upper()} {lot_size} lots of {pair} @ {result.price}",
            )
        else:
            error = result.error if result else "Unknown error"
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"Order failed: {error}",
            )
