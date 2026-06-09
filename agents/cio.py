"""Chief Investment Officer Agent — the final decision maker.

Never analyzes charts directly. Listens to every other agent and decides:
BUY, SELL, WAIT, REJECT.
"""

from __future__ import annotations

from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class CIOAgent(Agent):
    """Agent #1 — Chief Investment Officer.

    The final decision maker. Collects reports from all agents,
    resolves conflicts, and approves/rejects trades.
    """

    name = "cio"
    role = "Chief Investment Officer"
    priority = 0  # Runs last — final decision

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Make the final trading decision based on all agent reports."""
        reports: dict[str, dict] = context.get("agent_reports", {})
        pair: str = context.get("pair", "EURUSD")
        direction: str = context.get("direction", "long")
        pipeline_state: str = context.get("pipeline_state", "idle")

        # Collect signals
        bullish_agents = []
        bearish_agents = []
        neutral_agents = []
        reject_agents = []

        for agent_name, report in reports.items():
            signal = report.get("signal", "NEUTRAL")
            if signal == "BULLISH":
                bullish_agents.append(agent_name)
            elif signal == "BEARISH":
                bearish_agents.append(agent_name)
            elif signal == "REJECT":
                reject_agents.append(agent_name)
            else:
                neutral_agents.append(agent_name)

        # Decision logic
        total = len(reports)
        if total == 0:
            return AgentReport(
                agent_name=self.name,
                signal="WAIT",
                confidence=0.0,
                reasoning="No agent reports received. Waiting.",
            )

        # Critical: If Devil's Advocate rejects, we reject
        if "devils-advocate" in reject_agents:
            return AgentReport(
                agent_name=self.name,
                signal="REJECT",
                confidence=0.9,
                data={"decision": "REJECT", "reason": "Devil's Advocate rejected trade"},
                reasoning="Devil's Advocate found critical weaknesses. Trade rejected.",
            )

        # Need majority consensus
        if direction == "long":
            consensus = len(bullish_agents) / total
        else:
            consensus = len(bearish_agents) / total

        # Risk Manager must approve
        risk_approved = reports.get("risk-manager", {}).get("signal") != "REJECT"

        # Trade Thesis must be strong
        thesis_signal = reports.get("trade-thesis", {}).get("signal", "NEUTRAL")
        thesis_confidence = reports.get("trade-thesis", {}).get("confidence", 0)

        # Final decision
        if not risk_approved:
            decision = "REJECT"
            reason = "Risk Manager rejected"
        elif reject_agents:
            decision = "WAIT"
            reason = f"{len(reject_agents)} agent(s) raised concerns"
        elif consensus >= 0.6 and thesis_confidence >= 0.5:
            decision = "BUY" if direction == "long" else "SELL"
            reason = f"Strong consensus ({consensus:.0%}) and thesis ({thesis_confidence:.0%})"
        else:
            decision = "WAIT"
            reason = f"Insufficient consensus ({consensus:.0%}) or thesis strength ({thesis_confidence:.0%})"

        confidence = consensus * 0.6 + thesis_confidence * 0.4

        reasoning = f"CIO Decision for {pair}:\n"
        reasoning += f"Bullish agents: {bullish_agents}\n"
        reasoning += f"Bearish agents: {bearish_agents}\n"
        reasoning += f"Neutral agents: {neutral_agents}\n"
        reasoning += f"Rejected by: {reject_agents}\n"
        reasoning += f"Consensus: {consensus:.0%}\n"
        reasoning += f"Decision: {decision} — {reason}"

        return AgentReport(
            agent_name=self.name,
            signal=decision,
            confidence=confidence,
            data={
                "decision": decision,
                "pair": pair,
                "direction": direction,
                "consensus": consensus,
                "bullish_count": len(bullish_agents),
                "bearish_count": len(bearish_agents),
                "reason": reason,
            },
            reasoning=reasoning,
        )
