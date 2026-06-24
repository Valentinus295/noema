"""Daily Experience Replay & Consolidation.

Implements two key mechanisms from continual learning:

1. Experience Replay Buffer:
   - Stores significant trade episodes (largest |PnL|, most informative)
   - Replayed during daily consolidation to prevent catastrophic forgetting
   - Priority-based sampling: trades with higher |PnL| or surprise are replayed more often

2. Regret Minimization:
   - Compares actual outcomes against counterfactual "best possible" actions
   - "What if we took the opposite trade?" — quantifies regret
   - "What if we used a tighter SL?" — parameter optimization through regret
   - Regret-minimizing updates to procedural rules and agent weights

3. Anti-Catastrophic Forgetting:
   - Elastic Weight Consolidation (EWC) via semantic memory
   - Weekly replay of top-N significant episodes
   - Learning rate decay on well-established patterns
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from noema.learning.performance import PerformanceTracker
from noema.learning.safeguards import LearningSafeguards
from noema.memory.manager import MemoryManager

logger = structlog.get_logger(__name__)


@dataclass
class ReplayEpisode:
    """An episode stored in the experience replay buffer."""
    episode_id: str  # Usually the trade_id
    symbol: str
    features: dict[str, Any]
    agent_signals: dict[str, dict]
    outcome_won: bool
    pnl: float
    priority: float  # Higher = replayed more often
    stored_at: float = field(default_factory=time.time)
    times_replayed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperienceReplay:
    """Priority experience replay buffer for significant trading episodes.

    Stores the most informative trade episodes and replays them during
    consolidation to reinforce learning and prevent forgetting.

    Priority calculation:
        priority = |pnl| * (1 + surprise_factor)
    where surprise_factor is higher when the outcome contradicted agent consensus.
    """

    MAX_BUFFER_SIZE = 500
    MIN_PRIORITY_FOR_STORAGE = 0.1  # Don't store trivial trades
    DEFAULT_BATCH_SIZE = 20

    def __init__(self):
        self._buffer: list[ReplayEpisode] = []
        self._replay_count: int = 0

    def add_episode(
        self,
        episode_id: str,
        symbol: str,
        features: dict[str, Any],
        agent_signals: dict[str, dict],
        outcome_won: bool,
        pnl: float,
        consensus_signal: str | None = None,
    ) -> bool:
        """Add an episode to the replay buffer.

        Returns True if stored, False if below priority threshold.
        """
        # Compute priority: significant PnL + surprise factor
        abs_pnl = abs(pnl)

        # Surprise: how much did the outcome contradict the consensus?
        surprise_factor = self._compute_surprise(agent_signals, outcome_won, consensus_signal)

        priority = abs_pnl * (1.0 + surprise_factor)

        if priority < self.MIN_PRIORITY_FOR_STORAGE:
            return False

        episode = ReplayEpisode(
            episode_id=episode_id,
            symbol=symbol,
            features=features,
            agent_signals=agent_signals,
            outcome_won=outcome_won,
            pnl=pnl,
            priority=priority,
        )

        self._buffer.append(episode)

        # Prune if over capacity (remove lowest priority)
        if len(self._buffer) > self.MAX_BUFFER_SIZE:
            self._buffer.sort(key=lambda e: e.priority)
            removed = self._buffer[:len(self._buffer) - self.MAX_BUFFER_SIZE]
            self._buffer = self._buffer[-self.MAX_BUFFER_SIZE:]
            logger.debug(
                "replay_buffer_pruned",
                removed=len(removed),
                remaining=len(self._buffer),
            )

        return True

    def sample_batch(
        self, batch_size: int | None = None, min_priority: float = 0.0
    ) -> list[ReplayEpisode]:
        """Sample a batch of episodes for replay.

        Uses priority-weighted sampling: higher priority episodes
        are more likely to be selected for replay.

        Args:
            batch_size: Number of episodes to sample (default: DEFAULT_BATCH_SIZE)
            min_priority: Minimum priority threshold

        Returns:
            List of sampled ReplayEpisodes
        """
        n = batch_size or self.DEFAULT_BATCH_SIZE

        candidates = [e for e in self._buffer if e.priority >= min_priority]
        if not candidates:
            return []

        # Priority-weighted sampling
        priorities = np.array([e.priority for e in candidates], dtype=np.float64)
        probs = priorities / priorities.sum()

        n_sample = min(n, len(candidates))
        indices = np.random.choice(len(candidates), size=n_sample, replace=False, p=probs)

        sampled = [candidates[i] for i in indices]
        for ep in sampled:
            ep.times_replayed += 1

        self._replay_count += n_sample
        return sampled

    def get_weekly_replay_batch(self, n: int = 10) -> list[ReplayEpisode]:
        """Get the most significant episodes for weekly replay.

        Used to prevent catastrophic forgetting by periodically
        re-exposing the system to its most informative experiences.
        """
        sorted_eps = sorted(self._buffer, key=lambda e: e.priority, reverse=True)
        return sorted_eps[:n]

    def decay_priorities(self, decay_rate: float = 0.95) -> None:
        """Decay priorities of older episodes to favor recent experiences."""
        for ep in self._buffer:
            # Decay based on time since storage
            age_days = (time.time() - ep.stored_at) / 86400
            decay = decay_rate ** age_days
            ep.priority *= decay

    def _compute_surprise(
        self,
        agent_signals: dict[str, dict],
        outcome_won: bool,
        consensus_signal: str | None,
    ) -> float:
        """Compute how surprising the outcome was given agent signals.

        High surprise = most agents were confident but wrong.
        """
        if not agent_signals:
            return 0.5

        bullish_count = 0
        bearish_count = 0
        total = len(agent_signals)

        for signal_data in agent_signals.values():
            signal = signal_data.get("signal", "").upper()
            if signal in ("BUY", "BULLISH", "LONG"):
                bullish_count += 1
            elif signal in ("SELL", "BEARISH", "SHORT"):
                bearish_count += 1

        # If outcome contradicts strong consensus → high surprise
        if outcome_won and bullish_count > bearish_count:
            consensus_right = True
        elif not outcome_won and bearish_count > bullish_count:
            consensus_right = True
        else:
            consensus_right = False

        if not consensus_right and total >= 3:
            # How strong was the wrong consensus?
            max_side = max(bullish_count, bearish_count)
            return max_side / total  # 0.0 to 1.0
        elif consensus_right:
            return 0.1  # Low surprise — consensus was right
        else:
            return 0.3  # No clear consensus


class DailyConsolidator:
    """End-of-day consolidation: experience replay + regret minimization.

    Runs at the end of each trading day to:
    1. Replay significant episodes through the memory system
    2. Compute and minimize regret across recent trades
    3. Update EWC frozen patterns
    4. Prune low-confidence rules
    5. Generate daily learning report
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        performance_tracker: PerformanceTracker,
        replay_buffer: ExperienceReplay,
        safeguards: LearningSafeguards,
    ):
        self._memory = memory_manager
        self._tracker = performance_tracker
        self._replay = replay_buffer
        self._safeguards = safeguards
        self._daily_reports: list[dict[str, Any]] = []

    async def consolidate(self) -> dict[str, Any]:
        """Run full daily consolidation cycle.

        Only runs if learning is not frozen (Guardian kill-switch #16).
        """
        if not self._safeguards.can_learn(self._tracker._global_stats):
            logger.warning(
                "daily_consolidation_skipped",
                reason="learning_safeguards_blocked",
            )
            return {
                "status": "skipped",
                "reason": "learning_safeguards_active",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }

        # 1. Experience replay
        replay_result = await self._run_experience_replay()
        report["replay"] = replay_result

        # 2. Regret minimization
        regret_result = await self._run_regret_minimization()
        report["regret"] = regret_result

        # 3. Memory consolidation
        memory_result = await self._memory.consolidate_daily()
        report["memory"] = memory_result

        # 4. Decay replay buffer priorities
        self._replay.decay_priorities()

        report["status"] = "complete"
        self._daily_reports.append(report)
        if len(self._daily_reports) > 30:  # Keep last 30 days
            self._daily_reports = self._daily_reports[-30:]

        logger.info("daily_consolidation_complete", **report)
        return report

    async def _run_experience_replay(self) -> dict[str, Any]:
        """Replay significant episodes to reinforce learning.

        For each replayed episode:
        - Re-evaluate semantic similarity to current patterns
        - Check if procedural rules would have fired correctly
        - Record outcomes for pattern tracking
        """
        batch = self._replay.sample_batch()
        if not batch:
            return {"episodes_replayed": 0}

        matches_found = 0
        rules_correct = 0
        rules_wrong = 0

        for ep in batch:
            # Re-evaluate against semantic memory
            if ep.features:
                similar = self._memory.semantic.query(
                    ep.features, symbol=ep.symbol, top_k=5
                )
                if similar:
                    matches_found += 1
                    for pattern, sim in similar:
                        self._memory.semantic.record_pattern_outcome(
                            pattern.pattern_id, ep.outcome_won
                        )

                # Check procedural rules
                context = {"features": ep.features, **ep.features}
                matching_rules = self._memory.procedural.get_matching_rules(context)

                for rule in matching_rules:
                    # Did this rule's action align with the outcome?
                    rule_correct = self._check_rule_alignment(rule.action, ep.outcome_won)
                    if rule_correct:
                        rules_correct += 1
                    else:
                        rules_wrong += 1

        result = {
            "episodes_replayed": len(batch),
            "semantic_matches": matches_found,
            "rules_correct": rules_correct,
            "rules_wrong": rules_wrong,
            "rule_accuracy": round(
                rules_correct / max(rules_correct + rules_wrong, 1), 4
            ),
        }

        logger.info("experience_replay_complete", **result)
        return result

    async def _run_regret_minimization(self) -> dict[str, Any]:
        """Compute and minimize regret across recent trades.

        Regret = what-if analysis:
        - "What if we sized differently?"
        - "What if we waited for better confluence?"
        - "What if we used the opposite signal?"

        High-regret trades are flagged for procedural rule adjustment.
        """
        # Get recent losing trades
        significant = await self._memory.get_significant_episodes(n=20)
        losers = [e for e in significant if e.get("pnl", 0) < 0]

        if not losers:
            return {"regret_analyzed": 0, "regret_actions": 0}

        regret_actions = 0
        total_regret = 0.0

        for trade in losers:
            pnl = trade.get("pnl", 0)
            confidence = trade.get("confidence", 0.5)
            features = trade.get("features", {})
            agent_signals = trade.get("agent_signals", {})

            # Regret #1: Did we trade against weak consensus?
            consensus_strength = self._compute_consensus_strength(agent_signals)
            if consensus_strength < 0.6 and confidence > 0.6:
                # High regret: took a trade with weak consensus at high confidence
                regret = abs(pnl) * (1.0 + (confidence - consensus_strength))
                total_regret += regret

                # Action: create a filter rule requiring stronger consensus
                self._memory.procedural.create_rule(
                    name=f"min_consensus_for_{trade.get('symbol', '')}",
                    conditions={"consensus_strength": {"lt": 0.6}},
                    action="WAIT",
                    category="filter",
                    confidence=0.6,
                    notes=f"Regret minimization: trade_id={trade.get('trade_id', '?')} had {consensus_strength:.2f} consensus but lost {abs(pnl):.2f}",
                )
                regret_actions += 1

            # Regret #2: Did we size too large for the confidence?
            if features and confidence < 0.5 and abs(pnl) > 2.0:
                # High regret: low confidence but large loss
                regret = abs(pnl) * 2.0
                total_regret += regret

                self._memory.procedural.create_rule(
                    name=f"reduce_size_low_confidence",
                    conditions={"confidence": {"lt": 0.5}},
                    action="REDUCE_SIZE",
                    category="risk",
                    confidence=0.7,
                    notes=f"Regret minimization: trade_id={trade.get('trade_id', '?')} had confidence {confidence:.2f} but lost {abs(pnl):.2f}",
                )
                regret_actions += 1

        result = {
            "regret_analyzed": len(losers),
            "regret_actions": regret_actions,
            "total_regret": round(total_regret, 2),
        }

        logger.info("regret_minimization_complete", **result)
        return result

    @staticmethod
    def _compute_consensus_strength(agent_signals: dict[str, dict]) -> float:
        """Compute how strong the consensus was (0.5 = split, 1.0 = unanimous)."""
        if not agent_signals:
            return 0.5
        signals = [
            s.get("signal", "").upper()
            for s in agent_signals.values()
            if s.get("signal")
        ]
        if not signals:
            return 0.5
        from collections import Counter
        counts = Counter(signals)
        max_count = max(counts.values())
        return max_count / len(signals)

    @staticmethod
    def _check_rule_alignment(action: str, outcome_won: bool) -> bool:
        """Check if a rule's action would have led to a win."""
        # For simplicity: BUY/SELL actions align with winning trades
        # WAIT/REDUCE_SIZE align with avoiding losing trades
        if outcome_won:
            return action in ("BUY", "SELL", "TIGHTEN_TP")
        else:
            return action in ("WAIT", "REDUCE_SIZE", "WIDEN_SL")

    def get_last_report(self) -> dict[str, Any] | None:
        """Get the most recent consolidation report."""
        return self._daily_reports[-1] if self._daily_reports else None

    def get_weekly_summary(self) -> dict[str, Any]:
        """Generate a weekly learning summary."""
        recent = self._daily_reports[-7:]
        if not recent:
            return {"period": "weekly", "status": "no_data"}

        total_replayed = sum(
            r.get("replay", {}).get("episodes_replayed", 0) for r in recent
        )
        total_regret_actions = sum(
            r.get("regret", {}).get("regret_actions", 0) for r in recent
        )

        return {
            "period": "weekly",
            "days_consolidated": len(recent),
            "total_episodes_replayed": total_replayed,
            "total_regret_actions": total_regret_actions,
            "latest_at": recent[-1].get("timestamp", ""),
        }
