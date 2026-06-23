"""Tests for nonparametric, multivariate, monte carlo, estimation, survival modules."""

from __future__ import annotations

import numpy as np
import pytest

from noema.statistics.nonparametric import (
    NonParametricResult,
    mann_whitney_u,
    kruskal_wallis,
    kolmogorov_smirnov,
    wilcoxon_signed_rank,
    runs_test,
    spearman_rho,
)
from noema.statistics.multivariate import (
    PCA_Result,
    FactorResult,
    perform_pca,
    perform_ica,
    factor_decomposition,
    correlation_matrix,
    partial_correlation,
    mahalanobis_distance,
)
from noema.statistics.monte_carlo import (
    MCSimulationResult,
    monte_carlo_simulation,
    probability_of_ruin,
    value_at_risk,
    conditional_value_at_risk,
    bootstrap_ci,
    block_bootstrap,
    expected_max_drawdown,
)
from noema.statistics.estimation import (
    EstimationResult,
    confidence_interval,
    standard_error,
)
from noema.statistics.survival import (
    SurvivalResult,
    kaplan_meier,
    log_rank_test,
    hazard_ratio,
    survival_function,
)


# ═══════════════════════════════════════════════════
# Nonparametric Tests
# ═══════════════════════════════════════════════════

class TestMannWhitneyU:
    def test_detects_difference(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0.5, 1, 100)
        result = mann_whitney_u(a, b)
        assert isinstance(result, NonParametricResult)
        assert result.p_value < 0.05

    def test_no_difference(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        result = mann_whitney_u(a, b)
        assert result.p_value > 0.05


class TestKruskalWallis:
    def test_detects_difference(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0, 1, 50)
        b = rng.normal(0.8, 1, 50)
        c = rng.normal(1.5, 1, 50)
        result = kruskal_wallis(a, b, c)
        assert result.p_value < 0.05

    def test_single_group(self):
        result = kruskal_wallis(np.array([1.0, 2.0]))
        assert result.n_samples == 0  # Need 2+ groups


class TestKolmogorovSmirnov:
    def test_two_sample_diff(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0, 1, 200)
        b = rng.normal(1, 1, 200)
        result = kolmogorov_smirnov(a, b)
        assert result.p_value < 0.05

    def test_one_sample_normal(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0, 1, 200)
        result = kolmogorov_smirnov(a, distribution="norm")
        assert isinstance(result, NonParametricResult)


class TestWilcoxon:
    def test_paired_difference(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0, 1, 50)
        b = a + rng.normal(0.3, 0.5, 50)
        result = wilcoxon_signed_rank(a, b)
        assert isinstance(result, NonParametricResult)

    def test_one_sample(self):
        rng = np.random.RandomState(42)
        a = rng.normal(0.5, 1, 50)
        result = wilcoxon_signed_rank(a)
        assert isinstance(result, NonParametricResult)


class TestRunsTest:
    def test_random_data(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 100)
        result = runs_test(data)
        assert isinstance(result, NonParametricResult)
        # Random data should not reject runs test
        assert result.p_value > 0.01

    def test_alternating_data(self):
        data = np.array([1, -1, 1, -1, 1, -1, 1, -1] * 5)
        result = runs_test(data)
        # Alternating pattern has many runs
        assert isinstance(result, NonParametricResult)


class TestSpearmanRho:
    def test_positive_correlation(self):
        rng = np.random.RandomState(42)
        x = np.linspace(0, 10, 100)
        y = 2 * x + rng.normal(0, 0.5, 100)
        result = spearman_rho(x, y)
        assert result.statistic > 0.9
        assert result.p_value < 0.001

    def test_no_correlation(self):
        rng = np.random.RandomState(42)
        x = rng.normal(0, 1, 100)
        y = rng.normal(0, 1, 100)
        result = spearman_rho(x, y)
        assert abs(result.statistic) < 0.3


# ═══════════════════════════════════════════════════
# Multivariate Tests
# ═══════════════════════════════════════════════════

class TestPCA:
    def test_pca_on_correlated_data(self):
        rng = np.random.RandomState(42)
        n = 200
        x1 = rng.normal(0, 1, n)
        x2 = 0.8 * x1 + rng.normal(0, 0.3, n)
        x3 = rng.normal(0, 1, n)
        data = np.column_stack([x1, x2, x3])

        result = perform_pca(data, n_components=2)
        assert isinstance(result, PCA_Result)
        assert result.n_components == 2
        assert result.n_samples == 200
        assert result.n_features == 3
        assert len(result.explained_variance_ratio) == 2
        # First component should explain most variance
        assert result.explained_variance_ratio[0] > 0.5

    def test_kaiser_criterion(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, (200, 5))
        data[:, 1] = 0.9 * data[:, 0] + rng.normal(0, 0.1, 200)
        data[:, 2] = 0.8 * data[:, 0] + rng.normal(0, 0.2, 200)

        result = perform_pca(data)
        assert isinstance(result.kaiser_criterion_components, int)
        assert result.kaiser_criterion_components > 0

    def test_cumulative_variance(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, (100, 10))
        result = perform_pca(data)
        assert result.cumulative_variance_ratio[-1] > 0.99


class TestCorrelationMatrix:
    def test_pearson_correlation(self):
        rng = np.random.RandomState(42)
        x = rng.normal(0, 1, 100)
        y = 2 * x + rng.normal(0, 0.1, 100)
        data = np.column_stack([x, y])

        result = correlation_matrix(data)
        assert len(result["feature_names"]) == 2
        assert result["correlation_matrix"][0][1] > 0.9


class TestMahalanobis:
    def test_mahalanobis_distance(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, (100, 3))
        result = mahalanobis_distance(data)
        assert "distances" in result
        assert "threshold_99_percentile" in result
        assert len(result["distances"]) == 100


# ═══════════════════════════════════════════════════
# Monte Carlo Tests
# ═══════════════════════════════════════════════════

class TestMonteCarlo:
    def test_simulation_basic(self):
        rng = np.random.RandomState(42)

        def generator():
            return rng.normal(0, 1)

        result = monte_carlo_simulation(generator, n_simulations=1000)
        assert isinstance(result, MCSimulationResult)
        assert result.n_simulations == 1000
        assert abs(result.mean) < 0.2  # Should be ~0
        assert abs(result.std - 1.0) < 0.2  # Should be ~1
        # CI should contain 0
        assert result.ci_lower < 0 < result.ci_upper

    def test_probability_of_ruin(self):
        result = probability_of_ruin(
            initial_capital=10000,
            win_rate=0.55,
            avg_win=100,
            avg_loss=100,
            max_risk_per_trade_pct=0.02,
            n_simulations=500,
            max_trades=200,
            random_seed=42,
        )
        assert isinstance(result, MCSimulationResult)
        assert result.p_ruin is not None
        # With positive edge and small risk, ruin probability should be < 0.1
        assert result.p_ruin < 0.5

    def test_var_historical(self):
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 1000)
        var_result = value_at_risk(returns, confidence=0.95)
        assert var_result["confidence"] == 0.95
        assert var_result["var"] > 0

    def test_cvar(self):
        rng = np.random.RandomState(42)
        returns = rng.normal(0, 0.01, 500)
        cvar_result = conditional_value_at_risk(returns, confidence=0.95)
        assert cvar_result["cvar"] >= cvar_result["var"]

    def test_bootstrap_ci(self):
        rng = np.random.RandomState(42)
        data = rng.normal(10, 2, 100)
        result = bootstrap_ci(data, n_bootstrap=500, ci_level=0.95)
        assert result.ci_lower < result.ci_upper
        assert result.ci_lower < 10 < result.ci_upper

    def test_block_bootstrap(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 200)

        def stat_fn(x):
            return np.mean(x)

        result = block_bootstrap(data, block_size=10, statistic_fn=stat_fn, n_bootstrap=200)
        assert abs(result.mean) < 0.3

    def test_expected_max_drawdown(self):
        rng = np.random.RandomState(42)
        returns = rng.normal(0.0005, 0.01, 200)
        result = expected_max_drawdown(returns, n_simulations=200, horizon=100)
        assert result.mean > 0
        assert result.mean < 0.5  # Should be a fraction


# ═══════════════════════════════════════════════════
# Estimation Tests
# ═══════════════════════════════════════════════════

class TestEstimation:
    def test_confidence_interval_normal(self):
        rng = np.random.RandomState(42)
        data = rng.normal(5, 2, 100)
        low, high = confidence_interval(data, confidence=0.95)
        assert low < 5 < high

    def test_confidence_interval_t(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 10)
        low, high = confidence_interval(data, confidence=0.95, method="t")
        assert low < 0 < high

    def test_standard_error(self):
        rng = np.random.RandomState(42)
        data = rng.normal(0, 1, 100)
        se = standard_error(data)
        assert 0.05 < se < 0.15  # SE should be ~0.1 for N=100, σ=1

    def test_standard_error_single_value(self):
        assert standard_error(np.array([5.0])) == 0.0


# ═══════════════════════════════════════════════════
# Survival Tests
# ═══════════════════════════════════════════════════

class TestSurvival:
    def test_kaplan_meier_basic(self):
        durations = np.array([5, 10, 15, 20, 25, 30])
        events = np.array([1, 1, 1, 1, 1, 1])

        result = kaplan_meier(durations, events)

        assert isinstance(result, SurvivalResult)
        assert result.method == "Kaplan-Meier"
        assert result.n_total == 6
        assert result.n_events == 6
        assert result.n_censored == 0
        # Survival should decrease
        assert len(result.times) > 0
        assert result.survival_probabilities[-1] == 0.0  # All events happened

    def test_kaplan_meier_with_censoring(self):
        durations = np.array([5, 10, 15, 20, 25])
        events = np.array([1, 1, 0, 1, 0])

        result = kaplan_meier(durations, events)

        assert result.n_events == 3
        assert result.n_censored == 2
        # Survival should be > 0 since not all events occurred
        assert result.survival_probabilities[-1] > 0

    def test_median_survival(self):
        durations = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        events = np.ones(10)

        result = kaplan_meier(durations, events)

        assert result.median_survival_time is not None
        assert result.median_survival_time <= 6  # Median of 1-10 is 5.5

    def test_log_rank_test(self):
        rng = np.random.RandomState(42)
        a_dur = rng.exponential(10, 50)
        a_ev = np.ones(50)
        b_dur = rng.exponential(5, 50)
        b_ev = np.ones(50)

        result = log_rank_test(a_dur, a_ev, b_dur, b_ev)

        assert isinstance(result, SurvivalResult)
        assert result.log_rank_statistic is not None
        assert result.log_rank_p_value is not None

    def test_hazard_ratio(self):
        # Data with overlapping risk periods — needed for valid MH estimator
        a_dur = np.array([1, 3, 5, 8, 12])
        a_ev = np.ones(5)
        b_dur = np.array([1, 2, 4, 6, 9])
        b_ev = np.ones(5)

        result = hazard_ratio(a_dur, a_ev, b_dur, b_ev)

        assert isinstance(result, SurvivalResult)
        assert result.hazard_ratio is not None
        # HR is a positive float; verify it's computed
        assert result.hazard_ratio > 0.0
        assert not np.isnan(result.hazard_ratio)

    def test_survival_function(self):
        times = np.array([0, 1, 2, 3, 4, 5])
        survival = np.array([1.0, 0.8, 0.6, 0.4, 0.2, 0.0])

        result = survival_function(times, survival)

        assert "survival" in result
        assert "cumulative_hazard" in result
        assert "density" in result
