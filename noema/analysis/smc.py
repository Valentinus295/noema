"""Smart Money Concepts (SMC) analysis for Noema.

Enhanced with JARVIS reference patterns:
- Fractal swing detection (JARVIS-style)
- Walk-forward market structure (BOS/CHoCH with StructureEvent tracking)
- Validated order blocks (multiple confirmation criteria)
- FVG detection with mitigation tracking
- Liquidity sweep detection (prior-swing-level penetration)
- Confluence-based entry model (find_setup)

Custom implementations for institutional trading concepts:
- Order Blocks (Bullish & Bearish) with validation
- Fair Value Gaps (FVG) with mitigation state
- Liquidity Sweeps with displacement measurement
- Break of Structure (BOS) & Change of Character (CHoCH)
- Setup entry model requiring sweep + OB + FVG + structure confluence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ======================================================================
# Dataclasses — JARVIS-enhanced type system
# ======================================================================

@dataclass
class Swing:
    """A detected swing point (JARVIS-style fractal detection).

    A swing high requires price to be higher than `lookback` candles
    on each side, and holds the unique maximum at that index.
    """
    type: str              # "high" or "low"
    price: float
    index: int
    timeframe: str = "H1"
    validated: bool = False  # Confirmed by subsequent price action


@dataclass
class StructureEvent:
    """A market structure event (BOS or CHoCH).

    JARVIS walk-forward approach: tracks last swing high/low and detects
    breaks. BOS = trend continuation, CHoCH = potential reversal.
    """
    type: str              # "BOS" or "CHoCH"
    direction: str         # "bullish" or "bearish"
    price: float
    index: int
    broken_swing: Swing    # The swing point that was broken
    confidence: float = 0.0  # 0-1 based on momentum at break


@dataclass
class OrderBlock:
    """Represents a detected order block (JARVIS-enhanced).

    OB = last opposing candle before >=2 consecutive impulsive candles.
    Validated when price respects the zone (bounces off it).
    Invalidated when price closes through the zone.
    """
    type: str               # "bullish" or "bearish"
    high: float
    low: float
    midpoint: float
    index: int
    validated: bool = False
    invalidated: bool = False
    strength: float = 0.0   # 0-1, based on impulse magnitude
    impulse_candles: int = 0  # How many consecutive candles moved after OB
    wick_pct: float = 0.0   # Wick size as % of body (smaller is cleaner)


@dataclass
class FairValueGap:
    """Represents a detected Fair Value Gap (JARVIS-enhanced).

    3-candle imbalance: bullish = low[i+1] > high[i-1].
    Mitigation state tracks whether price has revisited the gap.
    """
    type: str               # "bullish" or "bearish"
    high: float
    low: float
    midpoint: float
    index: int
    filled: bool = False
    mitigated: bool = False  # Price touched the gap zone (even partially)
    gap_size_pct: float = 0.0  # Size relative to price


@dataclass
class LiquiditySweep:
    """Represents a detected liquidity sweep (JARVIS-enhanced).

    Price penetrates a prior swing level but closes back on the
    original side within the same candle (rejection). Lookback: 30 bars.
    """
    type: str               # "buy_side" or "sell_side"
    level: float            # The swing level that was swept
    sweep_high: float       # Wick high of sweep candle
    sweep_low: float        # Wick low of sweep candle
    index: int
    displacement: float     # How much price moved after sweep
    sweep_type: str = "simple"  # "simple" or "engineered" (double tap)
    wick_pct: float = 0.0   # How far did the wick penetrate?


@dataclass
class Setup:
    """JARVIS entry model — confluence of sweep + OB + FVG + structure.

    Requires:
    1. Higher-timeframe trend alignment
    2. Structure event (BOS or CHoCH) in entry direction
    3. Liquidity sweep in opposite direction (stop hunt)
    4. Unmitigated order block near current price
    5. Optional but preferred: unmitigated FVG overlapping OB
    """
    direction: str          # "BUY" or "SELL"
    htf_trend: str          # Higher-timeframe trend direction
    structure_event: Optional[StructureEvent] = None
    sweep: Optional[LiquiditySweep] = None
    order_block: Optional[OrderBlock] = None
    fvg: Optional[FairValueGap] = None
    confluence_score: float = 0.0  # 0-5 (number of confirming factors)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    max_distance_pips: float = 20.0  # Max allowed distance from OB to entry
    valid: bool = False
    reasoning: str = ""


@dataclass
class SMCReport:
    """Comprehensive SMC analysis output.

    Expanded from original to include JARVIS-style swing tracking
    and structure event history.
    """
    order_blocks: list[OrderBlock] = field(default_factory=list)
    fair_value_gaps: list[FairValueGap] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)
    swings: list[Swing] = field(default_factory=list)
    structure_events: list[StructureEvent] = field(default_factory=list)
    bos_detected: bool = False
    choch_detected: bool = False
    bos_direction: str = "none"
    current_trend: str = "neutral"  # Current walk-forward trend
    setup: Optional[Setup] = None
    reasoning: str = ""
    confidence: float = 0.0


# ======================================================================
# SMCForecaster — The Enhanced Analyzer
# ======================================================================

class SMCForecaster:
    """Smart Money Concepts analyzer (JARVIS-enhanced).

    Detects institutional footprints in price action:
    - Fractal swing detection (JARVIS-style)
    - Walk-forward market structure with BOS/CHoCH tracking
    - Validated order blocks (multiple criteria)
    - FVGs with mitigation tracking
    - Liquidity sweeps with prior-swing-level penetration
    - Confluence entry model (find_setup)
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="smc")

    # ==================================================================
    # Swing Detection — JARVIS fractal approach
    # ==================================================================

    def detect_swings(
        self,
        df: pd.DataFrame,
        lookback: int = 3,
        min_swing_distance: int = 3,
    ) -> list[Swing]:
        """Detect swing highs/lows using JARVIS fractal approach.

        A swing high: price[i] > all prices in [i-lookback, i+lookback].
        Unique max enforced — no duplicate swing points within
        min_swing_distance candles.
        """
        if df is None or df.empty or len(df) < (2 * lookback + 1):
            return []

        swings: list[Swing] = []
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)

        # Detect swing highs
        for i in range(lookback, n - lookback):
            window_low = i - lookback
            window_high = i + lookback

            if highs[i] == np.max(highs[window_low:window_high + 1]):
                is_unique = True
                for j in range(window_low, window_high + 1):
                    if j != i and highs[j] == highs[i]:
                        is_unique = False
                        break
                if is_unique:
                    swings.append(Swing(type="high", price=float(highs[i]), index=i))

            if lows[i] == np.min(lows[window_low:window_high + 1]):
                is_unique = True
                for j in range(window_low, window_high + 1):
                    if j != i and lows[j] == lows[i]:
                        is_unique = False
                        break
                if is_unique:
                    swings.append(Swing(type="low", price=float(lows[i]), index=i))

        swings.sort(key=lambda s: s.index)

        # Enforce minimum distance between same-type swings
        filtered: list[Swing] = []
        last_high_idx = -min_swing_distance - 1
        last_low_idx = -min_swing_distance - 1

        for swing in swings:
            if swing.type == "high":
                if swing.index - last_high_idx >= min_swing_distance:
                    filtered.append(swing)
                    last_high_idx = swing.index
            else:
                if swing.index - last_low_idx >= min_swing_distance:
                    filtered.append(swing)
                    last_low_idx = swing.index

        return filtered

    # ==================================================================
    # Market Structure — JARVIS walk-forward BOS/CHoCH
    # ==================================================================

    def detect_structure(
        self,
        df: pd.DataFrame,
        swing_lookback: int = 3,
        max_events: int = 10,
    ) -> dict[str, Any]:
        """Walk-forward market structure tracking (JARVIS-style).

        Maintains last swing high and last swing low, detects:
        - BOS: Price breaks last SH in same direction as prevailing trend
        - CHoCH: Price breaks last SH/L in opposite direction (reversal signal)
        """
        if df is None or df.empty or len(df) < 20:
            return {
                "events": [], "current_trend": "neutral",
                "swing_highs": [], "swing_lows": [],
                "bos_detected": False, "choch_detected": False,
                "bos_direction": "none",
            }

        swings = self.detect_swings(df, lookback=swing_lookback)
        if len(swings) < 4:
            return {
                "events": [], "current_trend": "neutral",
                "swing_highs": [s.price for s in swings if s.type == "high"],
                "swing_lows": [s.price for s in swings if s.type == "low"],
                "bos_detected": False, "choch_detected": False,
                "bos_direction": "none",
            }

        closes = df["close"].values
        events: list[StructureEvent] = []

        sh = next((s for s in swings if s.type == "high"), None)
        sl = next((s for s in swings if s.type == "low"), None)

        if sh is None or sl is None:
            return {
                "events": [], "current_trend": "neutral",
                "swing_highs": [], "swing_lows": [],
                "bos_detected": False, "choch_detected": False,
                "bos_direction": "none",
            }

        current_trend = "neutral"
        last_sh = sh
        last_sl = sl

        for i in range(min(sh.index, sl.index) + 1, len(df)):
            close = closes[i]

            if current_trend == "neutral":
                if close > last_sh.price:
                    current_trend = "bullish"
                elif close < last_sl.price:
                    current_trend = "bearish"

            elif current_trend == "bullish":
                if close > last_sh.price:
                    momentum = self._calc_momentum(closes, last_sh.index, i)
                    event = StructureEvent(
                        type="BOS", direction="bullish", price=close, index=i,
                        broken_swing=last_sh, confidence=min(1.0, momentum),
                    )
                    events.append(event)
                    candidates = [s for s in swings if s.type == "high" and s.index < i]
                    if candidates:
                        last_sh = candidates[-1]
                elif close < last_sl.price:
                    momentum = self._calc_momentum(closes, last_sl.index, i)
                    event = StructureEvent(
                        type="CHoCH", direction="bearish", price=close, index=i,
                        broken_swing=last_sl, confidence=min(1.0, momentum),
                    )
                    events.append(event)
                    current_trend = "bearish"
                    candidates = [s for s in swings if s.type == "low" and s.index < i]
                    if candidates:
                        last_sl = candidates[-1]

            elif current_trend == "bearish":
                if close < last_sl.price:
                    momentum = self._calc_momentum(closes, last_sl.index, i)
                    event = StructureEvent(
                        type="BOS", direction="bearish", price=close, index=i,
                        broken_swing=last_sl, confidence=min(1.0, momentum),
                    )
                    events.append(event)
                    candidates = [s for s in swings if s.type == "low" and s.index < i]
                    if candidates:
                        last_sl = candidates[-1]
                elif close > last_sh.price:
                    momentum = self._calc_momentum(closes, last_sh.index, i)
                    event = StructureEvent(
                        type="CHoCH", direction="bullish", price=close, index=i,
                        broken_swing=last_sh, confidence=min(1.0, momentum),
                    )
                    events.append(event)
                    current_trend = "bullish"
                    candidates = [s for s in swings if s.type == "high" and s.index < i]
                    if candidates:
                        last_sh = candidates[-1]

        recent_events = events[-max_events:] if len(events) > max_events else events

        bos_detected = False
        choch_detected = False
        bos_direction = "none"

        if recent_events:
            last_event = recent_events[-1]
            if last_event.type == "BOS":
                bos_detected = True
                bos_direction = last_event.direction
            elif last_event.type == "CHoCH":
                choch_detected = True
                bos_direction = last_event.direction

        return {
            "events": recent_events,
            "current_trend": current_trend,
            "swing_highs": [s.price for s in swings if s.type == "high"][-6:],
            "swing_lows": [s.price for s in swings if s.type == "low"][-6:],
            "bos_detected": bos_detected,
            "choch_detected": choch_detected,
            "bos_direction": bos_direction,
        }

    # Backward-compatible wrapper
    def detect_structure_breaks(
        self, df: pd.DataFrame, lookback: int = 20
    ) -> dict[str, Any]:
        """Legacy interface — delegates to detect_structure()."""
        return self.detect_structure(df, swing_lookback=3)

    # ==================================================================
    # Order Block Detection — JARVIS-enhanced with validation
    # ==================================================================

    def detect_order_blocks(
        self,
        df: pd.DataFrame,
        lookback: int = 20,
        min_impulse: float = 1.5,
        min_impulse_candles: int = 2,
        max_wick_pct: float = 0.5,
    ) -> list[OrderBlock]:
        """Detect Order Blocks — JARVIS-enhanced.

        Bullish OB: Last bearish candle before >=2 consecutive bullish
        candles that break structure upward.
        Bearish OB: Last bullish candle before >=2 consecutive bearish
        candles that break structure downward.
        Validation: OB zone is valid until price CLOSES through it.
        """
        if df is None or df.empty or len(df) < lookback + 3:
            return []

        order_blocks: list[OrderBlock] = []
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        opens = df["open"].values
        n = len(df)

        for i in range(lookback, n - min_impulse_candles - 1):
            recent_range = highs[i-lookback:i+1] - lows[i-lookback:i+1]
            avg_range = np.mean(recent_range) if len(recent_range) > 0 else 1.0
            impulse_threshold = avg_range * min_impulse

            # ---- Bullish OB ----
            if opens[i] > closes[i]:  # Bearish candle (potential OB)
                consecutive_bullish = 0
                total_impulse = 0.0
                for j in range(i + 1, min(i + 6, n)):
                    if closes[j] > opens[j] and closes[j] > closes[j - 1]:
                        consecutive_bullish += 1
                        total_impulse += closes[j] - closes[j - 1]
                    else:
                        break

                if consecutive_bullish >= min_impulse_candles and total_impulse > impulse_threshold:
                    body_high = opens[i]
                    body_low = closes[i]
                    body = body_high - body_low
                    upper_wick = highs[i] - body_high
                    lower_wick = body_low - lows[i]
                    wick_pct = (upper_wick + lower_wick) / body if body > 0 else 0.0

                    valid = True
                    for j in range(i + 1, n):
                        if closes[j] < body_low:
                            valid = False
                            break

                    ob = OrderBlock(
                        type="bullish",
                        high=body_high, low=body_low,
                        midpoint=(body_high + body_low) / 2,
                        index=i,
                        validated=valid and wick_pct < max_wick_pct,
                        strength=min(1.0, total_impulse / (avg_range * 3)),
                        impulse_candles=consecutive_bullish,
                        wick_pct=wick_pct,
                    )
                    order_blocks.append(ob)

            # ---- Bearish OB ----
            elif closes[i] > opens[i]:  # Bullish candle (potential OB)
                consecutive_bearish = 0
                total_impulse = 0.0
                for j in range(i + 1, min(i + 6, n)):
                    if opens[j] > closes[j] and closes[j] < closes[j - 1]:
                        consecutive_bearish += 1
                        total_impulse += closes[j - 1] - closes[j]
                    else:
                        break

                if consecutive_bearish >= min_impulse_candles and total_impulse > impulse_threshold:
                    body_high = closes[i]
                    body_low = opens[i]
                    body = body_high - body_low
                    upper_wick = highs[i] - body_high
                    lower_wick = body_low - lows[i]
                    wick_pct = (upper_wick + lower_wick) / body if body > 0 else 0.0

                    valid = True
                    for j in range(i + 1, n):
                        if closes[j] > body_high:
                            valid = False
                            break

                    ob = OrderBlock(
                        type="bearish",
                        high=body_high, low=body_low,
                        midpoint=(body_high + body_low) / 2,
                        index=i,
                        validated=valid and wick_pct < max_wick_pct,
                        strength=min(1.0, total_impulse / (avg_range * 3)),
                        impulse_candles=consecutive_bearish,
                        wick_pct=wick_pct,
                    )
                    order_blocks.append(ob)

        return order_blocks[-15:]

    # ==================================================================
    # Fair Value Gap Detection — JARVIS-enhanced with mitigation
    # ==================================================================

    def detect_fvg(
        self,
        df: pd.DataFrame,
        min_gap_pct: float = 0.0005,
        check_mitigation: bool = True,
    ) -> list[FairValueGap]:
        """Detect Fair Value Gaps — JARVIS-enhanced.

        Bullish FVG: Low of candle[i+1] > High of candle[i-1] (gap up).
        Bearish FVG: High of candle[i+1] < Low of candle[i-1] (gap down).
        Mitigation: Price revisiting the gap marks it as mitigated.
        """
        fvgs: list[FairValueGap] = []
        if df is None or df.empty or len(df) < 4:
            return fvgs

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        n = len(df)

        for i in range(2, n):
            price_ref = closes[i]
            if price_ref <= 0:
                continue
            min_gap = price_ref * min_gap_pct

            # Bullish FVG
            gap_up = lows[i] - highs[i - 2]
            if gap_up > min_gap:
                fvg = FairValueGap(
                    type="bullish",
                    high=float(lows[i]),
                    low=float(highs[i - 2]),
                    midpoint=float((lows[i] + highs[i - 2]) / 2),
                    index=i - 1,
                    gap_size_pct=float(gap_up / price_ref * 100),
                )
                fvgs.append(fvg)

            # Bearish FVG
            gap_down = lows[i - 2] - highs[i]
            if gap_down > min_gap:
                fvg = FairValueGap(
                    type="bearish",
                    high=float(lows[i - 2]),
                    low=float(highs[i]),
                    midpoint=float((lows[i - 2] + highs[i]) / 2),
                    index=i - 1,
                    gap_size_pct=float(gap_down / price_ref * 100),
                )
                fvgs.append(fvg)

        # Check mitigation and fill status
        if check_mitigation:
            for fvg in fvgs:
                for j in range(fvg.index + 1, n):
                    bar_high = highs[j]
                    bar_low = lows[j]

                    if fvg.type == "bullish":
                        if bar_low <= fvg.high:
                            fvg.mitigated = True
                        if closes[j] <= fvg.low:
                            fvg.filled = True
                            break
                    else:
                        if bar_high >= fvg.low:
                            fvg.mitigated = True
                        if closes[j] >= fvg.high:
                            fvg.filled = True
                            break

        unfilled = [f for f in fvgs if not f.filled]
        return unfilled[-10:]

    # ==================================================================
    # Liquidity Sweep Detection — JARVIS-enhanced
    # ==================================================================

    def detect_liquidity_sweeps(
        self,
        df: pd.DataFrame,
        lookback: int = 30,
        sweep_search_lookback: int = 30,
        min_displacement: float = 0.5,
    ) -> list[LiquiditySweep]:
        """Detect liquidity sweeps — JARVIS-enhanced.

        Searches for prior swing levels that get penetrated but rejected
        within the same candle.
        Buy-side sweep: Wick above prior swing high, close below.
        Sell-side sweep: Wick below prior swing low, close above.
        """
        sweeps: list[LiquiditySweep] = []
        if df is None or df.empty or len(df) < lookback + 5:
            return sweeps

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        n = len(df)

        swings = self.detect_swings(df, lookback=3)
        swing_high_levels = [s.price for s in swings if s.type == "high"]
        swing_low_levels = [s.price for s in swings if s.type == "low"]

        for i in range(sweep_search_lookback, n):
            if i < 15:
                continue
            recent_range = highs[i-14:i+1] - lows[i-14:i+1]
            atr = np.mean(recent_range) if len(recent_range) > 0 else 1.0

            search_start = max(0, i - sweep_search_lookback)
            search_window_highs = [
                h for h in swing_high_levels
                if search_start <= next((s.index for s in swings if s.type == "high" and s.price == h), 0) < i
            ]
            search_window_lows = [
                lw for lw in swing_low_levels
                if search_start <= next((s.index for s in swings if s.type == "low" and s.price == lw), 0) < i
            ]

            # Buy-side sweep
            for sh_level in search_window_highs:
                if highs[i] > sh_level and closes[i] < sh_level:
                    displacement = np.mean(closes[i+1:i+4]) - lows[i] if i + 4 < n else closes[i] - lows[i]
                    if displacement < 0 and abs(displacement) / atr > min_displacement:
                        sweep = LiquiditySweep(
                            type="buy_side", level=float(sh_level),
                            sweep_high=float(highs[i]), sweep_low=float(lows[i]),
                            index=i, displacement=float(abs(displacement)),
                        )
                        if not any(s.index == i and s.type == "buy_side" for s in sweeps):
                            sweeps.append(sweep)
                        break

            # Sell-side sweep
            for sl_level in search_window_lows:
                if lows[i] < sl_level and closes[i] > sl_level:
                    displacement = highs[i] - np.mean(closes[i+1:i+4]) if i + 4 < n else highs[i] - closes[i]
                    if displacement > 0 and displacement / atr > min_displacement:
                        sweep = LiquiditySweep(
                            type="sell_side", level=float(sl_level),
                            sweep_high=float(highs[i]), sweep_low=float(lows[i]),
                            index=i, displacement=float(abs(displacement)),
                        )
                        if not any(s.index == i and s.type == "sell_side" for s in sweeps):
                            sweeps.append(sweep)
                        break

        return sweeps[-8:]

    # ==================================================================
    # Entry Model — JARVIS find_setup() confluence
    # ==================================================================

    def find_setup(
        self,
        df: pd.DataFrame,
        htf_trend: str = "neutral",
        max_distance_pips: float = 20.0,
        pip_value: float = 0.0001,
    ) -> Optional[Setup]:
        """JARVIS entry model: confluence of sweep + OB + FVG + structure.

        BUY setup requires: HTF bullish, bullish structure event,
        sell-side sweep, unmitigated bullish OB near price.
        SELL setup: mirror logic.
        """
        if df is None or df.empty or len(df) < 50:
            return None

        current_price = float(df["close"].iloc[-1])
        max_distance = max_distance_pips * pip_value

        order_blocks = self.detect_order_blocks(df)
        fvgs = self.detect_fvg(df)
        sweeps = self.detect_liquidity_sweeps(df)
        structure = self.detect_structure(df)

        # ===== BUY SETUP =====
        if htf_trend in ("bullish", "neutral"):
            bull_events = [e for e in structure["events"]
                          if e.direction == "bullish" and e.index > len(df) - 40]
            sell_sweeps = [s for s in sweeps if s.type == "sell_side"]
            bull_obs = [ob for ob in order_blocks
                       if ob.type == "bullish" and not ob.invalidated]
            bull_fvgs = [f for f in fvgs if f.type == "bullish" and not f.mitigated]

            if sell_sweeps and bull_obs:
                sweep = sell_sweeps[-1]
                nearest_ob = None
                for ob in sorted(bull_obs, key=lambda o: abs(o.midpoint - current_price)):
                    if abs(current_price - ob.midpoint) < max_distance:
                        nearest_ob = ob
                        break

                if nearest_ob:
                    overlapping_fvg = None
                    for fvg in bull_fvgs:
                        if fvg.low <= nearest_ob.high and fvg.high >= nearest_ob.low:
                            overlapping_fvg = fvg
                            break

                    score = 1
                    if bull_events:
                        score += 1
                    if nearest_ob.validated:
                        score += 1
                    if overlapping_fvg:
                        score += 1
                    if nearest_ob.impulse_candles >= 3:
                        score += 1

                    entry_price = nearest_ob.midpoint
                    stop_loss = nearest_ob.low
                    risk = entry_price - stop_loss
                    take_profit = entry_price + (risk * 2.0)

                    setup = Setup(
                        direction="BUY", htf_trend=htf_trend,
                        structure_event=bull_events[-1] if bull_events else None,
                        sweep=sweep, order_block=nearest_ob, fvg=overlapping_fvg,
                        confluence_score=float(score),
                        entry_price=entry_price, stop_loss=stop_loss,
                        take_profit=take_profit, max_distance_pips=max_distance_pips,
                        valid=score >= 3,
                        reasoning=self._build_setup_reasoning(
                            "BUY", sweep, nearest_ob, overlapping_fvg,
                            bull_events, score,
                        ),
                    )
                    return setup

        # ===== SELL SETUP =====
        if htf_trend in ("bearish", "neutral"):
            bear_events = [e for e in structure["events"]
                          if e.direction == "bearish" and e.index > len(df) - 40]
            buy_sweeps = [s for s in sweeps if s.type == "buy_side"]
            bear_obs = [ob for ob in order_blocks
                       if ob.type == "bearish" and not ob.invalidated]
            bear_fvgs = [f for f in fvgs if f.type == "bearish" and not f.mitigated]

            if buy_sweeps and bear_obs:
                sweep = buy_sweeps[-1]
                nearest_ob = None
                for ob in sorted(bear_obs, key=lambda o: abs(o.midpoint - current_price)):
                    if abs(current_price - ob.midpoint) < max_distance:
                        nearest_ob = ob
                        break

                if nearest_ob:
                    overlapping_fvg = None
                    for fvg in bear_fvgs:
                        if fvg.low <= nearest_ob.high and fvg.high >= nearest_ob.low:
                            overlapping_fvg = fvg
                            break

                    score = 1
                    if bear_events:
                        score += 1
                    if nearest_ob.validated:
                        score += 1
                    if overlapping_fvg:
                        score += 1
                    if nearest_ob.impulse_candles >= 3:
                        score += 1

                    entry_price = nearest_ob.midpoint
                    stop_loss = nearest_ob.high
                    risk = stop_loss - entry_price
                    take_profit = entry_price - (risk * 2.0)

                    setup = Setup(
                        direction="SELL", htf_trend=htf_trend,
                        structure_event=bear_events[-1] if bear_events else None,
                        sweep=sweep, order_block=nearest_ob, fvg=overlapping_fvg,
                        confluence_score=float(score),
                        entry_price=entry_price, stop_loss=stop_loss,
                        take_profit=take_profit, max_distance_pips=max_distance_pips,
                        valid=score >= 3,
                        reasoning=self._build_setup_reasoning(
                            "SELL", sweep, nearest_ob, overlapping_fvg,
                            bear_events, score,
                        ),
                    )
                    return setup

        return None

    # ==================================================================
    # Full Analysis
    # ==================================================================

    def analyze(self, df: pd.DataFrame) -> SMCReport:
        """Run complete SMC analysis on OHLCV data."""
        swings = self.detect_swings(df)
        structure = self.detect_structure(df)
        order_blocks = self.detect_order_blocks(df)
        fvgs = self.detect_fvg(df)
        sweeps = self.detect_liquidity_sweeps(df)

        current_trend = structure.get("current_trend", "neutral")
        setup = self.find_setup(df, htf_trend=current_trend)

        confidence = 0.0
        if order_blocks:
            confidence += 0.2
        if fvgs:
            confidence += 0.15
        if sweeps:
            confidence += 0.2
        if structure["bos_detected"]:
            confidence += 0.15
            confidence += 0.05 * min(3, len(structure["events"]))
        if structure["choch_detected"]:
            confidence += 0.2
        if setup and setup.valid:
            confidence += 0.2

        reasoning = self._build_reasoning(order_blocks, fvgs, sweeps, structure, setup)

        return SMCReport(
            order_blocks=order_blocks,
            fair_value_gaps=fvgs,
            liquidity_sweeps=sweeps,
            swings=swings,
            structure_events=structure["events"],
            bos_detected=structure["bos_detected"],
            choch_detected=structure["choch_detected"],
            bos_direction=structure["bos_direction"],
            current_trend=current_trend,
            setup=setup,
            reasoning=reasoning,
            confidence=min(1.0, confidence),
        )

    # ==================================================================
    # Multi-Timeframe Structure
    # ==================================================================

    def get_mtf_swing_levels(
        self,
        prices: dict[str, pd.DataFrame],
        lookback: int = 3,
    ) -> dict[str, list[Swing]]:
        """Extract swing levels across multiple timeframes."""
        result: dict[str, list[Swing]] = {}
        for tf, df in prices.items():
            if df is not None and not df.empty and len(df) > 10:
                result[tf] = self.detect_swings(df, lookback=lookback)
        return result

    # ==================================================================
    # Helpers
    # ==================================================================

    def _find_swings(self, df: pd.DataFrame, lookback: int) -> dict[str, list[float]]:
        """Legacy helper for backward compatibility.

        DEPRECATED: Use detect_swings() directly instead.
        This wrapper is kept for backward compatibility only.
        Will be removed in a future major version.
        """
        swings = self.detect_swings(df, lookback=lookback)
        return {
            "highs": [s.price for s in swings if s.type == "high"][-6:],
            "lows": [s.price for s in swings if s.type == "low"][-6:],
        }

    def _calc_momentum(
        self, closes: np.ndarray, from_idx: int, to_idx: int,
    ) -> float:
        """Calculate momentum score for structure break. 0-1."""
        if to_idx <= from_idx or from_idx < 0 or to_idx >= len(closes):
            return 0.5
        segment = closes[from_idx:to_idx + 1]
        if len(segment) < 2:
            return 0.5
        diffs = np.diff(segment)
        same_direction = np.sum(np.sign(diffs) == np.sign(diffs[0]))
        consistency = same_direction / len(diffs) if len(diffs) > 0 else 0
        total_move = abs(segment[-1] - segment[0])
        avg_range = np.mean(np.abs(diffs)) if len(diffs) > 0 else 1.0
        magnitude_score = min(1.0, total_move / (avg_range * 3)) if avg_range > 0 else 0.5
        return consistency * 0.4 + magnitude_score * 0.6

    def _build_setup_reasoning(
        self, direction: str, sweep: LiquiditySweep, ob: OrderBlock,
        fvg: Optional[FairValueGap], events: list[StructureEvent], score: int,
    ) -> str:
        """Build human-readable reasoning for a setup."""
        parts = [f"{direction} setup (score={score}/5)"]
        parts.append(f"Sweep: {sweep.type} @ {sweep.level:.5f} "
                     f"(displacement: {sweep.displacement:.5f})")
        parts.append(f"Order Block: {ob.type} @ {ob.midpoint:.5f} "
                     f"(validated={ob.validated}, impulse_candles={ob.impulse_candles})")
        if fvg:
            parts.append(f"FVG: {fvg.type} overlapping OB zone "
                         f"(mitigated={fvg.mitigated})")
        if events:
            last = events[-1]
            parts.append(f"Structure: {last.type}({last.direction}) @ {last.price:.5f} "
                         f"(confidence={last.confidence:.2f})")
        parts.append(f"Entry: {ob.midpoint:.5f} | "
                     f"SL: {ob.low if direction == 'BUY' else ob.high:.5f}")
        return " | ".join(parts)

    def _build_reasoning(
        self,
        order_blocks: list[OrderBlock],
        fvgs: list[FairValueGap],
        sweeps: list[LiquiditySweep],
        structure: dict,
        setup: Optional[Setup] = None,
    ) -> str:
        """Build human-readable SMC reasoning."""
        parts = []

        if structure["choch_detected"]:
            parts.append(f"CHoCH detected: {structure['bos_direction'].upper()} — Potential trend reversal!")
        elif structure["bos_detected"]:
            parts.append(f"BOS: {structure['bos_direction'].upper()} — Trend continuation")
        else:
            trend = structure.get("current_trend", "neutral")
            parts.append(f"Current trend: {trend.upper()}")

        bullish_obs = [ob for ob in order_blocks if ob.type == "bullish"]
        bearish_obs = [ob for ob in order_blocks if ob.type == "bearish"]
        if bullish_obs:
            valid_obs = [ob for ob in bullish_obs if ob.validated]
            parts.append(
                f"Bullish OBs: {len(bullish_obs)} total, {len(valid_obs)} validated "
                f"(nearest @ {bullish_obs[-1].midpoint:.5f}, "
                f"strength={bullish_obs[-1].strength:.2f})"
            )
        if bearish_obs:
            valid_obs = [ob for ob in bearish_obs if ob.validated]
            parts.append(
                f"Bearish OBs: {len(bearish_obs)} total, {len(valid_obs)} validated "
                f"(nearest @ {bearish_obs[-1].midpoint:.5f})"
            )

        unmitigated = [f for f in fvgs if not f.mitigated]
        if fvgs:
            parts.append(f"FVGs: {len(fvgs)} total, {len(unmitigated)} unmitigated")

        if sweeps:
            last_sweep = sweeps[-1]
            parts.append(
                f"Recent sweep: {last_sweep.type} @ {last_sweep.level:.5f} "
                f"(displacement: {last_sweep.displacement:.5f})"
            )

        if setup:
            parts.append(f"Setup: {setup.direction} (score={setup.confluence_score}/5, valid={setup.valid})")

        return "\n".join(parts) if parts else "No significant SMC patterns detected"
