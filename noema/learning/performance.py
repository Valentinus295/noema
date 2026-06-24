"""Performance Tracking — agent-level win rate, Sharpe, profit factor.

Tracks every agent's contribution to trading outcomes:
- Win rate (trades where agent's signal matched outcome direction)
- Sharpe ratio (risk-adjusted returns from agent-backed trades)
- Profit factor (gross profit / gross loss for agent-backed trades)
- Calibration error (confidence vs. actual win rate)
- Recent performance (last N trades for recency weighting)
- Drawdown contribution (how much drawdown this agent's trades caused)

Used by WeightedVoter to allocate voting power proportionally to performance.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AgentPerformance:
    """Performance statistics for a single agent."""
    agent_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    sum_confidence_when_correct: float = 0.0
    sum_confidence_when_wrong: float = 0.0
    trades_when_consensus_winner: int = 0  # Agent was in majority AND trade won
    trades_when_lone_winner: int = 0       # Agent was alone correct
    trades_when_consensus_loser: int = 0   # Agent was in majority AND trade lost
    max_drawdown_contribution: float = 0.0
    recent_outcomes: list[float] = field(default_factory=list)  # Last 20 PnLs
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.5  # Prior: neutral
        return self.winning_trades / self.total_trades

    @property
    def profit_factor(self) -> float:
        """Gross profit / |gross loss|. >1.0 is profitable."""
        if abs(self.gross_loss) < 0.0001:
            return self.gross_profit if self.gross_profit > 0 else float("inf")
        return self.gross_profit / abs(self.gross_loss)

    @property
    def sharpe(self) -> float:
        """Simple Sharpe-like ratio from recent outcomes."""
        outcomes = self.recent_outcomes[-20:]  # Rolling 20-trade window
        if len(outcomes) < 3:
            return 0.0
        mean = np.mean(outcomes)
        std = np.std(outcomes, ddof=1)
        if std < 0.0001:
            return 0.0 if mean == 0 else (1.0 if mean > 0 else -1.0)
        return mean / std

    @property
    def calibration_error(self) -> float:
        """How well agent confidence predicts outcomes.

        Low error = well-calibrated. High error = over/under-confident.
        """
        total_correct = self.sum_confidence_when_correct
        total_wrong = self.sum_confidence_when_wrong
        if self.total_trades == 0:
            return 0.5  # Neutral prior
        # Mean confidence when correct - mean confidence when wrong
        n_correct = self.winning_trades
        n_wrong = self.losing_trades
        avg_correct = total_correct / max(n_correct, 1)
        avg_wrong = total_wrong / max(n_wrong, 1)
        return avg_correct - avg_wrong  # Positive = well-calibrated

    @property
    def performance_score(self) -> float:
        """Composite performance score for voting weight allocation.

        Combines: win rate (40%), profit factor (30%), Sharpe (20%), calibration (10%)
        """
        wr = self.win_rate
        pf = min(self.profit_factor, 5.0) / 5.0  # Normalize to [0, 1]
        sh = max(-1.0, min(self.sharpe, 3.0))     # Clip Sharpe to [-1, 3]
        sh_norm = (sh + 1.0) / 4.0                 # Normalize to [0, 1]
        cal = max(0.0, min(self.calibration_error, 1.0))

        score = 0.40 * wr + 0.30 * pf + 0.20 * sh_norm + 0.10 * cal
        return max(0.0, min(score, 1.0))

    def record_trade(
        self,
        won: bool,
        pnl: float,
        confidence: float,
        was_consensus: bool = False,
        was_lone_correct: bool = False,
    ) -> None:
        """Record a trade outcome for this agent.

        Args:
            won: Whether the trade was profitable
            pnl: Profit/loss amount
            confidence: Agent's reported confidence (0-1)
            was_consensus: Agent was in the majority opinion
            was_lone_correct: Agent was the only correct agent
        """
        self.total_trades += 1
        self.total_pnl += pnl

        if won:
            self.winning_trades += 1
            self.gross_profit += pnl
            self.sum_confidence_when_correct += confidence
            if was_consensus:
                self.trades_when_consensus_winner += 1
            if was_lone_correct:
                self.trades_when_lone_winner += 1
        else:
            self.losing_trades += 1
            self.gross_loss += abs(pnl)
            self.sum_confidence_when_wrong += confidence
            if was_consensus:
                self.trades_when_consensus_loser += 1

        # Track drawdown contribution
        self.max_drawdown_contribution = max(self.max_drawdown_contribution, abs(pnl))

        # Rolling recent outcomes
        self.recent_outcomes.append(pnl)
        if len(self.recent_outcomes) > 50:
            self.recent_outcomes = self.recent_outcomes[-50:]

        self.last_updated = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "sharpe": round(self.sharpe, 4),
            "calibration_error": round(self.calibration_error, 4),
            "performance_score": round(self.performance_score, 4),
            "total_pnl": round(self.total_pnl, 2),
            "lone_winner_rate": (
                self.trades_when_lone_winner / max(self.total_trades, 1)
            ),
        }


class PerformanceTracker:
    """Tracks performance for all agents across the trading pipeline.

    Integrates with GuardianState for drawdown and kill-switch awareness.
    """

    DEFAULT_MIN_TRADES_FOR_SCORE = 5  # Don't score agents with < N trades

    def __init__(self):
        self._agents: dict[str, AgentPerformance] = {}
        self._global_stats: dict[str, Any] = {
            "total_trades": 0,
            "total_wins": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "peak_pnl": 0.0,
            "consecutive_losses": 0,
            "consecutive_wins": 0,
        }

    def get_or_create(self, agent_name: str) -> AgentPerformance:
        """Get or create performance tracking for an agent."""
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentPerformance(agent_name=agent_name)
        return self._agents[agent_name]

    def record_trade(
        self,
        agent_signals: dict[str, dict[str, Any]],
        outcome: dict[str, Any],
        consensus_agents: set[str] | None = None,
    ) -> None:
        """Record a trade outcome across all agents that provided signals.

        Args:
            agent_signals: {agent_name: {signal, confidence}}
            outcome: {won: bool, pnl: float, direction: str}
            consensus_agents: Set of agent names that agreed with the consensus
        """
        won = outcome.get("won", False)
        pnl = outcome.get("pnl", 0.0)
        consensus = consensus_agents or set()

        # Determine which agents were correct
        correct_agents: set[str] = set()
        trade_direction = outcome.get("direction", "")

        for name, signal_data in agent_signals.items():
            signal = signal_data.get("signal", "").upper()
            # Determine if signal matched outcome direction
            if trade_direction == "long" and signal in ("BUY", "BULLISH", "LONG"):
                correct_agents.add(name)
            elif trade_direction == "short" and signal in ("SELL", "BEARISH", "SHORT"):
                correct_agents.add(name)

        # Record for each agent
        for name, signal_data in agent_signals.items():
            perf = self.get_or_create(name)
            agent_won = name in correct_agents
            confidence = signal_data.get("confidence", 0.5)
            was_consensus = name in consensus
            was_lone_correct = agent_won and name not in consensus

            perf.record_trade(
                won=agent_won,
                pnl=pnl if agent_won else -abs(pnl),
                confidence=confidence,
                was_consensus=was_consensus,
                was_lone_correct=was_lone_correct,
            )

        # Update global stats
        self._global_stats["total_trades"] += 1
        self._global_stats["total_pnl"] += pnl
        if won:
            self._global_stats["total_wins"] += 1
            self._global_stats["consecutive_wins"] += 1
            self._global_stats["consecutive_losses"] = 0
        else:
            self._global_stats["consecutive_losses"] += 1
            self._global_stats["consecutive_wins"] = 0

        # Track drawdown
        current_pnl = self._global_stats["total_pnl"]
        self._global_stats["peak_pnl"] = max(self._global_stats["peak_pnl"], current_pnl)
        dd = self._global_stats["peak_pnl"] - current_pnl
        self._global_stats["max_drawdown"] = max(self._global_stats["max_drawdown"], dd)

        logger.debug(
            "performance_trade_recorded",
            total=self._global_stats["total_trades"],
            pnl=round(pnl, 2),
            win_rate=round(self._global_stats["total_wins"] / self._global_stats["total_trades"], 3),
        )

    def get_agent_weights(
        self, min_trades: int | None = None
    ) -> dict[str, float]:
        """Get performance-based weights for all agents.

        Agents with fewer than min_trades get a neutral weight of 0.5.
        Weights are normalized to sum to N (so average = 1.0).

        Returns:
            {agent_name: weight} where weight is the number of votes
        """
        min_t = min_trades if min_trades is not None else self.DEFAULT_MIN_TRADES_FOR_SCORE

        raw_weights: dict[str, float] = {}
        for name, perf in self._agents.items():
            if perf.total_trades >= min_t:
                raw_weights[name] = perf.performance_score
            else:
                raw_weights[name] = 0.5  # Neutral prior

        # Normalize: average weight = 1.0 (each agent gets ~1 vote by default)
        total = sum(raw_weights.values())
        n = len(raw_weights)
        if total > 0 and n > 0:
            target_total = float(n)  # Sum to N
            raw_weights = {k: v / total * target_total for k, v in raw_weights.items()}

        return raw_weights

    def get_top_performers(self, n: int = 5) -> list[AgentPerformance]:
        """Get the top N performing agents by performance score."""
        scored = [
            p for p in self._agents.values()
            if p.total_trades >= self.DEFAULT_MIN_TRADES_FOR_SCORE
        ]
        scored.sort(key=lambda p: p.performance_score, reverse=True)
        return scored[:n]

    def get_bottom_performers(self, n: int = 5) -> list[AgentPerformance]:
        """Get the bottom N performing agents (for review/mutation)."""
        scored = [
            p for p in self._agents.values()
            if p.total_trades >= self.DEFAULT_MIN_TRADES_FOR_SCORE
        ]
        scored.sort(key=lambda p: p.performance_score)
        return scored[:n]

    def get_global_stats(self) -> dict[str, Any]:
        """Get global trading performance statistics."""
        gs = self._global_stats
        total = gs["total_trades"]
        return {
            **gs,
            "win_rate": gs["total_wins"] / max(total, 1),
            "profit_factor": self._compute_global_profit_factor(),
        }

    def _compute_global_profit_factor(self) -> float:
        gross_profit = sum(
            p.gross_profit for p in self._agents.values()
        )
        gross_loss = sum(
            p.gross_loss for p in self._agents.values()
        )
        if gross_loss < 0.0001:
            return gross_profit if gross_profit > 0 else float("inf")
        return gross_profit / gross_loss

    def get_agent_report(self, agent_name: str) -> AgentPerformance | None:
        """Get full performance report for a specific agent."""
        return self._agents.get(agent_name)

    def get_all_agent_reports(self) -> dict[str, dict[str, Any]]:
        """Get all agent performance reports."""
        return {name: perf.to_dict() for name, perf in self._agents.items()}

    def reset(self) -> None:
        """Reset all tracking (for testing)."""
        self._agents.clear()
        self._global_stats = {
            "total_trades": 0,
            "total_wins": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "peak_pnl": 0.0,
            "consecutive_losses": 0,
            "consecutive_wins": 0,
        }
