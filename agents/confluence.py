"""ConfluenceAgent — combines verdicts and computes final setup.

Contract pinned in docs/ARCHITECTURE.md §1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from vmpm.core.types import Bar, Bias, Direction, Setup, Timeframe, Verdict
from vmpm.indicators.rsi import rsi
from vmpm.indicators.candlestick import detect_pattern


@dataclass
class ConfluenceState:
    symbol: str
    trend_verdict: Verdict | None = None
    structure_verdict: Verdict | None = None
    fundamental_bias: Bias | None = None
    bars: list[Bar] = field(default_factory=list)
    rsi_value: float = 50.0
    candle_pattern: str | None = None


def _compute_confidence(verdicts: list[Verdict], weights: dict[str, float]) -> float:
    if not verdicts:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0

    for v in verdicts:
        w = weights.get(v.agent, 1.0)
        weighted_sum += v.strength * w
        total_weight += w

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _validate_setup(state: ConfluenceState) -> tuple[bool, str]:
    if not state.trend_verdict or state.trend_verdict.direction == Direction("neutral"):
        return False, "No clear trend"

    if not state.structure_verdict:
        return False, "No structure analysis"

    if state.rsi_value < 30 and state.trend_verdict.direction != Direction("bullish"):
        return False, "RSI oversold but trend not bullish"

    if state.rsi_value > 70 and state.trend_verdict.direction != Direction("bearish"):
        return False, "RSI overbought but trend not bearish"

    return True, "Valid setup"


def conflate(state: ConfluenceState) -> Setup | None:
    if not state.trend_verdict or not state.structure_verdict:
        return None

    valid, reason = _validate_setup(state)
    if not valid:
        return None

    verdicts = [state.trend_verdict, state.structure_verdict]
    weights = {"TrendAgent": 0.4, "StructureAgent": 0.6}
    score = _compute_confidence(verdicts, weights)

    if state.rsi_value < 30:
        score = min(1.0, score + 0.1)
    elif state.rsi_value > 70:
        score = min(1.0, score + 0.1)

    if state.candle_pattern:
        score = min(1.0, score + 0.05)

    direction = state.trend_verdict.direction
    if direction == Direction("neutral"):
        return None

    entry_lo = 0.0
    entry_hi = 0.0
    sl_ref = 0.0
    tp_ref = 0.0

    if state.bars:
        last_close = state.bars[-1].close
        atr = _compute_atr(state.bars)

        if direction == Direction("bullish"):
            entry_lo = last_close - atr * 0.3
            entry_hi = last_close + atr * 0.3
            sl_ref = last_close - atr * 2
            tp_ref = last_close + atr * 4
        else:
            entry_lo = last_close - atr * 0.3
            entry_hi = last_close + atr * 0.3
            sl_ref = last_close + atr * 2
            tp_ref = last_close - atr * 4

    return Setup(
        symbol=state.symbol,
        direction=direction,
        score=score,
        entry_zone_lo=entry_lo,
        entry_zone_hi=entry_hi,
        sl_reference=sl_ref,
        tp_reference=tp_ref,
        components={"trend": 0.0, "structure": 0.0, "rsi": 0.0, "candle": 0.0},
        settings_hash="",
        git_sha="",
        proposed_at_utc=datetime.now(timezone.utc),
    )


def _compute_atr(bars: list[Bar], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    tr_values = []
    for i in range(1, len(bars)):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low - bars[i - 1].close),
        )
        tr_values.append(tr)
    return sum(tr_values[-period:]) / period
