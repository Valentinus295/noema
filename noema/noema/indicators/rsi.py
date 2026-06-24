"""RSI indicator."""

from typing import Sequence
import math


def rsi(bars: Sequence, period: int = 14) -> float:
    if len(bars) < period + 1:
        return 50.0

    closes = [b.close for b in bars]
    gains = []
    losses = []

    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(delta if delta > 0 else 0)
        losses.append(-delta if delta < 0 else 0)

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
