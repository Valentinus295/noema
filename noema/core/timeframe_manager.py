"""Multi-Timeframe Analysis Manager for Noema.

Phase 3 component. Analyzes each symbol across M15, H1, H4, D1 timeframes
and resolves conflicts between higher-timeframe (HTF) trend and lower-timeframe
(LTF) entry timing.

Core principle:
- HTF (D1, H4) → Determine trend direction and strength (the "what")
- LTF (H1, M15) → Determine entry timing and precision (the "when")
- Conflict resolution: HTF up + LTF down = NO TRADE

Also provides:
- Trend alignment scoring (0-100) across timeframes
- Volatility regime detection per timeframe
- Support/resistance confluences across timeframes
- Entry trigger validation (LTF must confirm HTF)

PURE MATH: All calculations are deterministic. No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════
# Types & Enums
# ═══════════════════════════════════════════════════

class TrendDirection(str, Enum):
    """Multi-timeframe trend direction."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class VolatilityRegime(str, Enum):
    """Volatility regime classification per timeframe."""
    LOW = "LOW"           # < 0.5x average
    NORMAL = "NORMAL"     # 0.5x - 1.5x average
    HIGH = "HIGH"         # 1.5x - 3x average
    EXTREME = "EXTREME"   # > 3x average


class TimeframeAlignment(str, Enum):
    """Alignment status across timeframes."""
    ALIGNED = "ALIGNED"           # All timeframes agree on direction
    PARTIAL = "PARTIAL"           # Some agree, some neutral
    CONFLICT = "CONFLICT"         # HTF vs LTF disagree
    UNKNOWN = "UNKNOWN"


# ═══════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════

@dataclass
class TimeframeAnalysis:
    """Analysis for a single timeframe."""
    timeframe: str                 # "M15", "H1", "H4", "D1"
    trend: TrendDirection = TrendDirection.UNKNOWN
    trend_strength: float = 0.0    # 0.0-1.0 (ADX-based)
    trend_duration_bars: int = 0   # Bars since trend started
    price_vs_sma_50: float = 0.0   # Price relative to SMA 50 (%)
    price_vs_sma_200: float = 0.0  # Price relative to SMA 200 (%)
    ema_alignment: bool = False    # Fast EMA > Slow EMA (or reverse for bearish)
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    volatility_percentile: float = 50.0  # 0-100 volatility percentile
    atr_value: float = 0.0         # Average True Range (pips)
    rsi_value: float = 50.0        # RSI (14)
    macd_signal: str = "NEUTRAL"   # "BUY", "SELL", "NEUTRAL"
    sr_levels: list[float] = field(default_factory=list)  # Key S/R levels
    current_price: float = 0.0
    bar_count: int = 0             # Number of bars in data
    bars: list[dict[str, Any]] = field(default_factory=list)  # Raw bar data (last N)


@dataclass
class MultiTimeframeResult:
    """Aggregated multi-timeframe analysis for a symbol."""
    symbol: str
    analyses: dict[str, TimeframeAnalysis] = field(default_factory=dict)

    # Composite
    htf_trend: TrendDirection = TrendDirection.UNKNOWN     # D1 + H4
    ltf_trend: TrendDirection = TrendDirection.UNKNOWN     # H1 + M15
    alignment: TimeframeAlignment = TimeframeAlignment.UNKNOWN
    alignment_score: float = 0.0    # 0-100, higher = better aligned

    # Decision support
    can_trade: bool = False
    trade_direction: TrendDirection = TrendDirection.UNKNOWN
    entry_timeframe: str = "H1"     # Best timeframe for entry
    stop_loss_pips: float = 0.0     # Suggested SL based on ATR + S/R
    take_profit_pips: float = 0.0   # Suggested TP based on ATR + S/R

    # Risk flags
    htF_conflict: bool = False      # HTF says one thing, LTF says another
    extreme_volatility: bool = False
    consolidation_zone: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "htf_trend": self.htf_trend.value,
            "ltf_trend": self.ltf_trend.value,
            "alignment": self.alignment.value,
            "alignment_score": self.alignment_score,
            "can_trade": self.can_trade,
            "trade_direction": self.trade_direction.value,
            "entry_timeframe": self.entry_timeframe,
            "stop_loss_pips": self.stop_loss_pips,
            "take_profit_pips": self.take_profit_pips,
            "htf_conflict": self.htF_conflict,
            "extreme_volatility": self.extreme_volatility,
            "consolidation_zone": self.consolidation_zone,
            "warnings": self.warnings,
            "timeframes": {
                tf: {
                    "trend": a.trend.value,
                    "strength": a.trend_strength,
                    "volatility_regime": a.volatility_regime.value,
                    "rsi": a.rsi_value,
                    "macd": a.macd_signal,
                    "atr": a.atr_value,
                    "price_vs_sma50": a.price_vs_sma_50,
                    "price_vs_sma200": a.price_vs_sma_200,
                }
                for tf, a in self.analyses.items()
            },
        }


# ═══════════════════════════════════════════════════
# Timeframe Manager
# ═══════════════════════════════════════════════════

class TimeframeManager:
    """Multi-timeframe analysis manager.

    Analyzes price action across M15, H1, H4, D1 to determine:
    1. HTF trend (D1 + H4) — Should we trade?
    2. LTF timing (H1 + M15) — When and where to enter?
    3. Conflict resolution — Prevent trades against HTF trend.

    All analysis is deterministic (PURE MATH). No LLM calls.
    """

    # Timeframe hierarchy
    HIGHER_TF = ["D1", "H4"]     # Trend direction
    LOWER_TF = ["H1", "M15"]     # Entry timing
    ALL_TF = ["D1", "H4", "H1", "M15"]

    # Technical parameters
    SMA_PERIODS = {"SMA_50": 50, "SMA_200": 200}
    RSI_PERIOD = 14
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    ATR_PERIOD = 14
    ADX_PERIOD = 14
    ADX_TREND_THRESHOLD = 25.0

    # Conflict thresholds
    HTF_VS_LTF_CONFLICT_MIN = 0.6  # HTF trend strength must be >= this for conflict check
    ALIGNMENT_SCORE_NEUTRAL_WEIGHT = 0.3  # Weight given to neutral timeframes

    def __init__(self, config: Any = None):
        self.config = config

    # ── Data Ingestion ────────────────────────────────────────────

    def analyze_single_timeframe(
        self,
        timeframe: str,
        bars: list[dict[str, Any]],
    ) -> TimeframeAnalysis:
        """Analyze a single timeframe from bar data.

        Args:
            timeframe: Timeframe label ("M15", "H1", "H4", "D1").
            bars: List of OHLCV dicts, most recent last.

        Returns:
            TimeframeAnalysis with trend, volatility, technical indicators.
        """
        if not bars or len(bars) < 20:
            return TimeframeAnalysis(
                timeframe=timeframe,
                trend=TrendDirection.UNKNOWN,
                bar_count=len(bars) if bars else 0,
            )

        closes = np.array([float(b["close"]) for b in bars], dtype=float)
        highs = np.array([float(b.get("high", b["close"])) for b in bars], dtype=float)
        lows = np.array([float(b.get("low", b["close"])) for b in bars], dtype=float)
        current_price = closes[-1]

        analysis = TimeframeAnalysis(
            timeframe=timeframe,
            current_price=current_price,
            bar_count=len(bars),
            bars=bars[-200:],  # Keep last 200 for reference
        )

        # ── SMA calculations ──
        if len(closes) >= 200:
            sma_50 = np.mean(closes[-50:])
            sma_200 = np.mean(closes[-200:])
            analysis.price_vs_sma_50 = round((current_price / sma_50 - 1) * 100, 2)
            analysis.price_vs_sma_200 = round((current_price / sma_200 - 1) * 100, 2)

        # ── EMA alignment ──
        if len(closes) >= 50:
            ema_20 = self._ema(closes, 20)
            ema_50 = self._ema(closes, 50)
            if ema_20 is not None and ema_50 is not None:
                analysis.ema_alignment = (ema_20[-1] > ema_50[-1])

        # ── Trend detection (ADX + EMA) ──
        adx, plus_di, minus_di = self._adx(highs, lows, closes, self.ADX_PERIOD)
        if adx is not None and plus_di is not None and minus_di is not None:
            adx_val = adx[-1]
            if adx_val > self.ADX_TREND_THRESHOLD:
                analysis.trend_strength = min(adx_val / 100.0, 1.0)
                if plus_di[-1] > minus_di[-1]:
                    analysis.trend = TrendDirection.BULLISH
                else:
                    analysis.trend = TrendDirection.BEARISH
            else:
                # Weak ADX — use EMA slope for trend
                analysis.trend_strength = max(adx_val / self.ADX_TREND_THRESHOLD * 0.5, 0.1)
                if current_price > np.mean(closes[-20:]):
                    analysis.trend = TrendDirection.BULLISH
                else:
                    analysis.trend = TrendDirection.BEARISH
        else:
            # Fallback: simple moving average comparison
            analysis.trend_strength = 0.3
            sma_20 = np.mean(closes[-20:]) if len(closes) >= 20 else current_price
            analysis.trend = (
                TrendDirection.BULLISH if current_price > sma_20
                else TrendDirection.BEARISH
            )

        # ── RSI ──
        analysis.rsi_value = self._rsi(closes, self.RSI_PERIOD)

        # ── MACD ──
        macd_line, signal_line, histogram = self._macd(closes)
        if histogram is not None and macd_line is not None:
            if histogram[-1] > 0:
                analysis.macd_signal = "BUY"
            elif histogram[-1] < 0:
                analysis.macd_signal = "SELL"
            else:
                analysis.macd_signal = "NEUTRAL"

        # ── ATR ──
        analysis.atr_value = self._atr(highs, lows, closes, self.ATR_PERIOD)

        # ── Volatility regime ──
        analysis.volatility_regime, analysis.volatility_percentile = self._volatility_regime(
            closes, analysis.atr_value
        )

        # ── S/R levels ──
        analysis.sr_levels = self._find_sr_levels(highs, lows, closes)

        # ── Trend duration (bars since last cross) ──
        analysis.trend_duration_bars = self._trend_duration(closes)

        return analysis

    async def analyze_from_broker(
        self,
        symbol: str,
        broker: Any,
    ) -> MultiTimeframeResult:
        """Fetch and analyze all timeframes from a broker.

        Args:
            symbol: Trading symbol.
            broker: Broker instance.

        Returns:
            MultiTimeframeResult with full analysis.
        """
        import asyncio

        analyses: dict[str, TimeframeAnalysis] = {}

        for tf in self.ALL_TF:
            bars = await self._fetch_bars(broker, symbol, tf, 200)
            analyses[tf] = self.analyze_single_timeframe(tf, bars)

        return self.aggregate(symbol, analyses)

    def aggregate(
        self,
        symbol: str,
        analyses: dict[str, TimeframeAnalysis],
    ) -> MultiTimeframeResult:
        """Aggregate per-timeframe analyses into a multi-timeframe decision.

        Args:
            symbol: Trading symbol.
            analyses: Per-timeframe analysis results.

        Returns:
            MultiTimeframeResult with decision and warnings.
        """
        result = MultiTimeframeResult(
            symbol=symbol,
            analyses=analyses,
        )

        # ── Determine HTF trend (D1 + H4, weighted by strength) ──
        htf_signals = []
        for tf in self.HIGHER_TF:
            if tf in analyses and analyses[tf].trend != TrendDirection.UNKNOWN:
                a = analyses[tf]
                htf_signals.append((a.trend, a.trend_strength, tf))

        if htf_signals:
            # Weighted vote: stronger trend = more weight
            bullish_weight = sum(s[1] for s in htf_signals if s[0] == TrendDirection.BULLISH)
            bearish_weight = sum(s[1] for s in htf_signals if s[0] == TrendDirection.BEARISH)
            neutral_weight = sum(s[1] for s in htf_signals if s[0] == TrendDirection.NEUTRAL)

            max_weight = max(bullish_weight, bearish_weight, neutral_weight)
            if max_weight == bullish_weight and bullish_weight > 0:
                result.htf_trend = TrendDirection.BULLISH
            elif max_weight == bearish_weight and bearish_weight > 0:
                result.htf_trend = TrendDirection.BEARISH
            else:
                result.htf_trend = TrendDirection.NEUTRAL

        # ── Determine LTF trend (H1 + M15) ──
        ltf_signals = []
        for tf in self.LOWER_TF:
            if tf in analyses and analyses[tf].trend != TrendDirection.UNKNOWN:
                a = analyses[tf]
                ltf_signals.append((a.trend, a.trend_strength, tf))

        if ltf_signals:
            bullish_weight = sum(s[1] for s in ltf_signals if s[0] == TrendDirection.BULLISH)
            bearish_weight = sum(s[1] for s in ltf_signals if s[0] == TrendDirection.BEARISH)
            neutral_weight = sum(s[1] for s in ltf_signals if s[0] == TrendDirection.NEUTRAL)

            max_weight = max(bullish_weight, bearish_weight, neutral_weight)
            if max_weight == bullish_weight and bullish_weight > 0:
                result.ltf_trend = TrendDirection.BULLISH
            elif max_weight == bearish_weight and bearish_weight > 0:
                result.ltf_trend = TrendDirection.BEARISH
            else:
                result.ltf_trend = TrendDirection.NEUTRAL

        # ── Alignment detection ──
        result.alignment, result.alignment_score = self._compute_alignment(
            result.htf_trend, result.ltf_trend, analyses
        )

        # ── Conflict resolution: HTF up + LTF down = NO TRADE ──
        result.htF_conflict = self._is_htf_ltf_conflict(
            result.htf_trend, result.ltf_trend, analyses
        )

        # ── Decision: can we trade? ──
        result.can_trade = True

        if result.htF_conflict:
            result.can_trade = False
            result.warnings.append(
                f"HTF/LTF CONFLICT: HTF={result.htf_trend.value} vs LTF={result.ltf_trend.value}. "
                f"Higher timeframe trend must be respected — NO TRADE."
            )

        # Check for consolidation zone (multiple timeframes neutral)
        neutral_count = sum(
            1 for a in analyses.values()
            if a.trend == TrendDirection.NEUTRAL
        )
        if neutral_count >= 2:
            result.consolidation_zone = True
            result.warnings.append(
                f"CONSOLIDATION: {neutral_count} timeframes neutral — "
                f"wait for breakout before entering."
            )
            if neutral_count >= 3:
                result.can_trade = False

        # Check for extreme volatility
        extreme_count = sum(
            1 for a in analyses.values()
            if a.volatility_regime == VolatilityRegime.EXTREME
        )
        if extreme_count >= 1:
            result.extreme_volatility = True
            result.warnings.append(
                f"EXTREME VOLATILITY: {extreme_count} timeframe(s) at extreme levels — "
                f"widen stops or avoid new entries."
            )

        # ── Trade direction (from HTF) ──
        if result.can_trade and result.htf_trend in (TrendDirection.BULLISH, TrendDirection.BEARISH):
            result.trade_direction = result.htf_trend
        elif result.can_trade and result.ltf_trend in (TrendDirection.BULLISH, TrendDirection.BEARISH):
            result.trade_direction = result.ltf_trend

        # ── Entry timeframe selection ──
        result.entry_timeframe = self._select_entry_timeframe(analyses)

        # ── SL/TP suggestions ──
        result.stop_loss_pips, result.take_profit_pips = self._suggest_sl_tp(analyses)

        return result

    # ── Conflict Detection (THE CORE RULE) ────────────────────────

    def _is_htf_ltf_conflict(
        self,
        htf_trend: TrendDirection,
        ltf_trend: TrendDirection,
        analyses: dict[str, TimeframeAnalysis],
    ) -> bool:
        """Check if HTF and LTF disagree.

        True = CONFLICT → NO TRADE.
        The core rule: if D1/H4 says UP but H1/M15 says DOWN, stay out.

        Only applies when HTF has sufficient trend strength (>0.4).
        Neutral timeframes don't create conflicts.
        """
        # No conflict if either is unknown
        if htf_trend == TrendDirection.UNKNOWN or ltf_trend == TrendDirection.UNKNOWN:
            return False

        # No conflict if either is neutral
        if htf_trend == TrendDirection.NEUTRAL:
            return False
        if ltf_trend == TrendDirection.NEUTRAL:
            return False

        # Check HTF trend strength — strong HTF trend means we MUST follow it
        htf_strength = 0.0
        for tf in self.HIGHER_TF:
            if tf in analyses:
                a = analyses[tf]
                if a.trend == htf_trend:
                    htf_strength = max(htf_strength, a.trend_strength)

        # Only enforce conflict if HTF has meaningful trend strength
        if htf_strength < 0.3:
            return False

        # Conflict: HTF says BUY, LTF says SELL (or vice versa)
        return htf_trend != ltf_trend

    def _compute_alignment(
        self,
        htf_trend: TrendDirection,
        ltf_trend: TrendDirection,
        analyses: dict[str, TimeframeAnalysis],
    ) -> tuple[TimeframeAlignment, float]:
        """Compute alignment status and score across all timeframes."""
        # Collect non-unknown trends
        trends = []
        for a in analyses.values():
            if a.trend != TrendDirection.UNKNOWN:
                trends.append(a.trend)

        if len(trends) < 2:
            return TimeframeAlignment.UNKNOWN, 0.0

        # Count by direction
        bull_count = sum(1 for t in trends if t == TrendDirection.BULLISH)
        bear_count = sum(1 for t in trends if t == TrendDirection.BEARISH)
        neutral_count = sum(1 for t in trends if t == TrendDirection.NEUTRAL)

        total = len(trends)
        dominant = max(bull_count, bear_count, neutral_count)
        alignment_score = (dominant / total) * 100.0

        # Weight neutral timeframes
        if neutral_count > 0:
            alignment_score *= (1.0 - self.ALIGNMENT_SCORE_NEUTRAL_WEIGHT * neutral_count / total)

        if dominant == total:
            status = TimeframeAlignment.ALIGNED
        elif dominant >= total - 1:
            status = TimeframeAlignment.PARTIAL
        elif bull_count > 0 and bear_count > 0:
            status = TimeframeAlignment.CONFLICT
        else:
            status = TimeframeAlignment.PARTIAL

        return status, round(alignment_score, 1)

    def _select_entry_timeframe(
        self, analyses: dict[str, TimeframeAnalysis]
    ) -> str:
        """Select the best timeframe for entry execution.

        Prefer H1 (best balance of signal/noise), fall back to M15 or H4.
        """
        # Prefer H1 if available and not in extreme volatility
        h1 = analyses.get("H1")
        if h1 and h1.volatility_regime != VolatilityRegime.EXTREME:
            return "H1"

        # Fall to M15 if calm enough
        m15 = analyses.get("M15")
        if m15 and m15.volatility_regime != VolatilityRegime.EXTREME:
            return "M15"

        # Last resort: H4
        if "H4" in analyses:
            return "H4"

        return "H1"

    def _suggest_sl_tp(
        self,
        analyses: dict[str, TimeframeAnalysis],
    ) -> tuple[float, float]:
        """Suggest stop-loss and take-profit levels based on ATR and S/R.

        Returns:
            (stop_loss_pips, take_profit_pips)
        """
        # Use H1 ATR as base
        h1 = analyses.get("H1")
        h4 = analyses.get("H4")

        if h1 and h1.atr_value > 0:
            atr = h1.atr_value
        elif h4 and h4.atr_value > 0:
            atr = h4.atr_value
        else:
            return 0.0, 0.0

        # Convert ATR to pips (ATR is in price units)
        # For most pairs, 1 ATR unit ≈ 10,000 pips (if price = 1.xxxx)
        # Normalize: if price is ~1, multiply by 10000; if ~100, multiply by 100
        price = h1.current_price if h1 else (h4.current_price if h4 else 1.0)

        pip_factor = 10000 if price < 10 else (100 if price < 1000 else 1)
        atr_pips = atr * pip_factor

        # SL: 1.5x ATR
        sl_pips = round(atr_pips * 1.5, 1)

        # TP: 3x ATR (2:1 risk-reward minimum)
        tp_pips = round(atr_pips * 3.0, 1)

        # ── Refine with S/R levels ──
        if h1 and h1.sr_levels:
            sr_near = [lvl for lvl in h1.sr_levels
                       if abs(lvl - h1.current_price) / h1.current_price < 0.02]
            if sr_near:
                # Adjust SL to nearest S/R beyond ATR-based SL
                sl_price = h1.current_price - sl_pips / pip_factor
                for sr in sorted(sr_near):
                    if sr < sl_price:
                        sl_pips = round((h1.current_price - sr) * pip_factor, 1)
                        break

        return sl_pips, tp_pips

    # ── Technical Indicators (PURE MATH) ──────────────────────────

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray | None:
        """Exponential Moving Average."""
        if len(data) < period:
            return None
        alpha = 2.0 / (period + 1)
        ema = np.zeros(len(data))
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _rsi(self, closes: np.ndarray, period: int) -> float:
        """Relative Strength Index."""
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        return float(100.0 - 100.0 / (1.0 + rs))

    def _macd(
        self, closes: np.ndarray
    ) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        """MACD (12, 26, 9). Returns (macd_line, signal_line, histogram)."""
        if len(closes) < self.MACD_SLOW + self.MACD_SIGNAL:
            return None, None, None

        ema_fast = self._ema(closes, self.MACD_FAST)
        ema_slow = self._ema(closes, self.MACD_SLOW)

        if ema_fast is None or ema_slow is None:
            return None, None, None

        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, self.MACD_SIGNAL)

        if signal_line is None:
            return macd_line, None, None

        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _adx(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int
    ) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
        """Average Directional Index (ADX)."""
        if len(highs) < period + 1:
            return None, None, None

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        atr = np.zeros(len(tr))
        atr[0] = np.mean(tr[:period]) if len(tr) >= period else tr[0]
        for i in range(1, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_di = np.zeros(len(atr))
        minus_di = np.zeros(len(atr))

        # Smoothed +DI/-DI
        sm_plus_dm = np.zeros(len(atr))
        sm_minus_dm = np.zeros(len(atr))
        sm_atr = np.zeros(len(atr))

        if len(atr) >= period:
            sm_plus_dm[period - 1] = np.sum(plus_dm[:period])
            sm_minus_dm[period - 1] = np.sum(minus_dm[:period])
            sm_atr[period - 1] = np.sum(atr[:period])

            for i in range(period, len(atr)):
                sm_plus_dm[i] = sm_plus_dm[i - 1] - sm_plus_dm[i - 1] / period + plus_dm[i]
                sm_minus_dm[i] = sm_minus_dm[i - 1] - sm_minus_dm[i - 1] / period + minus_dm[i]
                sm_atr[i] = sm_atr[i - 1] - sm_atr[i - 1] / period + atr[i]

            for i in range(period - 1, len(atr)):
                if sm_atr[i] > 0:
                    plus_di[i] = 100.0 * sm_plus_dm[i] / sm_atr[i]
                    minus_di[i] = 100.0 * sm_minus_dm[i] / sm_atr[i]

        # DX = |+DI - -DI| / (+DI + -DI) * 100
        dx = np.zeros(len(atr))
        for i in range(len(atr)):
            denom = plus_di[i] + minus_di[i]
            if denom > 0:
                dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / denom

        # ADX = smoothed DX
        adx = np.zeros(len(dx))
        if len(dx) >= period:
            adx[period - 1] = np.mean(dx[:period])
            for i in range(period, len(dx)):
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

        return adx, plus_di, minus_di

    def _atr(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int
    ) -> float:
        """Average True Range — returns latest ATR value."""
        if len(highs) < 2:
            return 0.0

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        if len(tr) < period:
            return float(np.mean(tr))
        return float(np.mean(tr[-period:]))

    def _volatility_regime(
        self, closes: np.ndarray, atr: float
    ) -> tuple[VolatilityRegime, float]:
        """Classify current volatility regime."""
        if len(closes) < 20 or atr <= 0:
            return VolatilityRegime.NORMAL, 50.0

        # Historical ATR (rolling 20-bar averages)
        if len(closes) < 30:
            avg_atr = atr
        else:
            # Recompute ATR for historical windows
            hist_atrs = []
            for i in range(20, len(closes)):
                window_closes = closes[:i + 1]
                window_highs = window_closes  # approximation
                window_lows = window_closes
                hist_atrs.append(self._atr(window_highs, window_lows, window_closes, 14))
            avg_atr = np.mean(hist_atrs) if hist_atrs else atr

        if avg_atr <= 0:
            return VolatilityRegime.NORMAL, 50.0

        ratio = atr / avg_atr

        if ratio < 0.5:
            regime = VolatilityRegime.LOW
            percentile = max(0.0, ratio * 100)
        elif ratio < 1.5:
            regime = VolatilityRegime.NORMAL
            percentile = 25.0 + (ratio - 0.5) * 50
        elif ratio < 3.0:
            regime = VolatilityRegime.HIGH
            percentile = 75.0 + (ratio - 1.5) * 16.7
        else:
            regime = VolatilityRegime.EXTREME
            percentile = 95.0

        return regime, round(min(percentile, 100.0), 1)

    def _find_sr_levels(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> list[float]:
        """Find support and resistance levels from recent price action.

        Uses swing highs/lows detection with a simple peak-finding approach.
        Returns up to 4 levels (2 support, 2 resistance).
        """
        if len(highs) < 5:
            return []

        # Find swing highs and lows
        swing_highs = []
        swing_lows = []
        lookback = min(3, len(highs) // 3)

        for i in range(lookback, len(highs) - lookback):
            # Swing high
            is_swing_high = all(highs[i] >= highs[i - j] for j in range(1, lookback + 1)) and \
                            all(highs[i] >= highs[i + j] for j in range(1, lookback + 1))
            if is_swing_high:
                swing_highs.append(float(highs[i]))

            # Swing low
            is_swing_low = all(lows[i] <= lows[i - j] for j in range(1, lookback + 1)) and \
                           all(lows[i] <= lows[i + j] for j in range(1, lookback + 1))
            if is_swing_low:
                swing_lows.append(float(lows[i]))

        # Cluster nearby levels (within 0.5% of price)
        current = closes[-1]
        levels = []

        for sh in sorted(swing_highs, reverse=True)[:3]:
            if sh > current:
                # Avoid duplicate nearby levels
                if not levels or abs(sh - levels[-1]) / sh > 0.005:
                    levels.append(sh)
                    if len(levels) >= 2:
                        break

        levels.reverse()  # Higher levels first

        for sl in sorted(swing_lows)[:3]:
            if sl < current:
                if not levels or abs(sl - levels[-1]) / sl > 0.005:
                    levels.append(sl)
                    if len(levels) >= 4:
                        break

        return levels

    def _trend_duration(self, closes: np.ndarray) -> int:
        """Estimate bars since trend started (using SMA crossover)."""
        if len(closes) < 50:
            return 0

        sma_20 = np.convolve(closes, np.ones(20) / 20, mode='valid')
        sma_50 = np.convolve(closes, np.ones(50) / 50, mode='valid')

        # Align
        min_len = min(len(sma_20), len(sma_50))
        sma_20 = sma_20[-min_len:]
        sma_50 = sma_50[-min_len:]

        if len(sma_20) < 2:
            return 0

        # Find most recent crossover
        current_direction = sma_20[-1] > sma_50[-1]
        bars = 0
        for i in range(len(sma_20) - 2, -1, -1):
            if (sma_20[i] > sma_50[i]) != current_direction:
                bars = len(sma_20) - 1 - i
                break

        return bars if bars > 0 else len(closes)

    # ── Utility ────────────────────────────────────────────────────

    async def _fetch_bars(
        self, broker: Any, symbol: str, timeframe: str, count: int
    ) -> list[dict]:
        """Fetch bars from broker — mirrors ModernOrchestrator pattern."""
        import asyncio

        if hasattr(broker, 'bars') and callable(broker.bars):
            try:
                result = await broker.bars(symbol, timeframe, count)
                if result:
                    return list(result)
            except Exception:
                pass

        if hasattr(broker, 'get_candles') and callable(broker.get_candles):
            try:
                result = await asyncio.to_thread(
                    broker.get_candles, symbol, timeframe, count
                )
                if result:
                    return list(result)
            except Exception:
                pass

        if hasattr(broker, 'get_rates') and callable(broker.get_rates):
            try:
                result = await asyncio.to_thread(
                    broker.get_rates, symbol, timeframe, count
                )
                if result is not None:
                    if hasattr(result, 'to_dict'):
                        return result.to_dict('records')
                    if isinstance(result, list):
                        return result
            except Exception:
                pass

        return []

    # ── Static Helpers for External Use ────────────────────────────

    @staticmethod
    def is_htf_bullish(result: MultiTimeframeResult) -> bool:
        """Check if HTF trend is bullish."""
        return result.htf_trend == TrendDirection.BULLISH

    @staticmethod
    def is_htf_bearish(result: MultiTimeframeResult) -> bool:
        """Check if HTF trend is bearish."""
        return result.htf_trend == TrendDirection.BEARISH

    @staticmethod
    def entry_long_ok(result: MultiTimeframeResult) -> bool:
        """True if HTF bullish + LTF not bearish = LONG entry permitted."""
        return (
            result.can_trade
            and result.htf_trend == TrendDirection.BULLISH
            and result.ltf_trend != TrendDirection.BEARISH
        )

    @staticmethod
    def entry_short_ok(result: MultiTimeframeResult) -> bool:
        """True if HTF bearish + LTF not bullish = SHORT entry permitted."""
        return (
            result.can_trade
            and result.htf_trend == TrendDirection.BEARISH
            and result.ltf_trend != TrendDirection.BULLISH
        )
