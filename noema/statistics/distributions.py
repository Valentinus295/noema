"""Distribution fitting and goodness-of-fit tests.

Provides parametric distribution fitting with statistical rigor.
Every function returns typed dataclasses with test statistics and p-values.

Uses: numpy, scipy.stats
No LLM involvement — purely deterministic computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Tuple

import numpy as np
from scipy import stats as scipy_stats


class SupportedDistribution(str, Enum):
    """Supported probability distributions for fitting."""
    NORMAL = "normal"
    LOGNORMAL = "lognormal"
    T = "t"
    CAUCHY = "cauchy"
    LAPLACE = "laplace"
    EXPONENTIAL = "exponential"
    GAMMA = "gamma"
    BETA = "beta"
    WEIBULL = "weibull"
    PARETO = "pareto"
    UNIFORM = "uniform"
    STUDENT_T = "student_t"
    GENERALIZED_ERROR = "generalized_error"


@dataclass
class FitResult:
    """Result of distribution fitting.

    Attributes:
        distribution: The fitted distribution name.
        parameters: Dictionary of fitted parameters.
        aic: Akaike Information Criterion (lower = better fit).
        bic: Bayesian Information Criterion (lower = better fit).
        log_likelihood: Log-likelihood of the fit.
        ks_statistic: Kolmogorov-Smirnov test statistic.
        ks_p_value: K-S test p-value (H0: data follows distribution).
        anderson_statistic: Anderson-Darling test statistic.
        ad_critical_values: Anderson-Darling critical values.
        ad_significance_levels: Corresponding significance levels.
        chi_square_statistic: Chi-square goodness-of-fit statistic.
        chi_square_p_value: Chi-square p-value.
        n_samples: Number of data points.
        converged: Whether optimization converged.
    """
    distribution: str
    parameters: dict[str, float] = field(default_factory=dict)
    aic: float = float('inf')
    bic: float = float('inf')
    log_likelihood: float = float('-inf')
    ks_statistic: float = 0.0
    ks_p_value: float = 1.0
    anderson_statistic: float = 0.0
    ad_critical_values: list[float] = field(default_factory=list)
    ad_significance_levels: list[float] = field(default_factory=list)
    chi_square_statistic: float = 0.0
    chi_square_p_value: float = 1.0
    n_samples: int = 0
    converged: bool = False

    @property
    def fitted(self) -> bool:
        """True if distribution fitting converged (convenience alias)."""
        return self.converged
    chi_square_p_value: float = 1.0
    n_samples: int = 0
    converged: bool = False

    @property
    def fits_well(self) -> bool:
        """True if K-S test fails to reject (p > 0.05) at 5% level."""
        return self.ks_p_value > 0.05

    @property
    def summary(self) -> str:
        """Human-readable summary of fit results."""
        params_str = ", ".join(f"{k}={v:.4g}" for k, v in self.parameters.items())
        return (
            f"{self.distribution}: AIC={self.aic:.2f}, BIC={self.bic:.2f}, "
            f"KS stat={self.ks_statistic:.4f}, KS p={self.ks_p_value:.4f}, "
            f"params=({params_str})"
        )


def fit_distribution(
    data: np.ndarray,
    distribution: SupportedDistribution,
) -> FitResult:
    """Fit a specified distribution to data using MLE.

    Args:
        data: 1-D array of observations.
        distribution: Distribution type from SupportedDistribution enum.

    Returns:
        FitResult with fitted parameters, goodness-of-fit statistics, and p-values.

    Example:
        >>> import numpy as np
        >>> data = np.random.normal(0, 1, 1000)
        >>> result = fit_distribution(data, SupportedDistribution.NORMAL)
        >>> result.fits_well
        True
        >>> abs(result.parameters['loc']) < 0.2
        True
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    if n < 10:
        return FitResult(
            distribution=distribution.value,
            n_samples=n,
            converged=False,
        )

    params: dict[str, float] = {}
    converged = True

    try:
        if distribution == SupportedDistribution.NORMAL:
            loc, scale = scipy_stats.norm.fit(data)
            params = {"loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.norm.logpdf(data, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'norm', args=(loc, scale))
            dist = scipy_stats.norm(loc=loc, scale=scale)

        elif distribution == SupportedDistribution.LOGNORMAL:
            shape, loc, scale = scipy_stats.lognorm.fit(data, floc=0)
            params = {"shape": float(shape), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.lognorm.logpdf(data, shape, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'lognorm', args=(shape, loc, scale))
            dist = scipy_stats.lognorm(s=shape, loc=loc, scale=scale)

        elif distribution == SupportedDistribution.T:
            df, loc, scale = scipy_stats.t.fit(data)
            params = {"df": float(df), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.t.logpdf(data, df, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 't', args=(df, loc, scale))
            dist = scipy_stats.t(df=df, loc=loc, scale=scale)

        elif distribution == SupportedDistribution.CAUCHY:
            loc, scale = scipy_stats.cauchy.fit(data)
            params = {"loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.cauchy.logpdf(data, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'cauchy', args=(loc, scale))
            dist = scipy_stats.cauchy(loc=loc, scale=scale)

        elif distribution == SupportedDistribution.LAPLACE:
            loc, scale = scipy_stats.laplace.fit(data)
            params = {"loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.laplace.logpdf(data, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'laplace', args=(loc, scale))
            dist = scipy_stats.laplace(loc=loc, scale=scale)

        elif distribution == SupportedDistribution.EXPONENTIAL:
            loc, scale = scipy_stats.expon.fit(data)
            params = {"loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.expon.logpdf(data, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'expon', args=(loc, scale))
            dist = scipy_stats.expon(loc=loc, scale=scale)

        elif distribution == SupportedDistribution.GAMMA:
            a, loc, scale = scipy_stats.gamma.fit(data)
            params = {"a": float(a), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.gamma.logpdf(data, a, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'gamma', args=(a, loc, scale))
            dist = scipy_stats.gamma(a=a, loc=loc, scale=scale)

        elif distribution == SupportedDistribution.BETA:
            a, b, loc, scale = scipy_stats.beta.fit(data)
            params = {"a": float(a), "b": float(b), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.beta.logpdf(data, a, b, loc, scale))
            # K-S for beta: use empirical CDF approach
            # Since scipy.stats.kstest with 'beta' may be unstable, use empirical approach
            sorted_data = np.sort(data)
            theoretical_cdf = scipy_stats.beta.cdf(sorted_data, a, b, loc, scale)
            empirical_cdf_vals = np.arange(1, n + 1) / n
            ks_stat = float(np.max(np.abs(theoretical_cdf - empirical_cdf_vals)))
            ks_p = float(2 * scipy_stats.distributions.kstwo.sf(ks_stat, n))
            dist = scipy_stats.beta(a=a, b=b, loc=loc, scale=scale)

        elif distribution == SupportedDistribution.WEIBULL:
            c, loc, scale = scipy_stats.weibull_min.fit(data)
            params = {"c": float(c), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.weibull_min.logpdf(data, c, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'weibull_min', args=(c, loc, scale))
            dist = scipy_stats.weibull_min(c=c, loc=loc, scale=scale)

        elif distribution in (SupportedDistribution.PARETO,):
            b, loc, scale = scipy_stats.pareto.fit(data)
            params = {"b": float(b), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.pareto.logpdf(data, b, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'pareto', args=(b, loc, scale))
            dist = scipy_stats.pareto(b=b, loc=loc, scale=scale)

        elif distribution == SupportedDistribution.UNIFORM:
            loc, scale = scipy_stats.uniform.fit(data)
            params = {"loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.uniform.logpdf(data, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 'uniform', args=(loc, scale))
            dist = scipy_stats.uniform(loc=loc, scale=scale)

        elif distribution == SupportedDistribution.STUDENT_T:
            df, loc, scale = scipy_stats.t.fit(data)
            params = {"df": float(df), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.t.logpdf(data, df, loc, scale))
            ks_stat, ks_p = scipy_stats.kstest(data, 't', args=(df, loc, scale))
            dist = scipy_stats.t(df=df, loc=loc, scale=scale)

        elif distribution == SupportedDistribution.GENERALIZED_ERROR:
            # Generalized Error Distribution (GED) / Exponential Power Distribution
            # Use gennorm (generalized normal) from scipy.stats
            beta, loc, scale = scipy_stats.gennorm.fit(data)
            params = {"beta": float(beta), "loc": float(loc), "scale": float(scale)}
            log_lik = np.sum(scipy_stats.gennorm.logpdf(data, beta, loc, scale))
            # Use empirical KS for gennorm
            sorted_data = np.sort(data)
            theoretical_cdf = scipy_stats.gennorm.cdf(sorted_data, beta, loc, scale)
            empirical_cdf_vals = np.arange(1, n + 1) / n
            ks_stat = float(np.max(np.abs(theoretical_cdf - empirical_cdf_vals)))
            ks_p = float(2 * scipy_stats.distributions.kstwo.sf(ks_stat, n))
            dist = scipy_stats.gennorm(beta=beta, loc=loc, scale=scale)

        else:
            raise ValueError(f"Unsupported distribution: {distribution}")

        # Compute information criteria
        k = len(params)  # Number of parameters
        aic = float(2 * k - 2 * log_lik)
        bic = float(k * np.log(n) - 2 * log_lik)

        # Anderson-Darling test
        try:
            ad_result = scipy_stats.anderson(data, dist=distribution.value)
            ad_stat = float(ad_result.statistic)
            ad_crit = [float(c) for c in ad_result.critical_values]
            ad_sig = [float(s) for s in ad_result.significance_level]
        except Exception:
            # Fallback for distributions without built-in Anderson-Darling
            ad_stat = 0.0
            ad_crit = []
            ad_sig = []

        # Chi-square goodness of fit
        try:
            n_bins = int(np.sqrt(n))
            hist, bin_edges = np.histogram(data, bins=n_bins, density=False)
            # Expected counts based on fitted distribution
            expected = np.diff(dist.cdf(bin_edges)) * n
            # Avoid zero expected counts
            mask = expected > 0
            if mask.sum() > 1 and hist[mask].sum() > 0:
                chi2_stat, chi2_p = scipy_stats.chisquare(
                    hist[mask], f_exp=expected[mask]
                )
            else:
                chi2_stat, chi2_p = 0.0, 1.0
        except Exception:
            chi2_stat, chi2_p = 0.0, 1.0

        return FitResult(
            distribution=distribution.value,
            parameters=params,
            aic=aic,
            bic=bic,
            log_likelihood=float(log_lik),
            ks_statistic=float(ks_stat),
            ks_p_value=float(ks_p),
            anderson_statistic=ad_stat,
            ad_critical_values=ad_crit,
            ad_significance_levels=ad_sig,
            chi_square_statistic=float(chi2_stat),
            chi_square_p_value=float(chi2_p),
            n_samples=n,
            converged=converged,
        )

    except Exception:
        return FitResult(
            distribution=distribution.value,
            n_samples=n,
            converged=False,
        )


def distribution_test(
    data: np.ndarray,
    distribution: Optional[SupportedDistribution] = None,
) -> list[FitResult]:
    """Fit multiple distributions and rank by AIC.

    If distribution is specified, only fits that distribution.
    Otherwise fits all supported distributions and returns results ranked by AIC.

    Tries normal, lognormal, t, laplace, cauchy, exponential, gamma,
    weibull, beta, and generalized error distributions.

    Args:
        data: 1-D array of observations.
        distribution: Optional specific distribution to fit. If None, fits all.

    Returns:
        List of FitResult sorted by AIC (best fit first).
    """
    if distribution is not None:
        candidates = [distribution]
    else:
        candidates = [
            SupportedDistribution.NORMAL,
            SupportedDistribution.LOGNORMAL,
            SupportedDistribution.LAPLACE,
            SupportedDistribution.CAUCHY,
            SupportedDistribution.EXPONENTIAL,
            SupportedDistribution.GAMMA,
            SupportedDistribution.WEIBULL,
            SupportedDistribution.BETA,
            SupportedDistribution.UNIFORM,
            SupportedDistribution.GENERALIZED_ERROR,
        ]

    results = []
    for dist in candidates:
        result = fit_distribution(data, dist)
        if result.converged:
            results.append(result)

    # If a specific distribution was requested, return single result
    if distribution is not None:
        return results[0] if results else FitResult(
            distribution=distribution.value,
            n_samples=len(data),
            converged=False,
        )

    # Sort by AIC (lower is better fit)
    results.sort(key=lambda r: r.aic)
    return results


def empirical_cdf(data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Compute the empirical cumulative distribution function.

    Args:
        data: 1-D array of observations.

    Returns:
        Tuple of (x_values_sorted, cdf_values) as numpy arrays.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    sorted_data = np.sort(data)
    cdf = np.arange(1, n + 1) / n
    return sorted_data, cdf


def qq_plot_data(
    data: np.ndarray,
    distribution: SupportedDistribution = SupportedDistribution.NORMAL,
) -> Tuple[np.ndarray, np.ndarray]:
    """Generate QQ-plot data (theoretical vs empirical quantiles).

    Args:
        data: 1-D array of observations.
        distribution: Theoretical distribution to compare against.

    Returns:
        Tuple of (theoretical_quantiles, sample_quantiles) as numpy arrays.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    # Sort data
    sorted_data = np.sort(data)

    # Compute plotting positions (Filliben's estimate for normal)
    empirical_probs = (np.arange(1, n + 1) - 0.5) / n

    # Fit distribution
    fit = fit_distribution(data, distribution)

    # Get theoretical quantiles
    if distribution == SupportedDistribution.NORMAL:
        loc = fit.parameters.get("loc", 0.0)
        scale = fit.parameters.get("scale", 1.0)
        theoretical = scipy_stats.norm.ppf(empirical_probs, loc=loc, scale=scale)
    elif distribution == SupportedDistribution.LOGNORMAL:
        shape = fit.parameters.get("shape", 1.0)
        loc = fit.parameters.get("loc", 0.0)
        scale = fit.parameters.get("scale", 1.0)
        theoretical = scipy_stats.lognorm.ppf(empirical_probs, shape, loc, scale)
    elif distribution == SupportedDistribution.T:
        df = fit.parameters.get("df", 5.0)
        loc = fit.parameters.get("loc", 0.0)
        scale = fit.parameters.get("scale", 1.0)
        theoretical = scipy_stats.t.ppf(empirical_probs, df, loc, scale)
    elif distribution == SupportedDistribution.LAPLACE:
        loc = fit.parameters.get("loc", 0.0)
        scale = fit.parameters.get("scale", 1.0)
        theoretical = scipy_stats.laplace.ppf(empirical_probs, loc, scale)
    elif distribution == SupportedDistribution.GAMMA:
        a = fit.parameters.get("a", 2.0)
        loc = fit.parameters.get("loc", 0.0)
        scale = fit.parameters.get("scale", 1.0)
        theoretical = scipy_stats.gamma.ppf(empirical_probs, a, loc, scale)
    elif distribution == SupportedDistribution.EXPONENTIAL:
        loc = fit.parameters.get("loc", 0.0)
        scale = fit.parameters.get("scale", 1.0)
        theoretical = scipy_stats.expon.ppf(empirical_probs, loc, scale)
    else:
        # Generic: use fitted CDF inversion via approximation
        theoretical = np.quantile(data, empirical_probs)

    return theoretical, sorted_data
