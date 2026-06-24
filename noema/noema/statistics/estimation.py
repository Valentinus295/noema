"""Statistical estimation theory — MLE, GMM, Bayesian, confidence intervals.

Provides parametric estimation methods with rigorous diagnostics.
Every function returns typed EstimationResult with estimates and standard errors.

Uses: numpy, scipy
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
from scipy import optimize, stats as scipy_stats


@dataclass
class EstimationResult:
    """Result of a statistical estimation procedure.

    Attributes:
        method: Estimation method ("MLE", "GMM", "Bayesian").
        parameters: Dictionary of parameter estimates.
        standard_errors: Standard errors for each parameter.
        t_statistics: t-statistics for each parameter.
        p_values: P-values for each parameter (H0: param = 0).
        confidence_intervals: Dict of (lower, upper) for each parameter.
        log_likelihood: Log-likelihood at optimum (when available).
        converged: Whether optimization converged.
        n_observations: Number of data points.
        iterations: Number of optimizer iterations.
        diagnostics: Additional diagnostics.
    """
    method: str
    parameters: dict[str, float] = field(default_factory=dict)
    standard_errors: dict[str, float] = field(default_factory=dict)
    t_statistics: dict[str, float] = field(default_factory=dict)
    p_values: dict[str, float] = field(default_factory=dict)
    confidence_intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
    log_likelihood: Optional[float] = None
    converged: bool = False
    n_observations: int = 0
    iterations: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def significant_parameters(self, alpha: float = 0.05) -> list[str]:
        """List of parameters significant at given level."""
        return [k for k, p in self.p_values.items() if p < alpha]

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f"Estimation method: {self.method}"]
        lines.append(f"Converged: {self.converged}, N={self.n_observations}")
        for param, value in self.parameters.items():
            se = self.standard_errors.get(param, float('nan'))
            t = self.t_statistics.get(param, float('nan'))
            p = self.p_values.get(param, float('nan'))
            lines.append(f"  {param} = {value:.4f} (SE={se:.4f}, t={t:.2f}, p={p:.4f})")
        return "\n".join(lines)


def maximum_likelihood_estimation(
    data: np.ndarray,
    log_likelihood_fn: Callable[[np.ndarray, np.ndarray], float],
    initial_params: np.ndarray,
    param_names: Optional[list[str]] = None,
    bounds: Optional[list[tuple[float, float]]] = None,
    method: str = "L-BFGS-B",
    alpha: float = 0.05,
) -> EstimationResult:
    """Maximum Likelihood Estimation via numerical optimization.

    Finds parameters that maximize the log-likelihood function.

    Args:
        data: Observations.
        log_likelihood_fn: Function(params, data) → log-likelihood value.
        initial_params: Starting values for optimization.
        param_names: Names of parameters.
        bounds: Bounds for each parameter.
        method: Optimization method ("L-BFGS-B", "Nelder-Mead", "BFGS").
        alpha: Significance level for confidence intervals.

    Returns:
        EstimationResult with parameter estimates and inference.
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)

    if param_names is None:
        param_names = [f"theta_{i}" for i in range(len(initial_params))]

    # Minimize negative log-likelihood
    def neg_ll(params: np.ndarray) -> float:
        try:
            return -float(log_likelihood_fn(params, data))
        except (ValueError, RuntimeError):
            return 1e10  # Penalty for invalid parameters

    result = optimize.minimize(
        neg_ll,
        initial_params,
        method=method,
        bounds=bounds,
        options={"maxiter": 5000},
    )

    params = result.x
    converged = result.success

    # Hessian via finite differences at optimum
    try:
        hessian = _compute_hessian(lambda p: -log_likelihood_fn(p, data), params)
        cov_matrix = np.linalg.inv(hessian)
        std_errors = np.sqrt(np.diag(cov_matrix))
    except np.linalg.LinAlgError:
        # Fallback: identity SE
        std_errors = np.ones(len(params)) * np.nan

    # Build output dictionaries
    param_dict = {n: float(v) for n, v in zip(param_names, params)}
    se_dict = {n: float(s) for n, s in zip(param_names, std_errors)}
    t_dict = {n: float(param_dict[n] / se_dict[n]) if se_dict[n] > 1e-10 else 0.0
              for n in param_names}
    z = scipy_stats.norm.ppf(1 - alpha / 2)
    ci_dict = {
        n: (float(param_dict[n] - z * se_dict[n]), float(param_dict[n] + z * se_dict[n]))
        for n in param_names
    }
    p_dict = {n: float(2 * scipy_stats.norm.sf(abs(t_dict[n]))) for n in param_names}

    log_lik = float(log_likelihood_fn(params, data)) if converged else None

    return EstimationResult(
        method="MLE",
        parameters=param_dict,
        standard_errors=se_dict,
        t_statistics=t_dict,
        p_values=p_dict,
        confidence_intervals=ci_dict,
        log_likelihood=log_lik,
        converged=converged,
        n_observations=n,
        iterations=result.nit,
        diagnostics={
            "optimization_method": method,
            "optimizer_message": result.message,
            "aic": float(2 * len(params) - 2 * log_lik) if log_lik is not None else None,
            "bic": float(len(params) * np.log(n) - 2 * log_lik) if log_lik is not None else None,
        },
    )


def generalized_method_of_moments(
    data: np.ndarray,
    moment_conditions: Callable[[np.ndarray, np.ndarray], np.ndarray],
    initial_params: np.ndarray,
    param_names: Optional[list[str]] = None,
    weighting_matrix: Optional[np.ndarray] = None,
    alpha: float = 0.05,
) -> EstimationResult:
    """Generalized Method of Moments (GMM) estimation.

    Estimates parameters by minimizing a quadratic form of moment conditions.
    Robust to distributional assumptions — widely used in finance.

    Args:
        data: Observations (n_samples, n_variables).
        moment_conditions: Function(params, data) → vector of moment conditions.
            Should return a 1-D array where E[g] = 0 at true parameters.
        initial_params: Starting values.
        param_names: Parameter names.
        weighting_matrix: If None, uses identity (first step).
        alpha: Significance level.

    Returns:
        EstimationResult with GMM estimates.
    """
    data = np.asarray(data, dtype=float)

    n_params = len(initial_params)
    if param_names is None:
        param_names = [f"theta_{i}" for i in range(n_params)]

    # Evaluate moment conditions at initial params to get dimension
    g_init = np.asarray(moment_conditions(initial_params, data)).ravel()
    n_moments = len(g_init)

    # Weighting matrix
    if weighting_matrix is None:
        W = np.eye(n_moments)
    else:
        W = np.asarray(weighting_matrix)

    # GMM objective: g' W g
    def gmm_objective(params: np.ndarray) -> float:
        try:
            g = np.asarray(moment_conditions(params, data)).ravel()
            return float(g @ W @ g)
        except (ValueError, RuntimeError):
            return 1e12

    result = optimize.minimize(
        gmm_objective,
        initial_params,
        method="L-BFGS-B",
        options={"maxiter": 5000},
    )

    params = result.x
    converged = result.success

    # Standard errors from GMM variance formula
    g = np.asarray(moment_conditions(params, data)).ravel()
    try:
        # Jacobian of moment conditions
        G = _compute_jacobian(lambda p: np.asarray(moment_conditions(p, data)).ravel(), params)
        # Score matrix
        S = np.outer(g, g)
        # GMM covariance
        G_W_G = G.T @ W @ G
        G_W_S_W_G = G.T @ W @ S @ W @ G
        if n_moments > n_params:
            cov = np.linalg.inv(G_W_G) @ G_W_S_W_G @ np.linalg.inv(G_W_G)
        else:
            cov = np.linalg.inv(G_W_G) if np.linalg.matrix_rank(G_W_G) >= n_params else np.eye(n_params) * 0.01
        std_errors = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        std_errors = np.ones(n_params) * np.nan

    param_dict = {n: float(v) for n, v in zip(param_names, params)}
    se_dict = {n: float(s) for n, s in zip(param_names, std_errors)}
    t_dict = {n: float(param_dict[n] / se_dict[n]) if se_dict[n] > 1e-10 else 0.0
              for n in param_names}
    z_val = scipy_stats.norm.ppf(1 - alpha / 2)
    ci_dict = {
        n: (float(param_dict[n] - z_val * se_dict[n]), float(param_dict[n] + z_val * se_dict[n]))
        for n in param_names
    }
    p_dict = {n: float(2 * scipy_stats.norm.sf(abs(t_dict[n]))) for n in param_names}

    # J-statistic (overidentification test)
    j_stat = float(gmm_objective(params))
    j_df = n_moments - n_params if n_moments > n_params else 0
    j_p_value = float(scipy_stats.chi2.sf(j_stat, j_df)) if j_df > 0 else None

    return EstimationResult(
        method="GMM",
        parameters=param_dict,
        standard_errors=se_dict,
        t_statistics=t_dict,
        p_values=p_dict,
        confidence_intervals=ci_dict,
        converged=converged,
        n_observations=len(data) if data.ndim == 1 else data.shape[0],
        iterations=result.nit,
        diagnostics={
            "j_statistic": j_stat,
            "j_df": j_df,
            "j_p_value": j_p_value,
            "n_moments": n_moments,
            "n_params": n_params,
            "overidentified": n_moments > n_params,
        },
    )


def bayesian_estimation(
    data: np.ndarray,
    log_posterior_fn: Callable[[np.ndarray, np.ndarray], float],
    initial_params: np.ndarray,
    param_names: Optional[list[str]] = None,
    n_samples: int = 5000,
    n_burnin: int = 1000,
    step_size: float = 0.1,
    random_seed: Optional[int] = None,
) -> EstimationResult:
    """Bayesian parameter estimation via Metropolis-Hastings MCMC.

    Returns posterior means, credible intervals, and diagnostics.
    For well-behaved posteriors, approximates the full posterior distribution.

    Args:
        data: Observations.
        log_posterior_fn: Unnormalized log-posterior(params, data).
        initial_params: Starting point for the Markov chain.
        param_names: Parameter names.
        n_samples: Number of posterior samples (after burn-in).
        n_burnin: Number of burn-in iterations to discard.
        step_size: Proposal standard deviation.
        random_seed: Random seed.

    Returns:
        EstimationResult with posterior means and credible intervals.
    """
    data = np.asarray(data, dtype=float).ravel()
    rng = np.random.RandomState(random_seed)

    n_params = len(initial_params)
    if param_names is None:
        param_names = [f"theta_{i}" for i in range(n_params)]

    chain = np.zeros((n_samples, n_params))
    current = np.asarray(initial_params, dtype=float)
    current_lp = log_posterior_fn(current, data)
    accepted = 0

    # Burn-in
    for _ in range(n_burnin):
        proposal = current + rng.normal(0, step_size, n_params)
        try:
            proposal_lp = log_posterior_fn(proposal, data)
        except (ValueError, RuntimeError):
            continue
        log_ratio = proposal_lp - current_lp
        if log_ratio > 0 or np.log(rng.random()) < log_ratio:
            current = proposal
            current_lp = proposal_lp

    # Sampling
    for i in range(n_samples):
        proposal = current + rng.normal(0, step_size, n_params)
        try:
            proposal_lp = log_posterior_fn(proposal, data)
        except (ValueError, RuntimeError):
            chain[i] = current
            continue
        log_ratio = proposal_lp - current_lp
        if log_ratio > 0 or np.log(rng.random()) < log_ratio:
            current = proposal
            current_lp = proposal_lp
            accepted += 1
        chain[i] = current

    acceptance_rate = accepted / n_samples

    # Posterior summaries
    posterior_mean = np.mean(chain, axis=0)
    posterior_std = np.std(chain, axis=0, ddof=1)
    ci_lower = np.percentile(chain, 2.5, axis=0)
    ci_upper = np.percentile(chain, 97.5, axis=0)

    param_dict = {n: float(v) for n, v in zip(param_names, posterior_mean)}
    se_dict = {n: float(s) for n, s in zip(param_names, posterior_std)}
    ci_dict = {
        n: (float(ci_lower[i]), float(ci_upper[i]))
        for i, n in enumerate(param_names)
    }

    return EstimationResult(
        method="Bayesian (MCMC)",
        parameters=param_dict,
        standard_errors=se_dict,
        t_statistics={n: 0.0 for n in param_names},  # Bayesians don't use t-tests
        p_values={n: 1.0 for n in param_names},
        confidence_intervals=ci_dict,
        converged=acceptance_rate > 0.1,  # Heuristic: > 10% acceptance = healthy chain
        n_observations=len(data),
        iterations=n_samples + n_burnin,
        diagnostics={
            "acceptance_rate": acceptance_rate,
            "n_burnin": n_burnin,
            "n_posterior_samples": n_samples,
            "step_size": step_size,
            "gelman_rubin": None,  # Would need multiple chains
        },
    )


def confidence_interval(
    data: np.ndarray,
    confidence: float = 0.95,
    method: str = "normal",
) -> tuple[float, float]:
    """Compute a confidence interval for the mean.

    Args:
        data: Observations.
        confidence: Confidence level (0.95 = 95% CI).
        method: "normal" (z-interval), "t" (t-interval).

    Returns:
        Tuple of (lower_bound, upper_bound).
    """
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    mean = np.mean(data)
    se = np.std(data, ddof=1) / np.sqrt(n) if n > 1 else 0

    if method == "t" and n > 1:
        multiplier = scipy_stats.t.ppf((1 + confidence) / 2, df=n - 1)
    else:
        multiplier = scipy_stats.norm.ppf((1 + confidence) / 2)

    return (float(mean - multiplier * se), float(mean + multiplier * se))


def standard_error(data: np.ndarray) -> float:
    """Standard error of the mean."""
    data = np.asarray(data, dtype=float).ravel()
    n = len(data)
    if n < 2:
        return 0.0
    return float(np.std(data, ddof=1) / np.sqrt(n))


# ── Internal helpers ───────────────────────────────────────────────────

def _compute_hessian(
    fn: Callable[[np.ndarray], float],
    x: np.ndarray,
    eps: float = 1e-5,
) -> np.ndarray:
    """Compute Hessian matrix via central finite differences."""
    n = len(x)
    hessian = np.zeros((n, n))
    f0 = fn(x)

    for i in range(n):
        for j in range(i, n):
            x_pp = x.copy()
            x_pm = x.copy()
            x_mp = x.copy()
            x_mm = x.copy()

            ei, ej = np.zeros(n), np.zeros(n)
            ei[i], ej[j] = 1.0, 1.0

            x_pp[i] = x[i] + eps
            x_pp[j] = x[j] + eps
            x_pm[i] = x[i] + eps
            x_pm[j] = x[j] - eps
            x_mp[i] = x[i] - eps
            x_mp[j] = x[j] + eps
            x_mm[i] = x[i] - eps
            x_mm[j] = x[j] - eps

            h_ij = (fn(x_pp) - fn(x_pm) - fn(x_mp) + fn(x_mm)) / (4 * eps * eps)
            hessian[i, j] = h_ij
            hessian[j, i] = h_ij

    return hessian


def _compute_jacobian(
    fn: Callable[[np.ndarray], np.ndarray],
    x: np.ndarray,
    eps: float = 1e-6,
) -> np.ndarray:
    """Compute Jacobian via forward finite differences."""
    x = np.asarray(x, dtype=float)
    f0 = np.asarray(fn(x)).ravel()
    m = len(f0)
    n = len(x)
    jac = np.zeros((m, n))

    for i in range(n):
        x_plus = x.copy()
        x_plus[i] += eps
        f_plus = np.asarray(fn(x_plus)).ravel()
        jac[:, i] = (f_plus - f0) / eps

    return jac
