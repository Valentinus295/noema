"""Candlestick pattern detection."""

from typing import Sequence, Optional

Pattern = Optional[str]


def detect_pattern(bars: Sequence, lookback: int = 3) -> Pattern:
    if len(bars) < lookback:
        return None

    recent = bars[-lookback:]

    if len(recent) >= 2:
        curr = recent[-1]
        prev = recent[-2]

        if curr.open < curr.close and prev.open > prev.close:
            if curr.close > prev.open and curr.open < prev.close:
                return "bullish_engulfing"

        if curr.open > curr.close and prev.open < prev.close:
            if curr.close < prev.open and curr.open > prev.close:
                return "bearish_engulfing"

    if len(recent) >= 3:
        curr = recent[-1]
        prev1 = recent[-2]
        prev2 = recent[-3]

        if curr.close > curr.open and curr.close > prev1.high and prev1.close < prev1.open:
            if prev2.close > prev2.open:
                return "morning_star"

        if curr.close < curr.open and curr.close < prev1.low and prev1.close > prev1.open:
            if prev2.close < prev2.open:
                return "evening_star"

    if len(recent) >= 1:
        curr = recent[-1]
        body = abs(curr.close - curr.open)
        wick = curr.high - curr.low

        if body > 0 and wick > 3 * body:
            if curr.close < curr.open:
                return "hammer"
            elif curr.close > curr.open:
                return "shooting_star"

    return None
