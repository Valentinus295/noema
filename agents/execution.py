"""Execution Agent — handles trade implementation.

Places orders, modifies orders, moves SL, partial close, close trades.
"""

from __future__ import annotations

from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class ExecutionAgent(Agent):
    """Agent #14 — Trade implementation.

    Places orders, modifies orders, moves SL, partial close, close trades.
    """

    name = "execution"
    role = "Trade Executor"
    priority = 0

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Execute a validated trade through the broker."""
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

        try:
            import MetaTrader5 as mt5

            symbol_info = mt5.symbol_info(pair)
            if symbol_info is None:
                return AgentReport(
                    agent_name=self.name,
                    signal="ERROR",
                    confidence=0.0,
                    reasoning=f"Symbol {pair} not found",
                )

            point = symbol_info.point
            tick = mt5.symbol_info_tick(pair)

            if direction == "long":
                price = tick.ask
                order_type = mt5.ORDER_TYPE_BUY
                sl = stop_loss if stop_loss > 0 else price - 100 * point
                tp = take_profit if take_profit > 0 else price + 200 * point
            else:
                price = tick.bid
                order_type = mt5.ORDER_TYPE_SELL
                sl = stop_loss if stop_loss > 0 else price + 100 * point
                tp = take_profit if take_profit > 0 else price - 200 * point

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pair,
                "volume": lot_size,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": magic,
                "comment": "VMPM",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return AgentReport(
                    agent_name=self.name,
                    signal="EXECUTED",
                    confidence=1.0,
                    data={
                        "ticket": result.order,
                        "price": result.price,
                        "volume": result.volume,
                        "sl": sl,
                        "tp": tp,
                        "pair": pair,
                        "direction": direction,
                    },
                    reasoning=f"Order executed: {direction.upper()} {lot_size} lots of {pair} @ {result.price}",
                )
            else:
                error = result.comment if result else "Unknown error"
                return AgentReport(
                    agent_name=self.name,
                    signal="ERROR",
                    confidence=0.0,
                    reasoning=f"Order failed: {error}",
                )

        except ImportError:
            return AgentReport(
                agent_name=self.name,
                signal="SIMULATED",
                confidence=0.8,
                data={
                    "pair": pair,
                    "direction": direction,
                    "lot_size": lot_size,
                    "sl": stop_loss,
                    "tp": take_profit,
                },
                reasoning=f"[PAPER TRADE] {direction.upper()} {lot_size} lots of {pair}",
            )
