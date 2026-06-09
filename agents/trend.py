"""TrendAgent — D1/H4/H1 trend via MA(50)/MA(200) + HH/HL or LH/LL.

Contract pinned in docs/ARCHITECTURE.md §1.
Input: OHLCV bars per timeframe. Output: TrendVerdict(direction, strength).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from vmpm.core.types import Bar, Direction, Timeframe, Verdict


@dataclass(frozen=True, slots=True)
class TrendSignal:
    direction: Direction
    strength: float
    justification: str


def _compute_ma(bars: Sequence[Bar], period: int) -> float:
    if len(bars) < period:
        raise ValueError(f"Need {period} bars for MA({period})")
    return sum(b.close for b in bars[-period:]) / period


def _is_bullish_trend(bars: Sequence[Bar], tf: Timeframe) -> tuple[bool, float, str]:
    if len(bars) < 200:
        return False, 0.0, "Insufficient data"

    ma50 = _compute_ma(bars, 50)
    ma200 = _compute_ma(bars, 200)

    if ma50 <= ma200:
        return False, 0.0, "MA(50) not above MA(200)"

    closes = [b.close for b in bars[-50:]]
    highs = [b.high for b in bars[-50:]]
    lows = [b.low for b in bars[-50:]]

    higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
    higher_lows = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])

    strength = (higher_highs * 0.5 + higher_lows * 0.5) / 50
    strength = min(1.0, max(0.0, strength))

    return True, strength, f"HH: {higher_highs}/50, HL: {higher_lows}/50"


def _is_bearish_trend(bars: Sequence[Bar], tf: Timeframe) -> tuple[bool, float, str]:
    if len(bars) < 200:
        return False, 0.0, "Insufficient data"

    ma50 = _compute_ma(bars, 50)
    ma200 = _compute_ma(bars, 200)

    if ma50 >= ma200:
        return False, 0.0, "MA(50) not below MA(200)"

    closes = [b.close for b in bars[-50:]]
    highs = [b.high for b in bars[-50:]]
    lows = [b.low for b in bars[-50:]]

    lower_highs = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
    lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

    strength = (lower_highs * 0.5 + lower_lows * 0.5) / 50
    strength = min(1.0, max(0.0, strength))

    return True, strength, f"LH: {lower_highs}/50, LL: {lower_lows}/50"


def analyze_trend(symbol: str, bars_by_tf: dict[Timeframe, Sequence[Bar]]) -> Verdict:
    verdicts: list[Verdict] = []

    for tf in (Timeframe("D1"), Timeframe("H4"), Timeframe("H1")):
        bars = bars_by_tf.get(tf, [])
        if not bars:
            continue

        bullish, bull_strength, bull_just = _is_bullish_trend(bars, tf)
        bearish, bear_strength, bear_just = _is_bearish_trend(bars, tf)

        if bullish:
            verdicts.append(
                Verdict(
                    agent="TrendAgent",
                    symbol=symbol,
                    timeframe=tf,
                    direction=Direction("bullish"),
                    strength=bull_strength,
                    rationale=bull_just,
                )
            )
        elif bearish:
            verdicts.append(
                Verdict(
                    agent="TrendAgent",
                    symbol=symbol,
                    timeframe=tf,
                    direction=Direction("bearish"),
                    strength=bear_strength,
                    rationale=bear_just,
                )
            )
        else:
            verdicts.append(
                Verdict(
                    agent="TrendAgent",
                    symbol=symbol,
                    timeframe=tf,
                    direction=Direction("neutral"),
                    strength=0.0,
                    rationale="No clear trend",
                )
            )

    primary = (
        verdicts[0]
        if verdicts
        else Verdict(
            agent="TrendAgent",
            symbol=symbol,
            timeframe=Timeframe("H1"),
            direction=Direction("neutral"),
            strength=0.0,
            rationale="No data",
        )
    )

    return primary
