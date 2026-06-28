"""Devil's Advocate Agent — LLM-powered trade challenger.

Uses NIM + instructor to find weaknesses in the trade thesis.
The most important agent for preventing bad trades.

Updated: Uses DevilsAdvocateOutput with instructor guaranteed valid outputs.
Must output at least 2 specific issues or approve with justification.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import LLMAgent, AgentReport, AgentType
from noema.core.registry import AgentRegistry
from noema.core.nim_client import NIMClient, ModelTier
from noema.core.llm_structured import (
    DevilsAdvocateOutput,
    Verdict,
)
from noema.decision import RiskContext, inject_risk_context
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


@AgentRegistry.register("devils-advocate", layer="decision", needs_nim=True)
class DevilsAdvocateAgent(LLMAgent):
    """Agent #12 — LLM-powered trade challenger.

    Finds weaknesses in the trade thesis before the CIO decides.
    The most important agent for capital preservation.
    Uses instructor for guaranteed valid outputs with ≥2 issues requirement.
    """

    name = "devils-advocate"
    role = "Devil's Advocate"
    priority = 3
    model_tier = ModelTier.STANDARD
    system_prompt = SYSTEM_PROMPT
    response_model = DevilsAdvocateSchema  # Legacy model
    structured_model = DevilsAdvocateOutput  # New instructor-powered model
    temperature = 0.4
    tier_name = "decision"

    def __init__(self, config=None, nim_client: NIMClient | None = None):
        super().__init__(config=config, nim_client=nim_client)
        self._risk_context: RiskContext | None = None

    def set_risk_context(self, risk: RiskContext) -> None:
        """Set the current risk context for prompt injection (TradingAgents pattern)."""
        self._risk_context = risk

    def _build_system_prompt(self) -> str:
        """Build system prompt with risk context injection."""
        prompt = self.system_prompt
        if self._risk_context is not None:
            prompt = inject_risk_context(prompt, self._risk_context, agent_name=self.name)
        if self.response_model and not self.tools:
            from noema.models.schemas import schema_prompt
            prompt += "\n\n" + schema_prompt(self.response_model)
        return prompt

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

        parts.append("\n## Requirements:")
        parts.append("- If you reject or find issues, you MUST list at least 2 specific objections.")
        parts.append("- If you approve, you MUST include justification explaining why.")
        parts.append("- Provide an alternative view: what would the opposing trade look like?")
        parts.append("- Be SPECIFIC. No vague objections like 'markets are risky'.")

        return "\n".join(parts)

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert DevilsAdvocate or DevilsAdvocateOutput schema to AgentReport."""
        # Handle new DevilsAdvocateOutput model
        if isinstance(result, DevilsAdvocateOutput):
            if result.verdict == Verdict.APPROVE:
                signal = "APPROVE"
                confidence = 1.0 - result.confidence_reduction
            elif result.verdict == Verdict.REJECT:
                signal = "REJECT"
                confidence = result.confidence_reduction
            else:
                signal = "NEEDS_REVISION"
                confidence = 0.5 - result.confidence_reduction

            return AgentReport(
                agent_name=self.name,
                signal=signal,
                confidence=max(0.0, confidence),
                data=result.model_dump(),
                reasoning=(
                    f"Verdict: {result.verdict.value} | "
                    f"Issues: {'; '.join(result.issues[:3])} | "
                    f"Alternative: {result.alternative_view[:100]}"
                ),
                agent_type=AgentType.LLM,
                llm_latency_ms=llm_latency_ms,
            )
        # Handle legacy DevilsAdvocateSchema
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
