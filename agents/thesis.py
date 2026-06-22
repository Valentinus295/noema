"""Trade Thesis Agent — LLM-powered case builder for trades.

Uses NIM to synthesize all agent reports into a coherent trade narrative.
This is where LLM reasoning adds the most value — weighing conflicting signals.
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import LLMAgent, AgentReport, AgentType
from noema.core.nim_client import NIMClient, ModelTier
from noema.models.schemas import TradeThesis as TradeThesisSchema, TradeDirection

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are the Trade Thesis Builder for a forex trading system.

Your job: Given analysis from multiple specialist agents, build a compelling case FOR or AGAINST trading a specific pair.

You receive:
- Technical analysis results (trend, structure, S/R, momentum, price action)
- Current market data (price, recent candles)
- The direction hint (long or short)

You must:
1. Weigh the evidence from each agent
2. Identify which signals are strongest and weakest
3. Build a coherent narrative explaining WHY this trade should or shouldn't happen
4. Identify the SINGLE biggest risk
5. Assign a conviction score (0.0 = no conviction, 1.0 = absolute certainty)

Be analytical, not emotional. Focus on evidence, not hope.
If the evidence is mixed, say so — don't force a trade that isn't there."""


class TradeThesisAgent(LLMAgent):
    """Agent #11 — LLM-powered trade thesis builder.

    Synthesizes all agent reports into a coherent trade narrative.
    Uses NIM to weigh conflicting signals and build conviction.
    """

    name = "trade-thesis"
    role = "Trade Thesis Builder"
    priority = 2
    model_tier = ModelTier.STANDARD
    system_prompt = SYSTEM_PROMPT
    response_model = TradeThesisSchema
    temperature = 0.3

    def __init__(self, config=None, nim_client: NIMClient | None = None):
        super().__init__(config=config, nim_client=nim_client)

    def _build_user_message(self, context: dict[str, Any]) -> str:
        """Format agent reports as structured input for the LLM."""
        analysis = context.get("analysis", {})
        analysis_signals = context.get("analysis_signals", {})
        symbol = context.get("symbol", "EURUSD")
        current_price = context.get("current_price", 0)
        bars = context.get("bars", [])

        parts = [
            f"## Trade Setup: {symbol}",
            f"Current Price: {current_price}",
            "",
            "## Agent Analysis Results:",
        ]

        for agent_name, signal in analysis_signals.items():
            confidence = context.get("analysis_confidence", {}).get(agent_name, 0)
            data = analysis.get(agent_name, {})
            parts.append(f"\n### {agent_name}")
            parts.append(f"  Signal: {signal} (confidence: {confidence:.0%})")
            if data:
                # Include key data points
                for key, value in data.items():
                    if key not in ("agent_name", "timestamp") and value:
                        parts.append(f"  {key}: {value}")

        # Add recent candle summary
        if bars:
            last_5 = bars[-5:] if len(bars) >= 5 else bars
            parts.append("\n## Recent Candles (last 5):")
            for bar in last_5:
                parts.append(
                    f"  O={bar.open:.5f} H={bar.high:.5f} L={bar.low:.5f} C={bar.close:.5f}"
                )

        return "\n".join(parts)

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert TradeThesis schema to AgentReport."""
        if isinstance(result, TradeThesisSchema):
            signal = result.direction.value if result.direction != TradeDirection.NO_TRADE else "NEUTRAL"
            return AgentReport(
                agent_name=self.name,
                signal=signal,
                confidence=result.conviction,
                data=result.model_dump(),
                reasoning=result.narrative,
                agent_type=AgentType.LLM,
                llm_latency_ms=llm_latency_ms,
            )
        return super()._to_report(result, llm_latency_ms)
