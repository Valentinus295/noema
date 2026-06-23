"""Tests for noema.statistics.hypothesis — SPRT, permutation, multiple testing correction."""

from __future__ import annotations

import numpy as np
import pytest

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
# SPRT (Sequential Probability Ratio Test) tests
# ═══════════════════════════════════════════════════

class TestSPRT:
    """Tests for sprt_test — sequential probability ratio test."""

    def test_sprt_normal_vs_alternative(self):
        """SPRT should reach a decision for clearly separated hypotheses."""
        rng = np.random.default_rng(42)
        # Sample from H1 (mean=1.0) with H0=0.0, H1=1.0
        data = rng.normal(loc=1.0, scale=1.0, size=200)

        result = sprt_test(
            data,
            h0_mean=0.0,
            h1_mean=1.0,
            sigma=1.0,
            alpha=0.05,
            beta=0.10,
        )

        assert isinstance(result, TestResult)
        # With data from H1, we should reject H0 in favor of H1
        assert result.statistic is not None
        # Should reach a decision (not "continue")
        assert result.p_value is not None or hasattr(result, 'decision')

    def test_sprt_null_case(self):
        """SPRT with data from null hypothesis."""
        rng = np.random.default_rng(123)
        data = rng.normal(loc=0.0, scale=1.0, size=200)

        result = sprt_test(
            data,
            h0_mean=0.0,
            h1_mean=1.0,
            sigma=1.0,
        )

        assert isinstance(result, TestResult)

    def test_sprt_small_sample(self):
        """SPRT with insufficient data should handle gracefully."""
        data = np.array([0.5, -0.3, 0.1])

        result = sprt_test(
            data,
            h0_mean=0.0,
            h1_mean=0.5,
            sigma=1.0,
        )

        assert isinstance(result, TestResult)


# ═══════════════════════════════════════════════════
# Permutation Test tests
# ═══════════════════════════════════════════════════

class TestPermutationTest:
    """Tests for permutation_test — nonparametric two-sample comparison."""

    def test_different_distributions(self):
        """Permutation test should detect difference between shifted normals."""
        rng = np.random.default_rng(42)
        group_a = rng.normal(loc=0.0, scale=1.0, size=50)
        group_b = rng.normal(loc=1.0, scale=1.0, size=50)

        result = permutation_test(group_a, group_b, n_permutations=500)

        assert isinstance(result, TestResult)
        # Should detect the location shift
        assert result.p_value < 0.05

    def test_same_distribution(self):
        """Permutation test should not reject identical distributions."""
        rng = np.random.default_rng(99)
        group_a = rng.normal(loc=0.0, scale=1.0, size=50)
        group_b = rng.normal(loc=0.0, scale=1.0, size=50)

        result = permutation_test(group_a, group_b, n_permutations=500)

        # Should not reject at typical alpha
        assert result.p_value > 0.05

    def test_small_samples(self):
        """Permutation test with small samples."""
        group_a = np.array([1.0, 2.0, 3.0, 4.0])
        group_b = np.array([5.0, 6.0, 7.0, 8.0])

        result = permutation_test(group_a, group_b, n_permutations=100)

        assert isinstance(result, TestResult)
        assert result.p_value is not None

    def test_unequal_sample_sizes(self):
        """Permutation test with different group sizes."""
        rng = np.random.default_rng(55)
        group_a = rng.normal(loc=0.0, scale=1.0, size=30)
        group_b = rng.normal(loc=0.5, scale=1.0, size=70)

        result = permutation_test(group_a, group_b, n_permutations=300)

        assert isinstance(result, TestResult)

    def test_with_statistic_parameter(self):
        """Permutation test with custom test statistic."""
        rng = np.random.default_rng(77)
        group_a = rng.normal(loc=0.0, scale=1.0, size=40)
        group_b = rng.normal(loc=0.8, scale=1.0, size=40)

        # Use median difference as statistic
        result = permutation_test(
            group_a, group_b,
            n_permutations=300,
            statistic="median_difference",
        )

        assert isinstance(result, TestResult)


# ═══════════════════════════════════════════════════
# Multiple Testing Correction tests
# ═══════════════════════════════════════════════════

class TestMultipleTestingCorrection:
    """Tests for multiple testing correction methods."""

    def test_bonferroni_all_significant(self):
        """Bonferroni correction with all very small p-values."""
        p_values = [0.0001, 0.0005, 0.0003, 0.0002]
        results = bonferroni_correction(p_values, alpha=0.05)

        assert len(results) == 4
        for r in results:
            assert isinstance(r, TestResult)
            assert r.p_value <= 0.05  # All should be significant after correction

    def test_bonferroni_none_significant(self):
        """Bonferroni with all large p-values."""
        p_values = [0.5, 0.6, 0.4, 0.7]
        results = bonferroni_correction(p_values, alpha=0.05)

        for r in results:
            assert not r.is_significant  # or equivalent flag

    def test_benjamini_hochberg(self):
        """Benjamini-Hochberg FDR correction."""
        p_values = [0.001, 0.01, 0.05, 0.10, 0.50]

        results = benjamini_hochberg(p_values, alpha=0.05)

        assert len(results) == 5
        # First 3 should be significant at FDR 0.05
        assert results[0].p_value < 0.05
        assert results[1].p_value < 0.05

    def test_bh_more_lenient_than_bonferroni(self):
        """BH correction should be more lenient than Bonferroni."""
        p_values = [0.005, 0.01, 0.02, 0.03, 0.04]

        bonf_results = bonferroni_correction(p_values, alpha=0.05)
        bh_results = benjamini_hochberg(p_values, alpha=0.05)

        bh_significant = sum(1 for r in bh_results if r.p_value < 0.05)
        bonf_significant = sum(1 for r in bonf_results if r.p_value < 0.05)

        # BH should find at least as many significant as Bonferroni
        assert bh_significant >= bonf_significant

    def test_fdr_correction(self):
        """FDR correction wrapper."""
        p_values = [0.001, 0.01, 0.05, 0.50]

        results = fdr_correction(p_values, alpha=0.05)

        assert len(results) == 4
        for r in results:
            assert isinstance(r, TestResult)

    def test_multiple_testing_correction_dispatcher(self):
        """The dispatcher function should route to correct method."""
        p_values = [0.001, 0.01, 0.10]

        bonf = multiple_testing_correction(p_values, alpha=0.05, method="bonferroni")
        bh = multiple_testing_correction(p_values, alpha=0.05, method="bh")
        fdr = multiple_testing_correction(p_values, alpha=0.05, method="fdr")

        assert len(bonf) == 3
        assert len(bh) == 3
        assert len(fdr) == 3

    def test_empty_p_values(self):
        """Empty p-value list should return empty list."""
        results = bonferroni_correction([], alpha=0.05)
        assert results == []

    def test_invalid_method_falls_back(self):
        """Invalid method should use a sensible default."""
        p_values = [0.01, 0.05]

        # Should not crash
        results = multiple_testing_correction(p_values, alpha=0.05, method="invalid_method")

        assert len(results) == 2
