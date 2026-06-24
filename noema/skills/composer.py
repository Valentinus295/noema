"""Skill Composer — compose skills into trading setups.

A Setup is a combination of skills that together form a complete trading decision.
The Composer selects, orders, and weights skills based on:
1. Current market context (what conditions are active)
2. Skill performance history (which skills work best)
3. Skill complementarity (which skills work well together)
4. Risk constraints (which skills are mandatory for safety)

Setup lifecycle:
    1. gather_candidates() — collect skills whose activation conditions are met
    2. rank_candidates() — rank by performance, complementarity, and priority
    3. compose_setup() — assemble the top skills into a coherent setup
    4. validate_setup() — ensure the setup meets minimum requirements
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from noema.skills.registry import SkillRegistry, Skill, SkillCategory
from noema.skills.evaluator import SkillEvaluator

logger = structlog.get_logger(__name__)


@dataclass
class SkillSetup:
    """A composed trading setup — a specific combination of skills.

    Each setup is a hypothesis: "When these conditions are met, use these skills
    in this order, and the expected outcome is this signal with this confidence."
    """
    setup_id: str
    name: str
    skills: list[dict[str, Any]]  # [{skill_id, parameters, weight}]
    signal: str  # "BUY", "SELL", "WAIT"
    confidence: float  # 0.0 - 1.0
    category: str = "general"
    market_conditions: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    status: str = "active"  # "active", "testing", "retired"

    @property
    def win_rate(self) -> float:
        return self.winning_trades / max(self.total_trades, 1)

    def record_outcome(self, won: bool, pnl: float) -> None:
        self.total_trades += 1
        if won:
            self.winning_trades += 1
        self.total_pnl += pnl

    def to_dict(self) -> dict[str, Any]:
        return {
            "setup_id": self.setup_id,
            "name": self.name,
            "skills": self.skills,
            "signal": self.signal,
            "confidence": round(self.confidence, 4),
            "category": self.category,
            "market_conditions": self.market_conditions,
            "win_rate": round(self.win_rate, 4),
            "total_trades": self.total_trades,
            "total_pnl": round(self.total_pnl, 2),
            "status": self.status,
        }


class SkillComposer:
    """Composes trading skills into coherent setups.

    The Composer is the bridge between raw skills and actionable trading setups.
    It uses the SkillEvaluator to select high-performing skills and combines them
    based on complementarity data.

    Usage:
        composer = SkillComposer(evaluator)
        setup = composer.compose(market_context)
        if setup:
            signal = setup.signal
            confidence = setup.confidence
            skills_used = [s["skill_id"] for s in setup.skills]
    """

    MIN_SKILLS_PER_SETUP = 2
    MAX_SKILLS_PER_SETUP = 5
    MIN_CONFIDENCE_FOR_SETUP = 0.50
    REQUIRED_CATEGORIES = [SkillCategory.RISK]  # Risk skills are mandatory

    def __init__(self, evaluator: SkillEvaluator):
        self._evaluator = evaluator
        self._setups: dict[str, SkillSetup] = {}
        self._setup_history: list[str] = []  # Most recent setup IDs

    def compose(
        self,
        market_context: dict[str, Any],
        min_skills: int | None = None,
        max_skills: int | None = None,
    ) -> SkillSetup | None:
        """Compose a trading setup for the given market context.

        Algorithm:
        1. Gather candidate skills whose activation conditions are met
        2. Rank candidates by performance, complementarity, and priority
        3. Ensure at least one risk skill is included
        4. Select top skills (up to max_skills)
        5. Compute aggregate signal and confidence
        6. Create the SkillSetup

        Returns:
            SkillSetup if a valid setup can be composed, None otherwise
        """
        min_s = min_skills or self.MIN_SKILLS_PER_SETUP
        max_s = max_skills or self.MAX_SKILLS_PER_SETUP

        # 1. Gather candidates
        candidates = self._gather_candidates(market_context)

        if not candidates:
            logger.debug("skill_composer_no_candidates", context_keys=list(market_context.keys()))
            return None

        # 2. Rank candidates
        ranked = self._rank_candidates(candidates)

        # 3. Ensure required categories (risk, at minimum)
        selected = self._ensure_required_categories(ranked)

        # 4. Select remaining top skills
        for skill in ranked:
            if len(selected) >= max_s:
                break
            if skill.skill_id not in [s.skill_id for s in selected]:
                selected.append(skill)

        if len(selected) < min_s:
            logger.debug(
                "skill_composer_insufficient_skills",
                selected=len(selected),
                required=min_s,
            )
            return None

        # 5. Compute aggregate signal and confidence
        signal, confidence = self._aggregate_signals(selected, market_context)

        # 6. Check minimum confidence
        if confidence < self.MIN_CONFIDENCE_FOR_SETUP:
            # Create a WAIT setup instead
            signal = "WAIT"
            confidence = self._compute_wait_confidence(ranked, market_context)

        # 7. Create setup
        skill_configs = [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "category": s.category.value,
                "parameters": {**s.default_parameters},
                "weight": self._compute_skill_weight(s, market_context),
            }
            for s in selected
        ]

        setup_id = self._generate_setup_id(skill_configs, signal, market_context)

        # Check if we already have this setup
        if setup_id in self._setups:
            existing = self._setups[setup_id]
            existing.confidence = (existing.confidence * 0.7 + confidence * 0.3)  # EMA
            self._setup_history.append(setup_id)
            return existing

        setup = SkillSetup(
            setup_id=setup_id,
            name=self._generate_setup_name(selected, signal),
            skills=skill_configs,
            signal=signal,
            confidence=confidence,
            market_conditions=market_context,
        )

        self._setups[setup_id] = setup
        self._setup_history.append(setup_id)

        # Prune history
        if len(self._setup_history) > 500:
            self._setup_history = self._setup_history[-300:]

        logger.info(
            "skill_composer_setup_created",
            setup_id=setup_id,
            signal=signal,
            confidence=f"{confidence:.2%}",
            skills=[s.skill_id for s in selected],
        )

        return setup

    def record_setup_outcome(
        self, setup_id: str, won: bool, pnl: float, skill_ids: list[str]
    ) -> None:
        """Record the outcome of a setup for tracking."""
        setup = self._setups.get(setup_id)
        if setup:
            setup.record_outcome(won, pnl)

        # Also record at the skill level
        self._evaluator.record_skill_usage(skill_ids, won, pnl)

    def get_setup(self, setup_id: str) -> SkillSetup | None:
        """Get a specific setup by ID."""
        return self._setups.get(setup_id)

    def get_recent_setups(self, n: int = 10) -> list[SkillSetup]:
        """Get the most recent setups."""
        recent_ids = self._setup_history[-n:]
        return [
            self._setups[rid]
            for rid in recent_ids
            if rid in self._setups
        ]

    def get_best_setups(
        self, min_trades: int = 5, n: int = 5
    ) -> list[SkillSetup]:
        """Get the highest performing setups."""
        candidates = [
            s for s in self._setups.values()
            if s.total_trades >= min_trades and s.status == "active"
        ]
        candidates.sort(key=lambda s: s.win_rate, reverse=True)
        return candidates[:n]

    # ── Internal Methods ─────────────────────────────────────────────

    def _gather_candidates(self, context: dict[str, Any]) -> list[Skill]:
        """Gather skills whose activation conditions are met by the context."""
        candidates = []

        for skill in SkillRegistry.get_all():
            if self._check_conditions(skill.activation_conditions, context):
                candidates.append(skill)

        return candidates

    def _check_conditions(self, conditions: dict, context: dict) -> bool:
        """Check if all activation conditions are satisfied."""
        for key, value in conditions.items():
            if isinstance(value, bool) and value:
                # Boolean True → key must exist and be truthy
                if not context.get(key):
                    return False
            elif isinstance(value, str) and value != "defined":
                # String value → exact match
                if context.get(key) != value:
                    return False
            elif value == "defined":
                # Key must exist (any value)
                if key not in context:
                    return False
        return True

    def _rank_candidates(self, candidates: list[Skill]) -> list[Skill]:
        """Rank candidates by a combination of historical performance and priority.

        Score = normalized_score * priority_weight + base_priority * complement_bonus
        """
        scored: list[tuple[Skill, float]] = []

        for skill in candidates:
            skill_score = self._evaluator.get_skill_score(skill.skill_id)

            # Base performance
            perf_score = skill_score.normalized_score

            # Priority bonus
            priority_norm = min(skill.priority, 16) / 16.0  # Normalize to [0, 1]

            # Complement bonus: skills with strong track records get bonus
            complements = skill_score.complement_scores
            complement_bonus = 0.0
            if complements:
                valid = {k: v for k, v in complements.items() if not k.startswith("_")}
                if valid:
                    complement_bonus = sum(valid.values()) / len(valid) * 0.1

            total_score = perf_score * 0.6 + priority_norm * 0.3 + complement_bonus * 0.1
            scored.append((skill, total_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored]

    def _ensure_required_categories(self, ranked: list[Skill]) -> list[Skill]:
        """Ensure at least one skill from each required category is included."""
        selected: list[Skill] = []
        selected_ids: set[str] = set()

        for cat in self.REQUIRED_CATEGORIES:
            category_skills = [s for s in ranked if s.category == cat]
            if category_skills:
                selected.append(category_skills[0])
                selected_ids.add(category_skills[0].skill_id)

        # Add remaining highest-ranked skills
        for skill in ranked:
            if len(selected) >= self.MAX_SKILLS_PER_SETUP:
                break
            if skill.skill_id not in selected_ids:
                selected.append(skill)
                selected_ids.add(skill.skill_id)

        return selected

    def _aggregate_signals(
        self, skills: list[Skill], context: dict[str, Any]
    ) -> tuple[str, float]:
        """Aggregate signals and confidence from selected skills.

        Skills with higher win rates and stronger complementarity get more weight.
        """
        signals: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0}
        total_weight = 0.0

        for skill in skills:
            score = self._evaluator.get_skill_score(skill.skill_id)
            weight = score.normalized_score + 0.5  # Minimum weight of 0.5

            # Determine skill's default signal from context
            # This is a simplified mapping — real implementation would call the actual skill
            default_signal = self._get_skill_default_signal(skill.skill_id, context)

            signals[default_signal] += weight
            total_weight += weight

        if total_weight == 0:
            return "WAIT", 0.0

        # Normalize
        max_signal = max(signals, key=signals.get)  # type: ignore[arg-type]
        confidence = signals[max_signal] / total_weight

        return max_signal, min(confidence, 1.0)

    def _get_skill_default_signal(self, skill_id: str, context: dict) -> str:
        """Get the default signal for a skill given the market context.

        This is a heuristic mapping. In production, signals come from agent outputs.
        """
        # Use context hints to determine direction
        trend = context.get("trend", "")
        rsi = context.get("rsi", 50)

        if skill_id.startswith("rm_"):
            return "WAIT"  # Risk skills don't generate direction signals

        if trend == "bullish":
            return "BUY"
        elif trend == "bearish":
            return "SELL"
        elif rsi < 30:
            return "BUY"
        elif rsi > 70:
            return "SELL"
        else:
            return "WAIT"

    def _compute_wait_confidence(self, ranked: list[Skill], context: dict) -> float:
        """Compute confidence for a WAIT signal when setup doesn't meet minimum."""
        if not ranked:
            return 0.5
        # Higher = more reason to wait (low confluence)
        avg_score = sum(
            self._evaluator.get_skill_score(s.skill_id).normalized_score
            for s in ranked[:3]
        ) / max(len(ranked[:3]), 1)
        return 0.5 + (0.5 - avg_score) * 0.5  # Low avg_score → high wait confidence

    def _compute_skill_weight(self, skill: Skill, context: dict) -> float:
        """Compute the weight of a skill within the setup."""
        score = self._evaluator.get_skill_score(skill.skill_id)
        weight = score.normalized_score + 0.50
        return round(min(weight, 1.5), 4)

    def _generate_setup_id(
        self, skill_configs: list[dict], signal: str, context: dict
    ) -> str:
        """Generate a deterministic setup ID."""
        key = f"{sorted(s['skill_id'] for s in skill_configs)}:{signal}:{sorted(context.items())}"
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    def _generate_setup_name(self, skills: list[Skill], signal: str) -> str:
        """Generate a human-readable setup name."""
        skill_names = [s.name.split("(")[0].strip() for s in skills[:3]]
        return f"{signal}_{' + '.join(skill_names)}"

    @property
    def stats(self) -> dict[str, Any]:
        active = [s for s in self._setups.values() if s.status == "active"]
        return {
            "total_setups": len(self._setups),
            "active_setups": len(active),
            "recent_setups": len(self._setup_history),
            "avg_win_rate": round(
                sum(s.win_rate for s in active) / max(len(active), 1), 4
            ) if active else 0.0,
        }
