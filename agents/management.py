"""Trade Management Agent — manages live positions.

Monitors open profit, drawdown, news, volatility.
Capabilities: Move to Breakeven, Partial Close, Trailing Stop, Emergency Exit.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class TradeManagementAgent(DeterministicAgent):
    """Agent #15 — Manages live positions.

    Monitors: Open Profit, Drawdown, News Events, Volatility.
    Actions: Move to Breakeven, Partial Close, Trailing Stop, Emergency Exit.
    """

    name = "trade-management"
    role = "Trade Manager"
    priority = 0

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Evaluate open positions and determine management actions."""
        positions: list[dict] = context.get("open_positions", [])
        current_prices: dict[str, float] = context.get("current_prices", {})
        news_events: list[dict] = context.get("upcoming_news", [])

        actions: list[dict] = []

        for pos in positions:
            ticket = pos.get("ticket")
            symbol = pos.get("symbol", "")
            direction = pos.get("type", "buy")
            open_price = pos.get("open_price", 0)
            current = current_prices.get(symbol, 0)
            sl = pos.get("sl", 0)
            tp = pos.get("tp", 0)
            volume = pos.get("volume", 0)

            if current == 0 or open_price == 0:
                continue

            # Calculate P&L
            if direction == "buy":
                pnl_pips = (current - open_price) / 0.0001 if "JPY" not in symbol else (current - open_price) / 0.01
            else:
                pnl_pips = (open_price - current) / 0.0001 if "JPY" not in symbol else (open_price - current) / 0.01

            action = None

            # Move to Breakeven: if 50+ pips in profit
            if pnl_pips >= 50 and sl < open_price if direction == "buy" else sl > open_price:
                action = {"type": "move_to_breakeven", "ticket": ticket, "new_sl": open_price}

            # Trailing Stop: if 100+ pips in profit
            elif pnl_pips >= 100:
                if direction == "buy":
                    new_sl = current - 30 * 0.0001
                else:
                    new_sl = current + 30 * 0.0001
                action = {"type": "trailing_stop", "ticket": ticket, "new_sl": new_sl}

            # Partial Close: if 150+ pips in profit
            elif pnl_pips >= 150:
                action = {"type": "partial_close", "ticket": ticket, "close_volume": volume * 0.5}

            # Emergency Exit: if high-impact news imminent
            for news in news_events:
                if news.get("impact") == "high" and pnl_pips < 20:
                    action = {"type": "emergency_exit", "ticket": ticket}
                    break

            if action:
                actions.append(action)

        return AgentReport(
            agent_name=self.name,
            signal="ACTION" if actions else "HOLD",
            confidence=0.8 if actions else 0.5,
            data={
                "actions": actions,
                "positions_monitored": len(positions),
            },
            reasoning=f"Monitoring {len(positions)} positions. {len(actions)} management action(s) recommended."
                      if actions else f"Monitoring {len(positions)} positions. Holding — no action needed.",
        )
