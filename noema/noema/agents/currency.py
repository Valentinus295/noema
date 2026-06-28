"""Currency Strength Agent — ranks currencies by relative strength.

Uses econometric analysis to rank currencies and identify
the strongest/weakest pairs for trading.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

from noema.core.modern_agent import DeterministicAgent, AgentReport
from noema.core.registry import AgentRegistry

logger = structlog.get_logger(__name__)


@AgentRegistry.register("currency-strength", layer="data")
class CurrencyStrengthAgent(DeterministicAgent):
    """Agent #3 — Ranks currencies by relative strength.

    Answers: Which currency should we buy? Which should we sell?
    Which pair has the biggest imbalance?
    """

    name = "currency-strength"
    role = "Currency Strength Analyst"
    priority = 9

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Calculate currency strength scores from price data and fundamentals."""
        prices: dict[str, pd.DataFrame] = context.get("prices", {})
        fundamental_scores: dict[str, float] = context.get("fundamental_scores", {})

        # Calculate technical strength from price momentum
        technical_scores = self._calculate_technical_strength(prices)

        # Combine fundamental + technical
        combined = {}
        all_currencies = set(list(technical_scores.keys()) + list(fundamental_scores.keys()))
        for curr in all_currencies:
            tech = technical_scores.get(curr, 0.0)
            fund = fundamental_scores.get(curr, 0.0)
            combined[curr] = 0.5 * tech + 0.5 * fund

        # Rank
        sorted_currencies = sorted(combined.items(), key=lambda x: x[1], reverse=True)

        # Identify best pairs
        strongest = sorted_currencies[0] if sorted_currencies else ("N/A", 0)
        weakest = sorted_currencies[-1] if sorted_currencies else ("N/A", 0)

        best_pair = f"{strongest[0]}{weakest[0]}" if strongest[0] != weakest[0] else "N/A"

        signal = "BULLISH" if strongest[1] > 2 else "BEARISH" if weakest[1] < -2 else "NEUTRAL"

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=min(1.0, abs(strongest[1] - weakest[1]) / 10),
            data={
                "currency_scores": combined,
                "ranking": sorted_currencies,
                "strongest": strongest[0],
                "weakest": weakest[0],
                "best_pair": best_pair,
            },
            reasoning=self._build_reasoning(sorted_currencies, best_pair),
        )

    def _calculate_technical_strength(self, prices: dict[str, pd.DataFrame]) -> dict[str, float]:
        """Calculate technical strength from price momentum."""
        scores: dict[str, float] = {}
        # Extract unique currencies from pair names
        pairs = list(prices.keys())
        currencies = set()
        for pair in pairs:
            if len(pair) == 6:
                currencies.add(pair[:3])
                currencies.add(pair[3:])

        for pair, df in prices.items():
            if df is None or len(df) < 20:
                continue
            if len(pair) != 6:
                continue

            base = pair[:3]
            quote = pair[3:]

            # Momentum: 20-period return
            returns = df["close"].pct_change().tail(20).mean()
            # Volatility-adjusted momentum
            vol = df["close"].pct_change().tail(20).std()
            score = (returns / vol * np.sqrt(252)) if vol > 0 else 0

            scores[base] = scores.get(base, 0.0) + score
            scores[quote] = scores.get(quote, 0.0) - score

        return scores

    def _build_reasoning(self, ranking: list, best_pair: str) -> str:
        parts = ["Currency Strength Ranking:"]
        for curr, score in ranking:
            bar = "+" * int(abs(score)) if score > 0 else "-" * int(abs(score))
            parts.append(f"  {curr}: {score:+.2f} [{bar}]")
        if best_pair != "N/A":
            parts.append(f"\nRecommended pair: {best_pair}")
        return "\n".join(parts)
