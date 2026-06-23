"""Non-parametric statistical tests.

Distribution-free tests that don't assume normality.
Every function returns typed NonParametricResult with test statistics and p-values.

Uses: numpy, scipy.stats
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats as scipy_stats


@dataclass
class NonParametricResult:
    """Result of a non-parametric test.

    Attributes:
        test_name: Name of the test.
        statistic: Test statistic value.
        p_value: P-value.
        reject_null: Whether to reject H0 at alpha.
        alpha: Significance level.
        alternative: "two-sided", "greater", "less".
        effect_size: Effect size estimate.
        n_samples: Total sample size.
        additional_info: Test-specific details.
    """
    test_name: str
    statistic: float
    p_value: float
    reject_null: bool = False
    alpha: float = 0.05
    alternative: str = "two-sided"
    effect_size: float = 0.0
    n_samples: int = 0
    additional_info: dict[str, Any] = field(default_factory=dict)


def mann_whitney_u(
    group_a: np.ndarray,
    group_b: np.ndarray,
    alternative: str = "two-sided",
    alpha: float = 0.05,
) -> NonParametricResult:
    """Mann-Whitney U test (Wilcoxon rank-sum).

    Tests whether two independent samples come from the same distribution.
    Non-parametric alternative to the independent samples t-test.

    Args:
        group_a: First sample.
        group_b: Second sample.
        alternative: "two-sided", "greater" (A > B), or "less" (A < B).
        alpha: Significance level.

    Returns:
        NonParametricResult with U statistic and p-value.
    """
    group_a = np.asarray(group_a, dtype=float).ravel()
    group_b = np.asarray(group_b, dtype=float).ravel()

    n_a, n_b = len(group_a), len(group_b)
    n_total = n_a + n_b

    if n_a < 1 or n_b < 1:
        return NonParametricResult(
            test_name="Mann-Whitney U",
            statistic=0.0,
            p_value=1.0,
            n_samples=n_total,
        )

    try:
        stat, p_value = scipy_stats.mannwhitneyu(
            group_a, group_b, alternative=alternative
        )
        stat = float(stat)
        p_value = float(p_value)
    except Exception:
        # Fallback: manual computation
        combined = np.concatenate([group_a, group_b])
        ranks = scipy_stats.rankdata(combined)
        r1 = ranks[:n_a].sum()
        u1 = r1 - n_a * (n_a + 1) / 2
        u2 = n_a * n_b - u1
        stat = min(float(u1), float(u2))
        # Normal approximation
        mu = n_a * n_b / 2
        sigma = np.sqrt(n_a * n_b * (n_a + n_b + 1) / 12)
        if sigma > 0:
            z = (stat - mu) / sigma
            if alternative == "two-sided":
                p_value = 2 * scipy_stats.norm.sf(abs(z))
            elif alternative == "greater":
                p_value = scipy_stats.norm.sf(z)
            else:
                p_value = scipy_stats.norm.cdf(z)
        else:
            p_value = 1.0

    reject = p_value < alpha

    # Effect size: rank-biserial correlation
    r_effect = 1 - (2 * stat) / (n_a * n_b) if (n_a * n_b) > 0 else 0.0

    return NonParametricResult(
        test_name="Mann-Whitney U",
        statistic=float(stat),
        p_value=p_value,
        reject_null=reject,
        alpha=alpha,
        alternative=alternative,
        effect_size=float(r_effect),
        n_samples=n_total,
        additional_info={"n_a": n_a, "n_b": n_b},
    )


def kruskal_wallis(
    *groups: np.ndarray,
    alpha: float = 0.05,
) -> NonParametricResult:
    """Kruskal-Wallis H test (one-way ANOVA on ranks).

    Tests whether 2+ independent samples come from the same distribution.
    Non-parametric alternative to one-way ANOVA.

    Args:
        *groups: Two or more sample arrays.
        alpha: Significance level.

    Returns:
        NonParametricResult with H statistic and p-value.
    """
    if len(groups) < 2:
        return NonParametricResult(
            test_name="Kruskal-Wallis H",
            statistic=0.0,
            p_value=1.0,
            alpha=alpha,
            n_samples=0,
            additional_info={"n_groups": len(groups)},
        )

    cleaned = [np.asarray(g, dtype=float).ravel() for g in groups]
    n_total = sum(len(g) for g in cleaned)

    try:
        stat, p_value = scipy_stats.kruskal(*cleaned)
        stat = float(stat)
        p_value = float(p_value)
    except Exception:
        # Manual computation fallback
        all_data = np.concatenate(cleaned)
        ranks = scipy_stats.rankdata(all_data)
        idx = 0
        rank_sums = []
        for g in cleaned:
            n_g = len(g)
            rank_sums.append(ranks[idx:idx + n_g].sum())
            idx += n_g

        N = n_total
        H = (12 / (N * (N + 1))) * sum(
            (r ** 2) / n_g for r, n_g in zip(rank_sums, [len(g) for g in cleaned])
        ) - 3 * (N + 1)
        stat = float(H)
        df = len(groups) - 1
        p_value = float(scipy_stats.chi2.sf(H, df))

    reject = p_value < alpha

    # Effect size: eta-squared approximation
    H = float(stat)
    N = n_total
    eta_sq = H / (N - 1) if N > 1 else 0.0

    return NonParametricResult(
        test_name="Kruskal-Wallis H",
        statistic=float(stat),
        p_value=p_value,
        reject_null=reject,
        alpha=alpha,
        effect_size=float(eta_sq),
        n_samples=n_total,
        additional_info={
            "n_groups": len(groups),
            "group_sizes": [len(g) for g in cleaned],
            "degrees_of_freedom": len(groups) - 1,
        },
    )


def kolmogorov_smirnov(
    sample_a: np.ndarray,
    sample_b: np.ndarray | None = None,
    distribution: str = "norm",
    alternative: str = "two-sided",
    alpha: float = 0.05,
) -> NonParametricResult:
    """Kolmogorov-Smirnov test.

    Two modes:
    - One-sample: Test if sample_a follows a specified distribution.
    - Two-sample: Test if sample_a and sample_b come from the same distribution.

    Args:
        sample_a: First sample or single sample for one-sample test.
        sample_b: Optional second sample (two-sample test).
        distribution: Distribution name for one-sample test (scipy.stats style).
        alternative: "two-sided", "greater", or "less".
        alpha: Significance level.

    Returns:
        NonParametricResult with D statistic and p-value.
    """
    sample_a = np.asarray(sample_a, dtype=float).ravel()
    n_a = len(sample_a)

    if sample_b is not None:
        # Two-sample KS test
        sample_b = np.asarray(sample_b, dtype=float).ravel()
        n_b = len(sample_b)
        stat, p_value = scipy_stats.ks_2samp(sample_a, sample_b, alternative=alternative)
        stat = float(stat)
        p_value = float(p_value)
        n_total = n_a + n_b
        test_name = "Kolmogorov-Smirnov (two-sample)"
        additional = {"n_a": n_a, "n_b": n_b}
    else:
        # One-sample KS test
        try:
            stat, p_value = scipy_stats.kstest(sample_a, distribution)
            stat = float(stat)
            p_value = float(p_value)
        except Exception:
            # Assume normal as default
            loc, scale = float(np.mean(sample_a)), float(np.std(sample_a, ddof=1))
            stat, p_value = scipy_stats.kstest(sample_a, 'norm', args=(loc, scale))
            stat, p_value = float(stat), float(p_value)
        n_total = n_a
        test_name = "Kolmogorov-Smirnov (one-sample)"
        additional = {"distribution": distribution}

    reject = p_value < alpha

    return NonParametricResult(
        test_name=test_name,
        statistic=float(stat),
        p_value=p_value,
        reject_null=reject,
        alpha=alpha,
        alternative=alternative,
        n_samples=n_total,
        additional_info=additional,
    )


def wilcoxon_signed_rank(
    sample_a: np.ndarray,
    sample_b: np.ndarray | None = None,
    alternative: str = "two-sided",
    alpha: float = 0.05,
    zero_method: str = "wilcox",
) -> NonParametricResult:
    """Wilcoxon signed-rank test.

    Paired non-parametric test. Two modes:
    - Paired: Test if paired differences (a - b) have zero median.
    - One-sample: Test if sample_a has zero median (when sample_b is None).

    Args:
        sample_a: First sample.
        sample_b: Optional second sample (paired).
        alternative: "two-sided", "greater", or "less".
        alpha: Significance level.
        zero_method: How to handle zero differences.

    Returns:
        NonParametricResult with W statistic and p-value.
    """
    sample_a = np.asarray(sample_a, dtype=float).ravel()

    if sample_b is not None:
        sample_b = np.asarray(sample_b, dtype=float).ravel()
        if len(sample_a) != len(sample_b):
            return NonParametricResult(
                test_name="Wilcoxon Signed-Rank",
                statistic=0.0,
                p_value=1.0,
                alpha=alpha,
                n_samples=min(len(sample_a), len(sample_b)),
            )
        stat, p_value = scipy_stats.wilcoxon(
            sample_a, sample_b, alternative=alternative, zero_method=zero_method
        )
        n_total = len(sample_a)
    else:
        stat, p_value = scipy_stats.wilcoxon(
            sample_a, alternative=alternative, zero_method=zero_method
        )
        n_total = len(sample_a)

    stat = float(stat)
    p_value = float(p_value)
    reject = p_value < alpha

    # Effect size: matched-pairs rank-biserial correlation
    if n_total > 0:
        effect = stat / (n_total * (n_total + 1) / 4)
    else:
        effect = 0.0

    return NonParametricResult(
        test_name="Wilcoxon Signed-Rank",
        statistic=float(stat),
        p_value=p_value,
        reject_null=reject,
        alpha=alpha,
        alternative=alternative,
        effect_size=float(effect),
        n_samples=n_total,
        additional_info={"zero_method": zero_method},
    )


def runs_test(
    data: np.ndarray,
    alternative: str = "two-sided",
    alpha: float = 0.05,
) -> NonParametricResult:
    """Wald-Wolfowitz runs test for randomness.

    Tests whether a sequence of observations is random (H0) vs. has
    systematic patterns (H1). Useful for detecting if an agent's
    signal sequence is non-random (e.g., persistent bullish bias).

    Args:
        data: 1-D sequence of observations.
        alternative: "two-sided", "greater" (clustered), or "less" (alternating).
        alpha: Significance level.

    Returns:
        NonParametricResult with Z statistic and p-value.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    if n < 2:
        return NonParametricResult(
            test_name="Runs Test",
            statistic=0.0,
            p_value=1.0,
            n_samples=n,
        )

    # Binarize around median
    median = float(np.median(data))
    binary = (data > median).astype(int)

    # Count runs
    runs = 1
    for i in range(1, n):
        if binary[i] != binary[i - 1]:
            runs += 1

    n1 = int(np.sum(binary))
    n2 = n - n1

    if n1 < 1 or n2 < 1:
        return NonParametricResult(
            test_name="Runs Test",
            statistic=float(runs),
            p_value=1.0,
            n_samples=n,
            additional_info={"n_above_median": n1, "n_below_median": n2},
        )

    # Expected runs and variance under H0
    expected_runs = (2 * n1 * n2) / n + 1
    var_runs = (2 * n1 * n2 * (2 * n1 * n2 - n)) / (n ** 2 * (n - 1))

    if var_runs <= 0:
        return NonParametricResult(
            test_name="Runs Test",
            statistic=float(runs),
            p_value=1.0,
            n_samples=n,
        )

    z = (runs - expected_runs) / np.sqrt(var_runs)

    # p-value
    if alternative == "two-sided":
        p_value = 2 * scipy_stats.norm.sf(abs(z))
    elif alternative == "greater":
        p_value = scipy_stats.norm.sf(z)
    else:
        p_value = scipy_stats.norm.cdf(z)

    reject = p_value < alpha

    return NonParametricResult(
        test_name="Runs Test",
        statistic=float(z),
        p_value=float(p_value),
        reject_null=reject,
        alpha=alpha,
        alternative=alternative,
        effect_size=float(z / np.sqrt(n)),
        n_samples=n,
        additional_info={
            "n_runs": int(runs),
            "expected_runs": round(expected_runs, 2),
            "n_above_median": n1,
            "n_below_median": n2,
        },
    )


def spearman_rho(
    x: np.ndarray,
    y: np.ndarray,
    alternative: str = "two-sided",
    alpha: float = 0.05,
) -> NonParametricResult:
    """Spearman rank correlation coefficient.

    Non-parametric measure of monotonic association.
    Used for correlation between agent signals and actual outcomes.

    Args:
        x: First variable.
        y: Second variable.
        alternative: "two-sided", "greater", or "less".
        alpha: Significance level.

    Returns:
        NonParametricResult with rho and p-value.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()

    if len(x) != len(y):
        raise ValueError(f"x and y must have same length: {len(x)} vs {len(y)}")

    n = len(x)
    if n < 3:
        return NonParametricResult(
            test_name="Spearman's ρ",
            statistic=0.0,
            p_value=1.0,
            n_samples=n,
        )

    rho, p_value = scipy_stats.spearmanr(x, y, alternative=alternative)
    rho = float(rho)
    p_value = float(p_value)

    reject = p_value < alpha

    return NonParametricResult(
        test_name="Spearman's ρ",
        statistic=rho,
        p_value=p_value,
        reject_null=reject,
        alpha=alpha,
        alternative=alternative,
        effect_size=rho,  # rho is already a standardized effect size [-1, 1]
        n_samples=n,
    )
