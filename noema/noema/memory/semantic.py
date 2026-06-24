"""Semantic Memory — Vector-based pattern similarity using numpy cosine sim.

Stores trading patterns as embeddings and retrieves similar historical patterns.
No external vector DB (ChromaDB, Pinecone) needed — uses numpy for fast in-process
similarity search. Patterns are enriched with metadata for context-aware retrieval.

Anti-Catastrophic Forgetting: Elastic Weight Consolidation (EWC) protects important
patterns from being overwritten during updates.

Pattern types tracked:
- Market regime patterns (trending, ranging, volatile)
- Setup patterns (breakout, pullback, reversal)
- Order block / FVG patterns
- Candlestick patterns with context
- Agent signal consensus patterns
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Try to import scipy for faster cosine distance
try:
    from scipy.spatial.distance import cosine as scipy_cosine
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    if _HAS_SCIPY:
        return float(1.0 - scipy_cosine(a, b))
    # Pure numpy fallback
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


@dataclass
class SemanticPattern:
    """A stored trading pattern with embedding and metadata."""
    pattern_id: str
    vector: np.ndarray
    pattern_type: str  # "regime", "setup", "candlestick", "signal_consensus", "outcome"
    symbol: str
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 1.0  # EWC importance weight (1.0 = neutral)
    created_at: float = field(default_factory=time.time)
    times_retrieved: int = 0
    positive_outcomes: int = 0
    negative_outcomes: int = 0

    @property
    def success_rate(self) -> float:
        total = self.positive_outcomes + self.negative_outcomes
        return self.positive_outcomes / total if total > 0 else 0.0

    def record_outcome(self, won: bool) -> None:
        if won:
            self.positive_outcomes += 1
        else:
            self.negative_outcomes += 1


class SemanticMemory:
    """Vector-based semantic memory for trading pattern similarity.

    Features:
    - Numpy cosine similarity search (no external DB)
    - Elastic Weight Consolidation (EWC) against catastrophic forgetting
    - Pattern importance tracking based on success rate
    - Multi-pattern-type retrieval with scoring
    - Automatic consolidation of similar patterns

    Vector dimensions:
    - Default: 32-dim embedding from feature extraction
    - Features: trend_score, volatility, momentum, rsi, session, regime, etc.
    """

    DEFAULT_DIM = 32
    MAX_PATTERNS = 10_000
    CONSOLIDATION_SIMILARITY_THRESHOLD = 0.92
    EWC_LAMBDA = 0.1  # EWC regularization strength

    def __init__(self, vector_dim: int = DEFAULT_DIM):
        self._dim = vector_dim
        self._patterns: dict[str, SemanticPattern] = {}
        self._pattern_ids: list[str] = []  # Ordered for recency
        self._ewc_frozen: set[str] = set()  # EWC-protected pattern IDs

    def _compute_embedding(self, features: dict[str, float]) -> np.ndarray:
        """Compute a deterministic embedding from feature dict.

        Uses a hashing trick to map named features to a fixed-dim vector.
        This is intentionally simple — future versions can use learned embeddings.
        """
        vec = np.zeros(self._dim, dtype=np.float64)

        # Normalize and map named features to vector positions
        for key, value in sorted(features.items()):
            if not isinstance(value, (int, float)):
                continue
            # Hash the feature name to a position
            h = int(hashlib.md5(key.encode()).hexdigest(), 16) % self._dim
            vec[h] += float(value)

        # Normalize to unit length
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec

    def store(
        self,
        features: dict[str, float],
        pattern_type: str,
        symbol: str,
        metadata: dict[str, Any] | None = None,
        importance: float = 1.0,
    ) -> str:
        """Store a pattern vector with metadata.

        Args:
            features: Named feature dict (e.g. {'trend': 0.8, 'rsi': 0.3, ...})
            pattern_type: Category ('regime', 'setup', 'candlestick', 'signal_consensus', 'outcome')
            symbol: Trading pair
            metadata: Additional context
            importance: EWC importance weight (higher = more protected)

        Returns:
            pattern_id for retrieval
        """
        vector = self._compute_embedding(features)
        pattern_id = hashlib.sha256(
            f"{symbol}:{pattern_type}:{time.time()}:{sorted(features.items())}".encode()
        ).hexdigest()[:16]

        pattern = SemanticPattern(
            pattern_id=pattern_id,
            vector=vector,
            pattern_type=pattern_type,
            symbol=symbol,
            metadata=metadata or {},
            importance=importance,
        )

        # Check for near-duplicates and consolidate
        if pattern_type in ("regime", "setup"):
            self._consolidate_if_similar(pattern)

        self._patterns[pattern_id] = pattern
        self._pattern_ids.append(pattern_id)

        # Prune if over capacity (remove least-important, non-EWC patterns)
        if len(self._pattern_ids) > self.MAX_PATTERNS:
            self._prune()

        logger.debug(
            "semantic_pattern_stored",
            pattern_id=pattern_id,
            type=pattern_type,
            symbol=symbol,
            total_patterns=len(self._patterns),
        )

        return pattern_id

    def query(
        self,
        features: dict[str, float],
        pattern_type: str | None = None,
        symbol: str | None = None,
        top_k: int = 10,
        min_similarity: float = 0.5,
    ) -> list[tuple[SemanticPattern, float]]:
        """Find the top-K most similar patterns.

        Args:
            features: Feature dict to match against
            pattern_type: Optional filter by pattern category
            symbol: Optional filter by trading pair
            top_k: Number of results
            min_similarity: Minimum cosine similarity threshold

        Returns:
            List of (pattern, similarity_score) tuples, sorted by similarity desc
        """
        query_vec = self._compute_embedding(features)

        candidates: list[tuple[SemanticPattern, float]] = []

        for pid in reversed(self._pattern_ids):  # Prefer recent patterns
            pattern = self._patterns.get(pid)
            if pattern is None:
                continue

            if pattern_type and pattern.pattern_type != pattern_type:
                continue
            if symbol and pattern.symbol != symbol:
                continue

            sim = _cosine_similarity(query_vec, pattern.vector)
            if sim >= min_similarity:
                candidates.append((pattern, sim))

        # Sort by similarity descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        result = candidates[:top_k]

        # Update retrieval stats
        for pattern, _ in result:
            pattern.times_retrieved += 1

        return result

    def query_multi_type(
        self,
        features: dict[str, float],
        pattern_types: list[str] | None = None,
        symbol: str | None = None,
        top_k: int = 5,
    ) -> dict[str, list[tuple[SemanticPattern, float]]]:
        """Query across multiple pattern types and return grouped results."""
        types = pattern_types or ["regime", "setup", "candlestick", "signal_consensus"]
        results: dict[str, list[tuple[SemanticPattern, float]]] = {}

        for pt in types:
            matches = self.query(features, pattern_type=pt, symbol=symbol, top_k=top_k)
            if matches:
                results[pt] = matches

        return results

    def get_best_patterns(
        self, pattern_type: str, symbol: str | None = None, n: int = 5
    ) -> list[SemanticPattern]:
        """Get the highest-success-rate patterns for a type.

        Used for strategy breeding: identify which patterns work best.
        """
        candidates = [
            p for p in self._patterns.values()
            if p.pattern_type == pattern_type
            and (symbol is None or p.symbol == symbol)
            and (p.positive_outcomes + p.negative_outcomes) >= 3  # Minimum sample
        ]
        candidates.sort(key=lambda p: p.success_rate, reverse=True)
        return candidates[:n]

    def record_pattern_outcome(self, pattern_id: str, won: bool) -> None:
        """Record whether a pattern led to a winning or losing trade."""
        pattern = self._patterns.get(pattern_id)
        if pattern:
            pattern.record_outcome(won)
            # Update EWC importance based on success/failure
            if won:
                pattern.importance = min(pattern.importance * 1.1, 5.0)
            else:
                pattern.importance = max(pattern.importance * 0.9, 0.2)
            logger.debug(
                "semantic_pattern_outcome",
                pattern_id=pattern_id,
                won=won,
                success_rate=f"{pattern.success_rate:.2%}",
            )

    # ── Anti-Catastrophic Forgetting: Elastic Weight Consolidation ───

    def freeze_important_patterns(
        self, min_importance: float = 2.0, min_samples: int = 5
    ) -> int:
        """EWC: Freeze important patterns to protect from catastrophic forgetting.

        Patterns with high importance and sufficient sample size are added to
        the EWC frozen set. These patterns cannot be consolidated/pruned.

        Returns:
            Number of patterns frozen
        """
        frozen = 0
        for pid, pattern in self._patterns.items():
            total = pattern.positive_outcomes + pattern.negative_outcomes
            if pattern.importance >= min_importance and total >= min_samples:
                self._ewc_frozen.add(pid)
                frozen += 1

        logger.info(
            "ewc_patterns_frozen",
            frozen=frozen,
            total_patterns=len(self._patterns),
            ewc_lambda=self.EWC_LAMBDA,
        )
        return frozen

    def is_frozen(self, pattern_id: str) -> bool:
        """Check if a pattern is EWC-protected."""
        return pattern_id in self._ewc_frozen

    def _consolidate_if_similar(self, new_pattern: SemanticPattern) -> bool:
        """Merge with existing pattern if highly similar.

        Returns True if consolidated (merged), False if kept as new.
        """
        for pid in list(self._pattern_ids):
            existing = self._patterns.get(pid)
            if existing is None or pid in self._ewc_frozen:
                continue
            if existing.pattern_type != new_pattern.pattern_type:
                continue
            if existing.symbol != new_pattern.symbol:
                continue

            sim = _cosine_similarity(new_pattern.vector, existing.vector)
            if sim >= self.CONSOLIDATION_SIMILARITY_THRESHOLD:
                # Merge: update vector as weighted average, combine stats
                w_new = 1.0
                w_existing = float(existing.times_retrieved + 1)
                existing.vector = (
                    existing.vector * w_existing + new_pattern.vector * w_new
                ) / (w_existing + w_new)
                existing.metadata.update(new_pattern.metadata)
                existing.positive_outcomes += new_pattern.positive_outcomes
                existing.negative_outcomes += new_pattern.negative_outcomes
                existing.importance = max(existing.importance, new_pattern.importance)

                logger.debug(
                    "semantic_pattern_consolidated",
                    pattern_id=pid,
                    similarity=f"{sim:.4f}",
                )
                return True

        return False

    def _prune(self) -> None:
        """Remove the least important non-EWC patterns to stay under MAX_PATTERNS."""
        # Score each pattern: lower = better candidate for removal
        candidates = []
        for pid in self._pattern_ids:
            if pid in self._ewc_frozen:
                continue
            p = self._patterns.get(pid)
            if p is None:
                continue
            score = p.importance * (p.times_retrieved + 1)
            candidates.append((pid, score))

        # Remove bottom 20% that are not frozen
        candidates.sort(key=lambda x: x[1])
        to_remove = max(1, len(candidates) // 5)
        for pid, _ in candidates[:to_remove]:
            del self._patterns[pid]
            self._pattern_ids.remove(pid)

        logger.info(
            "semantic_memory_pruned",
            removed=to_remove,
            remaining=len(self._patterns),
        )

    @property
    def stats(self) -> dict[str, Any]:
        """Return memory statistics."""
        types = {}
        for p in self._patterns.values():
            types.setdefault(p.pattern_type, {"count": 0, "avg_success": 0.0})
            types[p.pattern_type]["count"] += 1
            types[p.pattern_type]["avg_success"] += p.success_rate

        for t in types:
            types[t]["avg_success"] = round(
                types[t]["avg_success"] / max(types[t]["count"], 1), 3
            )

        return {
            "total_patterns": len(self._patterns),
            "frozen_patterns": len(self._ewc_frozen),
            "by_type": types,
            "vector_dim": self._dim,
        }

    def clear(self) -> None:
        """Clear all patterns (for testing)."""
        self._patterns.clear()
        self._pattern_ids.clear()
        self._ewc_frozen.clear()
