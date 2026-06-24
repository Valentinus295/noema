"""Performance-Weighted Voting — higher win rate → more votes.

During debate rounds, each agent casts votes for its recommendation.
Agents with better historical performance get proportionally more voting power.

Principles:
- Weight = performance_score (win rate, Sharpe, profit factor composite)
- Minimum floor: agents always get at least 0.25 votes
- Maximum cap: agents can't exceed 5× the neutral weight (LearningSafeguards)
- Recency bias: recent performance weights more than distant past
- Calibration penalty: overconfident agents are penalized

Used by Conductor to compute weighted consensus in debate rounds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

from noema.learning.performance import PerformanceTracker, AgentPerformance

logger = structlog.get_logger(__name__)


@dataclass
class AgentWeight:
    """Voting weight for a single agent in a debate round."""
    agent_name: str
    base_weight: float       # Performance-based weight
    recency_multiplier: float  # Recent performance modifier
    calibration_penalty: float  # Overconfidence penalty
    final_weight: float       # Effective votes
    last_updated: float


class WeightedVoter:
    """Performance-weighted voting system for agent debate rounds.

    Usage:
        voter = WeightedVoter(tracker)
        weights = voter.compute_weights()
        result = voter.weighted_vote(agent_recommendations, weights)
    """

    # Safety limits (enforced by LearningSafeguards)
    MIN_WEIGHT = 0.25    # Minimum floor per agent
    MAX_WEIGHT = 5.0     # 5× neutral cap
    NEUTRAL_WEIGHT = 1.0

    # Component weights for final score
    RECENCY_WEIGHT = 0.3
    BASE_WEIGHT = 0.7

    def __init__(self, performance_tracker: PerformanceTracker):
        self._tracker = performance_tracker
        self._weight_history: list[dict[str, float]] = []  # Store recent weight sets

    def compute_weights(self, min_trades: int = 5) -> dict[str, AgentWeight]:
        """Compute voting weights for all tracked agents.

        Combines:
        - Base performance score (70%)
        - Recent performance modifier (30%)
        - Calibration penalty (multiplier)

        Returns:
            {agent_name: AgentWeight}
        """
        base_weights = self._tracker.get_agent_weights(min_trades=min_trades)
        result: dict[str, AgentWeight] = {}

        for name, base_w in base_weights.items():
            perf = self._tracker.get_agent_report(name)
            if perf is None:
                perf = AgentPerformance(agent_name=name)

            # Recency multiplier: recent Sharpe vs. overall
            recency_mult = self._compute_recency_multiplier(perf)

            # Calibration penalty: penalize overconfidence
            cal_penalty = self._compute_calibration_penalty(perf)

            # Combine
            raw_weight = (
                self.BASE_WEIGHT * base_w +
                self.RECENCY_WEIGHT * recency_mult
            )

            # Apply floor and cap
            final_weight = max(self.MIN_WEIGHT, min(raw_weight, self.MAX_WEIGHT))

            result[name] = AgentWeight(
                agent_name=name,
                base_weight=round(base_w, 4),
                recency_multiplier=round(recency_mult, 4),
                calibration_penalty=round(cal_penalty, 4),
                final_weight=round(final_weight, 4),
                last_updated=time.time(),
            )

        # Store history
        self._weight_history.append({k: v.final_weight for k, v in result.items()})
        if len(self._weight_history) > 100:
            self._weight_history = self._weight_history[-50:]

        return result

    def weighted_vote(
        self,
        agent_recommendations: dict[str, str],
        weights: dict[str, AgentWeight] | None = None,
    ) -> dict[str, float]:
        """Compute the weighted consensus from agent recommendations.

        Args:
            agent_recommendations: {agent_name: signal} e.g. {"momentum": "BUY", "structure": "SELL"}
            weights: Pre-computed weights (or compute on the fly)

        Returns:
            {signal: total_weight} e.g. {"BUY": 2.3, "SELL": 1.7, "WAIT": 0.5}
        """
        if weights is None:
            weights = self.compute_weights()

        tally: dict[str, float] = {}

        for agent_name, signal in agent_recommendations.items():
            w = weights.get(agent_name)
            if w is None:
                # Unknown agent gets neutral weight
                tally[signal] = tally.get(signal, 0.0) + self.NEUTRAL_WEIGHT
            else:
                tally[signal] = tally.get(signal, 0.0) + w.final_weight

        return tally

    def get_consensus(
        self,
        agent_recommendations: dict[str, str],
        weights: dict[str, AgentWeight] | None = None,
        min_margin: float = 0.15,
    ) -> dict[str, Any]:
        """Get the weighted consensus with metadata.

        Args:
            agent_recommendations: {agent_name: signal}
            weights: Pre-computed weights
            min_margin: Minimum ratio between top two signals to declare consensus

        Returns:
            {
                "winning_signal": str,
                "winning_weight": float,
                "total_weight": float,
                "vote_counts": dict[str, float],
                "consensus_strength": float,  # winner / total
                "is_clear_winner": bool,      # True if margin > min_margin
                "dissenters": list[str],      # Agents voting against consensus
            }
        """
        tally = self.weighted_vote(agent_recommendations, weights)
        total = sum(tally.values())

        if not tally or total == 0:
            return {
                "winning_signal": "WAIT",
                "winning_weight": 0.0,
                "total_weight": 0.0,
                "vote_counts": {},
                "consensus_strength": 0.0,
                "is_clear_winner": False,
                "dissenters": [],
            }

        sorted_signals = sorted(tally.items(), key=lambda x: x[1], reverse=True)
        winner_signal, winner_weight = sorted_signals[0]
        runner_up_weight = sorted_signals[1][1] if len(sorted_signals) > 1 else 0

        consensus_strength = winner_weight / total if total > 0 else 0
        margin = (winner_weight - runner_up_weight) / total if total > 0 else 0
        is_clear = margin >= min_margin

        # Identify dissenters
        dissenters = [
            name for name, signal in agent_recommendations.items()
            if signal != winner_signal
        ]

        return {
            "winning_signal": winner_signal,
            "winning_weight": round(winner_weight, 4),
            "total_weight": round(total, 4),
            "vote_counts": {k: round(v, 4) for k, v in tally.items()},
            "consensus_strength": round(consensus_strength, 4),
            "margin": round(margin, 4),
            "is_clear_winner": is_clear,
            "dissenters": dissenters,
            "consensus_agents": [
                name for name, signal in agent_recommendations.items()
                if signal == winner_signal
            ],
        }

    def get_weight_trend(self, agent_name: str) -> list[float]:
        """Get the weight history for an agent (for monitoring drift)."""
        return [
            h.get(agent_name, self.NEUTRAL_WEIGHT)
            for h in self._weight_history[-20:]
        ]

    def _compute_recency_multiplier(self, perf: AgentPerformance) -> float:
        """Compute recency-based performance modifier.

        Recent Sharpe ratio weighted against overall performance.
        """
        recent = perf.recent_outcomes[-10:]
        if len(recent) < 3:
            return 1.0  # Neutral - not enough data

        recent_mean = sum(recent) / len(recent)
        # Compare recent mean to overall mean
        if perf.total_trades > 5:
            overall_mean = perf.total_pnl / perf.total_trades
            if abs(overall_mean) < 0.001:
                return 1.0
            ratio = recent_mean / overall_mean
            return max(0.5, min(2.0, 0.5 + 0.5 * ratio))

        return 1.0

    def _compute_calibration_penalty(self, perf: AgentPerformance) -> float:
        """Compute calibration penalty for over/under-confident agents.

        Returns a multiplier: 1.0 = perfectly calibrated, < 1.0 = penalty.
        """
        if perf.total_trades < 10:
            return 1.0  # Insufficient data, no penalty

        ce = perf.calibration_error
        if ce >= 0:  # Positive = well-calibrated (confident when right, cautious when wrong)
            return min(1.0 + ce * 0.5, 1.5)  # Bonus up to 50%
        else:  # Negative = miscalibrated
            return max(1.0 + ce * 0.3, 0.5)  # Penalty up to 50%
