"""Learning Agent — LLM-powered post-trade reflection.

Uses NIM to reflect on trade outcomes and store lessons learned.
This is where the system gets smarter over time.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import LLMAgent, AgentReport, AgentType
from noema.core.nim_client import NIMClient, ModelTier
from noema.models.schemas import TradeReflection

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are the Learning Agent for a forex trading system.

Your job: After a trade concludes (or after a NO_TRADE decision), reflect on what happened and extract lessons for the future.

You receive:
- The trade decision that was made
- All the analysis that led to that decision
- The outcome (if known)

You must:
1. Identify what worked correctly in the analysis
2. Identify what was wrong or misleading
3. Extract a specific, actionable lesson
4. Classify the pattern type (e.g., "trend_continuation", "reversal", "breakout", "range_trade")
5. Decide: Should we look for this type of setup again?
6. List specific adjustments for next time

Rules:
- Be honest. If the analysis was wrong, say so.
- Be specific. "Watch for news" is useless. "The trade failed because NFP was 2 hours away and volatility spiked" is useful.
- Focus on PATTERN RECOGNITION. What pattern did this market situation match?
- Store insights that will be relevant for FUTURE trades, not just this one.
- If a trade succeeded for the wrong reasons (lucky), note that too."""


class LearningAgent(LLMAgent):
    """Agent #17 — LLM-powered post-trade reflection.

    Reflects on trade outcomes and stores lessons for future decisions.
    This is how the system improves over time.
    """

    name = "learning"
    role = "Learning & Reflection"
    priority = 100  # Runs last, after everything
    model_tier = ModelTier.FAST  # No rush — background task
    system_prompt = SYSTEM_PROMPT
    response_model = TradeReflection
    temperature = 0.4  # Slightly creative for insight extraction

    def __init__(self, config=None, nim_client: NIMClient | None = None):
        super().__init__(config=config, nim_client=nim_client)

    def _build_user_message(self, context: dict[str, Any]) -> str:
        """Format trade data for reflection."""
        decision = context.get("decision", {})
        analysis = context.get("analysis", {})
        symbol = context.get("symbol", "UNKNOWN")

        parts = [
            f"## Post-Trade Reflection: {symbol}",
            "",
            "## Decision Made:",
        ]

        if decision:
            parts.append(f"  Decision: {decision.get('decision', 'UNKNOWN')}")
            parts.append(f"  Confidence: {decision.get('confidence', 0):.0%}")
            parts.append(f"  Consensus: {decision.get('consensus_score', 0):.0%}")
            parts.append(f"  Reasoning: {decision.get('final_reasoning', 'None')}")
            parts.append(f"  Thesis Approved: {decision.get('thesis_approved', 'Unknown')}")
            parts.append(f"  Devil Approved: {decision.get('devil_approved', 'Unknown')}")
        else:
            parts.append("  [No decision recorded]")

        parts.append("\n## Analysis That Led to Decision:")
        for agent_name, data in analysis.items():
            signal = data.get("signal", "UNKNOWN")
            parts.append(f"  {agent_name}: {signal}")

        # Check if there's trade outcome data
        trade_result = context.get("trade_result", {})
        if trade_result:
            parts.append("\n## Trade Outcome:")
            parts.append(f"  Entry: {trade_result.get('entry_price', 'Unknown')}")
            parts.append(f"  Exit: {trade_result.get('exit_price', 'Unknown')}")
            parts.append(f"  P&L: {trade_result.get('pnl', 'Unknown')}")
            parts.append(f"  Duration: {trade_result.get('duration', 'Unknown')}")
        else:
            parts.append("\n## Trade Outcome: [Trade still open or NO_TRADE decision]")

        parts.append("\nReflect on this trade. What can we learn?")
        return "\n".join(parts)

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert TradeReflection to AgentReport and store in memory."""
        if isinstance(result, TradeReflection):
            # Store reflection in agent memory for future reference
            self.memory.store_reflection(result.model_dump())

            return AgentReport(
                agent_name=self.name,
                signal="COMPLETE",
                confidence=1.0,
                data=result.model_dump(),
                reasoning=(
                    f"Lesson: {result.lesson_learned} | "
                    f"Pattern: {result.pattern_type} | "
                    f"Should repeat: {result.should_repeat}"
                ),
                agent_type=AgentType.LLM,
                llm_latency_ms=llm_latency_ms,
            )
        return super()._to_report(result, llm_latency_ms)
