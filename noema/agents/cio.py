"""Chief Investment Officer Agent — LLM-powered final decision maker.

The CIO doesn't just count votes — it reasons about the trade-offs.
Uses NIM + instructor to synthesize thesis, devil's advocate, and all analysis
into a final decision.

Updated: Uses CIOOutput with instructor guaranteed valid outputs.
Decision is binary + conditions. MUST reference evidence from all 3 prior agents.

Enhanced with TradingAgents patterns:
- Debate synthesis: Structured Thesis-vs-Devil debate summary
- Risk context injection: Current account state, P&L, exposure, drawdown
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import LLMAgent, AgentReport, AgentType
from noema.core.nim_client import NIMClient, ModelTier
from noema.core.llm_structured import (
    CIOOutput,
    TradeSignal,
)
from noema.decision import RiskContext, inject_risk_context
from noema.decision.debate_synthesis import (
    synthesize_debate,
    format_debate_for_cio,
)
from noema.models.schemas import CIODecision, TradeDirection

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) of a forex trading system.

Your job: Make the FINAL trading decision. BUY, SELL, or NO_TRADE.

You receive:
1. All agent analysis results (trend, structure, S/R, momentum, price action, institutional)
2. The Trade Thesis (the case FOR the trade)
3. The Devil's Advocate (the case AGAINST the trade)

You must:
1. Weigh the thesis against the devil's advocate objections
2. Consider the consensus among analysis agents
3. Make a clear decision: BUY, SELL, or NO_TRADE
4. Assign a confidence score
5. Explain your reasoning in 3-5 sentences

Rules:
- If the Devil's Advocate raises valid objections, reduce confidence accordingly
- If agents disagree significantly, prefer NO_TRADE (capital preservation)
- Never trade below 40% confidence
- A strong thesis + weak objections = trade with high confidence
- A weak thesis + strong objections = NO_TRADE
- Mixed signals = NO_TRADE (there's always another opportunity)
- Be decisive. Indecision is also a decision (NO_TRADE)."""


class CIOAgent(LLMAgent):
    """Agent #1 — LLM-powered final decision maker.

    Synthesizes thesis + devil's advocate + fundamental bias + all analysis
    into a final BUY/SELL/NO_TRADE. Uses instructor for guaranteed valid outputs.
    MUST reference evidence from all 3 prior agents (Thesis, Devil, Fundamental).
    """

    name = "cio"
    role = "Chief Investment Officer"
    priority = 0  # Runs last — final decision
    model_tier = ModelTier.HEAVY
    system_prompt = SYSTEM_PROMPT
    response_model = CIODecision  # Legacy model
    structured_model = CIOOutput  # New instructor-powered model
    temperature = 0.2
    tier_name = "decision"

    def __init__(self, config=None, nim_client: NIMClient | None = None):
        super().__init__(config=config, nim_client=nim_client)
        self._risk_context: RiskContext | None = None

    def set_risk_context(self, risk: RiskContext) -> None:
        """Set the current risk context for injection into prompts (TradingAgents pattern)."""
        self._risk_context = risk

    def _build_user_message(self, context: dict[str, Any]) -> str:
        """Format everything the CIO needs to make a decision."""
        analysis = context.get("analysis", {})
        analysis_signals = context.get("analysis_signals", {})
        thesis = context.get("thesis", {})
        devil = context.get("devil", {})
        fundamental = context.get("fundamental", {})
        symbol = context.get("symbol", "EURUSD")
        current_price = context.get("current_price", 0)

        parts = [
            f"## CIO Decision Required: {symbol}",
            f"Current Price: {current_price}",
            "",
            "## Analysis Agent Signals:",
        ]

        bullish = sum(1 for s in analysis_signals.values() if s == "BULLISH")
        bearish = sum(1 for s in analysis_signals.values() if s == "BEARISH")
        neutral = sum(1 for s in analysis_signals.values() if s in ("NEUTRAL", "ERROR"))
        parts.append(f"  Bullish: {bullish} | Bearish: {bearish} | Neutral: {neutral}")

        for agent_name, signal in analysis_signals.items():
            conf = context.get("analysis_confidence", {}).get(agent_name, 0)
            parts.append(f"  {agent_name}: {signal} ({conf:.0%})")

        # Fundamental Bias
        parts.append("\n## Fundamental Bias (macro/fundamental context):")
        if fundamental:
            parts.append(f"  Direction: {fundamental.get('direction', 'UNKNOWN')}")
            parts.append(f"  Score: {fundamental.get('score', 0):.3f}")
            parts.append(f"  Explanation: {fundamental.get('explanation', 'None')}")
        else:
            parts.append("  [No fundamental bias available]")

        # Trade thesis
        parts.append("\n## Trade Thesis (FOR the trade):")
        if thesis:
            parts.append(f"  Direction: {thesis.get('direction', 'UNKNOWN')}")
            parts.append(f"  Conviction: {thesis.get('conviction', 0):.0%}")
            parts.append(f"  Narrative: {thesis.get('narrative', 'None')}")
            parts.append(f"  Evidence FOR: {thesis.get('evidence_for', [])}")
            parts.append(f"  Evidence AGAINST: {thesis.get('evidence_against', [])}")
            parts.append(f"  Key Risk: {thesis.get('key_risk', 'None')}")
        else:
            parts.append("  [No thesis available]")

        # Devil's advocate
        parts.append("\n## Devil's Advocate (AGAINST the trade):")
        if devil:
            parts.append(f"  Should Trade: {devil.get('should_trade', 'Unknown')}")
            parts.append(f"  Objections: {devil.get('objections', [])}")
            parts.append(f"  Missing Evidence: {devil.get('missing_evidence', [])}")
            parts.append(f"  Worst Case: {devil.get('worst_case_scenario', 'Unknown')}")
            parts.append(f"  Confidence Reduction: {devil.get('confidence_reduction', 0):.0%}")
        else:
            parts.append("  [No devil's advocate available — be extra cautious]")

        # ── DEBATE SYNTHESIS (TradingAgents pattern) ──
        if thesis and devil:
            try:
                synthesis = synthesize_debate(thesis, devil, symbol=symbol)
                debate_section = format_debate_for_cio(synthesis)
                parts.append("\n" + debate_section)
            except Exception as e:
                logger.warning("debate_synthesis_failed", error=str(e))

        parts.append("\n## Requirements:")
        parts.append("- Make a clear decision: BUY, SELL, or NO_TRADE")
        parts.append("- Reference specific evidence FROM the Trade Thesis")
        parts.append("- Reference specific evidence FROM the Devil's Advocate")
        parts.append("- Reference specific evidence FROM the Fundamental Bias")
        parts.append("- List conditions that must hold for the decision to remain valid")
        parts.append("- If overriding position size, explain why")

        return "\n".join(parts)

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert CIOOutput or CIODecision schema to AgentReport."""
        # Handle new CIOOutput model
        if isinstance(result, CIOOutput):
            signal = result.final_decision.value
            return AgentReport(
                agent_name=self.name,
                signal=signal,
                confidence=result.confidence,
                data=result.model_dump(),
                reasoning=result.rationale,
                agent_type=AgentType.LLM,
                llm_latency_ms=llm_latency_ms,
            )
        # Handle legacy CIODecision
        if isinstance(result, CIODecision):
            signal = result.decision.value
            return AgentReport(
                agent_name=self.name,
                signal=signal,
                confidence=result.confidence,
                data=result.model_dump(),
                reasoning=result.final_reasoning,
                agent_type=AgentType.LLM,
                llm_latency_ms=llm_latency_ms,
            )
        return super()._to_report(result, llm_latency_ms)
