"""Opportunity Surveillance Agent — watches price continuously.

Never sleeps. Monitors price approaching support/resistance, order blocks, liquidity.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class OpportunitySurveillanceAgent(Agent):
    """Agent #8 — Watches price continuously.

    Monitors: Price approaching support, resistance, order blocks, liquidity.
    Output: Potential Opportunity Detected.
    """

    name = "opportunity-surveillance"
    role = "Opportunity Surveillance Monitor"
    priority = 4

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Monitor price for opportunities at key zones."""
        df: pd.DataFrame = context.get("price_data")
        buy_zones: list[dict] = context.get("buy_zones", [])
        sell_zones: list[dict] = context.get("sell_zones", [])
        order_blocks: list[dict] = context.get("order_blocks", [])

        if df is None or len(df) < 5:
            return AgentReport(agent_name=self.name, signal="NEUTRAL", reasoning="No data")

        current_price = float(df["close"].iloc[-1])
        atr = float(df["high"].sub(df["low"]).rolling(14).mean().iloc[-1]) if len(df) > 14 else 0.0010

        opportunities = []

        # Check buy zones
        for zone in buy_zones:
            level = zone["level"]
            distance = abs(current_price - level)
            if distance < atr * 2:  # Within 2 ATR
                opportunities.append({
                    "type": "buy_zone",
                    "zone": zone["name"],
                    "level": level,
                    "distance_pips": distance / 0.0001 if "JPY" not in context.get("pair", "") else distance / 0.01,
                })

        # Check sell zones
        for zone in sell_zones:
            level = zone["level"]
            distance = abs(current_price - level)
            if distance < atr * 2:
                opportunities.append({
                    "type": "sell_zone",
                    "zone": zone["name"],
                    "level": level,
                    "distance_pips": distance / 0.0001 if "JPY" not in context.get("pair", "") else distance / 0.01,
                })

        # Check order blocks
        for ob in order_blocks:
            distance = abs(current_price - ob["midpoint"])
            if distance < atr * 1.5:
                opportunities.append({
                    "type": "order_block",
                    "ob_type": ob["type"],
                    "level": ob["midpoint"],
                })

        signal = "BULLISH" if any(o["type"].startswith("buy") or (o["type"] == "order_block" and o.get("ob_type") == "bullish") for o in opportunities) else \
                 "BEARISH" if any(o["type"].startswith("sell") or (o["type"] == "order_block" and o.get("ob_type") == "bearish") for o in opportunities) else \
                 "NEUTRAL"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=0.7 if opportunities else 0.2,
            data={
                "current_price": current_price,
                "opportunities": opportunities,
                "count": len(opportunities),
            },
            reasoning=f"Price {current_price:.5f}. {len(opportunities)} opportunity(ies) detected near key zones." if opportunities else f"Price {current_price:.5f}. No immediate opportunities.",
        )
