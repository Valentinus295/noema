"""Strategy Mutation — breed top performers, test variants.

Implements evolutionary search over trading strategies:
1. Selection: Pick top-N performing agent configurations
2. Crossover: Breed pairs to create hybrid strategies
3. Mutation: Introduce controlled variations
4. Evaluation: Track variant performance separately
5. Replacement: Replace underperformers with better variants

Variants are tracked in a sandbox before being promoted to production.
This prevents a single bad mutation from harming live trading.
"""

from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

from noema.learning.performance import PerformanceTracker, AgentPerformance

logger = structlog.get_logger(__name__)


@dataclass
class StrategyVariant:
    """A mutated strategy variant under evaluation.

    Variants start in 'testing' status and are promoted to 'active'
    only after meeting minimum performance criteria.
    """
    variant_id: str
    name: str
    parent_ids: list[str]  # IDs of parent strategies
    parameters: dict[str, Any]  # The mutated parameters
    generation: int = 0
    status: str = "testing"  # "testing", "promising", "active", "retired"
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    created_at: float = field(default_factory=time.time)
    promoted_at: float | None = None
    notes: str = ""

    @property
    def win_rate(self) -> float:
        return self.winning_trades / max(self.total_trades, 1)

    def record_trade(self, won: bool, pnl: float) -> None:
        self.total_trades += 1
        if won:
            self.winning_trades += 1
        self.total_pnl += pnl

    def meets_promotion_criteria(self, min_trades: int = 20, min_win_rate: float = 0.55) -> bool:
        """Check if this variant qualifies for promotion to active."""
        return (
            self.total_trades >= min_trades
            and self.win_rate >= min_win_rate
            and self.total_pnl > 0
        )


class StrategyMutator:
    """Evolutionary strategy optimizer for trading agent configurations.

    Maintains a population of strategy variants, breeds top performers,
    and gradually replaces underperformers with improved versions.

    Parameters that can be mutated:
    - Agent weights / priorities
    - RSI thresholds (oversold/overbought)
    - EMA periods (fast/slow)
    - Risk parameters (position size, SL multiplier)
    - Confluence thresholds
    - Timeframe preferences
    - Session filters
    """

    # Mutation parameters
    POPULATION_SIZE = 20
    MUTATION_RATE = 0.15       # Probability of each parameter being mutated
    MUTATION_MAGNITUDE = 0.10  # 10% standard deviation for continuous params
    CROSSOVER_PROBABILITY = 0.7
    ELITISM_COUNT = 3           # Top N variants survive unchanged
    MIN_TRADES_FOR_SELECTION = 10
    PROMOTION_MIN_TRADES = 20
    PROMOTION_MIN_WIN_RATE = 0.55

    # Parameter mutation ranges
    PARAM_BOUNDS: dict[str, Any] = {
        "rsi_oversold": {"min": 15.0, "max": 40.0, "type": "float"},
        "rsi_overbought": {"min": 60.0, "max": 85.0, "type": "float"},
        "ema_fast": {"min": 10, "max": 80, "type": "int"},
        "ema_slow": {"min": 100, "max": 300, "type": "int"},
        "confluence_threshold": {"min": 0.50, "max": 0.85, "type": "float"},
        "risk_per_trade": {"min": 0.001, "max": 0.05, "type": "float"},
        "min_risk_reward": {"min": 1.0, "max": 4.0, "type": "float"},
        "atr_multiplier_sl": {"min": 1.0, "max": 3.0, "type": "float"},
        "atr_multiplier_tp": {"min": 1.5, "max": 5.0, "type": "float"},
        "max_open_trades": {"min": 1, "max": 8, "type": "int"},
    }

    def __init__(self, performance_tracker: PerformanceTracker):
        self._tracker = performance_tracker
        self._population: dict[str, StrategyVariant] = {}
        self._generation = 0
        self._variant_counter = 0

    def seed_population(self, base_parameters: dict[str, Any]) -> list[str]:
        """Seed the initial population around a base parameter set.

        Creates variants by mutating the base parameters with increasing magnitude.

        Returns:
            List of variant IDs in the initial population
        """
        variant_ids = []

        # Seed with the base parameters
        base_variant = StrategyVariant(
            variant_id="seed_base",
            name="base_seed",
            parent_ids=[],
            parameters=copy.deepcopy(base_parameters),
            status="active",
            generation=0,
        )
        self._population["seed_base"] = base_variant
        variant_ids.append("seed_base")

        # Create mutated variants
        for i in range(self.POPULATION_SIZE - 1):
            mag = 0.05 + (i * 0.05)  # Increasing mutation magnitude
            mutated_params = self._mutate_params(base_parameters, magnitude=mag)
            vid = f"gen0_var{i}"
            variant = StrategyVariant(
                variant_id=vid,
                name=f"gen0_variant_{i}",
                parent_ids=["seed_base"],
                parameters=mutated_params,
                generation=0,
                status="testing",
            )
            self._population[vid] = variant
            variant_ids.append(vid)

        self._variant_counter = self.POPULATION_SIZE
        self._generation = 1
        logger.info(
            "strategy_population_seeded",
            population_size=len(self._population),
            base_params=list(base_parameters.keys()),
        )
        return variant_ids

    def evolve(self) -> dict[str, Any]:
        """Run one generation of evolution.

        1. Evaluate fitness of all variants
        2. Select parents via tournament selection
        3. Crossover to create children
        4. Mutate children
        5. Replace worst performers with children
        6. Increment generation counter

        Returns:
            Evolution report dict
        """
        if len(self._population) < 4:
            logger.warning("strategy_evolution_skipped", reason="population_too_small")
            return {"generation": self._generation, "status": "skipped"}

        # 1. Evaluate and rank
        ranked = self._rank_variants()
        elites = ranked[:self.ELITISM_COUNT]
        bottom = ranked[-max(2, len(ranked) // 4):]

        # 2. Select parents from top performers
        parent_pool = [v for v in ranked if v.total_trades >= self.MIN_TRADES_FOR_SELECTION]
        if len(parent_pool) < 2:
            parent_pool = ranked[:max(2, len(ranked) // 2)]

        # 3. Create children
        num_children = len(bottom)
        children_created = 0
        new_variants: list[StrategyVariant] = []

        for _ in range(num_children):
            if np.random.random() < self.CROSSOVER_PROBABILITY and len(parent_pool) >= 2:
                # Crossover: breed two parents
                p1, p2 = np.random.choice(parent_pool, size=2, replace=False)
                child_params = self._crossover(p1.parameters, p2.parameters)
                parent_ids = [p1.variant_id, p2.variant_id]
            else:
                # Mutation only: clone a single parent
                parent = np.random.choice(parent_pool)
                child_params = copy.deepcopy(parent.parameters)
                parent_ids = [parent.variant_id]

            # Mutate
            child_params = self._mutate_params(child_params)

            self._variant_counter += 1
            child = StrategyVariant(
                variant_id=f"gen{self._generation}_var{self._variant_counter}",
                name=f"gen{self._generation}_variant_{self._variant_counter}",
                parent_ids=parent_ids,
                parameters=child_params,
                generation=self._generation,
                status="testing",
            )
            new_variants.append(child)
            children_created += 1

        # 4. Replace bottom performers
        for old, new in zip(bottom, new_variants):
            old_vid = old.variant_id
            self._population.pop(old_vid, None)  # Remove old
            self._population[new.variant_id] = new  # Add new

        self._generation += 1

        report = {
            "generation": self._generation,
            "population_size": len(self._population),
            "children_created": children_created,
            "elites_preserved": len(elites),
            "variants_replaced": len(bottom),
            "top_variant": ranked[0].variant_id if ranked else None,
            "top_win_rate": round(ranked[0].win_rate, 4) if ranked else 0.0,
        }

        logger.info("strategy_evolution_complete", **report)
        return report

    def record_variant_trade(self, variant_id: str, won: bool, pnl: float) -> None:
        """Record a trade outcome for a specific variant."""
        variant = self._population.get(variant_id)
        if variant:
            variant.record_trade(won, pnl)

    def check_promotions(self) -> list[str]:
        """Check testing variants for promotion to active.

        Returns:
            List of promoted variant IDs
        """
        promoted = []
        for vid, variant in self._population.items():
            if variant.status == "testing" and variant.meets_promotion_criteria(
                min_trades=self.PROMOTION_MIN_TRADES,
                min_win_rate=self.PROMOTION_MIN_WIN_RATE,
            ):
                variant.status = "active"
                variant.promoted_at = time.time()
                promoted.append(vid)
                logger.info(
                    "strategy_variant_promoted",
                    variant_id=vid,
                    win_rate=f"{variant.win_rate:.2%}",
                    trades=variant.total_trades,
                    pnl=round(variant.total_pnl, 2),
                )

        return promoted

    def get_active_variants(self) -> list[StrategyVariant]:
        """Get all active (promoted) variants."""
        return [v for v in self._population.values() if v.status == "active"]

    def get_testing_variants(self) -> list[StrategyVariant]:
        """Get all variants still in testing."""
        return [v for v in self._population.values() if v.status == "testing"]

    def get_variant(self, variant_id: str) -> StrategyVariant | None:
        """Get a specific variant by ID."""
        return self._population.get(variant_id)

    # ── Genetic Operators ────────────────────────────────────────────

    def _mutate_params(
        self, params: dict[str, Any], magnitude: float | None = None
    ) -> dict[str, Any]:
        """Mutate a parameter set with controlled random variations.

        Each parameter has MUTATION_RATE probability of being altered.
        Continuous params get Gaussian noise. Discrete params get uniform integer shift.
        """
        mutated = copy.deepcopy(params)
        mag = magnitude if magnitude is not None else self.MUTATION_MAGNITUDE

        for key, bounds in self.PARAM_BOUNDS.items():
            if key not in mutated:
                continue
            if np.random.random() > self.MUTATION_RATE:
                continue

            current = mutated[key]
            if bounds["type"] == "float":
                # Gaussian perturbation
                noise = np.random.normal(0, abs(current) * mag)
                new_val = current + noise
                new_val = max(bounds["min"], min(bounds["max"], new_val))
                mutated[key] = round(new_val, 4)
            elif bounds["type"] == "int":
                # Uniform integer shift
                shift = np.random.randint(-2, 3)  # -2 to +2
                new_val = int(current) + shift
                new_val = max(int(bounds["min"]), min(int(bounds["max"]), new_val))
                mutated[key] = int(new_val)

        return mutated

    def _crossover(
        self, params_a: dict[str, Any], params_b: dict[str, Any]
    ) -> dict[str, Any]:
        """Uniform crossover: each parameter randomly from parent A or B."""
        child = {}
        all_keys = set(params_a.keys()) | set(params_b.keys())

        for key in all_keys:
            if key in params_a and key in params_b:
                child[key] = params_a[key] if np.random.random() < 0.5 else params_b[key]
            elif key in params_a:
                child[key] = params_a[key]
            else:
                child[key] = params_b[key]

        return child

    def _rank_variants(self) -> list[StrategyVariant]:
        """Rank all variants by fitness (win rate * sqrt(trades) for significance)."""
        variants = list(self._population.values())
        # Fitness = win_rate * sqrt(trades) — balances accuracy with statistical significance
        variants.sort(
            key=lambda v: v.win_rate * np.sqrt(max(v.total_trades, 1)),
            reverse=True,
        )
        return variants

    def get_population_report(self) -> dict[str, Any]:
        """Generate a population status report."""
        active = self.get_active_variants()
        testing = self.get_testing_variants()

        return {
            "generation": self._generation,
            "population_size": len(self._population),
            "active_variants": len(active),
            "testing_variants": len(testing),
            "top_variants": [
                {
                    "id": v.variant_id,
                    "name": v.name,
                    "win_rate": round(v.win_rate, 4),
                    "trades": v.total_trades,
                    "pnl": round(v.total_pnl, 2),
                    "status": v.status,
                }
                for v in self._rank_variants()[:5]
            ],
        }
