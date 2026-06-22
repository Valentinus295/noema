"""Macro Economic Agent — understands the world economy.

Sources: MT5 Economic Calendar, Interest Rates, CPI, GDP, Employment, Geopolitics.
Output: Currency strength scores and fundamental bias.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.analysis.fundamental import FundamentalAnalyzer, EconomicEvent, ImpactLevel
from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class MacroEconomicAgent(DeterministicAgent):
    """Agent #2 — Understands the world economy.

    Answers: What is happening globally? Are central banks hawkish?
    Which currencies are strongest/weakest?
    """

    name = "macro-economic"
    role = "Macro Economic Intelligence"
    priority = 10

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.analyzer = FundamentalAnalyzer(self.config)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Analyze economic calendar and produce fundamental bias."""
        events_raw = context.get("economic_events", [])
        events = [
            EconomicEvent(
                name=e.get("name", ""),
                currency=e.get("currency", ""),
                impact=ImpactLevel(e.get("impact", "low")),
                forecast=e.get("forecast"),
                actual=e.get("actual"),
                previous=e.get("previous"),
            )
            for e in events_raw
        ]

        report = self.analyzer.analyze_events(events, context)

        return AgentReport(
            agent_name=self.name,
            signal=report.bias.value.upper(),
            confidence=report.confidence,
            data={
                "currency_scores": report.currency_scores,
                "bias": report.bias.value,
                "high_impact_events": report.high_impact_events,
            },
            reasoning=report.reasoning,
        )
