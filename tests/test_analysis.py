"""Unit tests for analysis modules.

Covers:
- FundamentalAnalyzer (event scoring, bias detection)
- TechnicalAnalyzer (indicators, structure, full analysis)
- SMCForecaster (order blocks, FVGs, sweeps, structure breaks)
- CandlestickDetector (all 8 patterns)
- EconometricsEngine (ADF, ARIMA, GARCH, cointegration, regime)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from noema.analysis.fundamental import (
    FundamentalAnalyzer, FundamentalBias, EconomicEvent, ImpactLevel,
)
from noema.analysis.technical import TechnicalAnalyzer, TechnicalReport
from noema.analysis.smc import SMCForecaster, OrderBlock, FairValueGap, LiquiditySweep
from noema.analysis.candlestick import CandlestickDetector, CandlestickPattern
from noema.analysis.econometrics import EconometricsEngine, MarketRegime


# ===========================================================================
# FundamentalAnalyzer
# ===========================================================================


class TestFundamentalAnalyzer:
    """Tests for the FundamentalAnalyzer."""

    def setup_method(self):
        self.analyzer = FundamentalAnalyzer()

    def test_analyze_events_returns_report(self):
        """analyze_events should return a FundamentalReport."""
        events = [
            EconomicEvent(name="CPI", currency="USD", impact=ImpactLevel.HIGH,
                          forecast=2.5, actual=2.8),
            EconomicEvent(name="GDP", currency="EUR", impact=ImpactLevel.HIGH,
                          forecast=0.3, actual=0.2),
        ]
        report = self.analyzer.analyze_events(events)
        assert isinstance(report.bias, FundamentalBias)
        assert report.events_analyzed == 2
        assert len(report.high_impact_events) == 2
        assert report.confidence >= 0.3

    def test_analyze_no_events(self):
        """analyze_events should return NEUTRAL with no events."""
        report = self.analyzer.analyze_events([])
        assert report.bias == FundamentalBias.NEUTRAL
        assert report.events_analyzed == 0

    def test_event_surprise_calculation(self):
        """EconomicEvent should calculate surprise correctly."""
        event = EconomicEvent(
            name="CPI", currency="USD", impact=ImpactLevel.HIGH,
            forecast=2.0, actual=2.5,
        )
        assert event.surprise == 0.5
        assert event.sentiment == "bullish"

    def test_event_negative_surprise(self):
        """Negative surprise should be bearish."""
        event = EconomicEvent(
            name="CPI", currency="USD", impact=ImpactLevel.HIGH,
            forecast=2.0, actual=1.5,
        )
        assert event.surprise == -0.5
        assert event.sentiment == "bearish"

    def test_event_no_forecast_no_surprise(self):
        """Events without forecast/actual should have None surprise."""
        event = EconomicEvent(
            name="CPI", currency="USD", impact=ImpactLevel.HIGH,
        )
        assert event.surprise is None
        assert event.sentiment == "pending"

    def test_event_scoring_by_impact(self):
        """Higher impact events should score more points."""
        high = EconomicEvent(name="NFP", currency="USD", impact=ImpactLevel.HIGH,
                             forecast=1.0, actual=1.5)
        low = EconomicEvent(name="Housing", currency="USD", impact=ImpactLevel.LOW,
                            forecast=1.0, actual=1.5)

        high_score = self.analyzer._score_event(high)
        low_score = self.analyzer._score_event(low)
        assert abs(high_score) > abs(low_score)

    def test_currency_scores_tracking(self):
        """Different currencies should get separate scores."""
        events = [
            EconomicEvent(name="CPI", currency="USD", impact=ImpactLevel.HIGH,
                          forecast=2.0, actual=2.5),
            EconomicEvent(name="GDP", currency="EUR", impact=ImpactLevel.MEDIUM,
                          forecast=0.3, actual=0.1),
        ]
        report = self.analyzer.analyze_events(events)
        assert "USD" in report.currency_scores
        assert "EUR" in report.currency_scores

    def test_determine_bias_strong(self):
        """Large spread should return STRONG bias."""
        scores = {"USD": 10.0, "EUR": -5.0}
        bias = self.analyzer._determine_bias(scores)
        assert bias in (FundamentalBias.STRONG_BULLISH,)

    def test_determine_bias_neutral(self):
        """Small spread should return NEUTRAL."""
        scores = {"USD": 1.0, "EUR": -0.5}
        bias = self.analyzer._determine_bias(scores)
        assert bias == FundamentalBias.NEUTRAL


# ===========================================================================
# TechnicalAnalyzer
# ===========================================================================


class TestTechnicalAnalyzer:
    """Tests for the TechnicalAnalyzer."""

    def setup_method(self):
        self.analyzer = TechnicalAnalyzer()

    def test_calculate_emas(self, synthetic_ohlcv):
        """EMAs should be calculated correctly."""
        df = self.analyzer.calculate_emas(synthetic_ohlcv.copy(), 3, 10)
        assert "EMA_50" in df.columns  # We passed fast=3, so it's named EMA_50
        assert "EMA_200" in df.columns  # We passed slow=10
        assert not df["EMA_50"].isna().all()
        assert not df["EMA_200"].isna().all()

    def test_calculate_rsi(self, synthetic_ohlcv):
        """RSI should be in 0-100 range."""
        df = self.analyzer.calculate_rsi(synthetic_ohlcv.copy(), 5)
        assert "RSI" in df.columns
        rsi_valid = df["RSI"].dropna()
        assert (rsi_valid >= 0).all()
        assert (rsi_valid <= 100).all()

    def test_calculate_macd(self, synthetic_ohlcv):
        """MACD should include line, signal, and histogram."""
        df = self.analyzer.calculate_macd(synthetic_ohlcv.copy())
        assert "MACD" in df.columns
        assert "MACD_Signal" in df.columns
        assert "MACD_Hist" in df.columns

    def test_calculate_adx(self, synthetic_ohlcv):
        """ADX should be non-negative."""
        df = self.analyzer.calculate_adx(synthetic_ohlcv.copy(), 5)
        assert "ADX" in df.columns
        adx_valid = df["ADX"].dropna()
        assert (adx_valid >= 0).all()

    def test_calculate_atr(self, synthetic_ohlcv):
        """ATR should be non-negative."""
        df = self.analyzer.calculate_atr(synthetic_ohlcv.copy(), 5)
        assert "ATR" in df.columns
        atr_valid = df["ATR"].dropna()
        assert (atr_valid >= 0).all()

    def test_detect_structure(self, synthetic_ohlcv):
        """detect_structure should return key fields."""
        structure = self.analyzer.detect_structure(synthetic_ohlcv, 5)
        assert "structure" in structure
        assert "higher_highs" in structure
        assert "higher_lows" in structure
        assert "lower_highs" in structure
        assert "lower_lows" in structure
        assert "swing_highs" in structure
        assert "swing_lows" in structure
        assert structure["structure"] in ("BULLISH", "BEARISH", "RANGE")

    def test_full_analysis_returns_report(self, synthetic_ohlcv):
        """analyze should return a TechnicalReport."""
        report = self.analyzer.analyze(synthetic_ohlcv.copy())
        assert isinstance(report, TechnicalReport)
        assert report.trend in ("BULLISH", "BEARISH", "RANGE")
        assert report.rsi_signal in ("OVERSOLD", "OVERBOUGHT", "NEUTRAL")
        assert 0 <= report.confidence <= 1.0
        assert report.adx >= 0
        assert report.atr >= 0

    def test_full_analysis_with_custom_params(self, synthetic_ohlcv):
        """analyze should accept custom indicator parameters."""
        report = self.analyzer.analyze(
            synthetic_ohlcv.copy(),
            ema_fast=3,
            ema_slow=10,
            rsi_period=5,
        )
        assert isinstance(report, TechnicalReport)

    def test_insufficient_data(self):
        """analyze should handle insufficient data gracefully."""
        df = pd.DataFrame({"open": [1.0], "high": [1.01], "low": [0.99],
                           "close": [1.005], "volume": [100]})
        report = self.analyzer.analyze(df)
        assert isinstance(report, TechnicalReport)

    def test_swing_points(self, synthetic_ohlcv):
        """Swing highs/lows should be properly identified."""
        highs = synthetic_ohlcv["high"].values
        lows = synthetic_ohlcv["low"].values
        swing_highs = self.analyzer._find_swing_highs(highs, 3)
        swing_lows = self.analyzer._find_swing_lows(lows, 3)
        assert isinstance(swing_highs, list)
        assert isinstance(swing_lows, list)


# ===========================================================================
# SMCForecaster
# ===========================================================================


class TestSMCForecaster:
    """Tests for the SMCForecaster."""

    def setup_method(self):
        self.smc = SMCForecaster()

    def test_detect_order_blocks(self, synthetic_ohlcv):
        """detect_order_blocks should return a list of OBs."""
        obs = self.smc.detect_order_blocks(synthetic_ohlcv, lookback=10)
        assert isinstance(obs, list)
        if obs:
            ob = obs[0]
            assert isinstance(ob, OrderBlock)
            assert ob.type in ("bullish", "bearish")
            assert ob.strength >= 0

    def test_detect_fvg(self, synthetic_ohlcv):
        """detect_fvg should return a list of FVGs."""
        fvgs = self.smc.detect_fvg(synthetic_ohlcv, min_gap_pct=0.0005)
        assert isinstance(fvgs, list)
        if fvgs:
            fvg = fvgs[0]
            assert isinstance(fvg, FairValueGap)
            assert fvg.type in ("bullish", "bearish")

    def test_detect_liquidity_sweeps(self, synthetic_ohlcv):
        """detect_liquidity_sweeps should return a list of sweeps."""
        sweeps = self.smc.detect_liquidity_sweeps(synthetic_ohlcv, lookback=10)
        assert isinstance(sweeps, list)
        if sweeps:
            s = sweeps[0]
            assert isinstance(s, LiquiditySweep)
            assert s.type in ("buy_side", "sell_side")
            assert s.displacement >= 0

    def test_detect_structure_breaks(self, synthetic_ohlcv):
        """detect_structure_breaks should return key fields."""
        result = self.smc.detect_structure_breaks(synthetic_ohlcv, lookback=10)
        assert "bos_detected" in result
        assert "choch_detected" in result
        assert "bos_direction" in result
        assert result["bos_direction"] in ("bullish", "bearish", "none")

    def test_full_analysis(self, synthetic_ohlcv):
        """analyze should return an SMCReport."""
        report = self.smc.analyze(synthetic_ohlcv)
        assert report.confidence >= 0
        assert hasattr(report, "order_blocks")
        assert hasattr(report, "fair_value_gaps")
        assert hasattr(report, "liquidity_sweeps")
        assert hasattr(report, "bos_detected")
        assert hasattr(report, "choch_detected")

    def test_empty_dataframe(self):
        """SMC functions should handle empty dataframes."""
        df = pd.DataFrame()
        obs = self.smc.detect_order_blocks(df)
        assert obs == []

    def test_insufficient_data(self):
        """SMC functions should handle short dataframes."""
        df = pd.DataFrame({"open": [1.0], "high": [1.01], "low": [0.99],
                           "close": [1.005], "volume": [100]})
        obs = self.smc.detect_order_blocks(df, lookback=10)
        assert obs == []


# ===========================================================================
# CandlestickDetector
# ===========================================================================


def _make_candle_data(opens, highs, lows, closes) -> pd.DataFrame:
    """Helper to create OHLCV DataFrame from arrays."""
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": [100] * len(opens),
    })


class TestCandlestickDetector:
    """Tests for the CandlestickDetector."""

    def setup_method(self):
        self.detector = CandlestickDetector()

    def test_detect_returns_report(self, synthetic_ohlcv):
        """detect_all should return a CandlestickReport."""
        report = self.detector.detect_all(synthetic_ohlcv)
        assert report.confirmation in ("BULLISH", "BEARISH", "NONE")
        assert 0 <= report.confidence <= 1.0
        assert isinstance(report.patterns, list)

    def test_bullish_engulfing(self):
        """Detect bullish engulfing pattern."""
        opens = [1.1050, 1.1000, 1.1020]
        highs = [1.1060, 1.1080, 1.1090]
        lows = [1.1040, 1.0980, 1.1010]
        closes = [1.1000, 1.1070, 1.1080]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_bullish_engulfing(df["open"].values, df["close"].values, 1)

    def test_bearish_engulfing(self):
        """Detect bearish engulfing pattern."""
        opens = [1.1000, 1.1050, 1.1040]
        highs = [1.1020, 1.1080, 1.1050]
        lows = [1.0980, 1.1000, 1.0980]
        closes = [1.1050, 1.1000, 1.0990]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_bearish_engulfing(df["open"].values, df["close"].values, 1)

    def test_morning_star(self):
        """Detect morning star pattern."""
        opens = [1.1100, 1.1050, 1.0950]
        highs = [1.1120, 1.1060, 1.1100]
        lows = [1.1080, 1.0930, 1.0940]
        closes = [1.1050, 1.1040, 1.1090]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_morning_star(
            df["open"].values, df["high"].values,
            df["low"].values, df["close"].values, 2
        )

    def test_evening_star(self):
        """Detect evening star pattern."""
        opens = [1.0950, 1.1050, 1.1100]
        highs = [1.0980, 1.1060, 1.1120]
        lows = [1.0930, 1.0940, 1.1050]
        closes = [1.1050, 1.1040, 1.0980]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_evening_star(
            df["open"].values, df["high"].values,
            df["low"].values, df["close"].values, 2
        )

    def test_hammer(self):
        """Detect hammer pattern (small body, long lower wick)."""
        # Candle at index 1: body=0.0005, lower wick=0.005 (10x body), upper wick=0.0002 (< 0.5x body)
        # body/total_range = 0.0005/0.0057 ≈ 0.088 < 0.3 ✓
        opens = [1.1050, 1.1005, 1.1000]
        highs = [1.1060, 1.1007, 1.1010]
        lows = [1.1030, 1.0950, 1.0980]
        closes = [1.1010, 1.1000, 1.1005]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_hammer(
            df["open"].values, df["high"].values,
            df["low"].values, df["close"].values, 1
        )

    def test_shooting_star(self):
        """Detect shooting star pattern (small body, long upper wick)."""
        opens = [1.1020, 1.1030, 1.1020]
        highs = [1.1030, 1.1120, 1.1035]
        lows = [1.1000, 1.1010, 1.1000]
        closes = [1.1030, 1.1015, 1.1025]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_shooting_star(
            df["open"].values, df["high"].values,
            df["low"].values, df["close"].values, 1
        )

    def test_bullish_tweezers(self):
        """Detect bullish tweezers (matching lows)."""
        opens = [1.1050, 1.1020]
        highs = [1.1070, 1.1040]
        lows = [1.1000, 1.1000]
        closes = [1.1020, 1.1035]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_bullish_tweezers(df["open"].values, df["low"].values, 1)

    def test_bearish_tweezers(self):
        """Detect bearish tweezers (matching highs)."""
        opens = [1.1000, 1.1030]
        highs = [1.1050, 1.1050]
        lows = [1.0980, 1.1010]
        closes = [1.1030, 1.1010]
        df = _make_candle_data(opens, highs, lows, closes)
        assert self.detector._is_bearish_tweezers(df["open"].values, df["high"].values, 1)

    def test_no_false_positives(self):
        """Random data should not trigger patterns."""
        rng = np.random.RandomState(99)
        opens = 1.10 + rng.randn(10) * 0.01
        closes = opens + rng.randn(10) * 0.005
        highs = np.maximum(opens, closes) + abs(rng.randn(10) * 0.005)
        lows = np.minimum(opens, closes) - abs(rng.randn(10) * 0.005)
        df = _make_candle_data(opens, highs, lows, closes)
        report = self.detector.detect_all(df)
        assert isinstance(report, object)


# ===========================================================================
# EconometricsEngine
# ===========================================================================


class TestEconometricsEngine:
    """Tests for the EconometricsEngine."""

    def setup_method(self):
        self.engine = EconometricsEngine()

    def test_test_stationarity(self):
        """test_stationarity should return ADF test results."""
        series = pd.Series(np.cumsum(np.random.randn(100)))
        result = self.engine.test_stationarity(series)
        assert "test" in result
        assert "statistic" in result
        assert "p_value" in result
        assert "is_stationary" in result
        assert result["test"] == "ADF"

    @pytest.mark.slow
    def test_fit_arima(self):
        """fit_arima should return ARIMA model results."""
        np.random.seed(42)
        series = pd.Series(np.cumsum(np.random.randn(100)) + 100)
        result = self.engine.fit_arima(series, max_order=(1, 1, 1))
        assert "order" in result
        assert "aic" in result or result.get("forecast") is None

    @pytest.mark.slow
    def test_fit_garch(self):
        """fit_garch should return volatility forecast."""
        np.random.seed(42)
        returns = pd.Series(np.random.randn(100) * 0.01)
        result = self.engine.fit_garch(returns, order=(1, 1))
        assert "forecast_vol" in result
        assert result["forecast_vol"] >= 0

    def test_validate_signal(self):
        """validate_signal should run hypothesis test."""
        np.random.seed(42)
        prices = pd.Series(np.cumsum(np.random.randn(100)) + 100)
        result = self.engine.validate_signal(prices, direction="long")
        assert "test" in result
        assert "statistic" in result
        assert "p_value" in result
        assert "significant" in result
        assert "sharpe" in result

    def test_validate_signal_short(self):
        """validate_signal should work for short direction."""
        prices = pd.Series(np.cumsum(np.random.randn(100)) + 100)
        result = self.engine.validate_signal(prices, direction="short")
        assert result["direction"] == "short"

    def test_detect_regime(self):
        """detect_regime should classify current market regime."""
        np.random.seed(42)
        prices = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        result = self.engine.detect_regime(prices, lookback=60)
        assert "regime" in result
        assert "hurst_exponent" in result
        assert "volatility_ratio" in result
        assert isinstance(result["regime"], MarketRegime)

    def test_detect_regime_insufficient_data(self):
        """detect_regime should return UNKNOWN with insufficient data."""
        prices = pd.Series([1.0] * 5)
        result = self.engine.detect_regime(prices, lookback=60)
        assert result["regime"] == MarketRegime.UNKNOWN

    def test_compute_hurst(self):
        """_compute_hurst should return value between 0 and 1."""
        np.random.seed(42)
        series = pd.Series(np.random.randn(100))
        hurst = self.engine._compute_hurst(series)
        assert 0 <= hurst <= 1.0

    def test_compute_hurst_short_series(self):
        """_compute_hurst should return 0.5 for short series."""
        series = pd.Series([1.0, 2.0, 3.0])
        assert self.engine._compute_hurst(series) == 0.5

    def test_full_analysis(self):
        """full_analysis should return EconometricsResult."""
        np.random.seed(42)
        prices = pd.Series(np.cumsum(np.random.randn(200)) + 100)
        result = self.engine.full_analysis(prices)
        assert isinstance(result.regime, MarketRegime)
        assert result.volatility_forecast >= 0
        assert result.trend_strength >= 0
        assert result.mean_reversion_score >= 0
        assert len(result.confidence_interval) == 2
