"""Support & Resistance Agent — maps reaction zones.

Maps Asian, Daily, Weekly, Monthly, Yearly highs/lows as S/R zones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog

from vmpm.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


@dataclass
class Zone:
    """A support or resistance zone."""
    name: str
    type: str       # "support" or "resistance"
    level: float
    strength: int   # How many touches
    timeframe: str


class SupportResistanceAgent(DeterministicAgent):
    """Agent #6 — Maps reaction zones.

    Buy Areas: Asian Low, Daily Low, Weekly Low, Monthly Low, etc.
    Sell Areas: Asian High, Daily High, Weekly High, Monthly High, etc.
    """

    name = "support-resistance"
    role = "Support & Resistance Mapper"
    priority = 6

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Map S/R zones from multi-timeframe OHLCV data."""
        prices: dict[str, pd.DataFrame] = context.get("prices", {})
        pair: str = context.get("pair", "EURUSD")

        df = prices.get(pair)
        if df is None or len(df) < 20:
            return AgentReport(agent_name=self.name, signal="NEUTRAL", reasoning="No data")

        buy_zones: list[Zone] = []
        sell_zones: list[Zone] = []

        # Daily levels
        daily_low = float(df["low"].min())
        daily_high = float(df["high"].max())
        buy_zones.append(Zone("Daily Low", "support", daily_low, 1, "D1"))
        sell_zones.append(Zone("Daily High", "resistance", daily_high, 1, "D1"))

        # Weekly levels
        if "W1" in prices:
            wdf = prices["W1"]
            buy_zones.append(Zone("Weekly Low", "support", float(wdf["low"].min()), 1, "W1"))
            sell_zones.append(Zone("Weekly High", "resistance", float(wdf["high"].max()), 1, "W1"))

        # Monthly levels
        if "MN1" in prices:
            mdf = prices["MN1"]
            buy_zones.append(Zone("Monthly Low", "support", float(mdf["low"].min()), 1, "MN1"))
            sell_zones.append(Zone("Monthly High", "resistance", float(mdf["high"].max()), 1, "MN1"))

        # Asian session levels (00:00-09:00 EAT)
        asian_session = self._get_asian_session(df)
        if asian_session is not None:
            buy_zones.append(Zone("Asian Low", "support", float(asian_session["low"].min()), 1, "ASIA"))
            sell_zones.append(Zone("Asian High", "resistance", float(asian_session["high"].max()), 1, "ASIA"))

        # Current price
        current_price = float(df["close"].iloc[-1])

        # Find nearest zones
        nearest_support = max(
            [z for z in buy_zones if z.level < current_price],
            key=lambda z: z.level,
            default=None,
        )
        nearest_resistance = min(
            [z for z in sell_zones if z.level > current_price],
            key=lambda z: z.level,
            default=None,
        )

        signal = "NEUTRAL"
        if nearest_support and nearest_resistance:
            dist_support = current_price - nearest_support.level
            dist_resistance = nearest_resistance.level - current_price
            if dist_support < dist_resistance:
                signal = "BULLISH"  # Closer to support
            else:
                signal = "BEARISH"  # Closer to resistance

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=0.6 if signal != "NEUTRAL" else 0.3,
            data={
                "buy_zones": [{"name": z.name, "level": z.level, "tf": z.timeframe} for z in buy_zones],
                "sell_zones": [{"name": z.name, "level": z.level, "tf": z.timeframe} for z in sell_zones],
                "nearest_support": {"name": nearest_support.name, "level": nearest_support.level} if nearest_support else None,
                "nearest_resistance": {"name": nearest_resistance.name, "level": nearest_resistance.level} if nearest_resistance else None,
                "current_price": current_price,
            },
            reasoning=f"Price {current_price:.5f}. Nearest support: {nearest_support.name if nearest_support else 'N/A'} @ {nearest_support.level if nearest_support else 'N/A'}. Nearest resistance: {nearest_resistance.name if nearest_resistance else 'N/A'} @ {nearest_resistance.level if nearest_resistance else 'N/A'}.",
        )

    def _get_asian_session(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Extract Asian session candles (00:00-09:00 EAT)."""
        try:
            if "time" in df.columns:
                times = pd.to_datetime(df["time"])
                mask = (times.dt.hour >= 0) & (times.dt.hour < 9)
                return df[mask] if mask.any() else None
        except Exception:
            pass
        return None
