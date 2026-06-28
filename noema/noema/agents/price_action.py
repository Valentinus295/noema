"""Price Action Agent — reads the language of candles.

Detects candlestick patterns: Engulfing, Hammer, Morning Star, Shooting Star, etc.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

from noema.analysis.candlestick import CandlestickDetector
from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.core.registry import AgentRegistry

logger = structlog.get_logger(__name__)


@AgentRegistry.register("price-action", layer="analysis")
class PriceActionAgent(DeterministicAgent):
    """Agent #10 — Reads the language of candles.

    Detects: Bullish Engulfing, Hammer, Morning Star, Shooting Star, etc.
    """

    name = "price-action"
    role = "Price Action Analyst"
    priority = 3

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.detector = CandlestickDetector(self.config)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Detect candlestick patterns in OHLCV data."""
        df: pd.DataFrame = context.get("price_data")
        if df is None or len(df) < 5:
            return AgentReport(agent_name=self.name, signal="NEUTRAL", reasoning="Insufficient data")

        report = self.detector.detect_all(df)

        return AgentReport(
            agent_name=self.name,
            signal=report.confirmation,
            confidence=report.confidence,
            data={
                "patterns": [
                    {"name": p.name, "type": p.type, "strength": p.strength}
                    for p in report.patterns
                ],
                "confirmation": report.confirmation,
            },
            reasoning=report.reasoning,
        )
