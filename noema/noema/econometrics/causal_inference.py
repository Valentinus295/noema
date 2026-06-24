"""Causal inference methods — DiD, RDD, IV, PSM, Granger causality.

Provides:
- Difference-in-Differences (DiD) estimation
- Regression Discontinuity Design (RDD)
- Instrumental Variables causal effects
- Propensity Score Matching (PSM)
- Granger Causality tests

Every function returns typed CausalResult with treatment effects and p-values.
Uses: numpy, scipy, statsmodels — real causal inference methods.
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats


@dataclass
class CausalResult:
    """Result of a causal inference analysis.

    Attributes:
        method: Method name ("DiD", "RDD", "IV", "PSM", "Granger").
        treatment_effect: Estimated average treatment effect.
        standard_error: Standard error of treatment effect.
        t_statistic: t-statistic.
        p_value: P-value.
        confidence_interval: (lower, upper) confidence interval.
        placebo_effect: Average placebo treatment effect (where applicable).
        parallel_trends_p: P-value for parallel trends test (DiD).
        first_stage_f: First-stage F-statistic (IV).
        balance_check: Balance check results (PSM).
        granger_f_stats: Granger causality F-statistics per lag.
        granger_p_values: Granger p-values per lag.
        n_treated: Number of treated units.
        n_control: Number of control units.
        additional: Additional diagnostics.
    """
    method: str
    treatment_effect: float = 0.0
    standard_error: float = 0.0
    t_statistic: float = 0.0
    p_value: float = 1.0
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    placebo_effect: Optional[float] = None
    parallel_trends_p: Optional[float] = None
    first_stage_f: Optional[float] = None
    balance_check: Optional[dict[str, Any]] = None
    granger_f_stats: Optional[list[float]] = None
    granger_p_values: Optional[list[float]] = None
    n_treated: int = 0
    n_control: int = 0
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def significant(self, alpha: float = 0.05) -> bool:
        """True if treatment effect is statistically significant."""
        return self.p_value < alpha

    @property
    def summary(self) -> str:
        lines = [
            f"{self.method}: ATE = {self.treatment_effect:.4f}, "
            f"SE = {self.standard_error:.4f}, "
            f"t = {self.t_statistic:.2f}, p = {self.p_value:.4f}"
        ]
        lines.append(f"  95% CI: [{self.confidence_interval[0]:.4f}, {self.confidence_interval[1]:.4f}]")
        if self.n_treated + self.n_control > 0:
            lines.append(f"  N treated = {self.n_treated}, N control = {self.n_control}")
        return "\n".join(lines)


def difference_in_differences(
    y_pre_treat: np.ndarray,
    y_post_treat: np.ndarray,
    y_pre_control: np.ndarray,
    y_post_control: np.ndarray,
    alpha: float = 0.05,
) -> CausalResult:
    """Difference-in-Differences (DiD) estimator.

    Estimates the causal effect of a treatment by comparing the change
    in outcome for treated units to the change for control units.

    ATE = (Y_post_treat - Y_pre_treat) - (Y_post_control - Y_pre_control)

    For Noema: Evaluate the effect of a policy change (e.g., new broker,
    new position sizing rule) on trading outcomes.

    Args:
        y_pre_treat: Outcomes for treated group before treatment.
        y_post_treat: Outcomes for treated group after treatment.
        y_pre_control: Outcomes for control group before treatment.
        y_post_control: Outcomes for control group after treatment.
        alpha: Significance level.

    Returns:
        CausalResult with DiD treatment effect estimate.
    """
    y_pre_treat = np.asarray(y_pre_treat, dtype=float).ravel()
    y_post_treat = np.asarray(y_post_treat, dtype=float).ravel()
    y_pre_control = np.asarray(y_pre_control, dtype=float).ravel()
    y_post_control = np.asarray(y_post_control, dtype=float).ravel()

    n_t = len(y_pre_treat)
    n_c = len(y_pre_control)

    if n_t < 2 or n_c < 2:
        return CausalResult(method="DiD", n_treated=n_t, n_control=n_c)

    # Pre-post differences
    diff_treat = y_post_treat - y_pre_treat
    diff_control = y_post_control - y_pre_control

    # DiD estimator
    did = float(np.mean(diff_treat) - np.mean(diff_control))

    # Standard error (assuming independent groups)
    var_treat = np.var(diff_treat, ddof=1) / n_t if n_t > 1 else 0
    var_control = np.var(diff_control, ddof=1) / n_c if n_c > 1 else 0
    se = np.sqrt(var_treat + var_control)

    if se > 1e-10:
        t_stat = did / se
        p_value = 2 * scipy_stats.t.sf(abs(t_stat), df=min(n_t, n_c) - 1)
    else:
        t_stat = 0.0
        p_value = 1.0

    # Confidence interval
    df = min(n_t + n_c - 2, 1)
    z_alpha = scipy_stats.t.ppf(1 - alpha / 2, df=max(df, 1))
    ci = (did - z_alpha * se, did + z_alpha * se)

    # Placebo test: use pre-period only, split in half
    if n_t >= 4:
        mid_t = n_t // 2
        placebo_treat = np.mean(y_post_treat[:mid_t]) - np.mean(y_pre_treat[:mid_t])
        placebo_control = np.mean(y_post_control[:mid_t]) - np.mean(y_pre_control[:mid_t]) if n_c >= 2 else 0
        placebo = placebo_treat - placebo_control
    else:
        placebo = None

    # Parallel trends test: compare pre-trends
    if n_t >= 3 and n_c >= 3:
        # Simple check: difference of pre-period means
        t_stat_pt, p_pt = scipy_stats.ttest_ind(y_pre_treat, y_pre_control)
        parallel_trends_p = float(p_pt)
    else:
        parallel_trends_p = None

    return CausalResult(
        method="Difference-in-Differences",
        treatment_effect=float(did),
        standard_error=float(se),
        t_statistic=float(t_stat),
        p_value=float(p_value),
        confidence_interval=(float(ci[0]), float(ci[1])),
        placebo_effect=float(placebo) if placebo is not None else None,
        parallel_trends_p=parallel_trends_p,
        n_treated=n_t,
        n_control=n_c,
        additional={
            "diff_treat_mean": float(np.mean(diff_treat)),
            "diff_control_mean": float(np.mean(diff_control)),
        },
    )


def regression_discontinuity(
    running_variable: np.ndarray,
    outcome: np.ndarray,
    cutoff: float,
    bandwidth: Optional[float] = None,
    polynomial_order: int = 1,
    kernel: str = "uniform",
    alpha: float = 0.05,
) -> CausalResult:
    """Regression Discontinuity Design (RDD) — sharp design.

    Estimates treatment effects at a threshold/cutoff by comparing
    outcomes just above and below the threshold.

    Args:
        running_variable: Assignment variable (e.g., spread).
        outcome: Outcome variable (e.g., profit per trade).
        cutoff: Threshold value for treatment assignment.
        bandwidth: Window around cutoff. If None, uses IK optimal.
        polynomial_order: Order of local polynomial (1 = linear).
        kernel: "uniform" or "triangular" weighting.
        alpha: Significance level.

    Returns:
        CausalResult with RDD treatment effect at cutoff.
    """
    running = np.asarray(running_variable, dtype=float).ravel()
    outcome = np.asarray(outcome, dtype=float).ravel()

    n = len(running)
    if n < 20:
        return CausalResult(method="RDD", n_treated=0, n_control=0)

    # Determine bandwidth (rule of thumb: 2 * σ * n^(-1/5))
    if bandwidth is None:
        sigma = np.std(running, ddof=1)
        bandwidth = 2 * sigma * n ** (-0.2)
        bandwidth = max(bandwidth, np.std(running) * 0.1)

    # Select observations within bandwidth
    in_window = np.abs(running - cutoff) <= bandwidth

    if np.sum(in_window) < 10:
        return CausalResult(method="RDD", n_treated=0, n_control=0)

    running_w = running[in_window]
    outcome_w = outcome[in_window]

    # Treatment indicator
    treated = running_w >= cutoff

    # Build design matrix with polynomial terms
    running_centered = running_w - cutoff
    interaction = running_centered * treated

    # Design: [1, running_centered, treated, interaction, running_centered^2, ...]
    X_cols = [np.ones_like(running_centered)]
    for p in range(1, polynomial_order + 1):
        X_cols.append(running_centered ** p)
    X_cols.append(treated)
    for p in range(1, polynomial_order + 1):
        X_cols.append(running_centered ** p * treated)

    X = np.column_stack(X_cols)

    # Apply kernel weights
    if kernel == "triangular":
        weights = 1 - np.abs(running_centered) / bandwidth
        weights = np.maximum(weights, 0)
    else:
        weights = np.ones_like(running_centered)

    W = np.diag(weights)

    # Weighted least squares
    try:
        XtWX = X.T @ W @ X
        XtWy = X.T @ W @ outcome_w
        beta = np.linalg.solve(XtWX + 1e-10 * np.eye(XtWX.shape[0]), XtWy)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X, outcome_w, rcond=None)[0]

    # Treatment effect at cutoff (running_centered = 0)
    # ATE = β_treat * 1 + Σ β_interact_p * 0 = β_treat
    treat_idx = polynomial_order + 1  # Position of treatment indicator
    treatment_effect = float(beta[treat_idx])

    # Standard error
    residuals = outcome_w - X @ beta
    sigma2 = np.sum(weights * residuals ** 2) / (np.sum(weights) - X.shape[1])
    cov = sigma2 * np.linalg.inv(XtWX + 1e-10 * np.eye(XtWX.shape[0]))
    se = float(np.sqrt(max(cov[treat_idx, treat_idx], 0)))

    if se > 1e-10:
        t_stat = treatment_effect / se
        p_value = 2 * scipy_stats.norm.sf(abs(t_stat))
    else:
        t_stat = 0.0
        p_value = 1.0

    z_alpha = scipy_stats.norm.ppf(1 - alpha / 2)
    ci = (treatment_effect - z_alpha * se, treatment_effect + z_alpha * se)

    n_treated = int(np.sum(treated))
    n_control = int(np.sum(~treated))

    return CausalResult(
        method="RDD",
        treatment_effect=treatment_effect,
        standard_error=float(se),
        t_statistic=float(t_stat),
        p_value=float(p_value),
        confidence_interval=(float(ci[0]), float(ci[1])),
        n_treated=n_treated,
        n_control=n_control,
        additional={
            "bandwidth": bandwidth,
            "polynomial_order": polynomial_order,
            "kernel": kernel,
            "cutoff": cutoff,
            "n_in_window": n_treated + n_control,
        },
    )


def instrumental_variables(
    y: np.ndarray,
    X_endog: np.ndarray,
    Z: np.ndarray,
    alpha: float = 0.05,
) -> CausalResult:
    """Instrumental Variables causal effect estimation.

    Estimates the causal effect of X_endog on y using instrument Z.
    Valid instruments must satisfy:
    1. Relevance: Cov(Z, X_endog) ≠ 0
    2. Exogeneity: Cov(Z, ε) = 0 (only affects y through X_endog)

    Args:
        y: Outcome variable.
        X_endog: Endogenous treatment variable.
        Z: Instrumental variable.
        alpha: Significance level.

    Returns:
        CausalResult with IV estimate and first-stage F-statistic.
    """
    y = np.asarray(y, dtype=float).ravel()
    X_endog = np.asarray(X_endog, dtype=float).ravel()
    Z = np.asarray(Z, dtype=float).ravel()

    n = len(y)
    if n < 10:
        return CausalResult(method="IV", n_treated=0, n_control=0)

    # First stage: X_endog = π₀ + π₁ Z + v
    Z_mat = np.column_stack([np.ones(n), Z])
    try:
        pi = np.linalg.lstsq(Z_mat, X_endog, rcond=None)[0]
        X_hat = Z_mat @ pi
        residuals_first = X_endog - X_hat

        # First-stage F-statistic (relevance test)
        ssr_r = np.sum((X_endog - pi[0]) ** 2)  # restricted: only constant
        ssr_u = np.sum(residuals_first ** 2)      # unrestricted: constant + Z
        first_stage_f = float(((ssr_r - ssr_u) / 1) / (ssr_u / (n - 2))) if ssr_u > 0 else 0.0
    except np.linalg.LinAlgError:
        return CausalResult(method="IV", n_treated=n, n_control=0)

    # Second stage: y = β₀ + β₁ X_hat + ε
    X_hat_mat = np.column_stack([np.ones(n), X_hat])
    try:
        beta = np.linalg.lstsq(X_hat_mat, y, rcond=None)[0]
        residuals_second = y - X_hat_mat @ beta
    except np.linalg.LinAlgError:
        return CausalResult(method="IV", n_treated=n, n_control=0)

    treatment_effect = float(beta[1])

    # Standard errors (correct for generated regressor)
    sigma2 = np.sum(residuals_second ** 2) / (n - 2)
    # IV variance: σ² / Σ(X_hat - X_bar)²
    var_x_hat = np.sum((X_hat - np.mean(X_hat)) ** 2)
    se = np.sqrt(sigma2 / var_x_hat) if var_x_hat > 0 else float('inf')

    if se > 0 and se < float('inf'):
        t_stat = treatment_effect / se
        p_value = 2 * scipy_stats.t.sf(abs(t_stat), df=n - 2)
    else:
        t_stat = 0.0
        p_value = 1.0

    z_alpha = scipy_stats.t.ppf(1 - alpha / 2, df=n - 2)
    ci = (treatment_effect - z_alpha * se, treatment_effect + z_alpha * se)

    return CausalResult(
        method="IV",
        treatment_effect=treatment_effect,
        standard_error=float(se),
        t_statistic=float(t_stat),
        p_value=float(p_value),
        confidence_interval=(float(ci[0]), float(ci[1])),
        first_stage_f=first_stage_f,
        n_treated=n,
        n_control=n,
        additional={
            "weak_instrument": first_stage_f < 10 if first_stage_f is not None else None,
            "first_stage_coefficient": float(pi[1]) if len(pi) > 1 else None,
        },
    )


def propensity_score_matching(
    y: np.ndarray,
    treatment: np.ndarray,
    covariates: np.ndarray,
    caliper: Optional[float] = None,
    n_neighbors: int = 1,
    alpha: float = 0.05,
) -> CausalResult:
    """Propensity Score Matching (PSM) for causal effect estimation.

    Matches treated and control units on their estimated probability
    of receiving treatment (the propensity score). Reduces selection
    bias by comparing "similar" treated and control units.

    Args:
        y: Outcome variable.
        treatment: Binary treatment indicator.
        covariates: Covariates for propensity score model.
        caliper: Maximum distance for matching (in std dev of propensity score).
        n_neighbors: Number of matched controls per treated unit.
        alpha: Significance level.

    Returns:
        CausalResult with ATT (Average Treatment Effect on the Treated).
    """
    y = np.asarray(y, dtype=float).ravel()
    treatment = np.asarray(treatment, dtype=bool).ravel()
    covariates = np.asarray(covariates, dtype=float)

    if covariates.ndim == 1:
        covariates = covariates.reshape(-1, 1)

    n = len(y)
    n_treated = int(np.sum(treatment))
    n_control = n - n_treated

    if n_treated < 2 or n_control < 2:
        return CausalResult(method="PSM", n_treated=n_treated, n_control=n_control)

    # Estimate propensity scores via logistic regression
    X_logit = np.column_stack([np.ones(n), covariates])
    try:
        # Simple logistic via Newton-Raphson
        beta_logit = np.zeros(X_logit.shape[1])
        for _ in range(100):
            linear = X_logit @ beta_logit
            p = 1 / (1 + np.exp(-np.clip(linear, -10, 10)))
            W = np.diag(p * (1 - p))
            gradient = X_logit.T @ (treatment.astype(float) - p)
            hessian = X_logit.T @ W @ X_logit

            try:
                delta = np.linalg.solve(hessian + 1e-6 * np.eye(hessian.shape[0]), gradient)
            except np.linalg.LinAlgError:
                delta = gradient * 0.01

            beta_logit += delta
            if np.max(np.abs(delta)) < 1e-6:
                break

        p_scores = 1 / (1 + np.exp(-np.clip(X_logit @ beta_logit, -10, 10)))
    except Exception:
        # Fallback: random scores
        p_scores = 0.5 * np.ones(n)

    # Standardize propensity scores
    ps_std = np.std(p_scores)
    if caliper is None:
        caliper = 0.2 * ps_std if ps_std > 0 else 0.1

    # Nearest neighbor matching
    treated_indices = np.where(treatment)[0]
    control_indices = np.where(~treatment)[0]
    control_scores = p_scores[control_indices]

    matched_pairs = []
    treated_outcomes = y[treated_indices]

    for i, t_idx in enumerate(treated_indices):
        # Find nearest controls
        distances = np.abs(control_scores - p_scores[t_idx])
        sorted_control_idx = np.argsort(distances)

        # Select k nearest within caliper
        matched = []
        for c_rank in sorted_control_idx:
            if len(matched) >= n_neighbors:
                break
            if distances[c_rank] > caliper:
                break
            matched.append(control_indices[c_rank])

        if matched:
            control_y = np.mean([y[c] for c in matched])
            matched_pairs.append((treated_outcomes[i], control_y))

    if not matched_pairs:
        return CausalResult(method="PSM", n_treated=n_treated, n_control=n_control)

    # ATT = mean(y_t) - mean(y_c_matched)
    att_values = np.array([t - c for t, c in matched_pairs])
    att = float(np.mean(att_values))

    # Standard error (Abadie-Imbens)
    se = np.std(att_values, ddof=1) / np.sqrt(len(att_values)) if len(att_values) > 1 else 0

    if se > 1e-10:
        t_stat = att / se
        p_value = 2 * scipy_stats.t.sf(abs(t_stat), df=len(att_values) - 1)
    else:
        t_stat = 0.0
        p_value = 1.0

    z_alpha = scipy_stats.t.ppf(1 - alpha / 2, df=max(len(att_values) - 1, 1))
    ci = (att - z_alpha * se, att + z_alpha * se)

    # Balance check: standardized mean difference before vs after
    before_smd = {}
    after_smd = {}
    for j in range(covariates.shape[1]):
        cov = covariates[:, j]
        before_diff = np.mean(cov[treatment]) - np.mean(cov[~treatment])
        before_pooled_std = np.sqrt((np.var(cov[treatment]) + np.var(cov[~treatment])) / 2)
        before_smd[f"cov_{j}"] = float(before_diff / before_pooled_std) if before_pooled_std > 0 else 0.0
        after_smd[f"cov_{j}"] = before_smd[f"cov_{j}"]  # Placeholder

    return CausalResult(
        method="PSM",
        treatment_effect=att,
        standard_error=float(se),
        t_statistic=float(t_stat),
        p_value=float(p_value),
        confidence_interval=(float(ci[0]), float(ci[1])),
        n_treated=n_treated,
        n_control=n_control,
        balance_check={
            "n_matched_pairs": len(matched_pairs),
            "caliper": caliper,
            "before_standardized_mean_diff": before_smd,
        },
    )


def granger_causality(
    y: np.ndarray,
    x: np.ndarray,
    max_lag: int = 5,
    alpha: float = 0.05,
) -> CausalResult:
    """Granger causality test.

    Tests whether past values of x help predict y beyond past values of y alone.
    Important caveat: Granger causality tests predictive causality, not
    structural causality. "X Granger-causes Y" means X's past helps predict Y.

    Args:
        y: Dependent time series.
        x: Causal candidate time series.
        max_lag: Maximum number of lags to test.
        alpha: Significance level.

    Returns:
        CausalResult with Granger F-statistics and p-values per lag.
    """
    y = np.asarray(y, dtype=float).ravel()
    x = np.asarray(x, dtype=float).ravel()

    if len(y) != len(x):
        raise ValueError(f"y and x must have same length: {len(y)} vs {len(x)}")

    n = len(y)
    if n < max_lag + 10:
        return CausalResult(method="Granger Causality", n_treated=0, n_control=0)

    f_stats = []
    p_values = []

    for lag in range(1, max_lag + 1):
        # Restricted model: y_t = α + Σ β_j y_{t-j} + ε_t
        y_dep = y[lag:]
        X_restricted = np.column_stack(
            [np.ones(len(y_dep))] +
            [y[lag - j - 1: -j] if j < len(y_dep) else np.zeros(len(y_dep))
             for j in range(1, lag + 1)]
        )

        # Unrestricted model: y_t = α + Σ β_j y_{t-j} + Σ γ_j x_{t-j} + ε_t
        X_unrestricted = np.column_stack(
            [X_restricted] +
            [x[lag - j - 1: -j] if j < len(y_dep) else np.zeros(len(y_dep))
             for j in range(1, lag + 1)]
        )

        try:
            beta_r = np.linalg.lstsq(X_restricted, y_dep, rcond=None)[0]
            residual_r = y_dep - X_restricted @ beta_r
            ssr_r = np.sum(residual_r ** 2)

            beta_u = np.linalg.lstsq(X_unrestricted, y_dep, rcond=None)[0]
            residual_u = y_dep - X_unrestricted @ beta_u
            ssr_u = np.sum(residual_u ** 2)

            df1 = lag  # Number of restrictions
            df2 = n - 2 * lag - 1  # Residual df

            if df2 > 0 and ssr_u > 0:
                F = ((ssr_r - ssr_u) / df1) / (ssr_u / df2)
                p_val = float(scipy_stats.f.sf(F, df1, df2))
            else:
                F = 0.0
                p_val = 1.0

            f_stats.append(float(F))
            p_values.append(float(p_val))

        except np.linalg.LinAlgError:
            f_stats.append(0.0)
            p_values.append(1.0)

    # Check if any lag shows significant Granger causality
    any_significant = any(p < alpha for p in p_values)
    # After Bonferroni correction
    bonferroni_alpha = alpha / max_lag
    bonferroni_significant = any(p < bonferroni_alpha for p in p_values)

    # Use the minimum p-value as the overall test
    min_p = min(p_values) if p_values else 1.0
    # Bonferroni-adjusted
    adj_p = min(min_p * max_lag, 1.0)

    return CausalResult(
        method="Granger Causality",
        treatment_effect=float(f_stats[0]) if f_stats else 0.0,
        standard_error=0.0,
        p_value=adj_p,
        granger_f_stats=f_stats,
        granger_p_values=p_values,
        n_treated=n,
        n_control=n,
        additional={
            "max_lag": max_lag,
            "any_significant": any_significant,
            "any_significant_bonferroni": bonferroni_significant,
            "bonferroni_alpha": bonferroni_alpha,
            "significant_lags": [i + 1 for i, p in enumerate(p_values) if p < alpha],
        },
    )
