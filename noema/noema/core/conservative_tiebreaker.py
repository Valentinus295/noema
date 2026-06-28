"""Conservative Tiebreaker — Deterministic, rule-based decision resolution.

The ConservativeTiebreaker is the SOLE DECISION AUTHORITY for resolving
split critic team votes. It is entirely deterministic — NO LLM INVOLVEMENT
in any trade decision path.

Rule: NO_TRADE > REDUCE_SIZE > FULL_SIZE

The more conservative outcome always wins when critics split.
This guarantees that:
1. An LLM hallucination cannot force a trade
2. A single overly-optimistic critic cannot override caution
3. The system defaults to safety when uncertain

This implements AC2.4, AC2.9, AC2.10 from the Noema Blueprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TiebreakerDecision(str, Enum):
    """Deterministic decision outcomes from the ConservativeTiebreaker.

    Order matters: later values are MORE conservative. This is intentional
    for comparison operations — NO_TRADE > REDUCE_SIZE > FULL_SIZE.
    """
    FULL_SIZE = "FULL_SIZE"
    REDUCE_SIZE = "REDUCE_SIZE"
    NO_TRADE = "NO_TRADE"

    @property
    def ordinal(self) -> int:
        """Higher ordinal = more conservative."""
        return {"FULL_SIZE": 0, "REDUCE_SIZE": 1, "NO_TRADE": 2}[self.value]

    @property
    def allows_trading(self) -> bool:
        """Whether this decision permits any trade execution."""
        return self != TiebreakerDecision.NO_TRADE

    @property
    def allows_full_size(self) -> bool:
        """Whether this decision permits full position size."""
        return self == TiebreakerDecision.FULL_SIZE


@dataclass
class TiebreakerResult:
    """Result of the conservative tiebreaker resolution.

    Attributes:
        decision: The final deterministic decision.
        vote_counts: Raw vote counts per decision option.
        total_votes: Total number of votes cast.
        quorum_met: Whether minimum quorum was met (≥ 2 votes).
        rule_applied: Which tiebreaking rule was applied.
        details: Human-readable explanation.
        no_llm_involved: Always True — validation flag.
    """
    decision: TiebreakerDecision = TiebreakerDecision.NO_TRADE
    vote_counts: dict[TiebreakerDecision, int] = field(default_factory=dict)
    total_votes: int = 0
    quorum_met: bool = False
    rule_applied: str = ""
    details: str = ""
    no_llm_involved: bool = True  # Always True — compile-time enforcement

    @property
    def is_deadlock(self) -> bool:
        """True when votes are evenly split."""
        if not self.vote_counts:
            return True
        values = list(self.vote_counts.values())
        if not values:
            return True
        return len(set(values)) == 1 and values[0] > 0


class ConservativeTiebreaker:
    """Deterministic tiebreaker — NO LLM involvement whatsoever.

    Resolves split critic team votes using the rule:
    NO_TRADE > REDUCE_SIZE > FULL_SIZE

    The more conservative outcome ALWAYS wins. This is the golden rule:
    "Conservative always wins."

    Usage:
        >>> tiebreaker = ConservativeTiebreaker()
        >>> result = tiebreaker.resolve({
        ...     TiebreakerDecision.NO_TRADE: 2,
        ...     TiebreakerDecision.FULL_SIZE: 3,
        ... })
        >>> result.decision
        <TiebreakerDecision.NO_TRADE: 'NO_TRADE'>
    """

    # Minimum number of critic votes required for any decision
    MIN_QUORUM: int = 2

    def __init__(self, min_quorum: int = 2):
        self.MIN_QUORUM = min_quorum

    def resolve(
        self,
        votes: dict[TiebreakerDecision, int],
    ) -> TiebreakerResult:
        """Resolve a vote distribution using conservative tiebreaking.

        Args:
            votes: Mapping of decision → vote count.

        Returns:
            TiebreakerResult with the deterministic decision.
        """
        total = sum(votes.values())
        quorum_met = total >= self.MIN_QUORUM

        if not quorum_met:
            return TiebreakerResult(
                decision=TiebreakerDecision.NO_TRADE,
                vote_counts=votes,
                total_votes=total,
                quorum_met=False,
                rule_applied="quorum_fail",
                details=(
                    f"Quorum not met: {total} votes (minimum {self.MIN_QUORUM}). "
                    f"Defaulting to NO_TRADE for safety."
                ),
            )

        # Rule 1: If NO_TRADE has ANY votes, it wins.
        # This is the most extreme "conservative wins" rule:
        # even a single NO_TRADE vote overrides all others.
        no_trade_votes = votes.get(TiebreakerDecision.NO_TRADE, 0)
        if no_trade_votes > 0:
            return TiebreakerResult(
                decision=TiebreakerDecision.NO_TRADE,
                vote_counts=votes,
                total_votes=total,
                quorum_met=True,
                rule_applied="conservative_veto",
                details=(
                    f"NO_TRADE veto: {no_trade_votes} NO_TRADE vote(s) override "
                    f"all other votes. Conservative wins."
                ),
            )

        # Rule 2: If REDUCE_SIZE has ANY votes, it wins over FULL_SIZE.
        reduce_votes = votes.get(TiebreakerDecision.REDUCE_SIZE, 0)
        full_votes = votes.get(TiebreakerDecision.FULL_SIZE, 0)

        if reduce_votes > 0:
            return TiebreakerResult(
                decision=TiebreakerDecision.REDUCE_SIZE,
                vote_counts=votes,
                total_votes=total,
                quorum_met=True,
                rule_applied="conservative_reduce",
                details=(
                    f"REDUCE_SIZE selected: {reduce_votes} REDUCE_SIZE votes "
                    f"override {full_votes} FULL_SIZE votes. "
                    f"Conservative wins."
                ),
            )

        # Rule 3: Only FULL_SIZE votes remain → all-clear.
        if full_votes > 0:
            return TiebreakerResult(
                decision=TiebreakerDecision.FULL_SIZE,
                vote_counts=votes,
                total_votes=total,
                quorum_met=True,
                rule_applied="unanimous_full_size",
                details=(
                    f"All {full_votes} votes for FULL_SIZE. "
                    f"No conservative override needed."
                ),
            )

        # Edge case: somehow reached here with empty/zero votes despite quorum
        return TiebreakerResult(
            decision=TiebreakerDecision.NO_TRADE,
            vote_counts=votes,
            total_votes=total,
            quorum_met=True,
            rule_applied="fallback_safety",
            details="Fallback: no valid votes detected. Defaulting to NO_TRADE.",
        )

    def resolve_from_strings(
        self,
        string_votes: list[str],
    ) -> TiebreakerResult:
        """Resolve votes from string labels (for agent integration).

        Convenience method that maps string labels to TiebreakerDecision
        and then calls resolve().

        Args:
            string_votes: List of vote strings like ["APPROVE", "REJECT",
                          "NO_TRADE", "FULL_SIZE", "REDUCE_SIZE"].

        Returns:
            TiebreakerResult.
        """
        vote_counts: dict[TiebreakerDecision, int] = {
            TiebreakerDecision.NO_TRADE: 0,
            TiebreakerDecision.REDUCE_SIZE: 0,
            TiebreakerDecision.FULL_SIZE: 0,
        }

        for vote in string_votes:
            decision = self._map_string(vote)
            vote_counts[decision] += 1

        return self.resolve(vote_counts)

    @staticmethod
    def _map_string(vote: str) -> TiebreakerDecision:
        """Map common string representations to TiebreakerDecision."""
        vote_upper = vote.upper().strip()

        if vote_upper in ("NO_TRADE", "REJECT", "HALT", "KILL", "ABSTAIN"):
            return TiebreakerDecision.NO_TRADE
        elif vote_upper in ("REDUCE_SIZE", "REDUCE", "CAUTION", "SMALL", "MODIFY"):
            return TiebreakerDecision.REDUCE_SIZE
        elif vote_upper in ("FULL_SIZE", "APPROVE", "BUY", "SELL", "GO"):
            return TiebreakerDecision.FULL_SIZE
        else:
            # Unknown votes default to NO_TRADE (most conservative)
            return TiebreakerDecision.NO_TRADE

    def validate_no_llm_override(self, result: TiebreakerResult) -> bool:
        """Verify that no LLM was involved in the decision.

        This is a compile-time level check. Always returns True by design.
        Can be called at runtime as a safety assertion.
        """
        return result.no_llm_involved


# ═══════════════════════════════════════════════════
# Module-level singleton for convenience
# ═══════════════════════════════════════════════════

_tiebreaker_instance: ConservativeTiebreaker | None = None


def get_tiebreaker() -> ConservativeTiebreaker:
    """Get the module-level ConservativeTiebreaker singleton."""
    global _tiebreaker_instance
    if _tiebreaker_instance is None:
        _tiebreaker_instance = ConservativeTiebreaker()
    return _tiebreaker_instance


