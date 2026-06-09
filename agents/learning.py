"""Learning Agent — makes the system smarter after every trade.

Stores market conditions, outcomes, and calculates which setups work best.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class LearningAgent(Agent):
    """Agent #17 — Makes the system smarter.

    After every trade, stores: Market conditions, News conditions,
    Trend conditions, S/R Zone, RSI state, Candlestick pattern, Outcome.

    Calculates: Which setups work best, which sessions perform best,
    which order blocks perform best, which confirmations fail most.
    """

    name = "learning"
    role = "Learning Agent"
    priority = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.knowledge_file = Path("vmpm_knowledge.json")
        self.knowledge = self._load_knowledge()

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Learn from a completed trade."""
        trade = context.get("completed_trade", {})
        if not trade:
            return AgentReport(
                agent_name=self.name,
                signal="NEUTRAL",
                confidence=0.0,
                reasoning="No completed trade to learn from.",
            )

        # Record the trade with full context
        record = {
            "pair": trade.get("pair", ""),
            "direction": trade.get("direction", ""),
            "outcome": "win" if trade.get("pnl", 0) > 0 else "loss",
            "pnl": trade.get("pnl", 0),
            "session": trade.get("session", "unknown"),
            "market_regime": trade.get("market_regime", "unknown"),
            "trend": trade.get("trend", "unknown"),
            "rsi_at_entry": trade.get("rsi_at_entry", 50),
            "candlestick_pattern": trade.get("candlestick_pattern", "none"),
            "order_block_type": trade.get("order_block_type", "none"),
            "risk_reward": trade.get("risk_reward", 0),
            "confidence": trade.get("confidence", 0),
        }

        self.knowledge["trades"].append(record)
        self._save_knowledge()

        # Analyze patterns
        insights = self._analyze_patterns()

        return AgentReport(
            agent_name=self.name,
            signal="LEARNED",
            confidence=0.9,
            data={
                "recorded": True,
                "total_trades_learned": len(self.knowledge["trades"]),
                "insights": insights,
            },
            reasoning=f"Trade recorded. Total trades in knowledge base: {len(self.knowledge['trades'])}.\n"
                      f"Key insight: {insights.get('best_session', 'N/A')} session has highest win rate.",
        )

    def _analyze_patterns(self) -> dict[str, Any]:
        """Analyze patterns in trade history."""
        trades = self.knowledge["trades"]
        if len(trades) < 5:
            return {"message": "Need more trades for analysis"}

        # Session performance
        session_stats: dict[str, dict] = {}
        for t in trades:
            s = t.get("session", "unknown")
            if s not in session_stats:
                session_stats[s] = {"wins": 0, "total": 0, "pnl": 0}
            session_stats[s]["total"] += 1
            session_stats[s]["pnl"] += t.get("pnl", 0)
            if t.get("outcome") == "win":
                session_stats[s]["wins"] += 1

        for s in session_stats:
            session_stats[s]["win_rate"] = session_stats[s]["wins"] / session_stats[s]["total"]

        best_session = max(session_stats, key=lambda x: session_stats[x]["win_rate"]) if session_stats else "N/A"

        # Pattern performance
        pattern_stats: dict[str, dict] = {}
        for t in trades:
            p = t.get("candlestick_pattern", "none")
            if p not in pattern_stats:
                pattern_stats[p] = {"wins": 0, "total": 0}
            pattern_stats[p]["total"] += 1
            if t.get("outcome") == "win":
                pattern_stats[p]["wins"] += 1

        return {
            "best_session": best_session,
            "session_stats": session_stats,
            "pattern_stats": pattern_stats,
            "total_analyzed": len(trades),
        }

    def _load_knowledge(self) -> dict[str, Any]:
        """Load knowledge base from disk."""
        if self.knowledge_file.exists():
            try:
                return json.loads(self.knowledge_file.read_text())
            except Exception:
                pass
        return {"trades": [], "insights": {}}

    def _save_knowledge(self) -> None:
        """Save knowledge base to disk."""
        try:
            self.knowledge_file.write_text(json.dumps(self.knowledge, indent=2))
        except Exception as exc:
            self._logger.error("knowledge_save_failed", error=str(exc))
