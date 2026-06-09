"""Momentum Agent — measures exhaustion and momentum.

Uses RSI, MACD, and custom momentum metrics to detect
overbought/oversold conditions and divergence.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

from vmpm.analysis.technical import TechnicalAnalyzer
from vmpm.core.agent import Agent, AgentReport

logger = structlog.get_logger(__name__)


class MomentumAgent(Agent):
    """Agent #9 — Measures exhaustion.

    Uses: RSI, MACD, Momentum metrics.
    Answers: Are buyers exhausted? Are sellers exhausted?
    """

    name = "momentum"
    role = "Momentum Analyst"
    priority = 4

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.technical = TechnicalAnalyzer(self.config)

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Analyze momentum indicators for exhaustion signals."""
        df: pd.DataFrame = context.get("price_data")
        if df is None or len(df) < 30:
            return AgentReport(agent_name=self.name, signal="NEUTRAL", reasoning="Insufficient data")

        # Calculate indicators
        report = self.technical.analyze(df)

        # Detect divergence
        divergence = self._detect_divergence(df)

        signal = "NEUTRAL"
        if report.rsi_signal == "OVERSOLD":
            signal = "BULLISH"
        elif report.rsi_signal == "OVERBOUGHT":
            signal = "BEARISH"

        # Divergence overrides
        if divergence["bullish_divergence"]:
            signal = "BULLISH"
        elif divergence["bearish_divergence"]:
            signal = "BEARISH"

        confidence = 0.0
        if report.rsi_signal != "NEUTRAL":
            confidence += 0.3
        if abs(report.macd_histogram) > 0:
            confidence += 0.2
        if divergence["bullish_divergence"] or divergence["bearish_divergence"]:
            confidence += 0.3
        if report.adx > 25:
            confidence += 0.1

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=min(1.0, confidence),
            data={
                "rsi": report.rsi,
                "rsi_signal": report.rsi_signal,
                "macd": report.macd,
                "macd_signal": report.macd_signal_line,
                "macd_histogram": report.macd_histogram,
                "adx": report.adx,
                "divergence": divergence,
            },
            reasoning=f"RSI: {report.rsi:.1f} ({report.rsi_signal}). "
                      f"MACD Hist: {report.macd_histogram:.5f}. "
                      f"ADX: {report.adx:.1f}. "
                      f"Bullish div: {divergence['bullish_divergence']}. "
                      f"Bearish div: {divergence['bearish_divergence']}.",
        )

    def _detect_divergence(self, df: pd.DataFrame, lookback: int = 30) -> dict[str, bool]:
        """Detect RSI divergence with price."""
        if len(df) < lookback:
            return {"bullish_divergence": False, "bearish_divergence": False}

        prices = df["close"].tail(lookback).values

        # Simple RSI calculation
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).dropna().tail(lookback).values

        if len(rsi) < 10:
            return {"bullish_divergence": False, "bearish_divergence": False}

        # Find swing lows for bullish divergence
        price_lows = []
        rsi_lows = []
        for i in range(2, len(prices) - 2):
            if prices[i] < prices[i-1] and prices[i] < prices[i+1]:
                price_lows.append((i, prices[i]))
                if i < len(rsi):
                    rsi_lows.append((i, rsi[i]))

        # Bullish divergence: price makes lower low, RSI makes higher low
        bullish = False
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            if price_lows[-1][1] < price_lows[-2][1] and rsi_lows[-1][1] > rsi_lows[-2][1]:
                bullish = True

        # Find swing highs for bearish divergence
        price_highs = []
        rsi_highs = []
        for i in range(2, len(prices) - 2):
            if prices[i] > prices[i-1] and prices[i] > prices[i+1]:
                price_highs.append((i, prices[i]))
                if i < len(rsi):
                    rsi_highs.append((i, rsi[i]))

        bearish = False
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            if price_highs[-1][1] > price_highs[-2][1] and rsi_highs[-1][1] < rsi_highs[-2][1]:
                bearish = True

        return {"bullish_divergence": bullish, "bearish_divergence": bearish}
