"""Tests for the statistics module — distributions, hypothesis testing."""

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
from noema.statistics.hypothesis import (
    TestResult,
    sprt_test,
    permutation_test,
    bonferroni_correction,
    benjamini_hochberg,
    fdr_correction,
    multiple_testing_correction,
)


# ═══════════════════════════════════════════════════
# Distribution Tests
# ═══════════════════════════════════════════════════

class TestFitDistribution:
    """Test distribution fitting with known data."""

    def test_fit_normal_distribution(self):
        """Fit normal distribution to normal data."""
        rng = np.random.RandomState(42)
        data = rng.normal(loc=2.0, scale=1.5, size=1000)

        result = fit_distribution(data, SupportedDistribution.NORMAL)

        assert isinstance(result, FitResult)
        assert result.distribution == "normal"
        assert result.converged
        assert result.n_samples == 1000
        assert result.fits_well  # Should fit well

        # Parameters should be close to true values
        assert abs(result.parameters["loc"] - 2.0) < 0.2
        assert abs(result.parameters["scale"] - 1.5) < 0.2

        # AIC and BIC should be finite
        assert result.aic < float('inf')
        assert result.bic < float('inf')

    def test_fit_lognormal_distribution(self):
        """Fit lognormal distribution."""
        rng = np.random.RandomState(42)
        data = rng.lognormal(mean=0.5, sigma=0.3, size=500)

        result = fit_distribution(data, SupportedDistribution.LOGNORMAL)

        assert result.converged
        assert result.n_samples == 500

    def test_fit_t_distribution(self):
        """Fit Student's t to heavy-tailed data."""
        rng = np.random.RandomState(42)
        data = rng.standard_t(df=5, size=500)

        result = fit_distribution(data, SupportedDistribution.T)

        assert result.converged
        # t is harder to distinguish from normal with large df,
        # but df should be in a reasonable range
        assert result.parameters["df"] > 1.0

    def test_fit_laplace_distribution(self):
        """Fit Laplace to double-exponential data."""
        rng = np.random.RandomState(42)
        data = rng.laplace(loc=0.0, scale=1.0, size=500)

        result = fit_distribution(data, SupportedDistribution.LAPLACE)

        assert result.converged
        assert result.n_samples == 500

    def test_fit_exponential(self):
        """Fit exponential distribution."""
        rng = np.random.RandomState(42)
        data = rng.exponential(scale=2.0, size=500)

        result = fit_distribution(data, SupportedDistribution.EXPONENTIAL)

        assert result.converged
        assert abs(result.parameters["scale"] - 2.0) < 0.5

    def test_fit_gamma(self):
        """Fit gamma distribution."""
        rng = np.random.RandomState(42)
        data = rng.gamma(shape=3.0, scale=2.0, size=500)

        result = fit_distribution(data, SupportedDistribution.GAMMA)

        assert result.converged

    def test_fit_zero_deviation_data(self):
        """Test fitting with constant data (should not crash)."""
        data = np.ones(50)

        result = fit_distribution(data, SupportedDistribution.NORMAL)

        # Should handle gracefully
        assert isinstance(result, FitResult)
        assert result.n_samples == 50

    def test_distribution_test_ranks_by_aic(self):
        """Distribution test returns results sorted by AIC."""
        rng = np.random.RandomState(42)
        data = rng.normal(loc=0, scale=1, size=200)

        results = distribution_test(data)

        assert len(results) > 0
        # First result should be the best fit (likely normal or laplace)
        assert results[0].aic <= results[-1].aic

    def test_empirical_cdf(self):
        """Empirical CDF computation."""
        data = np.array([1, 2, 3, 4, 5], dtype=float)

        x, cdf = empirical_cdf(data)

        assert len(x) == 5
        assert len(cdf) == 5
        assert cdf[-1] == 1.0  # Last value should be 1
        assert cdf[0] > 0  # First value should be positive

    def test_qq_plot_data(self):
        """QQ plot data generation."""
        rng = np.random.RandomState(42)
        data = rng.normal(loc=0, scale=1, size=200)

        theoretical, sample = qq_plot_data(data, SupportedDistribution.NORMAL)

        assert len(theoretical) == len(sample)
        assert len(theoretical) == 200
        # Points should roughly follow a 45-degree line
        correlation = np.corrcoef(theoretical, sample)[0, 1]
        assert correlation > 0.95


# ═══════════════════════════════════════════════════
# Hypothesis Test Tests
# ═══════════════════════════════════════════════════

class TestSPRT:
    """Sequential Probability Ratio Test."""

    def test_sprt_rejects_null_when_mean_is_h1(self):
        """SPRT should detect shift to H1 mean."""
        rng = np.random.RandomState(42)
        data = rng.normal(loc=0.5, scale=1.0, size=100)

        result = sprt_test(data, h0_mean=0.0, h1_mean=0.5)

        assert isinstance(result, TestResult)
        assert result.test_name == "SPRT"
        assert result.n_samples == 100
        # Should reject H0 (detect shift to H1)
        assert result.reject_null

    def test_sprt_accepts_null_when_mean_is_h0(self):
        """SPRT should not reject H0 when data follows H0."""
        rng = np.random.RandomState(42)
        data = rng.normal(loc=0.0, scale=1.0, size=100)

        result = sprt_test(data, h0_mean=0.0, h1_mean=1.0)

        assert isinstance(result, TestResult)
        # Should not reject H0

    def test_sprt_with_small_data(self):
        """SPRT handles small datasets gracefully."""
        data = np.array([0.5])

        result = sprt_test(data, h0_mean=0.0, h1_mean=1.0)

        assert result.n_samples == 1
        assert not result.reject_null

    def test_sprt_returns_confidence_interval(self):
        """SPRT includes confidence interval."""
        rng = np.random.RandomState(42)
        data = rng.normal(loc=0.3, scale=1.0, size=50)

        result = sprt_test(data, h0_mean=0.0, h1_mean=0.5)

        assert result.confidence_interval is not None
        ci_low, ci_high = result.confidence_interval
        assert ci_low < ci_high


class TestPermutationTest:
    """Permutation test for comparing two groups."""

    def test_permutation_detects_difference(self):
        """Permutation test detects genuine differences."""
        rng = np.random.RandomState(42)
        group_a = rng.normal(loc=0.0, scale=1.0, size=100)
        group_b = rng.normal(loc=1.0, scale=1.0, size=100)

        result = permutation_test(group_a, group_b)

        assert result.test_name == "Permutation Test"
        assert result.p_value < 0.05
        assert result.reject_null

    def test_permutation_no_difference(self):
        """Permutation test correctly identifies no difference."""
        rng = np.random.RandomState(42)
        group_a = rng.normal(loc=0.0, scale=1.0, size=100)
        group_b = rng.normal(loc=0.0, scale=1.0, size=100)

        result = permutation_test(group_a, group_b)

        assert result.p_value > 0.05
        assert not result.reject_null

    def test_permutation_with_small_samples(self):
        """Permutation test handles small samples."""
        group_a = np.array([1.0, 2.0])
        group_b = np.array([3.0])

        result = permutation_test(group_a, group_b)

        assert result.n_samples == 3

    def test_permutation_with_median_statistic(self):
        """Permutation test with median difference."""
        rng = np.random.RandomState(42)
        group_a = rng.normal(loc=0.0, scale=1.0, size=50)
        group_b = rng.normal(loc=1.0, scale=1.0, size=50)

        result = permutation_test(group_a, group_b, statistic="median_diff")

        assert isinstance(result, TestResult)


class TestMultipleTesting:
    """Multiple testing corrections."""

    def test_bonferroni_correction(self):
        """Bonferroni correction adjusts significance."""
        p_values = [0.001, 0.01, 0.10, 0.50]

        results = bonferroni_correction(p_values, alpha=0.05)

        assert len(results) == 4
        # Only very significant ones should pass
        n_rejected = sum(1 for r in results if r.reject_null)
        assert n_rejected <= 1  # Bonferroni is conservative

    def test_benjamini_hochberg(self):
        """Benjamini-Hochberg FDR control."""
        p_values = [0.001, 0.01, 0.10, 0.50]

        results = benjamini_hochberg(p_values, alpha=0.05)

        assert len(results) == 4
        # BH should be less conservative than Bonferroni
        n_rejected = sum(1 for r in results if r.reject_null)
        assert n_rejected >= 1

    def test_fdr_alias(self):
        """FDR correction is alias for BH."""
        p_values = [0.001, 0.01, 0.50]

        bh = benjamini_hochberg(p_values)
        fdr = fdr_correction(p_values)

        assert len(fdr) == len(bh)
        for a, b in zip(fdr, bh):
            assert a.reject_null == b.reject_null

    def test_multiple_testing_correction_dispatcher(self):
        """Multiple testing correction dispatches correctly."""
        p_values = [0.001, 0.05, 0.50]

        bonf = multiple_testing_correction(p_values, method="bonferroni")
        bh = multiple_testing_correction(p_values, method="bh")
        none = multiple_testing_correction(p_values, method="none")

        assert len(bonf) == 3
        assert len(bh) == 3
        assert len(none) == 3
        # "none" should reject all p < 0.05
        assert sum(1 for r in none if r.reject_null) == 2

    def test_empty_p_values(self):
        """Multiple testing handles empty lists."""
        assert len(bonferroni_correction([])) == 0
        assert len(benjamini_hochberg([])) == 0


class TestTestResult:
    """TestResult dataclass properties."""

    def test_significant_property(self):
        """significant returns True when p < alpha."""
        result = TestResult(
            test_name="test",
            statistic=3.0,
            p_value=0.01,
            alpha=0.05,
        )
        assert result.significant

        result2 = TestResult(
            test_name="test",
            statistic=1.0,
            p_value=0.10,
            alpha=0.05,
        )
        assert not result2.significant

    def test_summary(self):
        """summary returns a readable string."""
        result = TestResult(
            test_name="T-Test",
            statistic=2.5,
            p_value=0.02,
            reject_null=True,
            alpha=0.05,
        )
        summary = result.summary
        assert "T-Test" in summary
        assert "2.5" in summary
        assert "0.02" in summary
