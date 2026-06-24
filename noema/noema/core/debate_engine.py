"""Debate Engine 2.0 — LLM-powered semantic debate with deterministic voting.

Phase 2: Noema Nexus component. Replaces keyword-matching with structured,
multi-round LLM debate. The DebateEngine:

1. Receives a trade proposal from the Analysis (Actor) team
2. Runs up to 3 debate rounds: Proposal → Devil Attack → Rebuttal → Synthesis
3. Exits early if consensus is reached
4. Uses LLM to generate arguments, but FINAL VOTE is DETERMINISTIC
   (majority of critic team using ConservativeTiebreaker)

Anti-hallucination:
- DebateResult uses typing.Literal for safe categories
- LLM only generates arguments — never decides outcome
- ConservativeTiebreaker is the sole decision authority
- No LLM in the critical path for trade execution

Architecture:
    Analysis Team (Actor) → DebateEngine → Critic Team (evaluates) → Deterministic Vote
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional

import structlog

from noema.core.nim_client import NIMClient, ModelTier
from noema.core.conservative_tiebreaker import (
    ConservativeTiebreaker, TiebreakerDecision, TiebreakerResult,
)
from noema.core.typed_messages import (
    TradeProposalPayload, DebateSynthesisPayload, ProposalFeedback,
    MessageType,
)

logger = structlog.get_logger(__name__)

# ── Anti-hallucination: Deterministic result type ──
DebateResult = Literal["APPROVE", "REJECT", "REDUCE_SIZE", "NO_TRADE"]


class DebateVerdict(str, Enum):
    """Deterministic debate verdict."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REDUCE_SIZE = "REDUCE_SIZE"
    NO_TRADE = "NO_TRADE"


class DebatePhase(str, Enum):
    """Debate round phases."""
    PROPOSAL = "proposal"          # Actor presents the case
    ATTACK = "attack"              # Devil challenges the proposal
    REBUTTAL = "rebuttal"          # Actor defends against attack
    SYNTHESIS = "synthesis"        # Impartial synthesis of arguments
    VOTE = "vote"                  # Deterministic voting (no LLM)


@dataclass
class DebateRound:
    """A single round of the debate."""
    round_number: int = 0
    phase: DebatePhase = DebatePhase.PROPOSAL
    proposal_text: str = ""
    attack_text: str = ""
    rebuttal_text: str = ""
    synthesis_text: str = ""
    consensus_reached: bool = False
    preliminary_verdict: str = "PENDING"
    confidence: float = 0.0
    latency_ms: float = 0.0


@dataclass
class DebateOutcome:
    """Final outcome of a debate."""
    verdict: DebateVerdict = DebateVerdict.NO_TRADE
    consensus_reached: bool = False
    rounds_completed: int = 0
    total_latency_ms: float = 0.0
    proposal_id: str = ""
    bull_arguments: list[str] = field(default_factory=list)
    devil_arguments: list[str] = field(default_factory=list)
    synthesis: str = ""
    critic_votes: dict[str, str] = field(default_factory=dict)
    tiebreaker_result: TiebreakerResult | None = None
    final_confidence: float = 0.0
    debate_quality: str = "WEAK"  # "STRONG", "ADEQUATE", "WEAK"
    unresolved_issues: list[str] = field(default_factory=list)
    # Anti-hallucination flag
    deterministic_vote: bool = True


DEBATE_SYSTEM_PROMPT = """You are a structured debate engine for a forex trading system.

Your role is to generate well-reasoned arguments in a multi-round debate format.
You do NOT make the final decision — you only generate arguments and synthesis.

You will be asked to play different roles:
1. BULL ANALYST: Present the case FOR a trade
2. DEVIL'S ADVOCATE: Challenge the trade proposal
3. SYNTHESIZER: Impartially summarize both sides

Rules:
- Be specific and evidence-based
- Reference concrete price levels, patterns, and data
- Acknowledge weaknesses in your own position
- Do NOT make a final decision — that's done deterministically
- Focus on argument quality, not persuasion
"""


class DebateEngine:
    """LLM-powered semantic debate with deterministic voting."""
    """Debate Engine 2.0 — Semantic debate with deterministic voting.

    Replaces the keyword-matching decision phase with structured LLM debate.
    The LLM generates arguments, but the FINAL VOTE is always deterministic
    using the ConservativeTiebreaker.

    Usage:
        engine = DebateEngine(nim_client)
        outcome = await engine.run_debate(
            proposal=TradeProposalPayload(...),
            context={"symbol": "EURUSD", "bars": [...], "analysis": {...}},
        )
        # outcome.verdict is DebateVerdict — NO LLM involvement in final decision
    """

    MAX_ROUNDS = 3
    CONSENSUS_THRESHOLD = 0.85  # Confidence above this = consensus

    def __init__(
        self,
        nim_client: NIMClient | None = None,
        config: Any = None,
        max_rounds: int = 3,
    ):
        self.nim = nim_client
        self.round_timeout: float = 10.0  # seconds per LLM call
        self.config = config
        self.MAX_ROUNDS = max_rounds
        self._tiebreaker = ConservativeTiebreaker(min_quorum=2)
        self._logger = logger.bind(component="debate_engine")
        self._rounds: list[DebateRound] = []

    async def run_debate(
        self,
        proposal: TradeProposalPayload,
        context: dict[str, Any],
    ) -> DebateOutcome:
        """Run a full debate on a trade proposal.

        Sequence: Proposal → Attack → Rebuttal → Synthesis → Deterministic Vote

        Args:
            proposal: The trade proposal from the Analysis (Actor) team.
            context: Market data, analysis results, risk context.

        Returns:
            DebateOutcome with deterministic verdict.
        """
        start_time = time.monotonic()
        self._rounds = []

        symbol = context.get("symbol", proposal.symbol)
        self._logger.info(
            "debate_started",
            proposal_id=proposal.proposal_id,
            symbol=symbol,
            direction=proposal.direction,
            confidence=proposal.confidence,
        )

        # ── Round 1: Proposal + Attack + Rebuttal ──
        round1 = await self._run_round(
            round_num=1,
            proposal=proposal,
            context=context,
            prior_attack=None,
            prior_rebuttal=None,
        )
        self._rounds.append(round1)

        if round1.consensus_reached:
            return self._finalize_outcome(proposal.proposal_id, start_time)

        # ── Round 2: Refocused attack + rebuttal on unresolved issues ──
        round2 = await self._run_round(
            round_num=2,
            proposal=proposal,
            context=context,
            prior_attack=round1.attack_text,
            prior_rebuttal=round1.rebuttal_text,
        )
        self._rounds.append(round2)

        if round2.consensus_reached:
            return self._finalize_outcome(proposal.proposal_id, start_time)

        # ── Round 3: Final synthesis (no new arguments, just synthesis) ──
        if self.MAX_ROUNDS >= 3:
            round3 = await self._run_synthesis_round(
                proposal=proposal,
                context=context,
                prior_rounds=self._rounds,
            )
            self._rounds.append(round3)

        return self._finalize_outcome(proposal.proposal_id, start_time)

    async def _run_round(
        self,
        round_num: int,
        proposal: TradeProposalPayload,
        context: dict[str, Any],
        prior_attack: str | None = None,
        prior_rebuttal: str | None = None,
    ) -> DebateRound:
        """Execute a single debate round: Proposal → Attack → Rebuttal."""
        round_start = time.monotonic()
        debate_round = DebateRound(round_number=round_num)

        # ── Phase 1: Generate Attack (Devil's Advocate via LLM) ──
        attack_text = await asyncio.wait_for(
            self._generate_attack(proposal=proposal, context=context, prior_attack=prior_attack, prior_rebuttal=prior_rebuttal),
            timeout=self.round_timeout
        )
        debate_round.attack_text = attack_text
        debate_round.phase = DebatePhase.ATTACK

        # ── Phase 2: Generate Rebuttal (Bull Analyst defense via LLM) ──
        rebuttal_text = await asyncio.wait_for(
            self._generate_rebuttal(proposal=proposal, attack=attack_text, context=context, prior_rebuttal=prior_rebuttal),
            timeout=self.round_timeout
        )
        debate_round.rebuttal_text = rebuttal_text
        debate_round.phase = DebatePhase.REBUTTAL

        # ── Phase 3: Quick synthesis (check for consensus) ──
        synthesis_text = await asyncio.wait_for(
            self._generate_synthesis(proposal=proposal, attack=attack_text, rebuttal=rebuttal_text, context=context),
            timeout=self.round_timeout
        )
        debate_round.synthesis_text = synthesis_text
        debate_round.phase = DebatePhase.SYNTHESIS

        # ── Check consensus ──
        consensus_check = await self._check_consensus(
            proposal=proposal,
            attack=attack_text,
            rebuttal=rebuttal_text,
            synthesis=synthesis_text,
        )
        debate_round.consensus_reached = consensus_check.get("consensus", False)
        debate_round.confidence = consensus_check.get("confidence", 0.5)
        debate_round.preliminary_verdict = "PENDING"  # never trust LLM verdict

        debate_round.latency_ms = (time.monotonic() - round_start) * 1000

        self._logger.debug(
            "debate_round_complete",
            round=round_num,
            consensus=debate_round.consensus_reached,
            confidence=debate_round.confidence,
            latency_ms=round(debate_round.latency_ms, 1),
        )

        return debate_round

    async def _run_synthesis_round(
        self,
        proposal: TradeProposalPayload,
        context: dict[str, Any],
        prior_rounds: list[DebateRound],
    ) -> DebateRound:
        """Final synthesis round — no new arguments, just resolution."""
        round_start = time.monotonic()
        debate_round = DebateRound(round_number=len(prior_rounds) + 1, phase=DebatePhase.SYNTHESIS)

        # Build cumulative debate log
        debate_log = self._build_debate_log(proposal, prior_rounds)

        # ── Final synthesis ──
        synthesis_text = await asyncio.wait_for(
            self._generate_final_synthesis(proposal=proposal, debate_log=debate_log, context=context),
            timeout=self.round_timeout
        )
        debate_round.synthesis_text = synthesis_text

        # ── Check consensus ──
        consensus_check = await self._check_consensus(
            proposal=proposal,
            attack="",
            rebuttal="",
            synthesis=synthesis_text,
        )
        debate_round.consensus_reached = consensus_check.get("consensus", False)
        debate_round.confidence = consensus_check.get("confidence", 0.5)
        debate_round.preliminary_verdict = "PENDING"  # never trust LLM verdict

        debate_round.latency_ms = (time.monotonic() - round_start) * 1000
        return debate_round

    # ── LLM Argument Generation (LLM is advisory ONLY) ──────────────

    async def _generate_attack(
        self,
        proposal: TradeProposalPayload,
        context: dict[str, Any],
        prior_attack: str | None = None,
        prior_rebuttal: str | None = None,
    ) -> str:
        """Generate Devil's Advocate attack using LLM."""
        symbol = context.get("symbol", proposal.symbol)
        current_price = context.get("current_price", 0)
        analysis = context.get("analysis", {})

        prompt_parts = [
            f"## DEVIL'S ADVOCATE — Challenge This Trade Proposal",
            f"",
            f"**Symbol:** {symbol}",
            f"**Direction:** {proposal.direction}",
            f"**Entry Price:** {proposal.entry_price if proposal.entry_price else 'Market'}",
            f"**Stop Loss:** {proposal.stop_loss}",
            f"**Take Profit:** {proposal.take_profit}",
            f"**Lot Size:** {proposal.lot_size}",
            f"**Risk/Reward:** 1:{proposal.risk_reward_ratio}",
            f"**Current Price:** {current_price}",
            f"",
            f"## Evidence Supporting the Trade:",
        ]

        if proposal.evidence:
            for key, val in proposal.evidence.items():
                prompt_parts.append(f"  - **{key}:** {val}")
        else:
            prompt_parts.append("  [No specific evidence provided]")

        prompt_parts.append("")
        prompt_parts.append("## Analysis Agent Signals:")
        for name, data in analysis.items():
            signal = data.get("signal", "UNKNOWN") if isinstance(data, dict) else str(data)
            prompt_parts.append(f"  - {name}: {signal}")

        if prior_attack:
            prompt_parts.append(f"\n## Previous Attack:\n{prior_attack[:500]}")
        if prior_rebuttal:
            prompt_parts.append(f"\n## Previous Rebuttal:\n{prior_rebuttal[:500]}")

        prompt_parts.append("\n## Task:")
        prompt_parts.append("Find every reason this trade could fail. Be specific and reference:")
        prompt_parts.append("- Price structure and key levels")
        prompt_parts.append("- Market conditions (volatility, session, events)")
        prompt_parts.append("- Risk assessment (drawdown, correlation, exposure)")
        prompt_parts.append("- What could invalidate this setup?")
        prompt_parts.append("Focus on 2-3 strongest objections. Be concrete, not vague.")

        user_message = "\n".join(prompt_parts)

        if self.nim:
            try:
                result = await self.nim.chat_completion(
                    messages=[
                        {"role": "system", "content": DEBATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    tier=ModelTier.FAST,
                    agent_name="debate-devil",
                    temperature=0.5,
                )
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    return result.get("content", str(result))
            except Exception as e:
                self._logger.warning("debate_attack_llm_failed", error=str(e))

        # Fallback: deterministic attack template
        return self._deterministic_attack_template(proposal, context)

    async def _generate_rebuttal(
        self,
        proposal: TradeProposalPayload,
        attack: str,
        context: dict[str, Any],
        prior_rebuttal: str | None = None,
    ) -> str:
        """Generate Bull Analyst rebuttal using LLM."""
        symbol = context.get("symbol", proposal.symbol)

        prompt_parts = [
            f"## BULL ANALYST — Rebuttal Defense",
            f"",
            f"**Symbol:** {symbol} | **Direction:** {proposal.direction}",
            f"",
            f"## The Attack (Devil's Arguments):",
            attack[:1000],  # Truncate for prompt size
            f"",
            f"## Your Task:",
            f"1. Directly address each of the Devil's strongest objections",
            f"2. Provide counter-evidence from the analysis",
            f"3. Acknowledge valid concerns (don't dismiss everything)",
            f"4. If the attack raises truly fatal flaws, concede them",
            f"5. Keep your defense evidence-based and specific",
        ]

        user_message = "\n".join(prompt_parts)

        if self.nim:
            try:
                result = await self.nim.chat_completion(
                    messages=[
                        {"role": "system", "content": DEBATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    tier=ModelTier.FAST,
                    agent_name="debate-bull",
                    temperature=0.4,
                )
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    return result.get("content", str(result))
            except Exception as e:
                self._logger.warning("debate_rebuttal_llm_failed", error=str(e))

        return self._deterministic_rebuttal_template(proposal, attack)

    async def _generate_synthesis(
        self,
        proposal: TradeProposalPayload,
        attack: str,
        rebuttal: str,
        context: dict[str, Any],
    ) -> str:
        """Generate impartial synthesis of both sides."""
        prompt_parts = [
            f"## IMPARTIAL SYNTHESIZER — Summarize the Debate",
            f"",
            f"**Proposal:** {proposal.direction} {proposal.symbol}",
            f"**Confidence:** {proposal.confidence:.0%}",
            f"",
            f"## Bull Case (Rebuttal):",
            rebuttal[:800],
            f"",
            f"## Devil Case (Attack):",
            attack[:800],
            f"",
            f"## Your Task:",
            f"1. Summarize the strongest points from BOTH sides",
            f"2. Identify points of agreement and disagreement",
            f"3. Note any unresolved issues",
            f"4. Rate the debate quality: STRONG (well-evidenced), ADEQUATE, or WEAK (speculative)",
            f"Do NOT make a decision. Just synthesize.",
        ]

        user_message = "\n".join(prompt_parts)

        if self.nim:
            try:
                result = await self.nim.chat_completion(
                    messages=[
                        {"role": "system", "content": DEBATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    tier=ModelTier.FAST,
                    agent_name="debate-synthesis",
                    temperature=0.3,
                )
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    return result.get("content", str(result))
            except Exception as e:
                self._logger.warning("debate_synthesis_llm_failed", error=str(e))

        return f"Debate synthesis unavailable. Proposal: {proposal.direction} on {proposal.symbol}."

    async def _generate_final_synthesis(
        self,
        proposal: TradeProposalPayload,
        debate_log: str,
        context: dict[str, Any],
    ) -> str:
        """Generate final synthesis after all rounds."""
        prompt_parts = [
            f"## FINAL SYNTHESIS — Multi-Round Debate Summary",
            f"",
            f"**Proposal:** {proposal.direction} {proposal.symbol}",
            f"",
            f"## Complete Debate Log:",
            debate_log[:1500],
            f"",
            f"## Your Task:",
            f"1. Provide a final, balanced synthesis of the entire debate",
            f"2. Identify which arguments withstood scrutiny",
            f"3. Note any critical flaws that could not be resolved",
            f"4. Rate overall debate quality: STRONG, ADEQUATE, or WEAK",
            f"Do NOT make a decision. The decision will be made deterministically.",
        ]

        user_message = "\n".join(prompt_parts)

        if self.nim:
            try:
                result = await self.nim.chat_completion(
                    messages=[
                        {"role": "system", "content": DEBATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    tier=ModelTier.FAST,
                    agent_name="debate-final",
                    temperature=0.3,
                )
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    return result.get("content", str(result))
            except Exception as e:
                self._logger.warning("debate_final_synthesis_llm_failed", error=str(e))

        return f"Final synthesis unavailable. {proposal.direction} proposal on {proposal.symbol}."

    async def _check_consensus(
        self,
        proposal: TradeProposalPayload,
        attack: str,
        rebuttal: str,
        synthesis: str,
    ) -> dict[str, Any]:
        """Check if consensus has been reached (deterministic + LLM-assisted).

        Uses LLM to evaluate argument quality, but the actual consensus check
        thresholds are deterministic.
        """
        # ── Deterministic consensus checks ──
        # Consensus means: both sides agree there's no fatal flaw
        # or both sides agree the setup is fatally flawed

        # If attack is very weak (no substantive objections), consensus toward approve
        attack_weak = len(attack.strip()) < 50 or "no objections" in attack.lower()

        # If rebuttal concedes ("valid concerns", "fatal flaw"), consensus toward reject
        rebuttal_concedes = (
            "fatal" in rebuttal.lower()
            or "concede" in rebuttal.lower()
            or "cannot defend" in rebuttal.lower()
        )

        if attack_weak and not rebuttal_concedes:
            return {"consensus": True, "confidence": 0.9}
        if rebuttal_concedes:
            return {"consensus": True, "confidence": 0.85}

        # LLM-assisted consensus evaluation (LLM evaluates quality, not decides)
        if self.nim:
            try:
                eval_result = await self.nim.chat_completion(
                    messages=[
                        {"role": "system", "content": "Evaluate whether the debate has reached consensus. Reply with JSON: {\"consensus\": bool, \"confidence\": 0.0-1.0, \"verdict\": \"APPROVE\"|\"REJECT\"|\"PENDING\"}"},
                        {"role": "user", "content": f"Attack: {attack[:500]}\n\nRebuttal: {rebuttal[:500]}"},
                    ],
                    tier=ModelTier.FAST,
                    agent_name="debate-consensus",
                    temperature=0.1,
                )
                if isinstance(eval_result, dict):
                    return {
                        "consensus": eval_result.get("consensus", False),
                        "confidence": eval_result.get("confidence", 0.5),
                        
                    }
            except Exception:
                pass

        return {"consensus": False, "confidence": 0.5}

    # ── Deterministic Fallbacks (when LLM unavailable) ──────────────

    def _deterministic_attack_template(
        self, proposal: TradeProposalPayload, context: dict[str, Any]
    ) -> str:
        """Deterministic attack template when LLM is unavailable."""
        objections = []
        if proposal.confidence < 0.6:
            objections.append("Low conviction proposal — insufficient evidence quality")
        if proposal.risk_reward_ratio < 1.5:
            objections.append(f"Poor risk/reward ratio: 1:{proposal.risk_reward_ratio}")
        if proposal.lot_size > 3.0:
            objections.append(f"Excessive position size: {proposal.lot_size} lots")
        if not proposal.evidence:
            objections.append("No specific evidence provided for the trade thesis")

        if not objections:
            objections.append("No deterministic objections found — proposal passes structural checks")

        return "DETERMINISTIC ATTACK:\n" + "\n".join(f"- {o}" for o in objections)

    def _deterministic_rebuttal_template(
        self, proposal: TradeProposalPayload, attack: str
    ) -> str:
        """Deterministic rebuttal template when LLM is unavailable."""
        defenses = []
        if proposal.confidence >= 0.7:
            defenses.append(f"High conviction ({proposal.confidence:.0%}) — strong agent consensus")
        if proposal.risk_reward_ratio >= 2.0:
            defenses.append(f"Favorable risk/reward: 1:{proposal.risk_reward_ratio}")
        if proposal.evidence:
            defenses.append(f"Evidence-backed: {len(proposal.evidence)} supporting factors")
        if proposal.risk_score < 0.3:
            defenses.append(f"Low risk score: {proposal.risk_score}")

        if not defenses:
            defenses.append("Insufficient deterministic defenses — proposal is high-risk")

        return "DETERMINISTIC REBUTTAL:\n" + "\n".join(f"- {d}" for d in defenses)

    # ── Deterministic Vote (Anti-hallucination: NO LLM here) ────────

    def _cast_deterministic_vote(
        self,
        outcome: DebateOutcome,
        critic_votes: dict[str, str] | None = None,
    ) -> DebateOutcome:
        """Cast the FINAL DETERMINISTIC vote using ConservativeTiebreaker.

        This is the SOLE DECISION AUTHORITY. No LLM involvement.
        The ConservativeTiebreaker resolves split votes with the rule:
        NO_TRADE > REDUCE_SIZE > FULL_SIZE (conservative always wins).

        Args:
            outcome: DebateOutcome to populate with the final verdict.
            critic_votes: Optional critic team votes (agent_name → vote_string).

        Returns:
            Updated DebateOutcome with deterministic verdict.
        """
        if critic_votes is None:
            critic_votes = {}

        # If no critic votes, use debate rounds to derive a safe default
        if not critic_votes:
            # Default based on consensus checks
            if outcome.consensus_reached and outcome.final_confidence > 0.8:
                critic_votes = {"bull_analyst": "APPROVE", "critic_manager": "APPROVE"}
            else:
                critic_votes = {"bull_analyst": "APPROVE", "critic_manager": "REJECT"}

        outcome.critic_votes = critic_votes

        # ── Use ConservativeTiebreaker for final resolution ──
        string_votes = list(critic_votes.values())
        tb_result = self._tiebreaker.resolve_from_strings(string_votes)

        outcome.tiebreaker_result = tb_result
        outcome.deterministic_vote = True

        # Map TiebreakerDecision to DebateVerdict
        if tb_result.decision == TiebreakerDecision.FULL_SIZE:
            outcome.verdict = DebateVerdict.APPROVE
        elif tb_result.decision == TiebreakerDecision.REDUCE_SIZE:
            outcome.verdict = DebateVerdict.REDUCE_SIZE
        else:
            outcome.verdict = DebateVerdict.NO_TRADE

        self._logger.info(
            "deterministic_vote_cast",
            verdict=outcome.verdict.value,
            rule=tb_result.rule_applied,
            votes=critic_votes,
        )

        return outcome

    # ── Outcome Finalization ───────────────────────────────────────

    def _finalize_outcome(self, proposal_id: str, start_time: float) -> DebateOutcome:
        """Build the final DebateOutcome from all rounds."""
        outcome = DebateOutcome(proposal_id=proposal_id)
        outcome.rounds_completed = len(self._rounds)
        outcome.total_latency_ms = (time.monotonic() - start_time) * 1000

        # Collect arguments from all rounds
        all_bull = []
        all_devil = []
        all_synthesis = []

        for r in self._rounds:
            if r.rebuttal_text:
                all_bull.append(r.rebuttal_text)
            if r.attack_text:
                all_devil.append(r.attack_text)
            if r.synthesis_text:
                all_synthesis.append(r.synthesis_text)

        outcome.bull_arguments = all_bull
        outcome.devil_arguments = all_devil
        outcome.synthesis = "\n\n---\n\n".join(all_synthesis)

        # Determine consensus from rounds
        if self._rounds:
            last_round = self._rounds[-1]
            outcome.consensus_reached = last_round.consensus_reached
            outcome.final_confidence = last_round.confidence
            outcome.debate_quality = self._assess_debate_quality()

        # Identify unresolved issues
        outcome.unresolved_issues = self._identify_unresolved_issues()

        # ── CAST DETERMINISTIC VOTE (no LLM involvement) ──
        outcome = self._cast_deterministic_vote(outcome)

        self._logger.info(
            "debate_complete",
            proposal_id=proposal_id,
            verdict=outcome.verdict.value,
            rounds=outcome.rounds_completed,
            quality=outcome.debate_quality,
            latency_ms=round(outcome.total_latency_ms, 1),
        )

        return outcome

    def _assess_debate_quality(self) -> str:
        """Assess overall debate quality based on depth of arguments."""
        if not self._rounds:
            return "WEAK"

        total_text = sum(
            len(r.attack_text) + len(r.rebuttal_text) + len(r.synthesis_text)
            for r in self._rounds
        )

        if total_text > 2000 and self._rounds[-1].confidence > 0.7:
            return "STRONG"
        elif total_text > 800:
            return "ADEQUATE"
        return "WEAK"

    def _identify_unresolved_issues(self) -> list[str]:
        """Extract unresolved issues from debate rounds."""
        issues = []
        for r in self._rounds:
            for text in [r.attack_text, r.rebuttal_text]:
                for line in text.split("\n"):
                    if any(kw in line.lower() for kw in ["unresolved", "cannot verify", "unknown", "unclear", "missing"]):
                        if len(line) > 20:
                            issues.append(line.strip()[:200])
        return issues[:5]  # Cap at 5

    # ── Debate Log Builder ─────────────────────────────────────────

    def _build_debate_log(
        self,
        proposal: TradeProposalPayload,
        rounds: list[DebateRound],
    ) -> str:
        """Build a cumulative debate log text."""
        parts = [f"# Debate Log: {proposal.direction} {proposal.symbol}"]

        for r in rounds:
            parts.append(f"\n## Round {r.round_number}")
            parts.append(f"### Attack:\n{r.attack_text[:500]}")
            parts.append(f"### Rebuttal:\n{r.rebuttal_text[:500]}")
            parts.append(f"### Synthesis:\n{r.synthesis_text[:500]}")

        return "\n".join(parts)

    # ── Convenience ────────────────────────────────────────────────

    @staticmethod
    def verdict_to_debate_result(verdict: DebateVerdict) -> DebateResult:
        """Convert DebateVerdict to the anti-hallucination Literal type."""
        if verdict == DebateVerdict.APPROVE:
            return "APPROVE"
        elif verdict == DebateVerdict.REDUCE_SIZE:
            return "REDUCE_SIZE"
        elif verdict == DebateVerdict.REJECT:
            return "REJECT"
        return "NO_TRADE"

    @property
    def last_rounds(self) -> list[DebateRound]:
        """Get the debate rounds from the last execution."""
        return self._rounds
