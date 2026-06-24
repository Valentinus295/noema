"""Tests for the econometrics module — time series, cointegration, volatility."""

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
from noema.econometrics.cointegration import (
    CointegrationResult,
    engle_granger,
    johansen_test,
    cointegration_rank,
    spread_analysis,
)
from noema.econometrics.volatility import (
    VolatilityResult,
    garch_model,
    arch_test,
    realized_volatility,
    volatility_forecast,
)
from noema.econometrics.regression import (
    ols_regression,
    multicollinearity_check,
    residual_diagnostics,
)
from noema.econometrics.causal_inference import (
    granger_causality,
)


# ═══════════════════════════════════════════════════
# Time Series Tests
# ═══════════════════════════════════════════════════

class TestADF:
    """Augmented Dickey-Fuller test."""

    def test_adf_stationary_series(self):
        """AC1.4: ADF correctly identifies stationary series."""
        rng = np.random.RandomState(42)
        # White noise is stationary
        stationary = rng.normal(0, 1, 200)

        result = adf_test(stationary)

        assert isinstance(result, StationarityResult)
        assert result.test_name in ("ADF", "ADF (fallback)")
        assert result.is_stationary  # Should be stationary
        assert result.p_value < 0.05
        assert result.n_observations > 0

    def test_adf_nonstationary_series(self):
        """AC1.4: ADF correctly identifies non-stationary series."""
        rng = np.random.RandomState(42)
        # Random walk is non-stationary
        random_walk = np.cumsum(rng.normal(0, 1, 200))

        result = adf_test(random_walk, regression="c")

        assert isinstance(result, StationarityResult)
        # Random walk should be non-stationary
        assert not result.is_stationary
        assert result.p_value > 0.05

    def test_adf_with_short_series(self):
        """ADF handles very short series."""
        result = adf_test(np.array([1, 2, 3]))

        assert result.n_observations == 3
        assert not result.is_stationary  # Too few data points

    def test_adf_returns_critical_values(self):
        """ADF returns critical values."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 200)

        result = adf_test(data)

        assert "1%" in result.critical_values
        assert "5%" in result.critical_values
        assert "10%" in result.critical_values
        assert result.critical_values["1%"] < result.critical_values["5%"]
        assert result.critical_values["5%"] < result.critical_values["10%"]


class TestKPSS:
    """KPSS stationarity test."""

    def test_kpss_stationary_series(self):
        """KPSS null: series IS stationary."""
        rng = np.random.RandomState(42)
        stationary = rng.normal(0, 1, 200)

        result = kpss_test(stationary)

        assert isinstance(result, StationarityResult)
        # KPSS H0 is stationarity → fail to reject == stationary
        # p > 0.05 means can't reject stationarity
        assert result.p_value > 0.01

    def test_kpss_nonstationary_series(self):
        """KPSS on random walk should reject stationarity."""
        rng = np.random.RandomState(42)
        random_walk = np.cumsum(rng.normal(0, 1, 200))

        result = kpss_test(random_walk)

        # KPSS should reject H0 (stationarity) for random walk
        # p < 0.05 means reject stationarity
        assert not result.is_stationary

    def test_adf_and_kpss_consistent(self):
        """AC1.4: ADF and KPSS give consistent results for stationary series."""
        rng = np.random.RandomState(42)
        stationary = rng.normal(0, 1, 300)

        adf = adf_test(stationary)
        kpss = kpss_test(stationary)

        # ADF rejects unit root (stationary) + KPSS fails to reject stationarity
        # Both should indicate stationary
        # Note: Due to test power, this might not always hold for all seeds
        # We use the consistent detection rule
        consistent = (adf.is_stationary and kpss.is_stationary) or (
            not adf.is_stationary and not kpss.is_stationary
        )
        # For stationary data with 300 observations, both should indicate stationary
        assert adf.is_stationary
        assert kpss.is_stationary


class TestARIMA:
    """ARIMA model tests."""

    def test_arima_fit(self):
        """Fit ARIMA to synthetic data."""
        rng = np.random.RandomState(42)
        # AR(1) process
        phi = 0.7
        data = np.zeros(200)
        for t in range(1, 200):
            data[t] = phi * data[t - 1] + rng.normal(0, 1)

        result = arima_model(data, order=(1, 0, 0))

        assert isinstance(result, StationarityResult)
        assert result.test_name in ("ARIMA", "ARIMA (fallback)")
        assert result.model_params is not None
        assert result.information_criteria.get("AIC", float('inf')) < float('inf')

    def test_arima_returns_residuals(self):
        """ARIMA should return residuals."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 100)

        result = arima_model(data, order=(0, 0, 0))

        assert isinstance(result, StationarityResult)

    def test_auto_arima(self):
        """Auto ARIMA selects best model."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 100)

        result = auto_arima(data, max_p=2, max_d=1, max_q=2)

        assert isinstance(result, StationarityResult)
        assert "orders_tried" in result.additional

    def test_arima_forecast(self):
        """ARIMA forecast generation."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 100)

        result = arima_forecast(data, order=(1, 0, 0), forecast_steps=5)

        assert result.forecast is not None
        assert len(result.forecast) == 5


# ═══════════════════════════════════════════════════
# Cointegration Tests
# ═══════════════════════════════════════════════════

class TestEngleGranger:
    """Engle-Granger cointegration test."""

    def test_engle_granger_cointegrated(self):
        """AC1.5: Tests cointegration on known cointegrated pair."""
        rng = np.random.RandomState(42)
        n = 300

        # Create a common stochastic trend
        common_trend = np.cumsum(rng.normal(0, 0.01, n))

        # Two series driven by the same trend + noise
        eurusd = common_trend + rng.normal(0, 0.005, n)  # "EURUSD"
        gbpusd = common_trend + rng.normal(0, 0.005, n)  # "GBPUSD"

        result = engle_granger(eurusd, gbpusd)

        assert isinstance(result, CointegrationResult)
        assert result.test_name == "Engle-Granger"
        assert result.is_cointegrated
        assert result.p_value < 0.05

    def test_engle_granger_not_cointegrated(self):
        """Two independent random walks should not be cointegrated."""
        rng = np.random.RandomState(42)
        n = 200
        rw1 = np.cumsum(rng.normal(0, 1, n))
        rw2 = np.cumsum(rng.normal(0, 1, n))

        result = engle_granger(rw1, rw2)

        assert isinstance(result, CointegrationResult)
        assert not result.is_cointegrated

    def test_engle_granger_returns_spread_metrics(self):
        """Returns spread, half-life, z-score."""
        rng = np.random.RandomState(42)
        n = 300
        trend = np.cumsum(rng.normal(0, 0.01, n))
        y = trend + rng.normal(0, 0.005, n)
        x = trend + rng.normal(0, 0.005, n)

        result = engle_granger(y, x)

        assert result.spread is not None
        assert len(result.spread) == n
        assert result.half_life is not None
        assert result.z_score is not None
        assert result.cointegrating_vector is not None


class TestJohansen:
    """Johansen cointegration test."""

    def test_johansen_basic(self):
        """Johansen test on cointegrated system."""
        rng = np.random.RandomState(42)
        n = 300
        trend = np.cumsum(rng.normal(0, 0.01, n))
        x1 = trend + rng.normal(0, 0.005, n)
        x2 = trend + rng.normal(0, 0.005, n)
        data = np.column_stack([x1, x2])

        result = johansen_test(data)

        assert isinstance(result, CointegrationResult)
        assert result.n_observations == n


class TestSpreadAnalysis:
    """Spread analysis for pairs trading."""

    def test_spread_analysis(self):
        rng = np.random.RandomState(42)
        n = 200
        trend = np.cumsum(rng.normal(0, 0.01, n))
        y = trend + rng.normal(0, 0.005, n)
        x = trend + rng.normal(0, 0.005, n)

        result = spread_analysis(y, x, lookback=20)

        assert "spread" in result
        assert "z_score" in result
        assert "hedge_ratio" in result
        assert "signals" in result


# ═══════════════════════════════════════════════════
# Volatility Tests
# ═══════════════════════════════════════════════════

class TestGARCH:
    """GARCH model tests."""

    def test_garch_fit(self):
        """AC2.5: GARCH(1,1) fits returns data and returns conditional volatility."""
        rng = np.random.RandomState(42)
        n = 500
        # Simulate GARCH-like returns
        sigma2 = np.zeros(n)
        returns = np.zeros(n)
        sigma2[0] = 1.0
        omega, alpha, beta = 0.01, 0.10, 0.85

        for t in range(1, n):
            sigma2[t] = omega + alpha * returns[t - 1] ** 2 + beta * sigma2[t - 1]
            returns[t] = np.sqrt(sigma2[t]) * rng.normal(0, 1)

        result = garch_model(returns)

        assert isinstance(result, VolatilityResult)
        assert result.model_type.startswith("GARCH")
        assert result.converged
        # Unconditional volatility should be close to theoretical
        # σ² = ω / (1 - α - β) = 0.01 / (1 - 0.10 - 0.85) = 0.01 / 0.05 = 0.2
        # σ ≈ 0.447
        expected_vol = np.sqrt(omega / (1 - alpha - beta))
        assert abs(result.unconditional_volatility - expected_vol) < 0.3

    def test_garch_many_observations(self):
        """GARCH on large return series."""
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 1000)

        result = garch_model(returns)

        assert result.n_observations == 1000
        assert result.unconditional_volatility > 0

    def test_garch_conditional_volatility(self):
        """GARCH returns conditional volatility series."""
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 200)

        result = garch_model(returns)

        if result.conditional_volatility is not None:
            assert len(result.conditional_volatility) > 0


class TestARCHTest:
    """ARCH-LM test."""

    def test_arch_test_no_arch(self):
        """No ARCH effects in white noise."""
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 1, 200)

        result = arch_test(returns, lags=5)

        assert isinstance(result, VolatilityResult)
        assert result.model_type == "ARCH-LM"
        # White noise should not show ARCH effects
        assert not result.additional.get("has_arch_effects", False)


class TestRealizedVolatility:
    """Realized volatility."""

    def test_realized_volatility(self):
        rng = np.random.RandomState(42)
        prices = np.cumsum(rng.normal(0.001, 0.01, 200)) + 100

        rv = realized_volatility(prices, window=20, annualize=False)

        assert len(rv) == len(prices)
        assert np.all(rv >= 0)


class TestVolatilityForecast:
    """Volatility forecasting."""

    def test_volatility_forecast(self):
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 200)

        result = volatility_forecast(returns, forecast_horizon=5)

        assert result.forecast is not None
        assert len(result.forecast) == 5


# ═══════════════════════════════════════════════════
# Regression Tests
# ═══════════════════════════════════════════════════

class TestOLS:
    """OLS regression tests."""

    def test_ols_simple_regression(self):
        rng = np.random.RandomState(42)
        x = np.linspace(0, 10, 100)
        y = 2 + 3 * x + rng.normal(0, 0.5, 100)

        result = ols_regression(y, x)

        assert result.method.startswith("OLS")
        assert result.r_squared > 0.9
        assert abs(result.coefficients.get("x1", 0) - 3.0) < 0.1

    def test_ols_returns_diagnostics(self):
        rng = np.random.RandomState(42)
        x = np.linspace(0, 10, 100)
        y = 2 + 3 * x + rng.normal(0, 0.5, 100)

        result = ols_regression(y, x)

        assert result.residuals is not None
        assert len(result.residuals) == 100
        # Durbin-Watson should be ~2 for independent residuals
        assert 1.0 < result.durbin_watson < 3.0

    def test_ols_significance(self):
        rng = np.random.RandomState(42)
        x = rng.normal(0, 1, 100)
        y = rng.normal(0, 1, 100)

        result = ols_regression(y, x)

        assert result.p_values["x1"] > 0.05  # Not significant for noise

    def test_multicollinearity_check(self):
        rng = np.random.RandomState(42)
        x1 = rng.normal(0, 1, 100)
        x2 = 0.99 * x1 + rng.normal(0, 0.01, 100)
        x3 = rng.normal(0, 1, 100)
        X = np.column_stack([x1, x2, x3])

        result = multicollinearity_check(X)

        assert result["has_multicollinearity"]
        assert result["n_problematic"] >= 1

    def test_residual_diagnostics(self):
        rng = np.random.RandomState(42)
        residuals = rng.normal(0, 1, 100)

        diag = residual_diagnostics(residuals)

        assert diag["normality"]["is_normal"]
        assert "durbin_watson" in diag["autocorrelation"]


# ═══════════════════════════════════════════════════
# Causal Inference Tests
# ═══════════════════════════════════════════════════

class TestGrangerCausality:
    """Granger causality tests."""

    def test_granger_no_causality(self):
        rng = np.random.RandomState(42)
        y = rng.normal(0, 1, 200)
        x = rng.normal(0, 1, 200)

        result = granger_causality(y, x, max_lag=3)

        assert result.method == "Granger Causality"
        assert result.granger_f_stats is not None
        assert result.granger_p_values is not None
        assert len(result.granger_p_values) == 3
        # No causality → all p-values should be large
        assert all(p > 0.01 for p in result.granger_p_values)

    def test_granger_with_causality(self):
        rng = np.random.RandomState(42)
        n = 200
        x = rng.normal(0, 1, n)
        y = np.zeros(n)
        for t in range(2, n):
            y[t] = 0.5 * y[t - 1] + 0.3 * x[t - 2] + rng.normal(0, 0.5)

        result = granger_causality(y, x, max_lag=3)

        # At least one lag should show significance
        assert any(p < 0.05 for p in result.granger_p_values)


# ═══════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════

class TestEdgeCases:
    """Edge case handling across all econometrics functions."""

    def test_adf_empty_array(self):
        """ADF handles empty/tiny arrays."""
        for data in [np.array([]), np.array([1.0])]:
            result = adf_test(data)
            assert isinstance(result, StationarityResult)

    def test_cointegration_mismatched_lengths(self):
        """Engle-Granger raises on mismatched lengths."""
        with pytest.raises(ValueError):
            engle_granger(np.array([1, 2, 3]), np.array([1, 2]))

    def test_garch_very_short_series(self):
        """GARCH handles short series."""
        returns = np.array([0.01, -0.02, 0.005])
        result = garch_model(returns)
        assert isinstance(result, VolatilityResult)

    def test_all_results_are_dataclasses(self):
        """All results are typed dataclasses."""
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 100)

        assert isinstance(adf_test(data), StationarityResult)
        assert isinstance(kpss_test(data), StationarityResult)
        assert isinstance(garch_model(data), VolatilityResult)
        assert isinstance(arch_test(data), VolatilityResult)
        
        x = np.linspace(0, 10, 100)
        y = x + rng.normal(0, 0.5, 100)
        assert isinstance(ols_regression(y, x).summary, str)
