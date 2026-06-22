"""ReflectorAgent — the brain that learns from every trade.

Like Hermes, this agent grows with the system. It mines losing trades
for patterns, identifies which setups work best, adapts risk parameters
based on performance, and generates correction prompts that update
the system's operating knowledge.

Self-improvement cycle:
1. Record every trade outcome with full context
2. Mine losers for common failure patterns
3. Compute Bayesian posterior on strategy edge
4. Adapt risk parameters based on regime + performance
5. Generate "lessons learned" that feed back into agent prompts
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Lesson:
    """A learned lesson from trade analysis."""
    lesson_id: str
    category: str           # "entry_timing", "risk_management", "regime", "pattern", "session"
    description: str
    confidence: float       # 0.0 - 1.0
    supporting_trades: int
    created_at: str = ""
    last_reinforced: str = ""
    times_applied: int = 0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.last_reinforced:
            self.last_reinforced = self.created_at


@dataclass
class RegimeAdaptation:
    """Dynamic parameter adjustments based on market regime."""
    regime: str             # "trending", "ranging", "volatile", "calm"
    risk_multiplier: float = 1.0
    min_confidence: float = 0.5
    preferred_sessions: list[str] = field(default_factory=list)
    avoided_patterns: list[str] = field(default_factory=list)


class ReflectorAgent:
    """Self-improving agent that learns from every trade.

    Inspired by the ReasoningBank pattern: agents distill successful
    and failed task experiences into generalized reasoning strategies
    that improve future decisions.
    """

    def __init__(self, knowledge_path: str = "data/reflector_knowledge.json") -> None:
        self.knowledge_path = Path(knowledge_path)
        self.knowledge_path.parent.mkdir(parents=True, exist_ok=True)
        self.knowledge = self._load_knowledge()
        self._trade_buffer: list[dict[str, Any]] = []

    def record_trade(self, trade: dict[str, Any]) -> None:
        """Record a completed trade with full context for learning."""
        record = {
            "ticket": trade.get("ticket", 0),
            "symbol": trade.get("symbol", ""),
            "direction": trade.get("direction", ""),
            "pnl": trade.get("pnl", 0.0),
            "pnl_pips": trade.get("pnl_pips", 0.0),
            "r_multiple": trade.get("r_multiple", 0.0),
            "session": trade.get("session", "unknown"),
            "market_regime": trade.get("market_regime", "unknown"),
            "trend": trade.get("trend", "unknown"),
            "rsi_at_entry": trade.get("rsi_at_entry", 50),
            "candlestick_pattern": trade.get("candlestick_pattern", "none"),
            "order_block_type": trade.get("order_block_type", "none"),
            "risk_reward": trade.get("risk_reward", 0),
            "confidence": trade.get("confidence", 0),
            "confluence_score": trade.get("confluence_score", 0),
            "entry_time": trade.get("entry_time", ""),
            "exit_time": trade.get("exit_time", ""),
            "exit_reason": trade.get("exit_reason", ""),
            "agent_reports": trade.get("agent_reports", {}),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

        self.knowledge["trades"].append(record)
        self._trade_buffer.append(record)

        # Auto-learn after every 10 trades
        if len(self._trade_buffer) >= 10:
            self._learn_from_buffer()

        self._save_knowledge()

    def learn(self) -> dict[str, Any]:
        """Run full learning cycle and return insights."""
        insights: dict[str, Any] = {}

        trades = self.knowledge["trades"]
        if len(trades) < 5:
            return {"message": "Need at least 5 trades for meaningful learning"}

        # 1. Mine losing trades for patterns
        insights["failure_patterns"] = self._mine_losing_trades()

        # 2. Identify best/worst setups
        insights["setup_analysis"] = self._analyze_setups()

        # 3. Session performance
        insights["session_analysis"] = self._analyze_sessions()

        # 4. Regime performance
        insights["regime_analysis"] = self._analyze_regimes()

        # 5. Pattern performance
        insights["pattern_analysis"] = self._analyze_patterns()

        # 6. Bayesian win-rate posterior
        insights["bayesian_edge"] = self._bayesian_win_rate()

        # 7. Generate/update lessons
        insights["lessons"] = self._generate_lessons()

        # 8. Compute regime adaptations
        insights["adaptations"] = self._compute_adaptations()

        self.knowledge["insights"] = insights
        self._save_knowledge()

        return insights

    def get_adapted_params(self, current_regime: str = "unknown") -> dict[str, Any]:
        """Get adapted parameters based on learned knowledge."""
        params: dict[str, Any] = {
            "risk_multiplier": 1.0,
            "min_confidence": 0.5,
            "preferred_sessions": ["london", "new_york"],
            "avoided_patterns": [],
            "lessons": [],
        }

        # Apply regime-specific adaptations
        adaptations = self.knowledge.get("adaptations", {})
        if current_regime in adaptations:
            adp = adaptations[current_regime]
            params["risk_multiplier"] = adp.get("risk_multiplier", 1.0)
            params["min_confidence"] = adp.get("min_confidence", 0.5)
            params["preferred_sessions"] = adp.get("preferred_sessions", ["london", "new_york"])
            params["avoided_patterns"] = adp.get("avoided_patterns", [])

        # Apply recent lessons
        lessons = self.knowledge.get("lessons", [])
        active_lessons = [l for l in lessons if l.get("confidence", 0) > 0.6]
        params["lessons"] = active_lessons[:5]  # Top 5 most confident

        # If win rate is dropping, tighten parameters
        bayesian = self.knowledge.get("insights", {}).get("bayesian_edge", {})
        if bayesian.get("posterior_mean", 0.5) < 0.45:
            params["min_confidence"] = 0.7
            params["risk_multiplier"] = 0.5
            logger.warning("win_rate_low_tightening", posterior=bayesian.get("posterior_mean"))

        return params

    def get_operating_manual(self) -> str:
        """Generate a text summary of learned knowledge for agent prompts."""
        lessons = self.knowledge.get("lessons", [])
        if not lessons:
            return "No lessons learned yet. Trading with default parameters."

        lines = ["LEARNED LESSONS (from trade history):", ""]
        for lesson in sorted(lessons, key=lambda x: x.get("confidence", 0), reverse=True)[:10]:
            conf = lesson.get("confidence", 0)
            desc = lesson.get("description", "")
            cat = lesson.get("category", "")
            lines.append(f"- [{cat.upper()}] {desc} (confidence: {conf:.0%})")

        return "\n".join(lines)

    # ── Learning methods ──

    def _mine_losing_trades(self) -> list[dict[str, Any]]:
        """Find common patterns in losing trades."""
        trades = self.knowledge["trades"]
        losers = [t for t in trades if t.get("pnl", 0) <= 0]

        if not losers:
            return []

        patterns: dict[str, list] = {}

        # Group by failure categories
        for t in losers:
            reasons = []
            if t.get("session") in ("off_hours", "asian"):
                reasons.append("bad_session")
            if t.get("market_regime") == "ranging" and t.get("trend") == "unknown":
                reasons.append("no_trend_in_ranging")
            if t.get("rsi_at_entry", 50) > 70 and t.get("direction") == "buy":
                reasons.append("overbought_entry")
            if t.get("rsi_at_entry", 50) < 30 and t.get("direction") == "sell":
                reasons.append("oversold_entry")
            if t.get("confidence", 1) < 0.5:
                reasons.append("low_confidence")
            if t.get("risk_reward", 0) < 2.0:
                reasons.append("poor_rr")
            if t.get("exit_reason") == "sl":
                reasons.append("stopped_out")
            if t.get("confluence_score", 1) < 0.6:
                reasons.append("weak_confluence")

            for reason in reasons:
                patterns.setdefault(reason, []).append(t)

        # Rank by frequency
        ranked = sorted(patterns.items(), key=lambda x: len(x[1]), reverse=True)
        return [
            {"pattern": name, "count": len(trades_), "pct": len(trades_) / len(losers) * 100}
            for name, trades_ in ranked[:10]
        ]

    def _analyze_setups(self) -> dict[str, Any]:
        """Analyze which setup characteristics lead to wins vs losses."""
        trades = self.knowledge["trades"]
        if not trades:
            return {}

        # Group by confluence score buckets
        buckets: dict[str, dict] = {
            "high_confidence": {"wins": 0, "losses": 0, "total_pnl": 0},
            "medium_confidence": {"wins": 0, "losses": 0, "total_pnl": 0},
            "low_confidence": {"wins": 0, "losses": 0, "total_pnl": 0},
        }

        for t in trades:
            conf = t.get("confidence", 0.5)
            pnl = t.get("pnl", 0)
            if conf >= 0.7:
                bucket = "high_confidence"
            elif conf >= 0.5:
                bucket = "medium_confidence"
            else:
                bucket = "low_confidence"

            if pnl > 0:
                buckets[bucket]["wins"] += 1
            else:
                buckets[bucket]["losses"] += 1
            buckets[bucket]["total_pnl"] += pnl

        for bucket in buckets:
            total = buckets[bucket]["wins"] + buckets[bucket]["losses"]
            buckets[bucket]["win_rate"] = buckets[bucket]["wins"] / total if total > 0 else 0

        return buckets

    def _analyze_sessions(self) -> dict[str, dict]:
        """Analyze performance by trading session."""
        trades = self.knowledge["trades"]
        sessions: dict[str, dict] = {}

        for t in trades:
            s = t.get("session", "unknown")
            if s not in sessions:
                sessions[s] = {"wins": 0, "losses": 0, "total_pnl": 0, "trades": []}
            sessions[s]["trades"].append(t.get("pnl", 0))
            if t.get("pnl", 0) > 0:
                sessions[s]["wins"] += 1
            else:
                sessions[s]["losses"] += 1
            sessions[s]["total_pnl"] += t.get("pnl", 0)

        for s in sessions:
            total = sessions[s]["wins"] + sessions[s]["losses"]
            sessions[s]["win_rate"] = sessions[s]["wins"] / total if total > 0 else 0
            pnls = sessions[s].pop("trades")
            sessions[s]["avg_pnl"] = sum(pnls) / len(pnls) if pnls else 0

        return sessions

    def _analyze_regimes(self) -> dict[str, dict]:
        """Analyze performance by market regime."""
        trades = self.knowledge["trades"]
        regimes: dict[str, dict] = {}

        for t in trades:
            r = t.get("market_regime", "unknown")
            if r not in regimes:
                regimes[r] = {"wins": 0, "losses": 0, "total_pnl": 0}
            if t.get("pnl", 0) > 0:
                regimes[r]["wins"] += 1
            else:
                regimes[r]["losses"] += 1
            regimes[r]["total_pnl"] += t.get("pnl", 0)

        for r in regimes:
            total = regimes[r]["wins"] + regimes[r]["losses"]
            regimes[r]["win_rate"] = regimes[r]["wins"] / total if total > 0 else 0

        return regimes

    def _analyze_patterns(self) -> dict[str, dict]:
        """Analyze performance by candlestick pattern."""
        trades = self.knowledge["trades"]
        patterns: dict[str, dict] = {}

        for t in trades:
            p = t.get("candlestick_pattern", "none")
            if p not in patterns:
                patterns[p] = {"wins": 0, "losses": 0, "total_pnl": 0}
            if t.get("pnl", 0) > 0:
                patterns[p]["wins"] += 1
            else:
                patterns[p]["losses"] += 1
            patterns[p]["total_pnl"] += t.get("pnl", 0)

        for p in patterns:
            total = patterns[p]["wins"] + patterns[p]["losses"]
            patterns[p]["win_rate"] = patterns[p]["wins"] / total if total > 0 else 0

        return patterns

    def _bayesian_win_rate(self) -> dict[str, float]:
        """Compute Bayesian posterior on win rate using Beta prior.

        Prior: Beta(alpha=4.5, beta=5.5) — weakly informative, mean=0.45
        """
        try:
            from scipy import stats as sp_stats
        except ImportError:
            sp_stats = None  # type: ignore[assignment]

        alpha_prior = 4.5
        beta_prior = 5.5

        trades = self.knowledge["trades"]
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        losses = len(trades) - wins

        alpha_post = alpha_prior + wins
        beta_post = beta_prior + losses

        posterior_mean = alpha_post / (alpha_post + beta_post)
        posterior_std = ((alpha_post * beta_post) /
                        ((alpha_post + beta_post) ** 2 * (alpha_post + beta_post + 1))) ** 0.5

        ci_lower = max(0, posterior_mean - 1.96 * posterior_std)
        ci_upper = min(1, posterior_mean + 1.96 * posterior_std)

        p_below_floor = sp_stats.beta.cdf(0.45, alpha_post, beta_post) if sp_stats else 0.5

        return {
            "posterior_mean": posterior_mean,
            "posterior_std": posterior_std,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "p_below_floor": p_below_floor,
            "total_trades": len(trades),
            "wins": wins,
            "alpha_post": alpha_post,
            "beta_post": beta_post,
        }

    def _generate_lessons(self) -> list[dict[str, Any]]:
        """Generate lessons from trade analysis."""
        lessons = list(self.knowledge.get("lessons", []))

        # Check failure patterns
        failures = self._mine_losing_trades()
        for f in failures[:5]:
            existing = next((l for l in lessons if l.get("description") == f["pattern"]), None)
            if existing:
                existing["confidence"] = min(1.0, existing["confidence"] + 0.05)
                existing["supporting_trades"] = f["count"]
                existing["last_reinforced"] = datetime.now(timezone.utc).isoformat()
            else:
                lessons.append({
                    "lesson_id": f"fail_{f['pattern']}_{int(time.time())}",
                    "category": "failure_pattern",
                    "description": f["pattern"],
                    "confidence": min(0.8, f["pct"] / 100),
                    "supporting_trades": f["count"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_reinforced": datetime.now(timezone.utc).isoformat(),
                    "times_applied": 0,
                })

        # Session lessons
        sessions = self._analyze_sessions()
        for s, data in sessions.items():
            if data.get("win_rate", 0) > 0.6 and data.get("wins", 0) >= 3:
                lessons.append({
                    "lesson_id": f"session_{s}_good",
                    "category": "session",
                    "description": f"Session {s} has high win rate ({data['win_rate']:.0%})",
                    "confidence": min(0.9, data["win_rate"]),
                    "supporting_trades": data.get("wins", 0) + data.get("losses", 0),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_reinforced": datetime.now(timezone.utc).isoformat(),
                    "times_applied": 0,
                })

        return lessons

    def _compute_adaptations(self) -> dict[str, dict]:
        """Compute regime-specific parameter adaptations."""
        regimes = self._analyze_regimes()
        adaptations: dict[str, dict] = {}

        for regime, data in regimes.items():
            win_rate = data.get("win_rate", 0.5)
            total = data.get("wins", 0) + data.get("losses", 0)

            if total < 5:
                continue

            if win_rate > 0.6:
                adaptations[regime] = {
                    "risk_multiplier": 1.2,
                    "min_confidence": 0.5,
                    "preferred_sessions": ["london", "new_york"],
                    "avoided_patterns": [],
                }
            elif win_rate < 0.4:
                adaptations[regime] = {
                    "risk_multiplier": 0.5,
                    "min_confidence": 0.7,
                    "preferred_sessions": [],
                    "avoided_patterns": ["all"],
                }
            else:
                adaptations[regime] = {
                    "risk_multiplier": 1.0,
                    "min_confidence": 0.55,
                    "preferred_sessions": ["london"],
                    "avoided_patterns": [],
                }

        return adaptations

    def _learn_from_buffer(self) -> None:
        """Process buffered trades and extract patterns."""
        if not self._trade_buffer:
            return

        # Analyze recent batch
        recent = self._trade_buffer[-10:]
        win_rate = sum(1 for t in recent if t.get("pnl", 0) > 0) / len(recent)

        if win_rate < 0.3:
            logger.warning("low_win_rate_detected", win_rate=win_rate, n_trades=len(recent))
            # Tighten parameters temporarily
            self.knowledge.setdefault("temporary_adjustments", {})
            self.knowledge["temporary_adjustments"]["min_confidence"] = 0.7
            self.knowledge["temporary_adjustments"]["risk_multiplier"] = 0.5

        self._trade_buffer.clear()

    # ── Persistence ──

    def _load_knowledge(self) -> dict[str, Any]:
        if self.knowledge_path.exists():
            try:
                return json.loads(self.knowledge_path.read_text())
            except Exception:
                pass
        return {"trades": [], "lessons": [], "insights": {}, "adaptations": {}}

    def _save_knowledge(self) -> None:
        try:
            self.knowledge_path.write_text(json.dumps(self.knowledge, indent=2, default=str))
        except Exception as exc:
            logger.error("knowledge_save_failed", error=str(exc))
