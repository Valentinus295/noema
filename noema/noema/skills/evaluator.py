"""Skill Evaluator — track individual skill performance over time.

Each skill's historical performance is tracked independently:
- Win rate when the skill was used as primary driver
- Average confidence accuracy
- Profit factor for skill-driven trades
- Skill complementarity (which skills work well together)
- Recent performance trend (improving/declining)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SkillScore:
    """Performance score for a single skill."""
    skill_id: str
    total_applications: int = 0
    successful_applications: int = 0
    total_pnl: float = 0.0
    avg_confidence: float = 0.0
    avg_confidence_when_correct: float = 0.0
    avg_confidence_when_wrong: float = 0.0
    complement_scores: dict[str, float] = field(default_factory=dict)  # skill_id → synergy score
    recent_outcomes: list[float] = field(default_factory=list)  # Last 20 PnLs
    first_used: float = 0.0
    last_used: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_applications == 0:
            return 0.5
        return self.successful_applications / self.total_applications

    @property
    def normalized_score(self) -> float:
        """Composite score: win_rate * log(1 + applications) for significance weighting."""
        import math
        significance = math.log(1 + self.total_applications)
        return self.win_rate * significance / (1 + significance)

    def record_application(
        self,
        won: bool,
        pnl: float,
        confidence: float,
        companion_skills: list[str] | None = None,
    ) -> None:
        """Record a trade outcome for this skill."""
        self.total_applications += 1
        self.total_pnl += pnl
        self.avg_confidence = (
            (self.avg_confidence * (self.total_applications - 1) + confidence)
            / self.total_applications
        )

        if won:
            self.successful_applications += 1
            self.avg_confidence_when_correct = (
                (self.avg_confidence_when_correct * (self.successful_applications - 1) + confidence)
                / self.successful_applications
            )
        else:
            n_wrong = self.total_applications - self.successful_applications
            self.avg_confidence_when_wrong = (
                (self.avg_confidence_when_wrong * (n_wrong - 1) + confidence)
                / n_wrong
            )

        # Track complement scores
        if companion_skills:
            for cs_id in companion_skills:
                if cs_id == self.skill_id:
                    continue
                current = self.complement_scores.get(cs_id, 0.0)
                n = self.complement_scores.get(f"_count_{cs_id}", 0) + 1
                # Exponential moving average of complement success
                self.complement_scores[cs_id] = current * 0.9 + (1.0 if won else 0.0) * 0.1
                self.complement_scores[f"_count_{cs_id}"] = n

        # Track recent outcomes
        self.recent_outcomes.append(pnl)
        if len(self.recent_outcomes) > 20:
            self.recent_outcomes = self.recent_outcomes[-20:]

        now = time.time()
        if self.first_used == 0:
            self.first_used = now
        self.last_used = now

    @property
    def recent_trend(self) -> float:
        """Positive = improving, negative = declining."""
        recent = self.recent_outcomes[-10:]
        if len(recent) < 3:
            return 0.0
        return sum(recent) / len(recent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "total_applications": self.total_applications,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 2),
            "avg_confidence": round(self.avg_confidence, 4),
            "recent_trend": round(self.recent_trend, 4),
            "normalized_score": round(self.normalized_score, 4),
            "top_complements": sorted(
                [
                    (k, round(v, 3))
                    for k, v in self.complement_scores.items()
                    if not k.startswith("_")
                ],
                key=lambda x: x[1],
                reverse=True,
            )[:3],
        }


class SkillEvaluator:
    """Tracks and evaluates the performance of individual trading skills.

    Maintains a leaderboard of skills by normalized score.
    Provides recommendations for skill combinations based on complement data.
    """

    DEFAULT_MIN_APPLICATIONS = 5

    def __init__(self):
        self._scores: dict[str, SkillScore] = {}

    def get_or_create(self, skill_id: str) -> SkillScore:
        """Get or create a skill score tracker."""
        if skill_id not in self._scores:
            self._scores[skill_id] = SkillScore(skill_id=skill_id)
        return self._scores[skill_id]

    def record_skill_usage(
        self,
        skill_ids: list[str],
        won: bool,
        pnl: float,
        confidences: dict[str, float] | None = None,
    ) -> None:
        """Record a trade outcome for the skills used in the setup.

        Args:
            skill_ids: List of skills that contributed to the trade
            won: Whether the trade was profitable
            pnl: Profit/loss amount
            confidences: Per-skill confidence (optional)
        """
        conf = confidences or {}

        for skill_id in skill_ids:
            score = self.get_or_create(skill_id)
            score.record_application(
                won=won,
                pnl=pnl,
                confidence=conf.get(skill_id, 0.5),
                companion_skills=skill_ids,
            )

        logger.debug(
            "skill_evaluator_recorded",
            skills=skill_ids,
            won=won,
            pnl=round(pnl, 2),
        )

    def get_skill_score(self, skill_id: str) -> SkillScore:
        """Get the performance score for a skill."""
        return self.get_or_create(skill_id)

    def get_top_skills(
        self, n: int = 10, min_applications: int | None = None
    ) -> list[SkillScore]:
        """Get the top-N performing skills by normalized score.

        Args:
            n: Number of skills to return
            min_applications: Minimum number of applications required

        Returns:
            List of SkillScores sorted by normalized score desc
        """
        min_apps = min_applications if min_applications is not None else self.DEFAULT_MIN_APPLICATIONS

        candidates = [
            s for s in self._scores.values()
            if s.total_applications >= min_apps
        ]
        candidates.sort(key=lambda s: s.normalized_score, reverse=True)
        return candidates[:n]

    def get_bottom_skills(
        self, n: int = 5, min_applications: int | None = None
    ) -> list[SkillScore]:
        """Get the lowest-performing skills (for review or retirement)."""
        min_apps = min_applications if min_applications is not None else self.DEFAULT_MIN_APPLICATIONS

        candidates = [
            s for s in self._scores.values()
            if s.total_applications >= min_apps
        ]
        candidates.sort(key=lambda s: s.normalized_score)
        return candidates[:n]

    def get_best_complements(self, skill_id: str, n: int = 3) -> list[tuple[str, float]]:
        """Get the skills that work best with a given skill."""
        score = self._scores.get(skill_id)
        if score is None:
            return []

        complements = [
            (k, v)
            for k, v in score.complement_scores.items()
            if not k.startswith("_")
        ]
        complements.sort(key=lambda x: x[1], reverse=True)
        return complements[:n]

    def get_leaderboard(self) -> list[dict[str, Any]]:
        """Get the full skill leaderboard."""
        return [s.to_dict() for s in self.get_top_skills(n=len(self._scores), min_applications=0)]

    def get_skills_report(self) -> dict[str, Any]:
        """Generate a summary report of all skill performance."""
        all_scores = list(self._scores.values())
        if not all_scores:
            return {"total_skills": 0}

        top5 = self.get_top_skills(n=5)
        bottom5 = self.get_bottom_skills(n=5)

        return {
            "total_skills_tracked": len(all_scores),
            "total_applications": sum(s.total_applications for s in all_scores),
            "best_skill": top5[0].to_dict() if top5 else None,
            "worst_skill": bottom5[-1].to_dict() if bottom5 else None,
            "top_5": [s.to_dict() for s in top5],
            "bottom_5": [s.to_dict() for s in bottom5],
        }

    def reset(self) -> None:
        """Reset all skill scores (for testing)."""
        self._scores.clear()
