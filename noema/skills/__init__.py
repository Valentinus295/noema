"""Noema Skill Registry — 15 concrete trading skills.

Skills are the atomic units of trading competence. Each skill represents
a specific pattern-recognition or decision-making capability. Skills are
composable into setups by the Composer.

Architecture:
- Registry: Central catalog of all available skills
- Skill: Named capability with activation conditions, input/output schemas
- Evaluator: Tracks individual skill performance
- Composer: Builds trading setups from skill combinations

Skills span four domains:
1. Technical (TA) — indicators, patterns, S/R
2. Structural (SMC) — order blocks, FVG, liquidity
3. Fundamental (FA) — macro, sentiment, events
4. Risk (RM) — sizing, hedging, correlation
"""

from noema.skills.registry import SkillRegistry, Skill, SkillCategory
from noema.skills.evaluator import SkillEvaluator, SkillScore
from noema.skills.composer import SkillComposer, SkillSetup

__all__ = [
    "SkillRegistry",
    "Skill",
    "SkillCategory",
    "SkillEvaluator",
    "SkillScore",
    "SkillComposer",
    "SkillSetup",
]
