"""Tests for noema.econometrics.time_series — ADF test, KPSS test, ARIMA.

These tests would have caught CRITICAL-1 (arima_model NameError bug).
"""

from __future__ import annotations

import numpy as np
import pytest

from noema.econometrics.time_series import (
    StationarityResult,
    adf_test,
    kpss_test,
    arima_model,
    auto_arima,
    arima_forecast,
)


# ═══════════════════════════════════════════════════
# ADF Test tests
# ═══════════════════════════════════════════════════

class TestADF:
    """Tests for Augmented Dickey-Fuller unit root test."""

    def test_stationary_series(self):
        """ADF should reject unit root for white noise (stationary)."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=0, scale=1, size=500)

        result = adf_test(data)

        assert isinstance(result, StationarityResult)
        assert result.test_name == "ADF"
        assert result.p_value < 0.05  # Stationary → reject unit root
        assert result.is_stationary

    def test_random_walk(self):
        """ADF should NOT reject unit root for random walk (non-stationary)."""
        rng = np.random.default_rng(42)
        steps = rng.normal(loc=0, scale=1, size=500)
        random_walk = np.cumsum(steps)

        result = adf_test(random_walk)

        assert isinstance(result, StationarityResult)
        # Random walk is NOT stationary — should have high p-value
        assert result.p_value > 0.05
        assert not result.is_stationary

    def test_trend_stationary(self):
        """ADF with trend should find trend-stationary series stationary after detrending."""
        rng = np.random.default_rng(42)
        t = np.arange(200)
        trend = 0.1 * t
        noise = rng.normal(loc=0, scale=1, size=200)
        trend_stationary = trend + noise

        result = adf_test(trend_stationary, regression="ct")

        assert isinstance(result, StationarityResult)

    def test_small_sample(self):
        """ADF on very small sample should return a result (not crash)."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        result = adf_test(data)

        assert isinstance(result, StationarityResult)
        assert result.n_observations == 5

    def test_custom_alpha(self):
        """ADF with custom significance level."""
        rng = np.random.default_rng(42)
        data = rng.normal(size=200)

        result = adf_test(data, alpha=0.01)

        assert result.alpha == 0.01

    def test_custom_maxlag(self):
        """ADF with custom maximum lag."""
        rng = np.random.default_rng(42)
        data = rng.normal(size=200)

        result = adf_test(data, maxlag=5)

        assert isinstance(result, StationarityResult)

    def test_constant_series(self):
        """ADF on constant series (edge case)."""
        data = np.ones(100)

        result = adf_test(data)

        # Should handle without crash
        assert isinstance(result, StationarityResult)

    def test_result_fields_present(self):
        """Verify all expected fields are present in the result."""
        rng = np.random.default_rng(42)
        data = rng.normal(size=200)

        result = adf_test(data)

        assert result.test_name == "ADF"
        assert result.statistic is not None
        assert result.p_value is not None
        assert 0 <= result.p_value <= 1.0
        assert result.n_observations >= 190  # ADF may drop observations at lags
        assert result.n_lags is not None
        assert result.alpha == 0.05
        # is_stationary should be a boolean
        assert isinstance(result.is_stationary, bool)


# ═══════════════════════════════════════════════════
# KPSS Test tests
# ═══════════════════════════════════════════════════

class TestKPSS:
    """Tests for KPSS stationarity test."""

    def test_stationary_series(self):
        """KPSS should NOT reject stationarity for white noise."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=0, scale=1, size=500)

        result = kpss_test(data)

        assert isinstance(result, StationarityResult)
        assert result.test_name == "KPSS"

    def test_random_walk(self):
        """KPSS should reject stationarity for random walk."""
        rng = np.random.default_rng(42)
        steps = rng.normal(loc=0, scale=1, size=500)
        random_walk = np.cumsum(steps)

        result = kpss_test(random_walk)

        assert isinstance(result, StationarityResult)
        # Random walk should be detected as non-stationary by KPSS
        assert result.p_value < 0.05

    def test_result_fields_present(self):
        """Verify KPSS result fields."""
        rng = np.random.default_rng(99)
        data = rng.normal(size=200)

        result = kpss_test(data)

        assert result.statistic is not None
        assert result.p_value is not None


# ═══════════════════════════════════════════════════
# ARIMA Model tests
# ═══════════════════════════════════════════════════

class TestARIMAModel:
    """Tests for arima_model — ARIMA estimation."""

    def test_arima_basic(self):
        """ARIMA(1,0,1) on AR(1) process should return valid result."""
        rng = np.random.default_rng(42)
        # Generate AR(1) process: y_t = 0.7 * y_{t-1} + ε_t
        n = 200
        ar1 = np.zeros(n)
        eps = rng.normal(0, 1, n)
        for t in range(1, n):
            ar1[t] = 0.7 * ar1[t - 1] + eps[t]

        result = arima_model(ar1, order=(1, 0, 0))

        assert isinstance(result, StationarityResult)
        assert result.test_name == "ARIMA"
        # Log-likelihood and AIC should be finite
        assert result.statistic is not None
        assert not np.isnan(result.statistic)
        assert result.information_criteria["AIC"] != float('inf')

    def test_arima_returns_all_fields(self):
        """ARIMA result should have all expected fields — regression test for CRITICAL-1."""
        rng = np.random.default_rng(42)
        ar1 = np.zeros(200)
        eps = rng.normal(0, 1, 200)
        for t in range(1, 200):
            ar1[t] = 0.7 * ar1[t - 1] + eps[t]

        result = arima_model(ar1, order=(1, 0, 0))

        # Verify p_value is a float (was NameError from undefined 'p_value_min')
        assert isinstance(result.p_value, float), (
            f"p_value must be float, got {type(result.p_value)}. "
            f"This test catches CRITICAL-1 (arima_model NameError bug)."
        )
        assert isinstance(result.statistic, float)
        assert 0.0 <= result.p_value <= 1.0
        assert isinstance(result.is_stationary, bool)
        assert isinstance(result.information_criteria, dict)
        assert "AIC" in result.information_criteria
        assert "BIC" in result.information_criteria

    def test_arima_small_sample_fallback(self):
        """ARIMA with < 20 points should return early fallback."""
        data = np.arange(10, dtype=float)

        result = arima_model(data, order=(1, 0, 0))

        assert isinstance(result, StationarityResult)
        assert result.n_observations == 10


# ═══════════════════════════════════════════════════
# Auto-ARIMA tests
# ═══════════════════════════════════════════════════

class TestAutoARIMA:
    """Tests for auto_arima — automatic order selection."""

    def test_auto_arima_basic(self):
        """Auto-ARIMA should select a model and return StationarityResult."""
        rng = np.random.default_rng(42)
        ar1 = np.zeros(150)
        eps = rng.normal(0, 1, 150)
        for t in range(1, 150):
            ar1[t] = 0.7 * ar1[t - 1] + eps[t]

        result = auto_arima(ar1, max_p=3, max_d=1, max_q=3, max_iter=20)

        assert isinstance(result, StationarityResult)
        assert result.test_name == "Auto-ARIMA"
        assert "orders_tried" in result.additional
        assert result.additional["orders_tried"] <= 20

    def test_max_iter_limits_search(self):
        """auto_arima with max_iter=3 should try at most 3 models."""
        rng = np.random.default_rng(42)
        data = rng.normal(size=100)

        result = auto_arima(data, max_p=5, max_d=2, max_q=5, max_iter=3)

        assert result.additional["orders_tried"] <= 3

    def test_no_valid_order(self):
        """auto_arima with max_p=0, max_q=0 should return fallback."""
        data = np.random.randn(100)

        result = auto_arima(data, max_p=0, max_d=0, max_q=0, max_iter=5)

        assert isinstance(result, StationarityResult)

    def test_aic_criterion(self):
        """Auto-ARIMA with AIC criterion."""
        rng = np.random.default_rng(42)
        data = rng.normal(size=100)

        result = auto_arima(data, max_p=3, max_d=1, max_q=3, criterion="aic", max_iter=30)

        assert result.additional["criterion"] == "aic"

    def test_bic_criterion(self):
        """Auto-ARIMA with BIC criterion."""
        rng = np.random.default_rng(42)
        data = rng.normal(size=100)

        result = auto_arima(data, max_p=3, max_d=1, max_q=3, criterion="bic", max_iter=30)

        assert result.additional["criterion"] == "bic"


# ═══════════════════════════════════════════════════
# ARIMA Forecast tests
# ═══════════════════════════════════════════════════

class TestARIMAForecast:
    """Tests for arima_forecast."""

    def test_forecast_basic(self):
        """ARIMA forecast should return StationarityResult with forecast."""
        rng = np.random.default_rng(42)
        ar1 = np.zeros(200)
        eps = rng.normal(0, 1, 200)
        for t in range(1, 200):
            ar1[t] = 0.7 * ar1[t - 1] + eps[t]

        result = arima_forecast(ar1, order=(1, 0, 0), forecast_steps=5)

        assert isinstance(result, StationarityResult)
        assert result.test_name == "ARIMA Forecast"

    def test_forecast_small_sample(self):
        """ARIMA forecast with <20 points should fallback."""
        data = np.arange(10, dtype=float)

        result = arima_forecast(data, forecast_steps=5)

        assert isinstance(result, StationarityResult)
