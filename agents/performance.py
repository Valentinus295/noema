"""Performance Analyst Agent — analyzes trading results.

Tracks win rate, drawdown, RR ratio, session performance, setup performance.
"""

from __future__ import annotations

from typing import Any

import structlog

from vmpm.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


class PerformanceAnalystAgent(DeterministicAgent):
    """Agent #16 — Analyzes results.

    Tracks: Win rate, Drawdown, RR ratio, Session performance, Setup performance.
    """

    name = "performance-analyst"
    role = "Performance Analyst"
    priority = 0

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Analyze historical trade performance."""
        trades: list[dict] = context.get("trade_history", [])

        if not trades:
            return AgentReport(
                agent_name=self.name,
                signal="NEUTRAL",
                confidence=0.0,
                data={"total_trades": 0},
                reasoning="No trade history to analyze.",
            )

        total = len(trades)
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]

        win_rate = len(wins) / total if total > 0 else 0
        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t.get("pnl", 0) for t in losses) / len(losses)) if losses else 0
        profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if losses and avg_loss > 0 else float("inf")

        # Max drawdown
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in trades:
            cumulative += t.get("pnl", 0)
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        # Session analysis
        session_stats: dict[str, dict] = {}
        for t in trades:
            session = t.get("session", "unknown")
            if session not in session_stats:
                session_stats[session] = {"wins": 0, "losses": 0, "pnl": 0}
            if t.get("pnl", 0) > 0:
                session_stats[session]["wins"] += 1
            else:
                session_stats[session]["losses"] += 1
            session_stats[session]["pnl"] += t.get("pnl", 0)

        signal = "BULLISH" if win_rate > 0.55 else "BEARISH" if win_rate < 0.4 else "NEUTRAL"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=min(1.0, win_rate),
            data={
                "total_trades": total,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "profit_factor": profit_factor,
                "max_drawdown": max_dd,
                "session_stats": session_stats,
            },
            reasoning=self._build_reasoning(total, len(wins), len(losses), win_rate, profit_factor, max_dd),
        )

    def _build_reasoning(self, total, wins, losses, win_rate, pf, max_dd) -> str:
        parts = [
            f"Performance Report ({total} trades):",
            f"  Win Rate: {win_rate:.1%} ({wins}W / {losses}L)",
            f"  Profit Factor: {pf:.2f}",
            f"  Max Drawdown: ${max_dd:,.2f}",
        ]
        if win_rate >= 0.6:
            parts.append("  ✓ Strong performance")
        elif win_rate < 0.4:
            parts.append("  ✗ Poor performance — review strategy")
        return "\n".join(parts)
