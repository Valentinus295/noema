"""
Debate Synthesis — combines Thesis + Devil's Advocate outputs into a structured
debate summary for the CIO.

Pattern inspired by TradingAgents' dual-debate architecture:
- Investment Debate: Bull Researcher ↔ Bear Researcher → Research Manager
- Risk Debate: Aggressive ↔ Conservative ↔ Neutral → Portfolio Manager

While Noema's Thesis → Devil → CIO chain is simpler, this module adds
adversarial depth by explicitly cross-referencing Thesis claims against
Devil objections before the CIO sees the final package.

The debate_synthesis() function takes the raw Thesis and Devil outputs
and produces:
1. A structured debate summary (point-by-point thesis claim vs devil objection)
2. A net conviction adjustment
3. Unresolved risks that the CIO must weigh
4. A recommendation for debate depth (single-pass or multi-round)

Future: Full multi-round debate (Thesis ↔ Devil back-and-forth) when
config.enable_multi_round_debate is True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DebatePoint:
    """A single point in the debate: thesis claim vs devil objection."""
    claim: str
    """What the thesis asserts."""

    objection: str | None = None
    """What the devil counters with, if anything."""

    resolution: str = "UNRESOLVED"
    """RESOLVED (thesis wins), RESOLVED_AGAINST (devil wins), or UNRESOLVED."""

    weight: float = 1.0
    """How much this point affects conviction (0.0-2.0)."""


@dataclass
class DebateSynthesis:
    """Synthesized output of the Thesis vs Devil's Advocate debate.

    This is the structured input consumed by the CIO Agent.
    Instead of getting raw thesis and devil separately, the CIO
    receives this pre-synthesized debate summary.
    """

    symbol: str = ""
    direction: str = "UNKNOWN"

    # ── Debate Points ────────────────────────────────────────────
    thesis_claims: list[str] = field(default_factory=list)
    """Claims made by the Trade Thesis agent."""

    devil_objections: list[str] = field(default_factory=list)
    """Objections raised by the Devil's Advocate."""

    debate_points: list[DebatePoint] = field(default_factory=list)
    """Point-by-point debate matches."""

    # ── Resolved Items ───────────────────────────────────────────
    resolved_thesis: list[str] = field(default_factory=list)
    """Thesis claims that the Devil could not refute."""

    resolved_devil: list[str] = field(default_factory=list)
    """Devil objections that successfully challenged thesis claims."""

    unresolved_issues: list[str] = field(default_factory=list)
    """Issues neither side could resolve — the CIO must judge."""

    # ── Conviction ───────────────────────────────────────────────
    original_conviction: float = 0.0
    """Thesis conviction before devil challenge."""

    confidence_reduction: float = 0.0
    """How much confidence the devil successfully reduced."""

    adjusted_conviction: float = 0.0
    """Net conviction after debate (original - reduction)."""

    conviction_tier: str = "LOW"
    """HIGH (>0.7), MEDIUM (0.4-0.7), LOW (<0.4)."""

    # ── CIO Guidance ─────────────────────────────────────────────
    recommendation: str = "NO_TRADE"
    """Suggested action for CIO: PROCEED, REDUCE_SIZE, or NO_TRADE."""

    key_risk: str = ""
    """The single most important risk the CIO must consider."""

    # ── Debate Metadata ──────────────────────────────────────────
    debate_quality: str = "ADEQUATE"
    """Quality assessment: STRONG (thorough challenge), ADEQUATE, or WEAK."""

    needs_multi_round: bool = False
    """Does this debate need another round for deeper adversarial testing?"""


# ── Synthesis Functions ────────────────────────────────────────────────

def synthesize_debate(
    thesis: dict[str, Any],
    devil: dict[str, Any],
    symbol: str = "",
    min_conviction: float = 0.4,
) -> DebateSynthesis:
    """Synthesize Thesis and Devil's Advocate outputs into a structured debate.

    This is the core function that transforms the raw LLM outputs from the
    Thesis agent and Devil's Advocate agent into a DebateSynthesis that the
    CIO gets as a structured input.

    Args:
        thesis: Output from the Trade Thesis agent (dict with direction,
                conviction, evidence_for, evidence_against, key_risk)
        devil: Output from the Devil's Advocate agent (dict with
               objections, should_trade, confidence_reduction, worst_case)
        symbol: Trading symbol
        min_conviction: Minimum conviction required to proceed

    Returns:
        DebateSynthesis ready for CIO consumption
    """
    synth = DebateSynthesis(symbol=symbol)

    # ── Extract raw data ─────────────────────────────────────────
    direction = thesis.get("direction", "UNKNOWN")
    synth.direction = direction

    evidence_for = thesis.get("evidence_for", [])
    evidence_against = thesis.get("evidence_against", [])
    thesis_narrative = thesis.get("narrative", "")
    thesis_key_risk = thesis.get("key_risk", "")

    devil_objections = devil.get("objections", [])
    devil_missing = devil.get("missing_evidence", [])
    devil_worst_case = devil.get("worst_case_scenario", "Unknown")
    confidence_reduction = devil.get("confidence_reduction", 0.0)

    synth.thesis_claims = list(evidence_for)
    synth.devil_objections = list(devil_objections)

    # ── Match claims to objections ───────────────────────────────
    debate_points: list[DebatePoint] = []

    # For each thesis claim, find the best-matching devil objection
    # (keyword-based matching — future: LLM-based semantic matching)
    remaining_objections = list(devil_objections)
    for claim in evidence_for:
        matched = _find_best_objection(claim, remaining_objections)
        if matched:
            remaining_objections.remove(matched)
            debate_points.append(DebatePoint(
                claim=claim,
                objection=matched,
                resolution="UNRESOLVED",
                weight=1.0,
            ))
        else:
            # Thesis claim unchallenged — this strengthens the thesis
            debate_points.append(DebatePoint(
                claim=claim,
                objection=None,
                resolution="RESOLVED",
                weight=0.5,  # Uncontested claims have less weight
            ))
            synth.resolved_thesis.append(claim)

    # Unmatched devil objections (devil raised concerns thesis didn't address)
    for objection in remaining_objections:
        debate_points.append(DebatePoint(
            claim="[Unaddressed by thesis]",
            objection=objection,
            resolution="RESOLVED_AGAINST",
            weight=1.5,  # Unaddressed objections carry more weight
        ))
        synth.resolved_devil.append(objection)

    synth.debate_points = debate_points

    # ── Identify unresolved issues ───────────────────────────────
    # These are things the CIO must judge
    unresolved: list[str] = []
    for dp in debate_points:
        if dp.resolution == "UNRESOLVED":
            unresolved.append(f"Claim: {dp.claim} | Objection: {dp.objection}")

    # Add missing evidence
    if devil_missing:
        unresolved.extend([f"Missing evidence: {m}" for m in devil_missing])

    # Add evidence against (from thesis itself)
    if evidence_against:
        unresolved.extend([f"Thesis acknowledges: {e}" for e in evidence_against])

    synth.unresolved_issues = unresolved

    # ── Conviction calculation ───────────────────────────────────
    original_conviction = thesis.get("conviction", 0.5)
    synth.original_conviction = original_conviction
    synth.confidence_reduction = min(confidence_reduction, 0.5)

    # Adjusted conviction: original minus devil's reduction
    # But also adjusted by debate quality
    resolved_for = len(synth.resolved_thesis)
    resolved_against = len(synth.resolved_devil)
    total_points = len(debate_points) if debate_points else 1

    debate_factor = (resolved_for - resolved_against) / total_points * 0.2
    adjusted = max(0.0, min(1.0, original_conviction - confidence_reduction + debate_factor))
    synth.adjusted_conviction = adjusted

    # ── Conviction tier ──────────────────────────────────────────
    if adjusted >= 0.7:
        synth.conviction_tier = "HIGH"
    elif adjusted >= 0.4:
        synth.conviction_tier = "MEDIUM"
    else:
        synth.conviction_tier = "LOW"

    # ── CIO guidance ─────────────────────────────────────────────
    if devil.get("should_trade", True) is False:
        synth.recommendation = "NO_TRADE"
    elif adjusted >= min_conviction and resolved_against <= resolved_for:
        synth.recommendation = "PROCEED"
    elif adjusted >= min_conviction * 0.75:
        synth.recommendation = "REDUCE_SIZE"
    else:
        synth.recommendation = "NO_TRADE"

    # ── Key risk ─────────────────────────────────────────────────
    if devil_objections:
        synth.key_risk = devil_objections[0]  # Most important objection
    elif thesis_key_risk:
        synth.key_risk = thesis_key_risk
    if devil_worst_case and devil_worst_case != "Unknown":
        synth.key_risk += f" | Worst case: {devil_worst_case}"

    # ── Debate quality ───────────────────────────────────────────
    if len(debate_points) >= 5 and resolved_against > 0:
        synth.debate_quality = "STRONG"
        synth.needs_multi_round = False
    elif len(debate_points) >= 3:
        synth.debate_quality = "ADEQUATE"
        synth.needs_multi_round = len(unresolved) > 3
    else:
        synth.debate_quality = "WEAK"
        synth.needs_multi_round = True

    logger.info(
        "debate_synthesized",
        symbol=symbol,
        direction=direction,
        original_conviction=original_conviction,
        adjusted_conviction=adjusted,
        recommendation=synth.recommendation,
        debate_quality=synth.debate_quality,
        unresolved_count=len(unresolved),
    )

    return synth


def format_debate_for_cio(synthesis: DebateSynthesis) -> str:
    """Format a DebateSynthesis into a prompt section for the CIO agent.

    The CIO receives this as part of its user message context.
    This replaces the raw thesis + devil sections with a structured
    debate summary that the CIO can reason about more effectively.

    Returns:
        Formatted string for CIO prompt context
    """
    lines = [
        f"## Debate Synthesis: {synthesis.symbol}",
        f"Direction: {synthesis.direction}",
        f"Original Conviction: {synthesis.original_conviction:.0%}",
        f"Conviction After Debate: {synthesis.adjusted_conviction:.0%} "
        f"({synthesis.conviction_tier})",
        f"Devil's Confidence Reduction: {synthesis.confidence_reduction:.0%}",
        f"Recommendation: {synthesis.recommendation}",
        "",
        "### Point-by-Point Debate",
    ]

    for i, dp in enumerate(synthesis.debate_points):
        lines.append(f"\n**Point {i+1}** (weight: {dp.weight:.1f})")
        lines.append(f"- THESIS: {dp.claim}")
        if dp.objection:
            lines.append(f"- DEVIL: {dp.objection}")
            lines.append(f"- Status: {dp.resolution}")
        else:
            lines.append("- Status: UNCHALLENGED (strengthens thesis)")

    if synthesis.resolved_thesis:
        lines.append(f"\n**Thesis Claims That Stood Up** ({len(synthesis.resolved_thesis)}):")
        for claim in synthesis.resolved_thesis:
            lines.append(f"  ✅ {claim}")

    if synthesis.resolved_devil:
        lines.append(f"\n**Devil Objections That Stood** ({len(synthesis.resolved_devil)}):")
        for obj in synthesis.resolved_devil:
            lines.append(f"  ⚠️ {obj}")

    if synthesis.unresolved_issues:
        lines.append(f"\n**Issues the CIO Must Resolve** ({len(synthesis.unresolved_issues)}):")
        for issue in synthesis.unresolved_issues[:5]:
            lines.append(f"  ❓ {issue}")

    lines.append(f"\n**Key Risk**: {synthesis.key_risk}")
    lines.append(f"**Debate Quality**: {synthesis.debate_quality}")
    if synthesis.needs_multi_round:
        lines.append("⚠️ This debate may benefit from another round of adversarial testing.")

    return "\n".join(lines)


def format_debate_for_report(synthesis: DebateSynthesis) -> str:
    """Format a DebateSynthesis for human-readable reporting.

    More condensed version suitable for log files and dashboards.
    """
    lines = [
        f"# Debate Report: {synthesis.symbol} ({synthesis.direction})",
        f"Conviction: {synthesis.original_conviction:.0%} → {synthesis.adjusted_conviction:.0%} "
        f"(-{synthesis.confidence_reduction:.0%})",
        f"Quality: {synthesis.debate_quality} | Verdict: {synthesis.recommendation}",
        "",
        f"**Key Risk**: {synthesis.key_risk}",
        "",
        "## Resolution Summary",
        f"Thesis wins: {len(synthesis.resolved_thesis)} | Devil wins: {len(synthesis.resolved_devil)} "
        f"| Unresolved: {len(synthesis.unresolved_issues)}",
    ]

    return "\n".join(lines)


# ── Helper: Objection Matching ─────────────────────────────────────────

def _find_best_objection(
    claim: str,
    objections: list[str],
) -> str | None:
    """Find the objection that best matches a claim using keyword overlap.

    Simple heuristic: count shared keywords, pick the objection with the
    highest overlap. Future enhancement: semantic similarity via embeddings.
    """
    if not objections:
        return None

    # Tokenize the claim
    claim_keywords = set(claim.lower().split()) - _STOP_WORDS

    best_idx = -1
    best_score = 0

    for i, objection in enumerate(objections):
        obj_keywords = set(objection.lower().split()) - _STOP_WORDS
        overlap = len(claim_keywords & obj_keywords)

        # Bonus for directional words (bullish/bearish, buy/sell, support/resistance)
        directional_bonus = 0
        for dw in _DIRECTIONAL_WORDS:
            if dw in claim.lower() and dw in objection.lower():
                directional_bonus += 1

        score = overlap + directional_bonus
        if score > best_score:
            best_score = score
            best_idx = i

    # Return the best match if it has meaningful overlap
    if best_score >= 1:
        return objections[best_idx]

    # If no keyword match, try to match the first remaining objection
    # as a catch-all (sometimes thesis claims are broad and objections are specific)
    if len(objections) == 1 and best_score == 0:
        return objections[0]

    return None


# ── Constants ──────────────────────────────────────────────────────────

_STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "from", "by", "about", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "and",
    "but", "or", "not", "no", "this", "that", "these", "those", "it",
    "its", "we", "they", "them", "their", "our",
}

_DIRECTIONAL_WORDS: set[str] = {
    "bullish", "bearish", "buy", "sell", "long", "short",
    "support", "resistance", "trend", "reversal", "breakout",
    "overbought", "oversold", "divergence", "momentum",
    "risk", "volatility", "hawkish", "dovish",
}
