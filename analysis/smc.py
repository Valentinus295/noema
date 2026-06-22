"""Smart Money Concepts (SMC) analysis for VMPM.

Custom implementations for institutional trading concepts:
- Order Blocks (Bullish & Bearish)
- Fair Value Gaps (FVG)
- Liquidity Sweeps
- Break of Structure (BOS)
- Change of Character (CHoCH)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class OrderBlock:
    """Represents a detected order block."""
    type: str               # "bullish" or "bearish"
    high: float
    low: float
    midpoint: float
    index: int
    validated: bool = False
    strength: float = 0.0   # 0-1


@dataclass
class FairValueGap:
    """Represents a detected Fair Value Gap."""
    type: str               # "bullish" or "bearish"
    high: float
    low: float
    midpoint: float
    index: int
    filled: bool = False


@dataclass
class LiquiditySweep:
    """Represents a detected liquidity sweep."""
    type: str               # "buy_side" or "sell_side"
    level: float
    sweep_high: float
    sweep_low: float
    index: int
    displacement: float     # How much price moved after sweep


@dataclass
class SMCReport:
    """Output from SMC analysis."""
    order_blocks: list[OrderBlock] = field(default_factory=list)
    fair_value_gaps: list[FairValueGap] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)
    bos_detected: bool = False
    choch_detected: bool = False
    bos_direction: str = "none"
    reasoning: str = ""
    confidence: float = 0.0


class SMCForecaster:
    """Smart Money Concepts analyzer.

    Detects institutional footprints in price action:
    - Order Blocks: Last opposing candle before impulsive move
    - FVGs: 3-candle gaps where one candle's range doesn't overlap
    - Liquidity Sweeps: Price taking out highs/lows then reversing
    - BOS/CHoCH: Structure breaks
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="smc")

    # ------------------------------------------------------------------
    # Order Block Detection
    # ------------------------------------------------------------------

    def detect_order_blocks(
        self, df: pd.DataFrame, lookback: int = 20, min_impulse: float = 1.5
    ) -> list[OrderBlock]:
        """Detect Order Blocks — last opposing candle before impulsive move.

        Bullish OB: Last bearish candle before bullish impulse that breaks structure.
        Bearish OB: Last bullish candle before bearish impulse that breaks structure.
        """
        if df is None or df.empty or len(df) < lookback + 3:
            return []
        order_blocks: list[OrderBlock] = []
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        opens = df["open"].values

        for i in range(lookback, len(df) - 3):
            # Calculate ATR for impulse threshold
            recent_range = highs[i-lookback:i+1] - lows[i-lookback:i+1]
            avg_range = np.mean(recent_range) if len(recent_range) > 0 else 1.0

            # Bullish OB: bearish candle followed by strong bullish move
            if opens[i] > closes[i]:  # Bearish candle
                # Check for bullish impulse (3+ candles up)
                impulse = closes[i+3] - closes[i] if i+3 < len(df) else 0
                if impulse > avg_range * min_impulse:
                    ob = OrderBlock(
                        type="bullish",
                        high=opens[i],  # Body high
                        low=closes[i],  # Body low
                        midpoint=(opens[i] + closes[i]) / 2,
                        index=i,
                        strength=min(1.0, impulse / (avg_range * 3)),
                    )
                    order_blocks.append(ob)

            # Bearish OB: bullish candle followed by strong bearish move
            elif closes[i] > opens[i]:  # Bullish candle
                impulse = closes[i] - closes[i+3] if i+3 < len(df) else 0
                if impulse > avg_range * min_impulse:
                    ob = OrderBlock(
                        type="bearish",
                        high=closes[i],  # Body high
                        low=opens[i],    # Body low
                        midpoint=(closes[i] + opens[i]) / 2,
                        index=i,
                        strength=min(1.0, impulse / (avg_range * 3)),
                    )
                    order_blocks.append(ob)

        return order_blocks[-10:]  # Return most recent 10

    # ------------------------------------------------------------------
    # Fair Value Gap Detection
    # ------------------------------------------------------------------

    def detect_fvg(self, df: pd.DataFrame, min_gap_pct: float = 0.001) -> list[FairValueGap]:
        """Detect Fair Value Gaps — 3-candle gaps in price.

        Bullish FVG: Low of candle 3 > High of candle 1 (gap up)
        Bearish FVG: High of candle 3 < Low of candle 1 (gap down)
        """
        fvgs: list[FairValueGap] = []
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        for i in range(2, len(df)):
            price = closes[i]
            min_gap = price * min_gap_pct

            # Bullish FVG: gap between candle 1 high and candle 3 low
            if lows[i] > highs[i-2] and (lows[i] - highs[i-2]) > min_gap:
                fvg = FairValueGap(
                    type="bullish",
                    high=lows[i],
                    low=highs[i-2],
                    midpoint=(lows[i] + highs[i-2]) / 2,
                    index=i-1,  # Middle candle
                )
                fvgs.append(fvg)

            # Bearish FVG: gap between candle 3 high and candle 1 low
            elif highs[i] < lows[i-2] and (lows[i-2] - highs[i]) > min_gap:
                fvg = FairValueGap(
                    type="bearish",
                    high=lows[i-2],
                    low=highs[i],
                    midpoint=(lows[i-2] + highs[i]) / 2,
                    index=i-1,
                )
                fvgs.append(fvg)

        # Check which FVGs have been filled
        current_price = closes[-1]
        for fvg in fvgs:
            if fvg.type == "bullish" and current_price <= fvg.low:
                fvg.filled = True
            elif fvg.type == "bearish" and current_price >= fvg.high:
                fvg.filled = True

        return [f for f in fvgs if not f.filled][-8:]  # Return unfilled recent FVGs

    # ------------------------------------------------------------------
    # Liquidity Sweep Detection
    # ------------------------------------------------------------------

    def detect_liquidity_sweeps(
        self, df: pd.DataFrame, lookback: int = 20
    ) -> list[LiquiditySweep]:
        """Detect liquidity sweeps — price taking out highs/lows then reversing.

        Buy-side sweep: Price spikes above recent high, then closes below.
        Sell-side sweep: Price spikes below recent low, then closes above.
        """
        sweeps: list[LiquiditySweep] = []
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        for i in range(lookback, len(df)):
            # Find recent swing high/low
            recent_high = np.max(highs[i-lookback:i])
            recent_low = np.min(lows[i-lookback:i])

            # Buy-side sweep: wick above high but close below
            if highs[i] > recent_high and closes[i] < recent_high:
                displacement = recent_high - lows[i]
                sweep = LiquiditySweep(
                    type="buy_side",
                    level=recent_high,
                    sweep_high=highs[i],
                    sweep_low=lows[i],
                    index=i,
                    displacement=displacement,
                )
                sweeps.append(sweep)

            # Sell-side sweep: wick below low but close above
            if lows[i] < recent_low and closes[i] > recent_low:
                displacement = highs[i] - recent_low
                sweep = LiquiditySweep(
                    type="sell_side",
                    level=recent_low,
                    sweep_high=highs[i],
                    sweep_low=lows[i],
                    index=i,
                    displacement=displacement,
                )
                sweeps.append(sweep)

        return sweeps[-5:]  # Return most recent 5

    # ------------------------------------------------------------------
    # Break of Structure / Change of Character
    # ------------------------------------------------------------------

    def detect_structure_breaks(
        self, df: pd.DataFrame, lookback: int = 20
    ) -> dict[str, Any]:
        """Detect BOS (Break of Structure) and CHoCH (Change of Character)."""
        structure = self._find_swings(df, lookback)

        swing_highs = structure["highs"]
        swing_lows = structure["lows"]

        bos_detected = False
        choch_detected = False
        bos_direction = "none"

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            current_price = df["close"].iloc[-1]

            # BOS: Price breaks above previous swing high in uptrend
            if current_price > swing_highs[-1]:
                bos_detected = True
                bos_direction = "bullish"

            # BOS: Price breaks below previous swing low in downtrend
            elif current_price < swing_lows[-1]:
                bos_detected = True
                bos_direction = "bearish"

            # CHoCH: Trend reversal — break of structure in opposite direction
            prev_trend = "bullish" if swing_highs[-1] > swing_highs[-2] else "bearish"
            if prev_trend == "bullish" and current_price < swing_lows[-1]:
                choch_detected = True
                bos_direction = "bearish"
            elif prev_trend == "bearish" and current_price > swing_highs[-1]:
                choch_detected = True
                bos_direction = "bullish"

        return {
            "bos_detected": bos_detected,
            "choch_detected": choch_detected,
            "bos_direction": bos_direction,
            "swing_highs": swing_highs[-4:],
            "swing_lows": swing_lows[-4:],
        }

    # ------------------------------------------------------------------
    # Full Analysis
    # ------------------------------------------------------------------

    def analyze(self, df: pd.DataFrame) -> SMCReport:
        """Run complete SMC analysis on OHLCV data."""
        order_blocks = self.detect_order_blocks(df)
        fvgs = self.detect_fvg(df)
        sweeps = self.detect_liquidity_sweeps(df)
        structure = self.detect_structure_breaks(df)

        # Confidence based on confluence
        confidence = 0.0
        if order_blocks:
            confidence += 0.25
        if fvgs:
            confidence += 0.2
        if sweeps:
            confidence += 0.25
        if structure["bos_detected"]:
            confidence += 0.15
        if structure["choch_detected"]:
            confidence += 0.15

        reasoning = self._build_reasoning(order_blocks, fvgs, sweeps, structure)

        return SMCReport(
            order_blocks=order_blocks,
            fair_value_gaps=fvgs,
            liquidity_sweeps=sweeps,
            bos_detected=structure["bos_detected"],
            choch_detected=structure["choch_detected"],
            bos_direction=structure["bos_direction"],
            reasoning=reasoning,
            confidence=min(1.0, confidence),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_swings(self, df: pd.DataFrame, lookback: int) -> dict[str, list[float]]:
        """Find swing highs and lows."""
        highs = df["high"].values
        lows = df["low"].values

        swing_highs = []
        swing_lows = []

        for i in range(lookback, len(df) - lookback):
            if highs[i] == np.max(highs[i-lookback:i+lookback+1]):
                swing_highs.append(float(highs[i]))
            if lows[i] == np.min(lows[i-lookback:i+lookback+1]):
                swing_lows.append(float(lows[i]))

        return {"highs": swing_highs[-6:], "lows": swing_lows[-6:]}

    def _build_reasoning(
        self,
        order_blocks: list[OrderBlock],
        fvgs: list[FairValueGap],
        sweeps: list[LiquiditySweep],
        structure: dict,
    ) -> str:
        """Build human-readable SMC reasoning."""
        parts = []

        if structure["bos_detected"]:
            parts.append(f"BOS detected: {structure['bos_direction'].upper()}")
        if structure["choch_detected"]:
            parts.append(f"CHoCH detected: {structure['bos_direction'].upper()} — Trend reversal!")

        bullish_obs = [ob for ob in order_blocks if ob.type == "bullish"]
        bearish_obs = [ob for ob in order_blocks if ob.type == "bearish"]
        if bullish_obs:
            parts.append(f"Bullish Order Blocks: {len(bullish_obs)} (nearest @ {bullish_obs[-1].midpoint:.5f})")
        if bearish_obs:
            parts.append(f"Bearish Order Blocks: {len(bearish_obs)} (nearest @ {bearish_obs[-1].midpoint:.5f})")

        if fvgs:
            parts.append(f"Unfilled FVGs: {len(fvgs)}")

        if sweeps:
            last_sweep = sweeps[-1]
            parts.append(f"Recent liquidity sweep: {last_sweep.type} @ {last_sweep.level:.5f}")

        return "\n".join(parts) if parts else "No significant SMC patterns detected"
