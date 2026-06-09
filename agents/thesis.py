"""Trade Thesis Agent — builds the case for a trade.

Think like a lawyer: Why should we buy? What evidence supports the trade?
"""

from __future__ import annotations

from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class TradeThesisAgent(Agent):
    """Agent #11 — Builds the case for a trade.

    Think like a lawyer: Why should we buy? Why should we sell?
    What evidence supports the trade?
    """

    name = "trade-thesis"
    role = "Trade Thesis Builder"
    priority = 2

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Build a comprehensive trade thesis from all agent reports."""
        reports: dict[str, dict] = context.get("agent_reports", {})
        pair: str = context.get("pair", "EURUSD")
        direction_hint: str = context.get("direction", "long")

        # Gather evidence
        evidence_for = []
        evidence_against = []

        # Fundamental evidence
        macro = reports.get("macro-economic", {})
        if macro.get("signal") == "BULLISH":
            evidence_for.append("Fundamentals bullish")
        elif macro.get("signal") == "BEARISH":
            if direction_hint == "long":
                evidence_against.append("Fundamentals bearish")
            else:
                evidence_for.append("Fundamentals bearish")

        # Trend evidence
        structure = reports.get("market-structure", {})
        if structure.get("signal") == "BULLISH":
            evidence_for.append("Bullish market structure")
        elif structure.get("signal") == "BEARISH":
            if direction_hint == "long":
                evidence_against.append("Bearish market structure")
            else:
                evidence_for.append("Bearish market structure")

        # S/R evidence
        sr = reports.get("support-resistance", {})
        if sr.get("signal") == "BULLISH":
            evidence_for.append("Price near support")
        elif sr.get("signal") == "BEARISH":
            if direction_hint == "long":
                evidence_against.append("Price near resistance")
            else:
                evidence_for.append("Price near resistance")

        # Momentum evidence
        momentum = reports.get("momentum", {})
        if momentum.get("signal") == "BULLISH":
            evidence_for.append("Momentum bullish (RSI oversold/divergence)")
        elif momentum.get("signal") == "BEARISH":
            evidence_for.append("Momentum bearish (RSI overbought)")

        # SMC evidence
        institutional = reports.get("institutional-footprint", {})
        if institutional.get("signal") == "BULLISH":
            evidence_for.append("Institutional demand zone")
        elif institutional.get("signal") == "BEARISH":
            evidence_for.append("Institutional supply zone")

        # Price action evidence
        price_action = reports.get("price-action", {})
        if price_action.get("signal") == "BULLISH":
            evidence_for.append("Bullish candlestick pattern")
        elif price_action.get("signal") == "BEARISH":
            evidence_for.append("Bearish candlestick pattern")

        # Build thesis
        total_evidence = len(evidence_for) + len(evidence_against)
        if total_evidence == 0:
            confidence = 0.0
            signal = "NEUTRAL"
        else:
            confidence = len(evidence_for) / total_evidence if direction_hint == "long" else len(evidence_against) / total_evidence
            if confidence >= 0.6:
                signal = "BULLISH" if direction_hint == "long" else "BEARISH"
            else:
                signal = "NEUTRAL"

        reasoning = f"Trade Case for {pair} ({direction_hint.upper()}):\n"
        reasoning += f"Evidence FOR: {', '.join(evidence_for) if evidence_for else 'None'}\n"
        reasoning += f"Evidence AGAINST: {', '.join(evidence_against) if evidence_against else 'None'}\n"
        reasoning += f"Confidence: {confidence:.1%}"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data={
                "pair": pair,
                "direction": direction_hint,
                "evidence_for": evidence_for,
                "evidence_against": evidence_against,
                "total_evidence": total_evidence,
            },
            reasoning=reasoning,
        )
