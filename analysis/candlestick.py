"""Candlestick pattern detection for VMPM.

Detects key reversal patterns for trade confirmation:
- Bullish: Engulfing, Morning Star, Hammer, Tweezers
- Bearish: Engulfing, Evening Star, Shooting Star, Tweezers
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CandlestickPattern:
    """A detected candlestick pattern."""
    name: str
    type: str           # "bullish" or "bearish"
    index: int          # Candle index where pattern completes
    strength: float     # 0-1
    description: str = ""


@dataclass
class CandlestickReport:
    """Output from candlestick analysis."""
    patterns: list[CandlestickPattern]
    confirmation: str = "NONE"      # BULLISH, BEARISH, NONE
    reasoning: str = ""
    confidence: float = 0.0


class CandlestickDetector:
    """Detects candlestick reversal patterns.

    Each pattern requires specific candle relationships:
    - Body size relative to wicks
    - Open/close relationships between consecutive candles
    - Position within the price range
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="candlestick")

    def detect_all(self, df: pd.DataFrame) -> CandlestickReport:
        """Detect all candlestick patterns in OHLCV data."""
        patterns: list[CandlestickPattern] = []

        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        # Check last 5 candles for patterns
        start = max(0, len(df) - 5)

        for i in range(start + 2, len(df)):
            # --- Bullish Patterns ---
            if self._is_bullish_engulfing(opens, closes, i):
                patterns.append(CandlestickPattern(
                    name="Bullish Engulfing",
                    type="bullish",
                    index=i,
                    strength=0.85,
                    description="Current bullish candle completely engulfs previous bearish candle",
                ))

            if self._is_morning_star(opens, highs, lows, closes, i):
                patterns.append(CandlestickPattern(
                    name="Morning Star",
                    type="bullish",
                    index=i,
                    strength=0.90,
                    description="Three-candle reversal: bearish, small body, bullish",
                ))

            if self._is_hammer(opens, highs, lows, closes, i):
                patterns.append(CandlestickPattern(
                    name="Hammer",
                    type="bullish",
                    index=i,
                    strength=0.70,
                    description="Small body at top with long lower wick",
                ))

            if self._is_bullish_tweezers(opens, lows, i):
                patterns.append(CandlestickPattern(
                    name="Bullish Tweezers",
                    type="bullish",
                    index=i,
                    strength=0.65,
                    description="Two candles with matching lows at support",
                ))

            # --- Bearish Patterns ---
            if self._is_bearish_engulfing(opens, closes, i):
                patterns.append(CandlestickPattern(
                    name="Bearish Engulfing",
                    type="bearish",
                    index=i,
                    strength=0.85,
                    description="Current bearish candle completely engulfs previous bullish candle",
                ))

            if self._is_evening_star(opens, highs, lows, closes, i):
                patterns.append(CandlestickPattern(
                    name="Evening Star",
                    type="bearish",
                    index=i,
                    strength=0.90,
                    description="Three-candle reversal: bullish, small body, bearish",
                ))

            if self._is_shooting_star(opens, highs, lows, closes, i):
                patterns.append(CandlestickPattern(
                    name="Shooting Star",
                    type="bearish",
                    index=i,
                    strength=0.70,
                    description="Small body at bottom with long upper wick",
                ))

            if self._is_bearish_tweezers(opens, highs, i):
                patterns.append(CandlestickPattern(
                    name="Bearish Tweezers",
                    type="bearish",
                    index=i,
                    strength=0.65,
                    description="Two candles with matching highs at resistance",
                ))

        # Determine overall confirmation
        bullish = [p for p in patterns if p.type == "bullish"]
        bearish = [p for p in patterns if p.type == "bearish"]

        if bullish and not bearish:
            confirmation = "BULLISH"
            confidence = max(p.strength for p in bullish)
        elif bearish and not bullish:
            confirmation = "BEARISH"
            confidence = max(p.strength for p in bearish)
        elif bullish and bearish:
            # Conflicting signals — take the stronger one
            if bullish[-1].strength > bearish[-1].strength:
                confirmation = "BULLISH"
                confidence = bullish[-1].strength * 0.7  # Reduced for conflict
            else:
                confirmation = "BEARISH"
                confidence = bearish[-1].strength * 0.7
        else:
            confirmation = "NONE"
            confidence = 0.0

        reasoning = self._build_reasoning(patterns, confirmation)

        return CandlestickReport(
            patterns=patterns,
            confirmation=confirmation,
            reasoning=reasoning,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Bullish Pattern Detectors
    # ------------------------------------------------------------------

    def _is_bullish_engulfing(self, opens: np.ndarray, closes: np.ndarray, i: int) -> bool:
        """Bullish Engulfing: Previous candle bearish, current candle bullish and engulfs."""
        if i < 1:
            return False
        prev_bearish = closes[i-1] < opens[i-1]
        curr_bullish = closes[i] > opens[i]
        engulfs = opens[i] <= closes[i-1] and closes[i] >= opens[i-1]
        return prev_bearish and curr_bullish and engulfs

    def _is_morning_star(
        self, opens: np.ndarray, highs: np.ndarray,
        lows: np.ndarray, closes: np.ndarray, i: int
    ) -> bool:
        """Morning Star: 3-candle bullish reversal."""
        if i < 2:
            return False
        # First: strong bearish
        first_bearish = closes[i-2] < opens[i-2]
        first_body = abs(closes[i-2] - opens[i-2])
        # Second: small body (star)
        second_body = abs(closes[i-1] - opens[i-1])
        avg_body = (abs(closes[i-2] - opens[i-2]) + abs(closes[i] - opens[i])) / 2
        is_star = second_body < avg_body * 0.3
        # Third: strong bullish closing above first body midpoint
        third_bullish = closes[i] > opens[i]
        third_closes_above = closes[i] > (opens[i-2] + closes[i-2]) / 2
        return first_bearish and is_star and third_bullish and third_closes_above

    def _is_hammer(
        self, opens: np.ndarray, highs: np.ndarray,
        lows: np.ndarray, closes: np.ndarray, i: int
    ) -> bool:
        """Hammer: Small body at top, long lower wick."""
        body = abs(closes[i] - opens[i])
        upper_wick = highs[i] - max(opens[i], closes[i])
        lower_wick = min(opens[i], closes[i]) - lows[i]
        total_range = highs[i] - lows[i]
        if total_range == 0:
            return False
        return (
            lower_wick > body * 2 and
            upper_wick < body * 0.5 and
            body / total_range < 0.3
        )

    def _is_bullish_tweezers(self, opens: np.ndarray, lows: np.ndarray, i: int) -> bool:
        """Bullish Tweezers: Two candles with matching lows."""
        if i < 1:
            return False
        tolerance = abs(lows[i]) * 0.0005  # 0.05% tolerance
        return abs(lows[i] - lows[i-1]) < tolerance

    # ------------------------------------------------------------------
    # Bearish Pattern Detectors
    # ------------------------------------------------------------------

    def _is_bearish_engulfing(self, opens: np.ndarray, closes: np.ndarray, i: int) -> bool:
        """Bearish Engulfing: Previous candle bullish, current candle bearish and engulfs."""
        if i < 1:
            return False
        prev_bullish = closes[i-1] > opens[i-1]
        curr_bearish = closes[i] < opens[i]
        engulfs = opens[i] >= closes[i-1] and closes[i] <= opens[i-1]
        return prev_bullish and curr_bearish and engulfs

    def _is_evening_star(
        self, opens: np.ndarray, highs: np.ndarray,
        lows: np.ndarray, closes: np.ndarray, i: int
    ) -> bool:
        """Evening Star: 3-candle bearish reversal."""
        if i < 2:
            return False
        first_bullish = closes[i-2] > opens[i-2]
        second_body = abs(closes[i-1] - opens[i-1])
        avg_body = (abs(closes[i-2] - opens[i-2]) + abs(closes[i] - opens[i])) / 2
        is_star = second_body < avg_body * 0.3
        third_bearish = closes[i] < opens[i]
        third_closes_below = closes[i] < (opens[i-2] + closes[i-2]) / 2
        return first_bullish and is_star and third_bearish and third_closes_below

    def _is_shooting_star(
        self, opens: np.ndarray, highs: np.ndarray,
        lows: np.ndarray, closes: np.ndarray, i: int
    ) -> bool:
        """Shooting Star: Small body at bottom, long upper wick."""
        body = abs(closes[i] - opens[i])
        upper_wick = highs[i] - max(opens[i], closes[i])
        lower_wick = min(opens[i], closes[i]) - lows[i]
        total_range = highs[i] - lows[i]
        if total_range == 0:
            return False
        return (
            upper_wick > body * 2 and
            lower_wick < body * 0.5 and
            body / total_range < 0.3
        )

    def _is_bearish_tweezers(self, opens: np.ndarray, highs: np.ndarray, i: int) -> bool:
        """Bearish Tweezers: Two candles with matching highs."""
        if i < 1:
            return False
        tolerance = abs(highs[i]) * 0.0005
        return abs(highs[i] - highs[i-1]) < tolerance

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_reasoning(self, patterns: list[CandlestickPattern], confirmation: str) -> str:
        if not patterns:
            return "No candlestick patterns detected in recent candles"

        parts = [f"Overall confirmation: {confirmation}"]
        for p in patterns[-3:]:
            parts.append(f"  {p.name} ({p.type}) @ candle {p.index} — strength {p.strength:.2f}")
            parts.append(f"    {p.description}")
        return "\n".join(parts)
