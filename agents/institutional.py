"""Institutional Footprint Agent — finds where smart money acted.

Detects Order Blocks, Liquidity Sweeps, Imbalances, Fair Value Gaps.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

from vmpm.analysis.smc import SMCForecaster
from vmpm.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class InstitutionalFootprintAgent(DeterministicAgent):
    """Agent #5 — Finds where smart money acted.

    Detects: Bullish/Bearish Order Blocks, Liquidity Sweeps, Imbalances, FVGs.
    Answers: Where did institutions enter? Where will they defend positions?
    """

    name = "institutional-footprint"
    role = "Institutional Footprint Analyst"
    priority = 7

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.smc = SMCForecaster(self.config)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Analyze institutional footprints in price data."""
        df: pd.DataFrame = context.get("price_data")
        if df is None or len(df) < 50:
            return AgentReport(agent_name=self.name, signal="NEUTRAL", reasoning="Insufficient data")

        report = self.smc.analyze(df)

        bullish_obs = [ob for ob in report.order_blocks if ob.type == "bullish"]
        bearish_obs = [ob for ob in report.order_blocks if ob.type == "bearish"]

        if bullish_obs and not bearish_obs:
            signal = "BULLISH"
        elif bearish_obs and not bullish_obs:
            signal = "BEARISH"
        elif bullish_obs and bearish_obs:
            signal = "BULLISH" if bullish_obs[-1].strength > bearish_obs[-1].strength else "BEARISH"
        else:
            signal = "NEUTRAL"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=report.confidence,
            data={
                "order_blocks": [
                    {"type": ob.type, "midpoint": ob.midpoint, "strength": ob.strength}
                    for ob in report.order_blocks
                ],
                "fair_value_gaps": [
                    {"type": fvg.type, "midpoint": fvg.midpoint}
                    for fvg in report.fair_value_gaps
                ],
                "liquidity_sweeps": [
                    {"type": s.type, "level": s.level}
                    for s in report.liquidity_sweeps
                ],
                "bos_detected": report.bos_detected,
                "choch_detected": report.choch_detected,
            },
            reasoning=report.reasoning,
        )
