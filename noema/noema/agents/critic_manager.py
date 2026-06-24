"""Critic Manager Agent — Critic team coordinator for Noema Nexus.

Phase 2: The CriticManager coordinates the Critic team's evaluation of trade
proposals. It NEVER uses LLM for override decisions — all final decisions
go through ConservativeTiebreaker.

The CriticManager:
1. Distributes proposals to critic team agents (Devil, Risk Manager, Guardian)
2. Collects and aggregates critic votes
3. Submits votes to the ConservativeTiebreaker for deterministic resolution
4. Returns a decisive verdict: APPROVE, REJECT, REDUCE_SIZE, or NO_TRADE

Anti-hallucination:
- The CriticManager NEVER uses LLM for decision overrides
- All vote aggregation is deterministic
- The ConservativeTiebreaker is the sole decision authority
- LLM is only used by individual critic agents for argument generation
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.core.conservative_tiebreaker import (
    ConservativeTiebreaker, TiebreakerDecision, TiebreakerResult,
)
from noema.core.typed_messages import ProposalFeedback, TradeProposalPayload

logger = structlog.get_logger(__name__)


class CriticManager(DeterministicAgent):
    """Agent — Critic Team Coordinator — NON-LLM tiebreaker.

    Coordinates the Critic team's evaluation of trade proposals.
    Uses ConservativeTiebreaker (PURE PYTHON) for final resolution.

    NEVER uses LLM for decision override. This is the anti-hallucination
    guarantee: the critic team's votes are counted deterministically.
    """

    name = "critic-manager"
    role = "Critic Team Manager"
    priority = 3  # Runs after analysis, before execution

    # Thresholds for decision quality
    MIN_CRITIC_VOTES = 2  # Minimum votes required for a decision
    APPROVE_THRESHOLD = 0.7  # Confidence threshold for approval
    REDUCE_THRESHOLD = 0.5  # Confidence threshold for reduced size

    def __init__(self, config=None, nim_client=None):
        super().__init__(config=config, nim_client=nim_client)
        self._tiebreaker = ConservativeTiebreaker(min_quorum=self.MIN_CRITIC_VOTES)
        self._decisions_made: int = 0
        self._approvals: int = 0
        self._rejections: int = 0

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Evaluate analysis team output and produce a critic verdict.

        This is the DETERMINISTIC critic evaluation. It:
        1. Collects votes from all critic team agents
        2. Weighs them by agent confidence and any performance-based weights
        3. Submits to ConservativeTiebreaker for resolution
        4. Returns a decisive verdict

        Args:
            context: Contains analysis results, proposal data, and critic votes.

        Returns:
            AgentReport with deterministic critic decision.
        """
        analysis_signals = context.get("analysis_signals", {})
        analysis_confidence = context.get("analysis_confidence", {})
        critic_votes = context.get("critic_votes", {})
        proposal = context.get("proposal", {})
        agent_weights = context.get("agent_weights", {})
        symbol = context.get("symbol", "UNKNOWN")
        risk_context = context.get("risk_context", {})

        # ── Collect and aggregate critic votes ──
        if critic_votes:
            vote_strings = list(critic_votes.values())
        else:
            # Derive from analysis signals if no explicit critic votes
            vote_strings = self._derive_votes_from_signals(
                analysis_signals, analysis_confidence, risk_context
            )

        # ── Apply agent weights to vote strengths (if available) ──
        if agent_weights and critic_votes:
            weighted_vote_strings = []
            for agent_name, vote in critic_votes.items():
                weight = agent_weights.get(agent_name, 1.0)
                if weight < 0.3:
                    # Heavily discounted agent — downgrade to NO_TRADE
                    weighted_vote_strings.append("NO_TRADE")
                elif weight < 0.7:
                    # Reduced weight — downgrade to more conservative
                    if vote.upper() in ("FULL_SIZE", "APPROVE", "BUY", "SELL"):
                        weighted_vote_strings.append("REDUCE_SIZE")
                    else:
                        weighted_vote_strings.append(vote)
                else:
                    weighted_vote_strings.append(vote)
            vote_strings = weighted_vote_strings

        # ── DETERMINISTIC RESOLUTION via ConservativeTiebreaker ──
        # This is the SOLE DECISION AUTHORITY — no LLM involvement
        tb_result = self._tiebreaker.resolve_from_strings(vote_strings)

        # ── Build the report ──
        self._decisions_made += 1
        signal = "NO_TRADE"
        confidence = 0.5
        reasoning_parts = [
            f"Critic Manager Decision for {symbol}",
            f"Votes received: {vote_strings}",
            f"Tiebreaker rule: {tb_result.rule_applied}",
            f"Final decision: {tb_result.decision.value}",
        ]

        if tb_result.decision == TiebreakerDecision.FULL_SIZE:
            signal = "APPROVE"
            confidence = self._calculate_approval_confidence(analysis_confidence)
            self._approvals += 1
            reasoning_parts.append("✓ All critics approve — trade authorized at FULL SIZE")
        elif tb_result.decision == TiebreakerDecision.REDUCE_SIZE:
            signal = "REDUCE_SIZE"
            confidence = self._calculate_reduce_confidence(analysis_confidence)
            reasoning_parts.append("⚠ Mixed critic votes — trade authorized at REDUCED SIZE")
        else:
            signal = "REJECT"
            confidence = 0.9
            self._rejections += 1
            reasoning_parts.append(f"✗ Trade REJECTED — {tb_result.rule_applied}")
            if tb_result.details:
                reasoning_parts.append(f"  Details: {tb_result.details}")

        # ── Log the decision ──
        logger.info(
            "critic_manager_decision",
            symbol=symbol,
            signal=signal,
            votes=vote_strings,
            rule=tb_result.rule_applied,
            total_decisions=self._decisions_made,
        )

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data={
                "verdict": signal,
                "tiebreaker_result": tb_result.decision.value,
                "tiebreaker_rule": tb_result.rule_applied,
                "votes": vote_strings,
                "vote_counts": tb_result.vote_counts,
                "quorum_met": tb_result.quorum_met,
                "no_llm_involved": tb_result.no_llm_involved,
                "decisions_made": self._decisions_made,
                "approvals": self._approvals,
                "rejections": self._rejections,
            },
            reasoning="\n".join(reasoning_parts),
        )

    def _derive_votes_from_signals(
        self,
        analysis_signals: dict[str, str],
        analysis_confidence: dict[str, float],
        risk_context: dict[str, Any],
    ) -> list[str]:
        """Derive critic votes from analysis agent signals when no explicit votes exist.

        This provides a fallback when the full critic team hasn't cast votes.
        The mapping is conservative — NO_TRADE is the default for uncertain signals.

        Args:
            analysis_signals: {agent_name: signal} from analysis agents.
            analysis_confidence: {agent_name: confidence} from analysis agents.
            risk_context: Current risk state.

        Returns:
            List of vote strings for ConservativeTiebreaker.
        """
        votes: list[str] = []

        # Count bullish vs bearish
        bullish = sum(1 for s in analysis_signals.values() if s == "BULLISH")
        bearish = sum(1 for s in analysis_signals.values() if s == "BEARISH")
        neutral = sum(1 for s in analysis_signals.values() if s in ("NEUTRAL", "ERROR"))

        # Average confidence
        confidences = list(analysis_confidence.values())
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Check risk context
        is_elevated_risk = (
            risk_context.get("is_critical", False)
            or risk_context.get("is_elevated", False)
            or risk_context.get("risk_multiplier", 1.0) < 0.7
        )

        # ── Vote generation ──
        if is_elevated_risk:
            # Any elevated risk → NO_TRADE vote from risk perspective
            votes.append("NO_TRADE")

        if bullish > bearish + 1 and avg_confidence > 0.6:
            votes.append("FULL_SIZE")
        elif abs(bullish - bearish) <= 1:
            votes.append("REDUCE_SIZE")  # Mixed signals → reduce
        else:
            votes.append("NO_TRADE")

        if neutral > bullish + bearish:
            votes.append("NO_TRADE")  # Too much uncertainty

        # Ensure minimum votes
        if len(votes) < self.MIN_CRITIC_VOTES:
            votes.append("NO_TRADE")  # Default conservatism

        return votes

    def _calculate_approval_confidence(
        self, analysis_confidence: dict[str, float]
    ) -> float:
        """Calculate approval confidence from analysis agent confidences."""
        confidences = [c for c in analysis_confidence.values() if c > 0]
        if not confidences:
            return 0.5
        avg = sum(confidences) / len(confidences)
        return min(0.95, max(0.5, avg))

    def _calculate_reduce_confidence(
        self, analysis_confidence: dict[str, float]
    ) -> float:
        """Calculate reduced-size confidence."""
        confidences = [c for c in analysis_confidence.values() if c > 0]
        if not confidences:
            return 0.4
        avg = sum(confidences) / len(confidences)
        return min(0.75, max(0.3, avg * 0.8))

    # ── Convenience Methods ────────────────────────────────────────

    def evaluate_proposal(
        self,
        proposal: TradeProposalPayload,
        critic_votes: dict[str, str],
        agent_weights: dict[str, float] | None = None,
    ) -> ProposalFeedback:
        """Evaluate a trade proposal and return structured feedback.

        This is a synchronous convenience method for evaluating proposals
        without going through the full agent pipeline.

        Args:
            proposal: The trade proposal to evaluate.
            critic_votes: Votes from critic team agents.
            agent_weights: Optional performance-based weights.

        Returns:
            ProposalFeedback with deterministic decision.
        """
        vote_strings = list(critic_votes.values())

        # Apply weights if provided
        if agent_weights:
            weighted = []
            for agent_name, vote in critic_votes.items():
                weight = agent_weights.get(agent_name, 1.0)
                if weight < 0.3:
                    weighted.append("NO_TRADE")
                elif weight < 0.7 and vote.upper() in ("FULL_SIZE", "APPROVE", "BUY", "SELL"):
                    weighted.append("REDUCE_SIZE")
                else:
                    weighted.append(vote)
            vote_strings = weighted

        tb_result = self._tiebreaker.resolve_from_strings(vote_strings)

        # Map to feedback decision
        if tb_result.decision == TiebreakerDecision.FULL_SIZE:
            decision = "APPROVE"
            reason = "All critic votes approve — trade authorized at full size"
        elif tb_result.decision == TiebreakerDecision.REDUCE_SIZE:
            decision = "MODIFY"
            reason = "Mixed critic votes — reduce position size by 50%"
        else:
            decision = "REJECT"
            reason = f"Trade rejected: {tb_result.rule_applied} — {tb_result.details}"

        # Calculate aggregate confidence
        critic_scores = dict(critic_votes)
        aggregate_confidence = proposal.confidence
        if tb_result.decision == TiebreakerDecision.NO_TRADE:
            aggregate_confidence = 0.1
        elif tb_result.decision == TiebreakerDecision.REDUCE_SIZE:
            aggregate_confidence *= 0.6

        return ProposalFeedback(
            proposal_id=proposal.proposal_id,
            decision=decision,
            reason=reason,
            suggested_modifications={
                "reduced_size_pct": 0.5 if decision == "MODIFY" else 1.0,
                "tiebreaker_rule": tb_result.rule_applied,
            },
            critic_scores=critic_scores,
            aggregate_confidence=round(aggregate_confidence, 2),
        )

    @property
    def decisions_made(self) -> int:
        return self._decisions_made

    @property
    def approval_rate(self) -> float:
        return self._approvals / self._decisions_made if self._decisions_made > 0 else 0.0

    def get_stats(self) -> dict[str, Any]:
        """Get critic manager statistics."""
        return {
            "name": self.name,
            "decisions_made": self._decisions_made,
            "approvals": self._approvals,
            "rejections": self._rejections,
            "approval_rate": self.approval_rate,
            "min_quorum": self._tiebreaker.MIN_QUORUM,
        }
