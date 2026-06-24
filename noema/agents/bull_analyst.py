"""Bull Analyst Agent — Actor team member for Noema Nexus.

Phase 2: The BullAnalyst is the primary proposal generator in the Analysis (Actor) team.
It synthesizes all analysis agent outputs into a structured trade proposal
with specific entry, stop-loss, and take-profit levels.

The BullAnalyst:
1. Receives analysis from all analysis team agents
2. Builds a structured trade thesis with concrete levels
3. Submits the proposal to the DebateEngine for critic evaluation
4. Participates in rebuttals during debate

This replaces/extends the TradeThesisAgent with actor-critic debate capabilities.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog

from noema.core.modern_agent import LLMAgent, AgentReport, AgentType
from noema.core.nim_client import NIMClient, ModelTier
from noema.models.schemas import TradeThesis as TradeThesisSchema, TradeDirection
from noema.decision import RiskContext, inject_risk_context
from noema.core.typed_messages import TradeProposalPayload

logger = structlog.get_logger(__name__)

BULL_ANALYST_SYSTEM_PROMPT = """You are the BULL ANALYST — the primary trade proposal generator for a forex trading system.

Your job: Synthesize analysis from multiple specialist agents into a concrete, actionable trade proposal.

You receive:
- Analysis results from technical agents (structure, S/R, momentum, institutional, etc.)
- Current market data (price, recent candles, session info)
- Risk context (account state, exposure, drawdown)

You MUST produce:
1. A specific DIRECTION (BUY or SELL) with concrete reasoning
2. Specific ENTRY PRICE level
3. Specific STOP LOSS level with reasoning
4. Specific TAKE PROFIT target with reasoning
5. A RISK/REWARD ratio (must be ≥ 1:2 for approval)
6. A CONFIDENCE score (0.0-1.0)
7. Supporting EVIDENCE from each analysis agent

Rules:
- Never propose a trade with R:R < 1:1.5
- Never propose a trade with confidence < 40%
- Always reference specific price levels for SL/TP
- If evidence is mixed, say so and reduce confidence
- Acknowledge weaknesses in your own thesis
- Focus on quality over quantity — one good proposal beats three mediocre ones
- If no clear setup exists, say NO_TRADE — patience is an edge"""


class BullAnalyst(LLMAgent):
    """Agent — Analysis (Actor) Team — Primary Trade Proposal Generator.

    Synthesizes analysis agent outputs into structured trade proposals
    with concrete entry, SL, and TP levels. Participates in the debate
    process by defending proposals against critic challenges.

    Uses LLM for reasoning, but final trade approval is DETERMINISTIC
    via the CriticManager + ConservativeTiebreaker.
    """

    name = "bull-analyst"
    role = "Bull Analyst (Actor Team)"
    priority = 2
    model_tier = ModelTier.STANDARD
    system_prompt = BULL_ANALYST_SYSTEM_PROMPT
    response_model = TradeThesisSchema
    temperature = 0.3
    tier_name = "decision"

    def __init__(self, config=None, nim_client: NIMClient | None = None):
        super().__init__(config=config, nim_client=nim_client)
        self._risk_context: RiskContext | None = None
        self._consecutive_rejections: int = 0
        self._max_rejections: int = 50  # Kill-switch threshold
        self._proposal_count: int = 0

    def set_risk_context(self, risk: RiskContext) -> None:
        """Set the current risk context for prompt injection."""
        self._risk_context = risk

    @property
    def consecutive_rejections(self) -> int:
        """Number of consecutive rejected proposals."""
        return self._consecutive_rejections

    @property
    def is_silenced(self) -> bool:
        """Whether agent should be silenced due to excessive rejections."""
        return self._consecutive_rejections >= self._max_rejections

    def record_rejection(self) -> None:
        """Record a proposal rejection."""
        self._consecutive_rejections += 1
        if self._consecutive_rejections >= self._max_rejections:
            logger.error(
                "bull_analyst_max_rejections",
                consecutive=self._consecutive_rejections,
                max=self._max_rejections,
            )

    def record_approval(self) -> None:
        """Record a proposal approval — resets rejection counter."""
        self._consecutive_rejections = 0

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
        """Format agent reports as structured input for the Bull Analyst."""
        analysis = context.get("analysis", {})
        analysis_signals = context.get("analysis_signals", {})
        symbol = context.get("symbol", "EURUSD")
        current_price = context.get("current_price", 0)
        bars = context.get("bars", [])
        risk_context = context.get("risk_context", {})

        parts = [
            f"## Trade Setup Analysis: {symbol}",
            f"Current Price: {current_price}",
            "",
        ]

        # Risk context summary
        if risk_context:
            parts.append("## Risk Context:")
            parts.append(f"  Exposure: {risk_context.get('exposure_pct', 0):.1f}%")
            parts.append(f"  Drawdown: {risk_context.get('drawdown_pct', 0):.1f}%")
            parts.append(f"  Consecutive Losses: {risk_context.get('consecutive_losses', 0)}")
            parts.append(f"  Open Positions: {risk_context.get('open_symbols', [])}")
            parts.append("")

        parts.append("## Analysis Agent Signals:")

        bullish = sum(1 for s in analysis_signals.values() if s == "BULLISH")
        bearish = sum(1 for s in analysis_signals.values() if s == "BEARISH")
        neutral = sum(1 for s in analysis_signals.values() if s in ("NEUTRAL", "ERROR"))
        parts.append(f"  Consensus: {bullish} bullish | {bearish} bearish | {neutral} neutral")

        for agent_name, signal in analysis_signals.items():
            confidence = context.get("analysis_confidence", {}).get(agent_name, 0)
            data = analysis.get(agent_name, {})
            parts.append(f"\n### {agent_name}")
            parts.append(f"  Signal: {signal} (confidence: {confidence:.0%})")
            if isinstance(data, dict):
                for key, value in data.items():
                    if key not in ("agent_name", "timestamp") and value:
                        if isinstance(value, (list, dict)):
                            parts.append(f"  {key}: {value}")
                        else:
                            str_val = str(value)[:200]
                            parts.append(f"  {key}: {str_val}")

        if bars:
            last_5 = bars[-5:] if len(bars) >= 5 else bars
            parts.append("\n## Recent Candles (last 5):")
            for bar in last_5:
                o = bar.get("open", 0)
                h = bar.get("high", 0)
                l = bar.get("low", 0)
                c = bar.get("close", 0)
                parts.append(f"  O={o:.5f} H={h:.5f} L={l:.5f} C={c:.5f}")

        parts.append("\n## Requirements:")
        parts.append("- Propose BUY, SELL, or NO_TRADE with specific reasoning")
        parts.append("- Identify SPECIFIC entry, stop-loss, and take-profit levels")
        parts.append("- Explain WHY each level was chosen (structure, S/R, ATR)")
        parts.append("- Calculate and state the R:R ratio")
        parts.append("- Acknowledge the main risk to this thesis")
        parts.append("- If evidence is insufficient, choose NO_TRADE")

        return "\n".join(parts)

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert TradeThesis schema to AgentReport for the team pipeline."""
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

    def build_proposal(
        self,
        report: AgentReport,
        symbol: str,
        entry_price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        lot_size: float = 0.01,
    ) -> TradeProposalPayload:
        """Build a structured trade proposal from an agent report.

        Args:
            report: The agent's analysis report.
            symbol: Trading symbol.
            entry_price: Entry price (0 = use current market).
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            lot_size: Position size in lots.

        Returns:
            TradeProposalPayload for the DebateEngine.
        """
        self._proposal_count += 1

        # Extract evidence from report data
        evidence = {}
        if isinstance(report.data, dict):
            for key, value in report.data.items():
                if key in ("narrative", "final_reasoning", "reasoning"):
                    continue
                if isinstance(value, (str, int, float, bool)):
                    evidence[key] = value

        # Calculate risk/reward
        risk_distance = abs(entry_price - stop_loss) if entry_price and stop_loss else 0
        reward_distance = abs(take_profit - entry_price) if entry_price and take_profit else 0
        rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0

        return TradeProposalPayload(
            proposal_id=f"prop-{self._proposal_count:04d}",
            direction=report.signal,
            symbol=symbol,
            confidence=report.confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward_ratio=round(rr_ratio, 2),
            lot_size=lot_size,
            evidence=evidence,
            risk_score=0.5 - report.confidence,  # Inverse: higher confidence = lower risk
            debate_quality="PENDING",
        )
