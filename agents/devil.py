"""Devil's Advocate Agent — destroys bad trades.

This is one of the most important agents. It argues AGAINST the trade.
"""

from __future__ import annotations

from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class DevilsAdvocateAgent(Agent):
    """Agent #12 — Destroys bad trades.

    Asks: Why might this trade fail? What are we missing?
    What contradicts the setup?
    """

    name = "devils-advocate"
    role = "Devil's Advocate — Trade Critic"
    priority = 1

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Critique the proposed trade and find weaknesses."""
        reports: dict[str, dict] = context.get("agent_reports", {})
        pair: str = context.get("pair", "EURUSD")
        direction: str = context.get("direction", "long")

        weaknesses: list[str] = []

        # Check for conflicting signals
        signals = {}
        for agent_name, report in reports.items():
            signals[agent_name] = report.get("signal", "NEUTRAL")

        bullish_agents = [k for k, v in signals.items() if v == "BULLISH"]
        bearish_agents = [k for k, v in signals.items() if v == "BEARISH"]

        if len(bearish_agents) > 0 and direction == "long":
            weaknesses.append(f"{len(bearish_agents)} agent(s) signal bearish: {', '.join(bearish_agents)}")

        if len(bullish_agents) > 0 and direction == "short":
            weaknesses.append(f"{len(bullish_agents)} agent(s) signal bullish: {', '.join(bullish_agents)}")

        # Check risk/reward
        risk = context.get("risk_reward", {})
        rr = risk.get("risk_reward_ratio", 0)
        if rr < 2.0:
            weaknesses.append(f"Poor risk/reward: 1:{rr:.1f} (minimum 1:2)")

        # Check session timing
        session = reports.get("session-intelligence", {})
        if session.get("data", {}).get("is_low_probability"):
            weaknesses.append("Low probability trading session")

        # Check trend alignment
        structure = reports.get("market-structure", {})
        if direction == "long" and structure.get("signal") == "BEARISH":
            weaknesses.append("Trading against bearish trend")
        elif direction == "short" and structure.get("signal") == "BULLISH":
            weaknesses.append("Trading against bullish trend")

        # Check opportunity proximity
        opportunity = reports.get("opportunity-surveillance", {})
        if opportunity.get("data", {}).get("count", 0) == 0:
            weaknesses.append("No clear opportunity at key zones")

        # Verdict
        if len(weaknesses) == 0:
            signal = "APPROVE"
            confidence = 0.8
        elif len(weaknesses) <= 1:
            signal = "APPROVE"
            confidence = 0.5
        else:
            signal = "REJECT"
            confidence = min(0.9, 0.3 + len(weaknesses) * 0.15)

        reasoning = f"Devil's Advocate Report for {pair} ({direction.upper()}):\n"
        reasoning += f"Weaknesses found: {len(weaknesses)}\n"
        for w in weaknesses:
            reasoning += f"  ⚠ {w}\n"
        reasoning += f"Verdict: {signal}"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data={
                "weaknesses": weaknesses,
                "weakness_count": len(weaknesses),
                "verdict": signal,
            },
            reasoning=reasoning,
        )
