"""Noema Self-Learning System — Phase 4.

Performance tracking, weighted voting, strategy mutation, and daily consolidation.

Learning Objectives:
1. Track agent-level performance (win rate, Sharpe, profit factor)
2. Performance-weighted voting in debate rounds
3. Strategy mutation: breed top performers, test variants
4. Daily experience replay with regret minimization

Anti-Catastrophic Forgetting:
- Elastic Weight Consolidation via semantic memory
- Experience replay buffer in consolidation
- Learning freeze on drawdown (Guardian kill-switch #16 integration)
"""

from noema.learning.performance import PerformanceTracker, AgentPerformance
from noema.learning.weighting import WeightedVoter, AgentWeight
from noema.learning.mutation import StrategyMutator, StrategyVariant
from noema.learning.consolidation import ExperienceReplay, DailyConsolidator
from noema.learning.safeguards import LearningSafeguards

__all__ = [
    "PerformanceTracker",
    "AgentPerformance",
    "WeightedVoter",
    "AgentWeight",
    "StrategyMutator",
    "StrategyVariant",
    "ExperienceReplay",
    "DailyConsolidator",
    "LearningSafeguards",
]
