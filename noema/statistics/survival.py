"""Survival analysis methods for trade duration and exit timing.

Provides:
- Kaplan-Meier survival estimator
- Cox Proportional Hazards model
- Log-rank test for comparing survival curves
- Hazard ratio estimation
- Survival function computation

Every function returns typed SurvivalResult with statistics and p-values.
Uses: numpy, scipy, lifelines (optional) — no LLM involvement.

For Noema: Survival analysis models how long trades stay open before
hitting SL, TP, or manual exit. Critical for understanding exit timing
and trade management strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats


@dataclass
class SurvivalResult:
    """Result of a survival analysis.

    Attributes:
        method: Analysis method ("kaplan_meier", "cox_ph", "log_rank").
        times: Event/censoring times.
        survival_probabilities: Survival function values at each time.
        cumulative_hazard: Nelson-Aalen cumulative hazard.
        confidence_intervals: (lower, upper) bands for survival function.
        median_survival_time: Estimated median survival time.
        n_events: Number of events (e.g., SL/TP hits).
        n_censored: Number of censored observations.
        n_total: Total observations.
        hazard_ratio: Hazard ratio (Cox PH).
        log_rank_statistic: Log-rank test statistic.
        log_rank_p_value: Log-rank test p-value.
        additional: Method-specific additional results.
    """
    method: str
    times: np.ndarray = field(default_factory=lambda: np.array([]))
    survival_probabilities: np.ndarray = field(default_factory=lambda: np.array([]))
    cumulative_hazard: np.ndarray = field(default_factory=lambda: np.array([]))
    confidence_intervals: Optional[tuple[np.ndarray, np.ndarray]] = None
    median_survival_time: Optional[float] = None
    n_events: int = 0
    n_censored: int = 0
    n_total: int = 0
    hazard_ratio: Optional[float] = None
    log_rank_statistic: Optional[float] = None
    log_rank_p_value: Optional[float] = None
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def event_rate(self) -> float:
        """Proportion of observations that experienced the event."""
        return self.n_events / self.n_total if self.n_total > 0 else 0.0

    def survival_at_time(self, t: float) -> float:
        """Get survival probability at time t."""
        if len(self.times) == 0:
            return 1.0
        # Find the last observation time <= t
        idx = np.searchsorted(self.times, t, side='right') - 1
        if idx < 0:
            return 1.0
        return float(self.survival_probabilities[idx])

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "median_survival_time": self.median_survival_time,
            "n_events": self.n_events,
            "n_censored": self.n_censored,
            "n_total": self.n_total,
            "event_rate": self.event_rate,
            "hazard_ratio": self.hazard_ratio,
        }


def kaplan_meier(
    durations: np.ndarray,
    event_observed: np.ndarray,
    alpha: float = 0.05,
) -> SurvivalResult:
    """Kaplan-Meier non-parametric survival estimator.

    Estimates the survival function S(t) = P(T > t) without any
    parametric assumptions.

    Args:
        durations: Time until event or censoring (positive values).
        event_observed: Binary array — 1 if event occurred, 0 if censored.
        alpha: Significance level for confidence bands.

    Returns:
        SurvivalResult with KM survival curve.

    Example (Noema trade exit times):
        >>> import numpy as np
        >>> durations = np.array([5, 10, 15, 20, 25, 30, 30])  # bars until exit
        >>> events = np.array([1, 1, 1, 0, 1, 1, 0])  # SL/TP hit or still open
        >>> result = kaplan_meier(durations, events)
        >>> result.median_survival_time
        20.0
    """
    durations = np.asarray(durations, dtype=float).ravel()
    event_observed = np.asarray(event_observed, dtype=bool).ravel()

    if len(durations) != len(event_observed):
        raise ValueError("durations and event_observed must have same length")

    n_total = len(durations)
    if n_total == 0:
        return SurvivalResult(method="Kaplan-Meier")

    # Sort by duration
    sort_idx = np.argsort(durations)
    sorted_durations = durations[sort_idx]
    sorted_events = event_observed[sort_idx]

    # Unique event times
    unique_times = np.unique(sorted_durations[sorted_events])

    if len(unique_times) == 0:
        return SurvivalResult(
            method="Kaplan-Meier",
            times=sorted_durations,
            survival_probabilities=np.ones(n_total),
            n_events=0,
            n_censored=n_total,
            n_total=n_total,
        )

    # Compute KM estimate
    survival = np.ones(len(unique_times))
    n_at_risk = n_total
    cumulative_hazard = np.zeros(len(unique_times))
    n_events_at_time = []

    for i, t in enumerate(unique_times):
        # Count events at this time
        events_at_t = np.sum((sorted_durations == t) & sorted_events)
        # Count censored before or at this time (but not at this exact event time)
        # KM: censorings contribute to at-risk until after the event time

        if n_at_risk > 0 and events_at_t > 0:
            survival_mult = (n_at_risk - events_at_t) / n_at_risk
            survival[i] = survival[i - 1] * survival_mult if i > 0 else survival_mult
            cumulative_hazard[i] = cumulative_hazard[i - 1] + events_at_t / n_at_risk if i > 0 else events_at_t / n_at_risk
        else:
            survival[i] = survival[i - 1] if i > 0 else 1.0
            cumulative_hazard[i] = cumulative_hazard[i - 1] if i > 0 else 0.0

        n_events_at_time.append(events_at_t)
        # Reduce at-risk for both events and censorings at/after this time
        at_t_mask = sorted_durations == t
        n_at_risk -= np.sum(at_t_mask)

    # Confidence bands (Greenwood formula)
    n_at_risk = n_total
    var_survival = np.zeros(len(unique_times))

    for i, t in enumerate(unique_times):
        events_at_t = n_events_at_time[i]
        if n_at_risk > 0 and n_at_risk > events_at_t:
            # Greenwood's formula: var(S) = S² * Σ d[j] / (n[j]*(n[j]-d[j]))
            cumulative_var = 0.0
            temp_at_risk = n_total
            for j in range(i + 1):
                d_j = n_events_at_time[j]
                if temp_at_risk > 0 and temp_at_risk > d_j:
                    cumulative_var += d_j / (temp_at_risk * (temp_at_risk - d_j))
                # Reduce at-risk for j
                at_j_mask = sorted_durations == unique_times[j]
                temp_at_risk -= np.sum(at_j_mask)

            var_survival[i] = survival[i] ** 2 * cumulative_var

        n_at_risk -= np.sum(sorted_durations == t)

    # Log-log transformation for CI
    z = scipy_stats.norm.ppf(1 - alpha / 2)
    # Avoid -inf log
    surv_clip = np.clip(survival, 1e-10, 1.0)
    se_log_log = np.sqrt(var_survival) / (-surv_clip * np.log(surv_clip))
    ci_lower = surv_clip ** np.exp(z * se_log_log)
    ci_upper = surv_clip ** np.exp(-z * se_log_log)

    # Median survival time
    median_time = None
    below_median = np.where(survival <= 0.5)[0]
    if len(below_median) > 0:
        median_time = float(unique_times[below_median[0]])

    n_events = int(np.sum(event_observed))
    n_censored = n_total - n_events

    return SurvivalResult(
        method="Kaplan-Meier",
        times=unique_times,
        survival_probabilities=survival,
        cumulative_hazard=cumulative_hazard,
        confidence_intervals=(ci_lower, ci_upper),
        median_survival_time=median_time,
        n_events=n_events,
        n_censored=n_censored,
        n_total=n_total,
        additional={
            "alpha": alpha,
            "greenwood_se": np.sqrt(var_survival).tolist(),
        },
    )


def cox_proportional_hazards(
    durations: np.ndarray,
    event_observed: np.ndarray,
    covariates: np.ndarray,
    alpha: float = 0.05,
) -> SurvivalResult:
    """Cox Proportional Hazards model.

    Semi-parametric model: h(t|X) = h0(t) * exp(β^T X).
    Estimates hazard ratios for each covariate without specifying
    the baseline hazard.

    For Noema: Model how different features (volatility, spread, session,
    ATR) affect the hazard rate of SL/TP being hit.

    Args:
        durations: Time until event/censoring.
        event_observed: Binary event indicator.
        covariates: (n_samples, n_features) matrix of covariates.
        alpha: Significance level.

    Returns:
        SurvivalResult with hazard ratios and model diagnostics.
    """
    durations = np.asarray(durations, dtype=float).ravel()
    event_observed = np.asarray(event_observed, dtype=bool).ravel()
    covariates = np.asarray(covariates, dtype=float)

    if covariates.ndim == 1:
        covariates = covariates.reshape(-1, 1)

    n_total, n_covars = covariates.shape

    if n_total < 5:
        return SurvivalResult(method="Cox PH", n_total=n_total)

    n_events = int(np.sum(event_observed))

    try:
        # Use partial likelihood maximization (Breslow tie handling)
        # Simplified Newton-Raphson for Cox PH
        beta = np.zeros(n_covars)
        learning_rate = 0.1
        max_iter = 200
        tol = 1e-6

        for iteration in range(max_iter):
            # Sort by duration (descending)
            order = np.argsort(-durations)
            sorted_dur = durations[order]
            sorted_ev = event_observed[order]
            sorted_X = covariates[order]

            # Compute gradient and Hessian of partial log-likelihood
            # at each event time
            gradient = np.zeros(n_covars)
            hessian = np.zeros((n_covars, n_covars))
            log_lik = 0.0

            for i in range(n_total):
                if sorted_ev[i]:
                    # Risk set: all subjects with duration >= current
                    risk_set = np.arange(i, n_total)
                    X_risk = sorted_X[risk_set]
                    exp_lin = np.exp(X_risk @ beta)

                    sum_exp = np.sum(exp_lin)
                    weighted_sum = (X_risk.T @ exp_lin) / sum_exp

                    # Gradient contribution
                    gradient += sorted_X[i] - weighted_sum

                    # Hessian contribution
                    for p in range(n_covars):
                        for q in range(p, n_covars):
                            h_val = -(np.sum(X_risk[:, p] * X_risk[:, q] * exp_lin) / sum_exp -
                                      weighted_sum[p] * weighted_sum[q])
                            hessian[p, q] += h_val
                            hessian[q, p] = hessian[p, q]

                    log_lik += sorted_X[i] @ beta - np.log(sum_exp)

            # Newton step
            try:
                hessian_reg = hessian + np.eye(n_covars) * 1e-6
                delta = np.linalg.solve(hessian_reg, gradient)
            except np.linalg.LinAlgError:
                delta = gradient * learning_rate

            beta_new = beta + delta
            change = np.max(np.abs(beta_new - beta))
            beta = beta_new

            if change < tol:
                break

        # Standard errors from inverse of negative Hessian
        try:
            se = np.sqrt(np.diag(np.linalg.inv(-hessian - np.eye(n_covars) * 1e-6)))
        except np.linalg.LinAlgError:
            se = np.full(n_covars, np.nan)

        # Hazard ratios
        hazard_ratios = np.exp(beta)
        hr_se = se * hazard_ratios

        # P-values (Wald test)
        z_scores = beta / np.where(se > 1e-10, se, np.nan)
        p_values = 2 * scipy_stats.norm.sf(np.abs(z_scores))

        # Confidence intervals for hazard ratios
        z_alpha = scipy_stats.norm.ppf(1 - alpha / 2)
        hr_ci_lower = np.exp(beta - z_alpha * se)
        hr_ci_upper = np.exp(beta + z_alpha * se)

        # Model diagnostics
        aic = 2 * n_covars - 2 * log_lik
        # Likelihood ratio test vs null model
        lr_stat = 2 * (log_lik - 0)  # null log-lik = 0 (all β = 0)
        lr_p_value = float(scipy_stats.chi2.sf(lr_stat, n_covars))

        # Baseline survival via Breslow estimator
        # Sort ascending for baseline
        asc_order = np.argsort(durations)
        asc_dur = durations[asc_order]
        asc_ev = event_observed[asc_order]
        asc_X = covariates[asc_order]

        unique_times = np.unique(asc_dur[asc_ev])
        baseline_cumhaz = np.zeros_like(unique_times, dtype=float)

        for i, t in enumerate(unique_times):
            at_t = asc_dur == t
            d_t = np.sum(asc_ev[at_t])
            risk_at_t = np.where(asc_dur >= t)[0]
            if len(risk_at_t) > 0 and d_t > 0:
                denom = np.sum(np.exp(asc_X[risk_at_t] @ beta))
                baseline_cumhaz[i] = d_t / denom

        baseline_cumhaz = np.cumsum(baseline_cumhaz)

        return SurvivalResult(
            method="Cox Proportional Hazards",
            times=unique_times,
            cumulative_hazard=baseline_cumhaz,
            n_events=n_events,
            n_censored=n_total - n_events,
            n_total=n_total,
            hazard_ratio=float(hazard_ratios[0]) if n_covars == 1 else None,
            additional={
                "beta": beta.tolist(),
                "standard_errors": se.tolist(),
                "hazard_ratios": hazard_ratios.tolist(),
                "hr_ci_lower": hr_ci_lower.tolist(),
                "hr_ci_upper": hr_ci_upper.tolist(),
                "z_scores": z_scores.tolist(),
                "p_values": p_values.tolist(),
                "log_likelihood": float(log_lik),
                "aic": float(aic),
                "lr_test_statistic": float(lr_stat),
                "lr_test_p_value": lr_p_value,
                "n_covariates": n_covars,
            },
        )

    except Exception:
        return SurvivalResult(
            method="Cox PH (failed)",
            n_events=int(np.sum(event_observed)),
            n_total=n_total,
        )


def log_rank_test(
    group_a_durations: np.ndarray,
    group_a_events: np.ndarray,
    group_b_durations: np.ndarray,
    group_b_events: np.ndarray,
    alpha: float = 0.05,
) -> SurvivalResult:
    """Log-rank test for comparing two survival curves.

    Tests H0: The two groups have identical survival functions.
    Non-parametric — makes no distributional assumptions.

    For Noema: Compare survival curves of trades during London vs NY,
    or high-volatility vs low-volatility regimes.

    Args:
        group_a_durations: Times for group A.
        group_a_events: Event indicators for group A.
        group_b_durations: Times for group B.
        group_b_events: Event indicators for group B.
        alpha: Significance level.

    Returns:
        SurvivalResult with log-rank statistic and p-value.
    """
    a_dur = np.asarray(group_a_durations, dtype=float).ravel()
    a_ev = np.asarray(group_a_events, dtype=bool).ravel()
    b_dur = np.asarray(group_b_durations, dtype=float).ravel()
    b_ev = np.asarray(group_b_events, dtype=bool).ravel()

    # Combine and label
    all_times = np.concatenate([a_dur, b_dur])
    all_events = np.concatenate([a_ev, b_ev])
    groups = np.concatenate([np.zeros(len(a_dur)), np.ones(len(b_dur))])

    # Sort by time
    sort_idx = np.argsort(all_times)
    sorted_times = all_times[sort_idx]
    sorted_events = all_events[sort_idx]
    sorted_groups = groups[sort_idx]

    # Unique event times
    event_mask = sorted_events
    unique_event_times = np.unique(sorted_times[event_mask])

    # Log-rank computation
    observed_minus_expected = 0.0
    var_sum = 0.0
    n_total = len(all_times)

    for t in unique_event_times:
        at_t = sorted_times == t
        n_at_risk = n_total - np.searchsorted(sorted_times, t)

        n_events_a = np.sum(at_t & event_mask & (sorted_groups == 0))
        n_events_b = np.sum(at_t & event_mask & (sorted_groups == 1))
        n_a = np.sum(sorted_times >= t) - np.sum((sorted_times >= t) & (sorted_groups == 1))
        n_b = np.sum(sorted_times >= t) & (sorted_groups == 1)
        n_a = np.sum((sorted_times >= t) & (sorted_groups == 0))
        n_b = np.sum((sorted_times >= t) & (sorted_groups == 1))

        total_events = n_events_a + n_events_b
        total_at_risk = n_a + n_b

        if total_at_risk > 0 and total_events > 0:
            expected_a = total_events * n_a / total_at_risk
            observed_minus_expected += (n_events_a - expected_a)

            if total_at_risk > 1:
                var_contrib = (n_a * n_b * total_events * (total_at_risk - total_events)) / \
                              (total_at_risk ** 2 * (total_at_risk - 1))
                var_sum += var_contrib

    if var_sum > 0:
        z_stat = observed_minus_expected / np.sqrt(var_sum)
    else:
        z_stat = 0.0

    # Chi-square with 1 df
    chi2_stat = z_stat ** 2
    p_value = float(scipy_stats.chi2.sf(chi2_stat, 1))

    return SurvivalResult(
        method="Log-Rank Test",
        log_rank_statistic=float(chi2_stat),
        log_rank_p_value=p_value,
        n_events=int(np.sum(all_events)),
        n_total=n_total,
        n_censored=n_total - int(np.sum(all_events)),
        additional={
            "z_statistic": float(z_stat),
            "group_a_n": len(a_dur),
            "group_b_n": len(b_dur),
            "significantly_different": p_value < alpha,
        },
    )


def hazard_ratio(
    group_a_durations: np.ndarray,
    group_a_events: np.ndarray,
    group_b_durations: np.ndarray,
    group_b_events: np.ndarray,
    alpha: float = 0.05,
) -> SurvivalResult:
    """Estimate hazard ratio between two groups (Mantel-Haenszel method).

    HR > 1: Group B has higher hazard (shorter survival) than Group A.
    HR < 1: Group B has lower hazard (longer survival) than Group A.

    Args:
        group_a_durations: Times for reference group A.
        group_a_events: Event indicators for group A.
        group_b_durations: Times for group B.
        group_b_events: Event indicators for group B.
        alpha: Significance level.

    Returns:
        SurvivalResult with log-rank test and hazard ratio.
    """
    # First run log-rank
    log_rank = log_rank_test(
        group_a_durations, group_a_events,
        group_b_durations, group_b_events,
        alpha=alpha,
    )

    # Mantel-Haenszel hazard ratio
    a_dur = np.asarray(group_a_durations, dtype=float).ravel()
    a_ev = np.asarray(group_a_events, dtype=bool).ravel()
    b_dur = np.asarray(group_b_durations, dtype=float).ravel()
    b_ev = np.asarray(group_b_events, dtype=bool).ravel()

    all_times = np.concatenate([a_dur, b_dur])
    all_events = np.concatenate([a_ev, b_ev])
    groups = np.concatenate([np.zeros(len(a_dur)), np.ones(len(b_dur))])

    sort_idx = np.argsort(all_times)
    sorted_times = all_times[sort_idx]
    sorted_events = all_events[sort_idx]
    sorted_groups = groups[sort_idx]

    # HR numerator & denominator
    numerator = 0.0
    denominator = 0.0

    for t in np.unique(sorted_times[sorted_events]):
        at_t = sorted_times == t
        d1 = np.sum(at_t & (sorted_groups == 0) & sorted_events)  # A events
        d2 = np.sum(at_t & (sorted_groups == 1) & sorted_events)  # B events
        n1 = np.sum((sorted_times >= t) & (sorted_groups == 0))   # A at risk
        n2 = np.sum((sorted_times >= t) & (sorted_groups == 1))   # B at risk
        total_n = n1 + n2
        total_d = d1 + d2

        if total_n > 0 and total_d > 0:
            numerator += d1 * n2 / total_n
            denominator += d2 * n1 / total_n

    if denominator > 0:
        hr = numerator / denominator
        hr_se = np.sqrt(1 / numerator + 1 / denominator) if numerator > 0 and denominator > 0 else float('inf')
    else:
        hr = 1.0
        hr_se = float('inf')

    return SurvivalResult(
        method="Hazard Ratio (Mantel-Haenszel)",
        hazard_ratio=float(hr),
        log_rank_statistic=log_rank.log_rank_statistic,
        log_rank_p_value=log_rank.log_rank_p_value,
        n_events=log_rank.n_events,
        n_total=log_rank.n_total,
        n_censored=log_rank.n_censored,
        additional={
            "hr_se": float(hr_se),
            "group_a_n": len(a_dur),
            "group_b_n": len(b_dur),
            "group_a_is_reference": True,
        },
    )


def survival_function(
    times: np.ndarray,
    survival_probs: np.ndarray,
) -> dict[str, np.ndarray]:
    """Compute derived quantities from a survival function.

    Args:
        times: Time points.
        survival_probs: Survival probability S(t) at each time.

    Returns:
        Dictionary with 'times', 'survival', 'cumulative_hazard', 'density'.
    """
    times = np.asarray(times, dtype=float).ravel()
    survival = np.asarray(survival_probs, dtype=float).ravel()

    # Cumulative hazard: H(t) = -ln(S(t))
    cumhaz = -np.log(np.clip(survival, 1e-10, 1.0))

    # Probability density: f(t) = -dS/dt
    f = np.zeros_like(survival)
    for i in range(1, len(survival)):
        dt = times[i] - times[i - 1]
        if dt > 0:
            f[i] = -(survival[i] - survival[i - 1]) / dt

    return {
        "times": times,
        "survival": survival,
        "cumulative_hazard": cumhaz,
        "density": f,
    }
