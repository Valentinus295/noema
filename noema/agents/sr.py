"""Support & Resistance Agent — maps reaction zones.

Enhanced with JARVIS swing-based S/R detection:
- Fractal swing levels across multiple timeframes (D1, W1, MN1)
- Session-level swings (Asia, London, NY) for intraday S/R
- Swing strength weighting (more touches = stronger zone)
- Confluence zones where multiple timeframe swings cluster
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
import structlog

from noema.analysis.smc import SMCForecaster, Swing
from noema.core.modern_agent import DeterministicAgent, AgentReport

logger = structlog.get_logger(__name__)


@dataclass
class Zone:
    """A support or resistance zone with enhanced metadata.

    Enhanced with:
    - swing_source: whether zone came from fractal swing or session extreme
    - touches: how many times price tested this level
    - confluence_count: how many timeframes agree on this zone
    """
    name: str
    type: str              # "support" or "resistance"
    level: float
    strength: int          # How many touches / confirmations
    timeframe: str
    swing_source: bool = False     # True if from fractal swing detection
    confluence_count: int = 1      # Number of timeframes clustering here
    is_session_level: bool = False  # Asian/London/NY session extreme


class SupportResistanceAgent(DeterministicAgent):
    """Agent #6 — Maps reaction zones using JARVIS swing detection.

    Zones come from two sources:
    1. **Session extremes**: Asian Low/High, Daily Low/High, Weekly/Monthly
    2. **Fractal swings**: Swing highs/lows from fractal detection on D1, W1, MN1

    Enhanced features:
    - Multi-timeframe swing detection for high-probability zones
    - Zone clustering: swings from multiple TFs near same price = strong zone
    - Session-level swing detection (Asia, London, NY) for intraday
    - Zone strength based on number of touches/confirmations
    """

    name = "support-resistance"
    role = "Support & Resistance Mapper"
    priority = 6

    # Session hours in EAT (UTC+3)
    ASIAN_START = 0
    ASIAN_END = 9
    LONDON_START = 10
    LONDON_END = 19
    NY_START = 15
    NY_END = 24

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.smc = SMCForecaster(self.config)
        self._zone_cluster_tolerance: float = 0.0003  # ~3 pips for clustering

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Map S/R zones from multi-timeframe OHLCV data.

        Builds zones from:
        1. Session extremes (Asian, London, NY, Daily, Weekly, Monthly)
        2. Fractal swing highs/lows across available timeframes
        3. Zone clustering for confluence detection
        """
        prices: dict[str, pd.DataFrame] = context.get("prices", {})
        pair: str = context.get("pair", "EURUSD")

        df = prices.get(pair) if pair in prices else prices.get("H1") if "H1" in prices else None
        if df is None:
            for tf in ["H1", "H4", "D1", "M15"]:
                if tf in prices:
                    df = prices[tf]
                    break

        if df is None or len(df) < 20:
            return AgentReport(
                agent_name=self.name,
                signal="NEUTRAL",
                reasoning="No price data available",
            )

        current_price = float(df["close"].iloc[-1])

        # Phase 1: Session-level zones
        buy_zones, sell_zones = self._build_session_zones(prices, df)

        # Phase 2: Swing-based zones
        swing_zones = self._build_swing_zones(prices)
        buy_zones.extend(swing_zones["supports"])
        sell_zones.extend(swing_zones["resistances"])

        # Phase 3: Zone clustering (confluence detection)
        buy_zones = self._cluster_zones(buy_zones, current_price)
        sell_zones = self._cluster_zones(sell_zones, current_price)

        # Phase 4: Find nearest zones
        nearest_support = self._find_nearest(buy_zones, current_price, below=True)
        nearest_resistance = self._find_nearest(sell_zones, current_price, below=False)

        # Phase 5: Signal determination
        signal, confidence, reasoning = self._evaluate_signal(
            current_price, nearest_support, nearest_resistance,
            buy_zones, sell_zones, df,
        )

        return AgentReport(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            data={
                "buy_zones": [
                    {"name": z.name, "level": z.level, "tf": z.timeframe,
                     "strength": z.strength, "swing_source": z.swing_source,
                     "confluence": z.confluence_count}
                    for z in buy_zones[-8:]
                ],
                "sell_zones": [
                    {"name": z.name, "level": z.level, "tf": z.timeframe,
                     "strength": z.strength, "swing_source": z.swing_source,
                     "confluence": z.confluence_count}
                    for z in sell_zones[-8:]
                ],
                "nearest_support": self._zone_to_dict(nearest_support),
                "nearest_resistance": self._zone_to_dict(nearest_resistance),
                "current_price": current_price,
                "zone_summary": {
                    "total_supports": len(buy_zones),
                    "total_resistances": len(sell_zones),
                    "swing_based_zones": sum(1 for z in buy_zones + sell_zones if z.swing_source),
                    "confluence_zones": sum(1 for z in buy_zones + sell_zones if z.confluence_count >= 2),
                },
            },
            reasoning=reasoning,
        )

    def _build_session_zones(
        self, prices: dict[str, pd.DataFrame], df: pd.DataFrame,
    ) -> tuple[list[Zone], list[Zone]]:
        """Build zones from session extremes and fixed timeframe levels."""
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
            buy_zones.append(Zone("Weekly Low", "support", float(wdf["low"].min()), 2, "W1"))
            sell_zones.append(Zone("Weekly High", "resistance", float(wdf["high"].max()), 2, "W1"))

        # Monthly levels
        if "MN1" in prices:
            mdf = prices["MN1"]
            buy_zones.append(Zone("Monthly Low", "support", float(mdf["low"].min()), 3, "MN1"))
            sell_zones.append(Zone("Monthly High", "resistance", float(mdf["high"].max()), 3, "MN1"))

        # Session-level extremes
        asian = self._get_session(df, self.ASIAN_START, self.ASIAN_END, "ASIA")
        if asian is not None:
            buy_zones.append(Zone("Asian Low", "support", float(asian["low"].min()),
                                  1, "ASIA", is_session_level=True))
            sell_zones.append(Zone("Asian High", "resistance", float(asian["high"].max()),
                                   1, "ASIA", is_session_level=True))

        london = self._get_session(df, self.LONDON_START, self.LONDON_END, "LONDON")
        if london is not None:
            buy_zones.append(Zone("London Low", "support", float(london["low"].min()),
                                  1, "LONDON", is_session_level=True))
            sell_zones.append(Zone("London High", "resistance", float(london["high"].max()),
                                   1, "LONDON", is_session_level=True))

        ny = self._get_session(df, self.NY_START, self.NY_END, "NY")
        if ny is not None:
            buy_zones.append(Zone("NY Low", "support", float(ny["low"].min()),
                                  1, "NY", is_session_level=True))
            sell_zones.append(Zone("NY High", "resistance", float(ny["high"].max()),
                                   1, "NY", is_session_level=True))

        return buy_zones, sell_zones

    def _build_swing_zones(
        self, prices: dict[str, pd.DataFrame],
    ) -> dict[str, list[Zone]]:
        """Build zones from fractal swing points across all timeframes.

        Higher timeframes carry more weight:
        M15/M30: strength 1 | H1: 2 | H4: 3 | D1: 4 | W1: 5 | MN1: 6
        """
        supports: list[Zone] = []
        resistances: list[Zone] = []

        tf_order = ["M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
        tf_strength = {"M15": 1, "M30": 1, "H1": 2, "H4": 3, "D1": 4, "W1": 5, "MN1": 6}

        for tf in tf_order:
            if tf not in prices or prices[tf] is None:
                continue
            tdf = prices[tf]
            if len(tdf) < 10:
                continue

            swings = self.smc.detect_swings(tdf, lookback=3, min_swing_distance=2)
            strength = tf_strength.get(tf, 1)

            for swing in swings[-8:]:
                if swing.type == "high":
                    resistances.append(Zone(
                        name=f"{tf} Swing High", type="resistance",
                        level=swing.price, strength=strength,
                        timeframe=tf, swing_source=True,
                    ))
                else:
                    supports.append(Zone(
                        name=f"{tf} Swing Low", type="support",
                        level=swing.price, strength=strength,
                        timeframe=tf, swing_source=True,
                    ))

        supports.sort(key=lambda z: z.strength, reverse=True)
        resistances.sort(key=lambda z: z.strength, reverse=True)

        return {"supports": supports, "resistances": resistances}

    def _cluster_zones(
        self, zones: list[Zone], current_price: float,
        tolerance: Optional[float] = None,
    ) -> list[Zone]:
        """Cluster nearby zones and increase strength for multi-TF confluence."""
        if not zones:
            return zones

        if tolerance is None:
            tolerance = current_price * 0.001

        zones.sort(key=lambda z: z.level)
        clustered: list[Zone] = []
        i = 0

        while i < len(zones):
            cluster = [zones[i]]
            j = i + 1
            while j < len(zones) and (zones[j].level - zones[i].level) <= tolerance:
                cluster.append(zones[j])
                j += 1

            if len(cluster) == 1:
                clustered.append(cluster[0])
            else:
                avg_level = np.mean([z.level for z in cluster])
                max_strength = max(z.strength for z in cluster)
                best_tf = max(cluster, key=lambda z: z.strength).timeframe
                is_swing = any(z.swing_source for z in cluster)
                names = list(set(z.name.split(" ")[0] for z in cluster))
                merged_name = " / ".join(names[:3])

                merged = Zone(
                    name=f"{merged_name} Zone", type=cluster[0].type,
                    level=float(avg_level), strength=max_strength + len(cluster) - 1,
                    timeframe=best_tf, swing_source=is_swing,
                    confluence_count=len(cluster),
                )
                clustered.append(merged)

            i = j

        return clustered

    def _evaluate_signal(
        self,
        current_price: float,
        nearest_support: Optional[Zone],
        nearest_resistance: Optional[Zone],
        buy_zones: list[Zone],
        sell_zones: list[Zone],
        df: pd.DataFrame,
    ) -> tuple[str, float, str]:
        """Determine signal from zone proximity and strength."""
        parts: list[str] = []

        if nearest_support:
            dist_s = current_price - nearest_support.level
            parts.append(
                f"Nearest support: {nearest_support.name} @ {nearest_support.level:.5f} "
                f"({dist_s:.5f} away, strength={nearest_support.strength}, "
                f"confluence={nearest_support.confluence_count})"
            )
        else:
            parts.append("No support zone below current price")

        if nearest_resistance:
            dist_r = nearest_resistance.level - current_price
            parts.append(
                f"Nearest resistance: {nearest_resistance.name} @ {nearest_resistance.level:.5f} "
                f"({dist_r:.5f} away, strength={nearest_resistance.strength}, "
                f"confluence={nearest_resistance.confluence_count})"
            )
        else:
            parts.append("No resistance zone above current price")

        signal = "NEUTRAL"
        confidence = 0.0

        if nearest_support and nearest_resistance:
            dist_s = current_price - nearest_support.level
            dist_r = nearest_resistance.level - current_price

            if dist_s < dist_r * 0.5:
                signal = "BULLISH"
                confidence = 0.4 + (0.05 * nearest_support.strength)
                if nearest_support.confluence_count >= 2:
                    confidence += 0.15
                    parts.append("Strong confluence support zone detected")
            elif dist_r < dist_s * 0.5:
                signal = "BEARISH"
                confidence = 0.4 + (0.05 * nearest_resistance.strength)
                if nearest_resistance.confluence_count >= 2:
                    confidence += 0.15
                    parts.append("Strong confluence resistance zone detected")
            elif dist_s < dist_r:
                signal = "BULLISH"
                confidence = 0.3
            else:
                signal = "BEARISH"
                confidence = 0.3

        elif nearest_support and not nearest_resistance:
            signal = "BULLISH"
            confidence = 0.5 + (0.05 * nearest_support.strength)
            parts.append("No overhead resistance — price in free territory")

        elif nearest_resistance and not nearest_support:
            signal = "BEARISH"
            confidence = 0.5 + (0.05 * nearest_resistance.strength)
            parts.append("No support below — price in free-fall territory")

        # Zone density adjustment
        support_confluence = sum(1 for z in buy_zones if z.confluence_count >= 2)
        resistance_confluence = sum(1 for z in sell_zones if z.confluence_count >= 2)

        if support_confluence >= 2 and signal == "BULLISH":
            confidence += 0.1
            parts.append(f"{support_confluence} confluence support zones below")
        elif resistance_confluence >= 2 and signal == "BEARISH":
            confidence += 0.1
            parts.append(f"{resistance_confluence} confluence resistance zones above")

        # Swing-based zones carry more weight
        if nearest_support and nearest_support.swing_source:
            confidence += 0.05
        if nearest_resistance and nearest_resistance.swing_source:
            confidence += 0.05

        swing_supports = [z for z in buy_zones if z.swing_source]
        swing_resistances = [z for z in sell_zones if z.swing_source]
        parts.append(f"Zones: {len(buy_zones)} support, {len(sell_zones)} resistance "
                     f"({len(swing_supports)}/{len(swing_resistances)} swing-based)")

        confidence = min(1.0, max(0.2, confidence))
        reasoning = " | ".join(parts)

        return signal, confidence, reasoning

    def _get_session(
        self, df: pd.DataFrame, start_hour: int, end_hour: int, name: str,
    ) -> Optional[pd.DataFrame]:
        """Extract session candles based on hour range."""
        try:
            if "time" not in df.columns:
                return None
            times = pd.to_datetime(df["time"])
            if end_hour > start_hour:
                mask = (times.dt.hour >= start_hour) & (times.dt.hour < end_hour)
            else:
                mask = (times.dt.hour >= start_hour) | (times.dt.hour < end_hour)
            session_df = df[mask]
            if len(session_df) > 0:
                return session_df
        except Exception as e:
            logger.debug("session_extraction_failed", session=name, error=str(e))
        return None

    def _find_nearest(
        self, zones: list[Zone], current_price: float, below: bool = True,
    ) -> Optional[Zone]:
        """Find the nearest zone above or below current price."""
        candidates = [
            z for z in zones
            if (below and z.level < current_price) or
               (not below and z.level > current_price)
        ]
        if not candidates:
            return None
        if below:
            return max(candidates, key=lambda z: z.level)
        else:
            return min(candidates, key=lambda z: z.level)

    def _zone_to_dict(self, zone: Optional[Zone]) -> Optional[dict[str, Any]]:
        """Convert Zone to JSON-safe dict."""
        if zone is None:
            return None
        return {
            "name": zone.name,
            "type": zone.type,
            "level": zone.level,
            "strength": zone.strength,
            "timeframe": zone.timeframe,
            "swing_source": zone.swing_source,
            "confluence_count": zone.confluence_count,
        }
