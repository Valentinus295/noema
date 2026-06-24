"""Tests for noema.statistics.distributions — fit_distribution, distribution_test, qq_plot_data, empirical_cdf."""

from __future__ import annotations

import numpy as np
import pytest

from noema.statistics.distributions import (
    FitResult,
    SupportedDistribution,
    fit_distribution,
    distribution_test,
    empirical_cdf,
    qq_plot_data,
)


# ═══════════════════════════════════════════════════
# fit_distribution tests
# ═══════════════════════════════════════════════════

class TestFitDistribution:
    """Tests for fit_distribution — fits data to a named distribution."""

    def test_fit_normal_distribution(self):
        """Fit normally-distributed data to a normal distribution."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=5.0, scale=2.0, size=1000)

        result = fit_distribution(data, SupportedDistribution.NORMAL)

        assert isinstance(result, FitResult)
        assert result.distribution == "normal"
        assert result.fitted
        # Estimated params should be close to (5, 2)
        assert 4.0 < result.parameters["loc"] < 6.0
        assert 1.5 < result.parameters["scale"] < 2.5
        assert 0.0 <= result.aic
        assert 0.0 <= result.bic

    def test_fit_exponential_distribution(self):
        """Fit exponential-distributed data."""
        rng = np.random.default_rng(42)
        data = rng.exponential(scale=3.0, size=500)

        result = fit_distribution(data, SupportedDistribution.EXPONENTIAL)

        assert result.fitted
        assert result.distribution == "exponential"

    def test_fit_lognormal_distribution(self):
        """Fit lognormally-distributed data."""
        rng = np.random.default_rng(42)
        data = rng.lognormal(mean=1.0, sigma=0.5, size=500)

        result = fit_distribution(data, SupportedDistribution.LOGNORMAL)

        assert result.fitted
        assert result.distribution == "lognormal"

    def test_fit_small_sample(self):
        """Fit should gracefully handle small samples."""
        data = np.array([1.0, 2.0, 3.0])

        result = fit_distribution(data, SupportedDistribution.NORMAL)

        # Should still attempt fitting
        assert isinstance(result, FitResult)

    def test_fit_constant_data(self):
        """Fit constant data (zero variance edge case)."""
        data = np.ones(100) * 5.0

        result = fit_distribution(data, SupportedDistribution.NORMAL)

        # Should handle gracefully
        assert isinstance(result, FitResult)


# ═══════════════════════════════════════════════════
# distribution_test tests
# ═══════════════════════════════════════════════════

class TestDistributionTest:
    """Tests for distribution_test — goodness-of-fit testing."""

    def test_normal_data_passes_normal_test(self):
        """Normal data tested against normal distribution should not reject."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=0, scale=1, size=500)

        result = distribution_test(data, SupportedDistribution.NORMAL)

        assert isinstance(result, FitResult)
        # Normal data should fit normal distribution (high p-value)
        assert result.ks_p_value > 0.01  # Should not be rejected at 1%

    def test_uniform_data_fails_normal_test(self):
        """Uniform data tested against normal should reject at low p-value."""
        rng = np.random.default_rng(42)
        data = rng.uniform(0, 1, size=500)

        result = distribution_test(data, SupportedDistribution.NORMAL)

        # Uniform data should NOT fit normal (low p-value)
        assert result.ks_p_value < 0.05

    def test_exponential_data_passes_exponential_test(self):
        """Exponential data tested against exponential should fit."""
        rng = np.random.default_rng(42)
        data = rng.exponential(scale=2.0, size=500)

        result = distribution_test(data, SupportedDistribution.EXPONENTIAL)

        assert result.ks_p_value > 0.01


# ═══════════════════════════════════════════════════
# empirical_cdf tests
# ═══════════════════════════════════════════════════

class TestEmpiricalCDF:
    """Tests for empirical_cdf — computes empirical cumulative distribution."""

    def test_basic_cdf(self):
        """ECDF should produce sorted values and increasing probabilities."""
        data = np.array([1.0, 3.0, 2.0, 5.0, 4.0])

        x, cdf = empirical_cdf(data)

        assert len(x) == len(data)
        assert len(cdf) == len(data)
        # x should be sorted
        assert np.all(np.diff(x) >= 0)
        # CDF should start at ~0.2 and end at 1.0
        assert cdf[-1] == pytest.approx(1.0, rel=0.01)
        # CDF should be non-decreasing
        assert np.all(np.diff(cdf) >= 0)

    def test_single_value(self):
        """ECDF of a single value."""
        x, cdf = empirical_cdf(np.array([5.0]))
        assert cdf[0] == pytest.approx(1.0)


# ═══════════════════════════════════════════════════
# qq_plot_data tests
# ═══════════════════════════════════════════════════

class TestQQPlotData:
    """Tests for qq_plot_data — computes quantile-quantile plot data."""

    def test_normal_qq(self):
        """QQ plot of normal data vs normal should lie on y=x line."""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=0, scale=1, size=200)

        theoretical, empirical = qq_plot_data(data, SupportedDistribution.NORMAL)

        assert len(theoretical) == 200
        assert len(empirical) == 200
        # Points should be roughly on y=x line (correlation close to 1)
        corr = np.corrcoef(theoretical, empirical)[0, 1]
        assert corr > 0.95

    def test_uniform_qq_vs_normal(self):
        """QQ plot of uniform data vs normal should deviate from line."""
        rng = np.random.default_rng(42)
        data = rng.uniform(0, 1, size=200)

        theoretical, empirical = qq_plot_data(data, SupportedDistribution.NORMAL)

        # Uniform vs normal QQ should show lower correlation
        corr = np.corrcoef(theoretical, empirical)[0, 1]
        assert corr < 0.98  # Deviates from y=x

    def test_qq_small_sample(self):
        """QQ plot with small sample should still return arrays."""
        data = np.random.randn(10)

        theoretical, empirical = qq_plot_data(data, SupportedDistribution.NORMAL)

        assert len(theoretical) == 10
        assert len(empirical) == 10
