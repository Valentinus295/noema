"""Noema Statistics Module — Statistical methods core.

Provides rigorous statistical functions for:
- Stationarity testing (ADF, KPSS, Phillips-Perron)
- Cointegration analysis (Engle-Granger, Johansen)
- Volatility modeling (GARCH, EGARCH, GJR-GARCH)
- Hypothesis testing (SPRT, permutation, multiple testing correction)
- Non-parametric methods (Mann-Whitney, Kruskal-Wallis, Kolmogorov-Smirnov)
- Multivariate analysis (PCA, ICA, factor decomposition)
- Monte Carlo simulation (P(ruin), VaR, CVaR)
- Estimation theory (MLE, GMM, Bayesian)
- Survival analysis (Kaplan-Meier, Cox PH)
- Decorators (type-checking, caching, validation)

All functions return typed dataclasses with test statistics and p-values.
No LLM involvement — purely deterministic statistical computation.
"""

from noema.statistics.distributions import (
    FitResult,
    fit_distribution,
    distribution_test,
    empirical_cdf,
    qq_plot_data,
    SupportedDistribution,
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
    stationary_bootstrap,
    expected_max_drawdown,
)
from noema.statistics.estimation import (
    EstimationResult,
    maximum_likelihood_estimation,
    generalized_method_of_moments,
    bayesian_estimation,
    confidence_interval,
    standard_error,
)
from noema.statistics.survival import (
    SurvivalResult,
    kaplan_meier,
    cox_proportional_hazards,
    log_rank_test,
    hazard_ratio,
    survival_function,
)
from noema.statistics.decorators import (
    validate_input,
    cache_result,
    log_call,
    timed,
    require_dataframe,
    check_numeric,
)

__all__ = [
    # Distributions
    "FitResult", "fit_distribution", "distribution_test",
    "empirical_cdf", "qq_plot_data", "SupportedDistribution",
    # Hypothesis
    "TestResult", "sprt_test", "permutation_test",
    "bonferroni_correction", "benjamini_hochberg", "fdr_correction",
    "multiple_testing_correction",
    # Nonparametric
    "NonParametricResult", "mann_whitney_u", "kruskal_wallis",
    "kolmogorov_smirnov", "wilcoxon_signed_rank", "runs_test", "spearman_rho",
    # Multivariate
    "PCA_Result", "FactorResult", "perform_pca", "perform_ica",
    "factor_decomposition", "correlation_matrix", "partial_correlation",
    "mahalanobis_distance",
    # Monte Carlo
    "MCSimulationResult", "monte_carlo_simulation", "probability_of_ruin",
    "value_at_risk", "conditional_value_at_risk", "bootstrap_ci",
    "block_bootstrap", "stationary_bootstrap", "expected_max_drawdown",
    # Estimation
    "EstimationResult", "maximum_likelihood_estimation",
    "generalized_method_of_moments", "bayesian_estimation",
    "confidence_interval", "standard_error",
    # Survival
    "SurvivalResult", "kaplan_meier", "cox_proportional_hazards",
    "log_rank_test", "hazard_ratio", "survival_function",
    # Decorators
    "validate_input", "cache_result", "log_call", "timed",
    "require_dataframe", "check_numeric",
]
