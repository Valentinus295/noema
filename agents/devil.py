"""Devil's Advocate Agent — LLM-powered trade challenger.

Uses NIM to find weaknesses in the trade thesis.
The most important agent for preventing bad trades.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import LLMAgent, AgentReport, AgentType
from noema.core.nim_client import NIMClient, ModelTier
from noema.models.schemas import DevilsAdvocate as DevilsAdvocateSchema

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are the Devil's Advocate for a forex trading system.

Your job: Given a trade thesis and all supporting evidence, find every reason WHY this trade could FAIL.

You are the skeptic. The risk-finder. The one who says "but what if..."

You receive:
- The trade thesis (direction, conviction, narrative)
- All agent analysis results
- Current market data

You must:
1. List specific, concrete objections (not vague "markets are risky")
2. Identify missing evidence that would strengthen the thesis
3. Describe the worst-case scenario in specific terms
4. Assign a confidence_reduction score (how much should this reduce the CIO's confidence?)

Rules:
- Be SPECIFIC. "Price could reverse" is useless. "Price is at a 61.8% Fib retracement with bearish RSI divergence on H4" is useful.
- If the thesis is strong, say so — don't manufacture objections for the sake of it.
- Focus on what's MISSING, not just what's present.
- Consider: What would a losing trader think in this situation?"""


class DevilsAdvocateAgent(LLMAgent):
    """Agent #12 — LLM-powered trade challenger.

    Finds weaknesses in the trade thesis before the CIO decides.
    The most important agent for capital preservation.
    """

    name = "devils-advocate"
    role = "Devil's Advocate"
    priority = 3
    model_tier = ModelTier.STANDARD
    system_prompt = SYSTEM_PROMPT
    response_model = DevilsAdvocateSchema
    temperature = 0.4  # Slightly higher for creative objection-finding

    def __init__(self, config=None, nim_client: NIMClient | None = None):
        super().__init__(config=config, nim_client=nim_client)

    def _build_user_message(self, context: dict[str, Any]) -> str:
        """Format thesis + analysis for the devil's advocate."""
        thesis = context.get("thesis", {})
        analysis = context.get("analysis", {})
        symbol = context.get("symbol", "EURUSD")
        current_price = context.get("current_price", 0)

        parts = [
            f"## Challenge This Trade: {symbol}",
            f"Current Price: {current_price}",
            "",
            "## The Trade Thesis:",
        ]

        if thesis:
            parts.append(f"  Direction: {thesis.get('direction', 'UNKNOWN')}")
            parts.append(f"  Conviction: {thesis.get('conviction', 0):.0%}")
            parts.append(f"  Narrative: {thesis.get('narrative', 'None provided')}")
            parts.append(f"  Key Risk: {thesis.get('key_risk', 'None identified')}")
            parts.append(f"  Evidence FOR: {thesis.get('evidence_for', [])}")
            parts.append(f"  Evidence AGAINST: {thesis.get('evidence_against', [])}")
        else:
            parts.append("  [No thesis provided — challenge everything]")

        parts.append("\n## Agent Analysis Summary:")
        for agent_name, data in analysis.items():
            signal = data.get("signal", "UNKNOWN")
            parts.append(f"  {agent_name}: {signal}")

        parts.append("\n## Your task: Find every reason this trade could fail.")
        return "\n".join(parts)

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert DevilsAdvocate schema to AgentReport."""
        if isinstance(result, DevilsAdvocateSchema):
            signal = "REJECT" if not result.should_trade else "APPROVE"
            return AgentReport(
                agent_name=self.name,
                signal=signal,
                confidence=1.0 - result.confidence_reduction,
                data=result.model_dump(),
                reasoning=f"Objections: {'; '.join(result.objections)} | Worst case: {result.worst_case_scenario}",
                agent_type=AgentType.LLM,
                llm_latency_ms=llm_latency_ms,
            )
        return super()._to_report(result, llm_latency_ms)
