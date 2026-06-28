"""Hypothesis testing — SPRT, permutation tests, multiple testing correction.

All functions return typed dataclasses with test statistics and p-values.
Uses: numpy, scipy.stats — real statistical libraries.
No LLM involvement — purely deterministic computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats


@dataclass
class TestResult:
    """Result of a hypothesis test.

    Attributes:
        test_name: Name of the test (e.g., "SPRT", "permutation").
        statistic: Test statistic value.
        p_value: P-value of the test.
        reject_null: Whether to reject the null hypothesis at alpha level.
        alpha: Significance level used.
        alternative: Alternative hypothesis direction ("two-sided", "greater", "less").
        confidence_interval: Optional (lower, upper) confidence interval.
        effect_size: Standardized effect size (e.g., Cohen's d).
        n_samples: Number of samples.
        additional_info: Any test-specific additional results.
    """
    test_name: str
    statistic: float
    p_value: float
    reject_null: bool = False
    alpha: float = 0.05
    alternative: str = "two-sided"
    confidence_interval: Optional[tuple[float, float]] = None
    effect_size: float = 0.0
    n_samples: int = 0
    additional_info: dict[str, Any] = field(default_factory=dict)

    @property
    def is_significant(self) -> bool:
        """True if p_value < alpha (alias for significant)."""
        return self.significant

    @property
    def significant(self) -> bool:
        """True if p_value < alpha (statistically significant)."""
        return self.p_value < self.alpha

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"{self.test_name}: stat={self.statistic:.4f}, "
            f"p={self.p_value:.4f}, "
            f"{'reject H0' if self.reject_null else 'fail to reject H0'}"
            f" at α={self.alpha}"
        )


def sprt_test(
    data: np.ndarray,
    h0_mean: float = 0.0,
    h1_mean: float = 0.5,
    alpha: float = 0.05,
    beta: float = 0.20,
    known_sigma: Optional[float] = None,
    sigma: Optional[float] = None,
) -> TestResult:
    """Sequential Probability Ratio Test (SPRT) for online hypothesis testing.

    Wald's SPRT for testing H0: μ = h0_mean vs H1: μ = h1_mean.
    Designed for sequential/online monitoring — can stop early.

    This is critical for Noema's real-time signal quality monitoring:
    detects if an agent's signal distribution has drifted from expected.

    Args:
        data: 1-D array of sequential observations.
        h0_mean: Mean under null hypothesis.
        h1_mean: Mean under alternative hypothesis.
        alpha: Type I error rate (false positive).
        beta: Type II error rate (false negative).
        known_sigma: Known standard deviation. If None, estimated from data.
        sigma: Alias for known_sigma (backward compatibility).

    Returns:
        TestResult with the log-likelihood ratio, terminal decision,
        and stopping time.

    Reference:
        Wald, A. (1945). "Sequential Tests of Statistical Hypotheses."
    """
    # Merge sigma alias into known_sigma
    known_sigma = sigma if sigma is not None else known_sigma

    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    if n < 2:
        return TestResult(
            test_name="SPRT",
            statistic=0.0,
            p_value=1.0,
            reject_null=False,
            alpha=alpha,
            alternative="two-sided",
            n_samples=n,
            additional_info={"stopped_early": False, "decision": "insufficient_data"},
        )

    # Estimate sigma if not provided
    sigma = known_sigma or max(float(np.std(data, ddof=1)), 1e-10)

    # Decision boundaries
    A = (1 - beta) / alpha  # Accept H1 if LLR >= ln(A)
    B = beta / (1 - alpha)  # Accept H0 if LLR <= ln(B)

    ln_A = np.log(A)
    ln_B = np.log(B)

    # Cumulative log-likelihood ratio
    # Under H0: N(h0_mean, sigma^2)
    # Under H1: N(h1_mean, sigma^2)
    # LLR = sum_i [ln(f1(x_i)) - ln(f0(x_i))]
    log_f1 = -0.5 * ((data - h1_mean) / sigma) ** 2
    log_f0 = -0.5 * ((data - h0_mean) / sigma) ** 2
    llr_cumsum = np.cumsum(log_f1 - log_f0)

    # Find stopping time
    stopping_idx = n
    decision = "continue"
    for i, llr in enumerate(llr_cumsum):
        if llr >= ln_A:
            stopping_idx = i + 1
            decision = "reject_H0"  # Accept H1
            break
        elif llr <= ln_B:
            stopping_idx = i + 1
            decision = "accept_H0"
            break

    final_llr = float(llr_cumsum[stopping_idx - 1])

    # Compute an approximate p-value from the final LLR
    # Using the relationship: LLR ~ N(±0.5*δ²*n, δ²*n) where δ = (h1-h0)/sigma
    # This gives an asymptotic p-value
    delta = (h1_mean - h0_mean) / sigma
    # Two-sided p-value approximation
    if np.abs(delta) < 1e-10:
        p_value = 1.0
    else:
        z_stat = final_llr / (abs(delta) * np.sqrt(stopping_idx))
        p_value = float(2 * scipy_stats.norm.sf(abs(z_stat)))

    reject_null = decision == "reject_H0"

    # Effect size (Cohen's d)
    effect_size = float((np.mean(data) - h0_mean) / sigma)

    # Confidence interval for the mean
    se = sigma / np.sqrt(n)
    ci_low = float(np.mean(data) - scipy_stats.norm.ppf(1 - alpha / 2) * se)
    ci_high = float(np.mean(data) + scipy_stats.norm.ppf(1 - alpha / 2) * se)

    return TestResult(
        test_name="SPRT",
        statistic=final_llr,
        p_value=p_value,
        reject_null=reject_null,
        alpha=alpha,
        alternative="two-sided",
        confidence_interval=(ci_low, ci_high),
        effect_size=effect_size,
        n_samples=n,
        additional_info={
            "stopping_index": stopping_idx,
            "decision": decision,
            "stopped_early": stopping_idx < n,
            "h0_mean": h0_mean,
            "h1_mean": h1_mean,
            "sigma": sigma,
            "ln_A": ln_A,
            "ln_B": ln_B,
            "delta": delta,
        },
    )


def permutation_test(
    group_a: np.ndarray,
    group_b: np.ndarray,
    statistic: str = "mean_diff",
    n_permutations: int = 10000,
    alternative: str = "two-sided",
    alpha: float = 0.05,
    random_seed: Optional[int] = None,
) -> TestResult:
    """Permutation test for comparing two groups.

    Non-parametric test that makes no distributional assumptions.
    Computes the exact (up to n_permutations) p-value by randomly
    shuffling group labels.

    Args:
        group_a: Observations from group A.
        group_b: Observations from group B.
        statistic: Test statistic — "mean_diff", "median_diff", "median_difference", or "t_stat".
        n_permutations: Number of random permutations.
        alternative: "two-sided", "greater" (A > B), or "less" (A < B).
        alpha: Significance level.
        random_seed: Optional seed for reproducibility.

    Returns:
        TestResult with permutation p-value.
    """
    group_a = np.asarray(group_a, dtype=float).ravel()
    group_b = np.asarray(group_b, dtype=float).ravel()

    n_a = len(group_a)
    n_b = len(group_b)
    n_total = n_a + n_b

    if n_a < 2 or n_b < 2:
        return TestResult(
            test_name="Permutation Test",
            statistic=0.0,
            p_value=1.0,
            alpha=alpha,
            n_samples=n_total,
        )

    rng = np.random.RandomState(random_seed)
    pooled = np.concatenate([group_a, group_b])

    # Observed test statistic
    if statistic in ("mean_diff", "mean_difference"):
        obs_stat = float(np.mean(group_a) - np.mean(group_b))
    elif statistic in ("median_diff", "median_difference"):
        obs_stat = float(np.median(group_a) - np.median(group_b))
    elif statistic == "t_stat":
        # Welch's t-statistic
        se = np.sqrt(np.var(group_a, ddof=1) / n_a + np.var(group_b, ddof=1) / n_b)
        obs_stat = float((np.mean(group_a) - np.mean(group_b)) / max(se, 1e-10))
    else:
        raise ValueError(f"Unknown statistic: {statistic}")

    # Permutation distribution
    perm_stats = np.zeros(n_permutations)
    for i in range(n_permutations):
        perm_indices = rng.permutation(n_total)
        perm_a = pooled[perm_indices[:n_a]]
        perm_b = pooled[perm_indices[n_a:]]

        if statistic == "mean_diff":
            perm_stats[i] = float(np.mean(perm_a) - np.mean(perm_b))
        elif statistic == "median_diff":
            perm_stats[i] = float(np.median(perm_a) - np.median(perm_b))
        else:  # t_stat
            se_p = np.sqrt(np.var(perm_a, ddof=1) / n_a + np.var(perm_b, ddof=1) / n_b)
            perm_stats[i] = float((np.mean(perm_a) - np.mean(perm_b)) / max(se_p, 1e-10))

    # Compute p-value
    if alternative == "two-sided":
        p_value = float(np.mean(np.abs(perm_stats) >= np.abs(obs_stat)))
    elif alternative == "greater":
        p_value = float(np.mean(perm_stats >= obs_stat))
    else:  # "less"
        p_value = float(np.mean(perm_stats <= obs_stat))

    reject_null = p_value < alpha

    # Effect size (Cohen's d)
    pooled_std = np.sqrt((np.var(group_a, ddof=1) * (n_a - 1) + np.var(group_b, ddof=1) * (n_b - 1)) / (n_total - 2))
    effect_size = float(obs_stat / max(pooled_std, 1e-10)) if statistic == "mean_diff" else 0.0

    return TestResult(
        test_name="Permutation Test",
        statistic=float(obs_stat),
        p_value=p_value,
        reject_null=reject_null,
        alpha=alpha,
        alternative=alternative,
        effect_size=effect_size,
        n_samples=n_total,
        additional_info={
            "n_permutations": n_permutations,
            "n_group_a": n_a,
            "n_group_b": n_b,
            "statistic_type": statistic,
        },
    )


def bonferroni_correction(p_values: list[float], alpha: float = 0.05) -> list[TestResult]:
    """Bonferroni correction for multiple hypothesis testing.

    Most conservative correction: α' = α / m.
    Returns TestResult for each p-value with corrected significance.

    Args:
        p_values: List of p-values from individual tests.
        alpha: Family-wise error rate.

    Returns:
        List of TestResult with adjusted significance decisions.
    """
    m = len(p_values)
    if m == 0:
        return []

    corrected_alpha = alpha / m
    results = []

    for i, p in enumerate(p_values):
        reject = p < corrected_alpha
        results.append(TestResult(
            test_name=f"Bonferroni_test_{i}",
            statistic=p,
            p_value=min(p * m, 1.0),  # Adjusted p-value
            reject_null=reject,
            alpha=corrected_alpha,
            alternative="two-sided",
            additional_info={
                "original_p_value": p,
                "adjusted_alpha": corrected_alpha,
                "n_tests": m,
                "correction": "bonferroni",
            },
        ))

    return results


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[TestResult]:
    """Benjamini-Hochberg procedure for controlling FDR.

    Less conservative than Bonferroni; controls the false discovery rate.
    Used when many simultaneous tests are performed (e.g., scanning
    many symbols for signal patterns).

    Args:
        p_values: List of p-values.
        alpha: Desired false discovery rate.

    Returns:
        List of TestResult with BH-adjusted significance.
    """
    m = len(p_values)
    if m == 0:
        return []

    # Sort p-values and track original indices
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    ranks = np.arange(1, m + 1)

    # Find the largest k such that p_k ≤ α * k / m
    bh_thresholds = alpha * ranks / m
    significant = np.array([pv <= thresh for (_, pv), thresh in zip(indexed, bh_thresholds)])

    # All tests with rank ≤ max significant rank are significant
    if significant.any():
        max_sig_rank = np.max(ranks[significant])
    else:
        max_sig_rank = 0

    results = []
    for original_idx, (i, pv) in enumerate(indexed):
        rank = original_idx + 1
        # Adjusted p-value
        adj_p = min(pv * m / rank if rank > 0 else pv, 1.0)
        reject = rank <= max_sig_rank and pv <= alpha
        results.append((original_idx, TestResult(
            test_name=f"BH_test_{original_idx}",
            statistic=pv,
            p_value=adj_p,
            reject_null=reject,
            alpha=alpha,
            alternative="two-sided",
            additional_info={
                "original_p_value": pv,
                "rank": rank,
                "n_tests": m,
                "correction": "benjamini_hochberg",
                "bh_threshold": alpha * rank / m,
            },
        )))

    # Restore original order
    results.sort(key=lambda x: x[0])
    return [r[1] for r in results]


def fdr_correction(p_values: list[float], alpha: float = 0.05) -> list[TestResult]:
    """Alias for Benjamini-Hochberg FDR correction.

    Convenience wrapper for the most common FDR procedure.
    """
    return benjamini_hochberg(p_values, alpha)


def multiple_testing_correction(
    p_values: list[float],
    method: str = "bh",
    alpha: float = 0.05,
) -> list[TestResult]:
    """Apply multiple testing correction.

    Args:
        p_values: List of unadjusted p-values.
        method: "bonferroni", "bh" (Benjamini-Hochberg), or "none".
        alpha: Significance level.

    Returns:
        List of corrected TestResult.
    """
    if method == "bonferroni":
        return bonferroni_correction(p_values, alpha)
    elif method in ("bh", "fdr"):
        return benjamini_hochberg(p_values, alpha)
    elif method == "none":
        return [
            TestResult(
                test_name=f"uncorrected_{i}",
                statistic=p,
                p_value=p,
                reject_null=p < alpha,
                alpha=alpha,
                additional_info={"correction": "none"},
            )
            for i, p in enumerate(p_values)
        ]
    else:
        # Unknown method — fall back to bonferroni
        return bonferroni_correction(p_values, alpha)
