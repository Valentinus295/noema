"""Technical analysis module for Noema.

Uses TA-Lib (C-speed) for classical indicators and custom logic
for Smart Money Concepts (SMC).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TechnicalReport:
    """Output from technical analysis."""
    trend: str = "NEUTRAL"              # BULLISH, BEARISH, RANGE
    ema_50: float = 0.0
    ema_200: float = 0.0
    price_above_ema50: bool = False
    price_above_ema200: bool = False
    ema50_above_ema200: bool = False
    rsi: float = 50.0
    rsi_signal: str = "NEUTRAL"         # OVERSOLD, OVERBOUGHT, NEUTRAL
    macd: float = 0.0
    macd_signal_line: float = 0.0
    macd_histogram: float = 0.0
    adx: float = 0.0
    atr: float = 0.0
    higher_highs: bool = False
    higher_lows: bool = False
    lower_highs: bool = False
    lower_lows: bool = False
    reasoning: str = ""
    confidence: float = 0.0


class TechnicalAnalyzer:
    """Classical technical analysis using TA-Lib and pandas.

    Provides:
    - EMA 50/200 crossover analysis
    - RSI overbought/oversold detection
    - MACD momentum analysis
    - ADX trend strength
    - ATR volatility measurement
    - Market structure (HH/HL/LH/LL)
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="technical")
        self._use_talib = self._check_talib()

    def _check_talib(self) -> bool:
        """Check if TA-Lib is available."""
        try:
            import talib
            return True
        except ImportError:
            self._logger.warning("talib_not_installed", fallback="pandas_ta")
            return False

    # ------------------------------------------------------------------
    # Core Indicators
    # ------------------------------------------------------------------

    def calculate_emas(self, df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
        """Calculate EMA 50 and EMA 200."""
        if self._use_talib:
            import talib
            df["EMA_50"] = talib.EMA(df["close"], timeperiod=fast)
            df["EMA_200"] = talib.EMA(df["close"], timeperiod=slow)
        else:
            df["EMA_50"] = df["close"].ewm(span=fast, adjust=False).mean()
            df["EMA_200"] = df["close"].ewm(span=slow, adjust=False).mean()
        return df

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Calculate RSI."""
        if self._use_talib:
            import talib
            df["RSI"] = talib.RSI(df["close"], timeperiod=period)
        else:
            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            df["RSI"] = 100 - (100 / (1 + rs))
        return df

    def calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate MACD, Signal, and Histogram."""
        if self._use_talib:
            import talib
            df["MACD"], df["MACD_Signal"], df["MACD_Hist"] = talib.MACD(df["close"])
        else:
            ema12 = df["close"].ewm(span=12, adjust=False).mean()
            ema26 = df["close"].ewm(span=26, adjust=False).mean()
            df["MACD"] = ema12 - ema26
            df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
            df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
        return df

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Calculate Average Directional Index."""
        if self._use_talib:
            import talib
            df["ADX"] = talib.ADX(df["high"], df["low"], df["close"], timeperiod=period)
        else:
            plus_dm = df["high"].diff()
            minus_dm = -df["low"].diff()
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0

            tr = self._true_range(df)
            atr = tr.rolling(period).mean()

            plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
            minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            df["ADX"] = dx.rolling(period).mean()
        return df

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Calculate Average True Range."""
        if self._use_talib:
            import talib
            df["ATR"] = talib.ATR(df["high"], df["low"], df["close"], timeperiod=period)
        else:
            df["ATR"] = self._true_range(df).rolling(period).mean()
        return df

    # ------------------------------------------------------------------
    # Market Structure
    # ------------------------------------------------------------------

    def detect_structure(self, df: pd.DataFrame, lookback: int = 20) -> dict[str, Any]:
        """Detect market structure (HH/HL/LH/LL).

        Returns swing points and current structure classification.
        """
        highs = df["high"].tail(lookback * 2).values
        lows = df["low"].tail(lookback * 2).values

        swing_highs = self._find_swing_highs(highs, lookback)
        swing_lows = self._find_swing_lows(lows, lookback)

        # Determine structure
        hh = hl = lh = ll = False

        if len(swing_highs) >= 2:
            hh = swing_highs[-1] > swing_highs[-2]
            lh = swing_highs[-1] < swing_highs[-2]

        if len(swing_lows) >= 2:
            hl = swing_lows[-1] > swing_lows[-2]
            ll = swing_lows[-1] < swing_lows[-2]

        if hh and hl:
            structure = "BULLISH"
        elif lh and ll:
            structure = "BEARISH"
        else:
            structure = "RANGE"

        return {
            "structure": structure,
            "higher_highs": hh,
            "higher_lows": hl,
            "lower_highs": lh,
            "lower_lows": ll,
            "swing_highs": swing_highs[-4:],
            "swing_lows": swing_lows[-4:],
        }

    # ------------------------------------------------------------------
    # Full Analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        df: pd.DataFrame,
        ema_fast: int = 50,
        ema_slow: int = 200,
        rsi_period: int = 14,
    ) -> TechnicalReport:
        """Run complete technical analysis on OHLCV data."""
        df = df.copy()

        # Calculate all indicators
        df = self.calculate_emas(df, ema_fast, ema_slow)
        df = self.calculate_rsi(df, rsi_period)
        df = self.calculate_macd(df)
        df = self.calculate_adx(df)
        df = self.calculate_atr(df)

        # Get latest values
        latest = df.iloc[-1]
        price = latest["close"]

        # Market structure
        structure = self.detect_structure(df)

        # Trend determination
        price_above_ema50 = price > latest["EMA_50"]
        price_above_ema200 = price > latest["EMA_200"]
        ema50_above_ema200 = latest["EMA_50"] > latest["EMA_200"]

        if price_above_ema50 and price_above_ema200 and ema50_above_ema200 and structure["structure"] == "BULLISH":
            trend = "BULLISH"
        elif not price_above_ema50 and not price_above_ema200 and not ema50_above_ema200 and structure["structure"] == "BEARISH":
            trend = "BEARISH"
        else:
            trend = "RANGE"

        # RSI signal
        rsi_val = latest["RSI"]
        if rsi_val <= 30:
            rsi_signal = "OVERSOLD"
        elif rsi_val >= 70:
            rsi_signal = "OVERBOUGHT"
        else:
            rsi_signal = "NEUTRAL"

        # Confidence
        confidence = 0.0
        if trend != "RANGE":
            confidence += 0.3
        if structure["structure"] != "RANGE":
            confidence += 0.2
        if rsi_signal != "NEUTRAL":
            confidence += 0.15
        if latest["ADX"] > 25:
            confidence += 0.15
        if latest["MACD_Hist"] > 0 and trend == "BULLISH":
            confidence += 0.1
        elif latest["MACD_Hist"] < 0 and trend == "BEARISH":
            confidence += 0.1

        return TechnicalReport(
            trend=trend,
            ema_50=float(latest["EMA_50"]),
            ema_200=float(latest["EMA_200"]),
            price_above_ema50=price_above_ema50,
            price_above_ema200=price_above_ema200,
            ema50_above_ema200=ema50_above_ema200,
            rsi=float(rsi_val),
            rsi_signal=rsi_signal,
            macd=float(latest["MACD"]),
            macd_signal_line=float(latest["MACD_Signal"]),
            macd_histogram=float(latest["MACD_Hist"]),
            adx=float(latest["ADX"]),
            atr=float(latest["ATR"]),
            higher_highs=structure["higher_highs"],
            higher_lows=structure["higher_lows"],
            lower_highs=structure["lower_highs"],
            lower_lows=structure["lower_lows"],
            reasoning=self._build_reasoning(trend, structure, rsi_signal, latest),
            confidence=min(1.0, confidence),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _true_range(self, df: pd.DataFrame) -> pd.Series:
        """Calculate True Range."""
        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift())
        low_close = abs(df["low"] - df["close"].shift())
        return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    def _find_swing_highs(self, highs: np.ndarray, lookback: int) -> list[float]:
        """Find swing highs in price data."""
        swings = []
        for i in range(lookback, len(highs) - lookback):
            if highs[i] == max(highs[i - lookback:i + lookback + 1]):
                swings.append(float(highs[i]))
        return swings

    def _find_swing_lows(self, lows: np.ndarray, lookback: int) -> list[float]:
        """Find swing lows in price data."""
        swings = []
        for i in range(lookback, len(lows) - lookback):
            if lows[i] == min(lows[i - lookback:i + lookback + 1]):
                swings.append(float(lows[i]))
        return swings

    def _build_reasoning(self, trend: str, structure: dict, rsi_signal: str, latest: pd.Series) -> str:
        """Build human-readable technical reasoning."""
        parts = [f"Trend: {trend}"]
        parts.append(f"Structure: {structure['structure']}")

        if structure["higher_highs"] and structure["higher_lows"]:
            parts.append("  Making Higher Highs & Higher Lows")
        elif structure["lower_highs"] and structure["lower_lows"]:
            parts.append("  Making Lower Highs & Lower Lows")

        parts.append(f"Price vs EMA50: {'Above' if latest['close'] > latest['EMA_50'] else 'Below'}")
        parts.append(f"Price vs EMA200: {'Above' if latest['close'] > latest['EMA_200'] else 'Below'}")
        parts.append(f"EMA50 vs EMA200: {'Bullish cross' if latest['EMA_50'] > latest['EMA_200'] else 'Bearish cross'}")
        parts.append(f"RSI: {latest['RSI']:.1f} ({rsi_signal})")
        parts.append(f"MACD Histogram: {latest['MACD_Hist']:.5f}")
        parts.append(f"ADX: {latest['ADX']:.1f} ({'Trending' if latest['ADX'] > 25 else 'Weak'})")

        return "\n".join(parts)
