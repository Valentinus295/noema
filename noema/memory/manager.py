"""MemoryManager — unified façade for all four memory stores.

Orchestrates episodic, semantic, working, and procedural memory systems.
Provides a single API for the learning pipeline: record → recall → learn → adapt.

The MemoryManager is the primary interface the rest of the system uses.
Individual memory stores can also be accessed directly when needed.

Lifecycle:
    1. record_trade_episode() — store complete trade narrative
    2. find_similar_patterns() — recall past patterns for current context
    3. evaluate_procedural_rules() — check if learned rules fire
    4. reinforce_from_outcome() — update all memory stores with result
    5. consolidate_daily() — end-of-day experience replay
"""

from __future__ import annotations

from typing import Any

import structlog

from noema.memory.episodic import EpisodicMemory
from noema.memory.semantic import SemanticMemory
from noema.memory.working import WorkingMemory
from noema.memory.procedural import ProceduralMemory

logger = structlog.get_logger(__name__)


class MemoryManager:
    """Unified memory façade for the Noema self-learning system.

    Usage:
        mm = MemoryManager(trade_store, redis_cache, rules_dir="noema_rules")
        await mm.initialize()

        # During trading:
        await mm.record_market_snapshot(snapshot)
        similar = mm.find_similar_patterns(current_features)
        rules = mm.get_matching_rules(current_context)
        best_action, confidence = mm.get_best_procedural_action(current_context)

        # After trade:
        await mm.record_trade_episode(episode)
        await mm.reinforce_from_outcome(trade_id, won, pnl)

        # Daily:
        await mm.consolidate_daily()
    """

    def __init__(
        self,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
        working: WorkingMemory | None = None,
        procedural: ProceduralMemory | None = None,
    ):
        self.episodic = episodic or EpisodicMemory(None)  # type: ignore[arg-type]
        self.semantic = semantic or SemanticMemory()
        self.working = working or WorkingMemory()
        self.procedural = procedural or ProceduralMemory()

    async def initialize(self) -> None:
        """Initialize all memory stores."""
        await self.procedural.initialize()
        logger.info("memory_manager_initialized", **self.stats)

    # ── Record Phase ─────────────────────────────────────────────────

    async def record_trade_episode(self, episode: dict[str, Any]) -> int:
        """Record a complete trade episode across all relevant stores.

        Args:
            episode: Complete trade context dict

        Returns:
            trade_id from episodic memory
        """
        # 1. Store the full narrative
        trade_id = await self.episodic.record_episode(episode)

        # 2. Extract and store semantic pattern
        features = episode.get("features", {})
        symbol = episode.get("symbol", "")
        if features and symbol:
            pattern_id = self.semantic.store(
                features=features,
                pattern_type=episode.get("pattern_type", "setup"),
                symbol=symbol,
                metadata={
                    "trade_id": trade_id,
                    "direction": episode.get("direction", ""),
                    "agent_signals": episode.get("agent_signals", {}),
                },
            )
            episode["pattern_id"] = pattern_id

        # 3. Create/update procedural rules from this episode if significant
        if episode.get("create_rules", True) and features:
            self._derive_rules_from_episode(episode)

        return trade_id

    async def close_trade_episode(self, trade_id: int, exit_price: float, pnl: float) -> None:
        """Close an open trade episode with exit details."""
        await self.episodic.close_episode(trade_id, exit_price, pnl)
        # Update working memory
        positions = self.working.get_positions()
        positions = [p for p in positions if p.get("trade_id") != trade_id]
        await self.working.set_positions(positions)

    async def record_market_snapshot(self, snapshot) -> None:
        """Update working memory with current market state."""
        await self.working.update_market_snapshot(snapshot)

    # ── Recall Phase ─────────────────────────────────────────────────

    def find_similar_patterns(
        self,
        features: dict[str, float],
        symbol: str | None = None,
        top_k: int = 10,
    ) -> list[tuple[Any, float]]:
        """Find historically similar patterns to the current context."""
        return self.semantic.query(features, symbol=symbol, top_k=top_k)

    def find_similar_patterns_multi(
        self,
        features: dict[str, float],
        symbol: str | None = None,
    ) -> dict[str, list[tuple[Any, float]]]:
        """Query all pattern types for the current context."""
        return self.semantic.query_multi_type(features, symbol=symbol)

    def get_matching_rules(
        self, context: dict[str, Any], category: str | None = None
    ) -> list[Any]:
        """Get procedural rules that match the current market context."""
        return self.procedural.get_matching_rules(context, category=category)

    def get_best_procedural_action(
        self, context: dict[str, Any], category: str = "entry"
    ) -> tuple[str | None, float]:
        """Get the highest-confidence matching procedural action."""
        return self.procedural.get_best_action(context, category=category)

    def get_recent_episodes(
        self, symbol: str | None = None, days: int = 30, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Retrieve recent trade episodes."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.episodic.get_episodes(symbol=symbol, days=days, limit=limit)
        ) if not asyncio.get_event_loop().is_running() else []

    async def get_significant_episodes(
        self, symbol: str | None = None, n: int = 20
    ) -> list[dict[str, Any]]:
        """Get the most significant episodes for experience replay."""
        return await self.episodic.get_significant_episodes(symbol=symbol, n=n)

    # ── Learn / Reinforce Phase ──

    async def reinforce_from_outcome(
        self, trade_id: int, won: bool, pnl: float, features: dict[str, float] | None = None
    ) -> None:
        """Reinforce all memory stores with a trade outcome.

        Updates:
        - Semantic: Record pattern outcome, adjust EWC importance
        - Procedural: Reinforce matched rules up/down
        - Working: Update position state
        """
        # Semantic memory update
        if features:
            # Find the closest pattern to this trade and record outcome
            similar = self.semantic.query(features, top_k=3)
            for pattern, sim in similar:
                self.semantic.record_pattern_outcome(pattern.pattern_id, won)
                # Very similar patterns get stronger reinforcement
                if sim > 0.90:
                    self.semantic.record_pattern_outcome(pattern.pattern_id, won)

        # Procedural memory update
        if features:
            context = {"features": features, **features}
            evaluated = self.procedural.evaluate_rules(context)
            for rule, matched in evaluated:
                if matched:
                    self.procedural.reinforce_rule(rule.rule_id, won)

        logger.info(
            "memory_reinforced",
            trade_id=trade_id,
            won=won,
            pnl=pnl,
            semantic_patterns_updated=len(similar) if features else 0,
        )

    async def store_reflection(self, trade_id: int, reflection: dict[str, Any]) -> None:
        """Store a post-trade reflection in episodic memory."""
        await self.episodic.store_reflection(trade_id, reflection)

    # ── Consolidation Phase ──────────────────────────────────────────

    async def consolidate_daily(self) -> dict[str, Any]:
        """Run end-of-day memory consolidation.

        1. Freeze important semantic patterns (EWC)
        2. Prune low-confidence procedural rules
        3. Save ruleset to disk
        4. Generate consolidation report
        """
        # EWC: protect patterns with strong track records
        frozen_count = self.semantic.freeze_important_patterns()

        # Prune rules below confidence floor
        low_conf_rules = [
            r for r in self.procedural._rules.values()
            if r.confidence < 0.1 and r.total_applications >= 5
        ]
        for rule in low_conf_rules:
            self.procedural.deprecate_rule(
                rule.rule_id,
                reason=f"Low confidence ({rule.confidence:.3f}) after {rule.total_applications} applications",
            )

        # Save ruleset
        self.procedural._save_ruleset()

        report = {
            "event": "daily_memory_consolidation",
            "ewc_frozen": frozen_count,
            "rules_deprecated": len(low_conf_rules),
            "semantic_total": self.semantic.stats["total_patterns"],
            "procedural_total": self.procedural.stats["total_rules"],
            "episodic_total": self.episodic.get_episode_count(),
        }

        logger.info("memory_consolidated_daily", **report)
        return report

    # ── Learning Freeze ──────────────────────────────────────────────

    def freeze_learning(self, reason: str = "drawdown") -> None:
        """Freeze all learning (kill-switch #16 integration)."""
        self.working._local["learning_frozen"] = True
        self.working._local["learning_freeze_reason"] = reason
        logger.warning("memory_learning_frozen", reason=reason)

    def unfreeze_learning(self) -> None:
        """Unfreeze learning (manual review cleared)."""
        self.working._local["learning_frozen"] = False
        self.working._local.pop("learning_freeze_reason", None)
        logger.info("memory_learning_unfrozen")

    def is_learning_frozen(self) -> bool:
        """Check if learning is currently frozen."""
        return self.working._local.get("learning_frozen", False)

    # ── Mutation Support ─────────────────────────────────────────────

    def get_best_patterns_for_breeding(
        self, pattern_type: str, n: int = 5
    ) -> list[Any]:
        """Get top-performing patterns for strategy mutation."""
        return self.semantic.get_best_patterns(pattern_type, n=n)

    def get_high_confidence_rules(
        self, min_confidence: float = 0.7, n: int = 10
    ) -> list[Any]:
        """Get highest-confidence rules for strategy breeding."""
        rules = self.procedural.get_rules(min_confidence=min_confidence)
        rules.sort(key=lambda r: r.confidence, reverse=True)
        return rules[:n]

    # ── Private Helpers ──────────────────────────────────────────────

    def _derive_rules_from_episode(self, episode: dict[str, Any]) -> None:
        """Derive procedural rules from trading episodes.

        Simple heuristic: if a combination of features led to a win/loss,
        encode it as a conditional rule.
        """
        features = episode.get("features", {})
        direction = episode.get("direction", "")
        pnl = episode.get("pnl", 0)
        pattern_type = episode.get("pattern_type", "")

        if not features or not direction:
            return

        # Only derive from significant outcomes
        if abs(pnl) < 0.1:
            return

        # Create a simplified condition set
        conditions: dict[str, Any] = {}
        for key in ("trend", "regime", "session"):
            if key in features:
                conditions[key] = features[key]
        if "rsi" in features:
            conditions["rsi"] = {"lt": features["rsi"] + 0.1, "gt": features["rsi"] - 0.1}

        if not conditions:
            return

        action = "BUY" if direction == "long" else "SELL"
        confidence = 0.5 + (0.1 if pnl > 0 else -0.1)

        rule_name = f"{pattern_type}_{direction}_{episode.get('symbol', '')}"

        # Check if a similar rule already exists
        existing = self.procedural.evaluate_rules(conditions, category="entry")
        already_exists = any(matched for _, matched in existing)

        if not already_exists and len(conditions) >= 2:
            self.procedural.create_rule(
                name=rule_name,
                conditions=conditions,
                action=action,
                category="entry",
                confidence=confidence,
                source_pattern_ids=episode.get("pattern_id", "").split(),
                notes=f"Derived from trade_id={episode.get('trade_id', '?')} with PnL={pnl}",
            )

    # ── Stats ────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "episodic": {"episodes_cached": self.episodic.get_episode_count()},
            "semantic": self.semantic.stats,
            "working": self.working.stats,
            "procedural": self.procedural.stats,
            "learning_frozen": self.is_learning_frozen(),
        }

    async def close(self) -> None:
        """Cleanup all memory stores."""
        await self.episodic.close()
        self.semantic.clear()  # Semantic is in-memory only
        await self.working.clear_all()
