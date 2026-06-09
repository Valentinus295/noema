"""MACD indicator."""

from typing import Sequence, Tuple


def macd(
    bars: Sequence, fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[float, float, float]:
    if len(bars) < slow + signal:
        return 0.0, 0.0, 0.0

    closes = [b.close for b in bars]

    def _ema(values: list, period: int) -> list:
        k = 2 / (period + 1)
        ema = [values[0]]
        for i in range(1, len(values)):
            ema.append(k * values[i] + (1 - k) * ema[-1])
        return ema

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
    signal_line = _ema(macd_line, signal)
    histogram = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]

    return macd_line[-1], signal_line[-1], histogram[-1]
