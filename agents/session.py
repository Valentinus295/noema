"""Session Intelligence Agent — understands market timing.

Tracks Sydney, Tokyo, London, New York sessions and overlaps.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

import structlog

from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)

# EAT = UTC+3
EAT = timezone(timedelta(hours=3))

SESSIONS = {
    "sydney":  {"open": 22, "close": 7},   # EAT
    "tokyo":   {"open": 1, "close": 10},    # EAT
    "london":  {"open": 10, "close": 19},   # EAT
    "new_york": {"open": 15, "close": 24},  # EAT
}

# Overlaps are high-volatility windows
OVERLAPS = {
    "london_ny": {"open": 15, "close": 19},
    "tokyo_london": {"open": 10, "close": 10},  # Brief handover
}


class SessionIntelligenceAgent(Agent):
    """Agent #7 — Understands market timing.

    Answers: Which session is active? When does volatility increase?
    When should we expect reversals?
    """

    name = "session-intelligence"
    role = "Session Intelligence Analyst"
    priority = 5

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Determine current session and trading window quality."""
        now = datetime.now(EAT)
        hour = now.hour

        # Determine active sessions
        active = []
        for name, times in SESSIONS.items():
            o, c = times["open"], times["close"]
            if o < c:
                if o <= hour < c:
                    active.append(name)
            else:  # Wraps midnight
                if hour >= o or hour < c:
                    active.append(name)

        # Check overlaps
        active_overlaps = []
        for name, times in OVERLAPS.items():
            o, c = times["open"], times["close"]
            if o <= hour < c:
                active_overlaps.append(name)

        # Determine probability window
        is_high_prob = len(active_overlaps) > 0 or "london" in active
        is_low_prob = len(active) == 0

        signal = "NEUTRAL"
        confidence = 0.5
        if is_high_prob:
            signal = "BULLISH"  # High probability window = favorable for trading
            confidence = 0.7
        elif is_low_prob:
            signal = "NEUTRAL"
            confidence = 0.3

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data={
                "active_sessions": active,
                "active_overlaps": active_overlaps,
                "is_high_probability": is_high_prob,
                "is_low_probability": is_low_prob,
                "current_hour_eat": hour,
            },
            reasoning=f"Active sessions: {', '.join(active) if active else 'None'}. "
                      f"Overlaps: {', '.join(active_overlaps) if active_overlaps else 'None'}. "
                      f"{'HIGH probability window' if is_high_prob else 'LOW probability window' if is_low_prob else 'Standard window'}.",
        )
