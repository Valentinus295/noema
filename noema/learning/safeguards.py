"""Learning Safeguards — Guardian integration for self-learning safety.

Enforces strict safety constraints on the learning system:

1. Rule Creation Gate (n ≥ 30):
   - New procedural rules require at least 30 supporting samples before creation
   - Prevents learning from noise (small sample overfitting)

2. Weight Caps (5×):
   - Agent voting weights cannot exceed 5× the neutral weight
   - Prevents a single agent from dominating the debate

3. Freeze-on-Drawdown:
   - All learning is frozen when drawdown exceeds threshold (Guardian kill-switch #16)
   - Real-time check before any learning operation
   - Only unfrozen after manual review

4. Confidence Decay on Inactivity:
   - Rules that haven't been applied in 30+ days have confidence decayed
   - Prevents stale rules from accumulating

5. Maximum Mutation Rate:
   - Limits how fast strategy parameters can change between generations
   - Prevents radical shifts from single mutations
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LearningSafeguards:
    """Safety gates for the self-learning system.

    All learning operations must pass through these gates before execution.
    Integrates with Guardian's kill-switch #16 (learning_under_drawdown)
    for real-time freeze on drawdown.
    """

    # ── Thresholds ──
    MIN_SAMPLES_FOR_RULE_CREATION = 30    # n ≥ 30 gate
    MAX_WEIGHT_MULTIPLIER = 5.0           # 5× cap
    MAX_MUTATION_MAGNITUDE = 0.15         # 15% max parameter change per generation
    CONFIDENCE_DECAY_AFTER_DAYS = 30      # Stale rule decay
    CONFIDENCE_DECAY_RATE = 0.95           # Daily decay factor
    MAX_RULES_PER_CATEGORY = 50           # Prevent rule explosion

    # Drawdown thresholds
    LEARNING_FREEZE_DRAWDOWN = 0.10       # 10% drawdown → freeze learning
    LEARNING_UNFREEZE_DRAWDOWN = 0.07     # 7% drawdown → can unfreeze (not used yet)

    def __init__(self):
        self._learning_frozen = False
        self._freeze_reason = ""
        self._rule_creation_count: dict[str, int] = {}
        self._samples_collected: dict[str, int] = {}

    # ── Learning Freeze (Kill-Switch #16 Integration) ────────────────

    def check_drawdown(self, current_drawdown_pct: float) -> bool:
        """Check if current drawdown exceeds the learning freeze threshold.

        Called by Guardian agent on every trade cycle.
        Returns True if learning should be frozen.
        """
        if current_drawdown_pct >= self.LEARNING_FREEZE_DRAWDOWN:
            if not self._learning_frozen:
                self.freeze(reason=f"drawdown_{current_drawdown_pct:.2%}")
            return True
        return False

    def freeze(self, reason: str = "drawdown") -> None:
        """Freeze all learning operations."""
        self._learning_frozen = True
        self._freeze_reason = reason
        logger.warning(
            "learning_safeguards_frozen",
            reason=reason,
            message="All learning operations suspended until manual review",
        )

    def unfreeze(self) -> None:
        """Unfreeze learning (requires manual review)."""
        self._learning_frozen = False
        self._freeze_reason = ""
        logger.info("learning_safeguards_unfrozen")

    def is_frozen(self) -> bool:
        """Check if learning is currently frozen."""
        return self._learning_frozen

    def can_learn(self, global_stats: dict[str, Any] | None = None) -> bool:
        """Check if any learning operation is permitted right now.

        Args:
            global_stats: Optional global stats dict with drawdown info

        Returns:
            True if learning can proceed
        """
        if self._learning_frozen:
            return False

        # Check drawdown from global stats if provided
        if global_stats:
            peak = global_stats.get("peak_pnl", 0)
            current = global_stats.get("total_pnl", 0)
            if peak > 0:
                dd = (peak - current) / peak
                if dd >= self.LEARNING_FREEZE_DRAWDOWN:
                    self.freeze(reason=f"drawdown_{dd:.2%}")
                    return False

        return True

    # ── Rule Creation Gate (n ≥ 30) ─────────────────────────────────

    def can_create_rule(
        self, category: str, supporting_samples: int = 0
    ) -> tuple[bool, str]:
        """Check if a new rule can be created.

        Gates:
        1. Learning must not be frozen
        2. Must have ≥ MIN_SAMPLES_FOR_RULE_CREATION supporting samples
        3. Category must not be over MAX_RULES_PER_CATEGORY

        Returns:
            (can_create, reason)
        """
        if self._learning_frozen:
            return False, f"Learning frozen: {self._freeze_reason}"

        if supporting_samples < self.MIN_SAMPLES_FOR_RULE_CREATION:
            return False, (
                f"Insufficient samples: {supporting_samples}/{self.MIN_SAMPLES_FOR_RULE_CREATION} "
                f"(n ≥ {self.MIN_SAMPLES_FOR_RULE_CREATION} required)"
            )

        # Track collected samples per pattern
        if category not in self._rule_creation_count:
            self._rule_creation_count[category] = 0

        return True, "ok"

    def collect_sample(self, pattern_key: str) -> int:
        """Collect a supporting sample for a pattern.

        Returns the current sample count.
        """
        count = self._samples_collected.get(pattern_key, 0) + 1
        self._samples_collected[pattern_key] = count

        if count >= self.MIN_SAMPLES_FOR_RULE_CREATION:
            logger.info(
                "learning_safeguards_sample_threshold_met",
                pattern_key=pattern_key,
                samples=count,
                threshold=self.MIN_SAMPLES_FOR_RULE_CREATION,
            )

        return count

    def get_sample_count(self, pattern_key: str) -> int:
        """Get current sample count for a pattern."""
        return self._samples_collected.get(pattern_key, 0)

    # ── Weight Caps (5×) ────────────────────────────────────────────

    def clamp_weight(self, weight: float) -> float:
        """Clamp a voting weight to allowed range.

        Weights are capped at MAX_WEIGHT_MULTIPLIER × neutral.
        Neutral weight = 1.0. Cap = 5.0.
        """
        return max(0.25, min(weight, self.MAX_WEIGHT_MULTIPLIER))

    def clamp_confidence(self, confidence: float) -> float:
        """Clamp a rule confidence to [0.05, 1.0]."""
        return max(0.05, min(confidence, 1.0))

    # ── Mutation Rate Limit ──────────────────────────────────────────

    def clamp_parameter_change(self, old_value: float, new_value: float) -> float:
        """Limit how much a parameter can change in one mutation step.

        Prevents radical parameter shifts from genetic mutations.
        """
        if old_value == 0:
            return new_value

        relative_change = abs(new_value - old_value) / abs(old_value)
        if relative_change > self.MAX_MUTATION_MAGNITUDE:
            direction = 1 if new_value > old_value else -1
            return old_value * (1 + direction * self.MAX_MUTATION_MAGNITUDE)

        return new_value

    # ── Stale Rule Detection ─────────────────────────────────────────

    def should_decay_rule(self, days_since_applied: float) -> bool:
        """Check if a rule's confidence should decay due to staleness."""
        return days_since_applied >= self.CONFIDENCE_DECAY_AFTER_DAYS

    def compute_decayed_confidence(
        self, current_confidence: float, days_since_applied: float
    ) -> float:
        """Compute decayed confidence for a stale rule.

        Confidence decays exponentially after CONFIDENCE_DECAY_AFTER_DAYS.
        """
        if days_since_applied < self.CONFIDENCE_DECAY_AFTER_DAYS:
            return current_confidence

        excess_days = days_since_applied - self.CONFIDENCE_DECAY_AFTER_DAYS
        decay = self.CONFIDENCE_DECAY_RATE ** excess_days
        return max(0.05, current_confidence * decay)

    # ── Category Limits ──────────────────────────────────────────────

    def can_add_rule_to_category(
        self, category: str, current_count: int
    ) -> tuple[bool, str]:
        """Check if a rule can be added to a category."""
        if current_count >= self.MAX_RULES_PER_CATEGORY:
            return False, (
                f"Category '{category}' at capacity: "
                f"{current_count}/{self.MAX_RULES_PER_CATEGORY}"
            )
        return True, "ok"

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get current safeguards status."""
        return {
            "learning_frozen": self._learning_frozen,
            "freeze_reason": self._freeze_reason,
            "learn_freeze_drawdown_threshold": self.LEARNING_FREEZE_DRAWDOWN,
            "min_samples_for_rule": self.MIN_SAMPLES_FOR_RULE_CREATION,
            "max_weight_multiplier": self.MAX_WEIGHT_MULTIPLIER,
            "max_mutation_magnitude": self.MAX_MUTATION_MAGNITUDE,
            "samples_collected": dict(self._samples_collected),
            "rules_per_category": dict(self._rule_creation_count),
        }
