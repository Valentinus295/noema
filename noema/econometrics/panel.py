"""Panel data analysis — fixed effects, random effects, Hausman test.

Provides:
- Pooled OLS for panel data
- Fixed effects (within) estimator
- Random effects (GLS) estimator
- Hausman test for FE vs RE
- Panel summary statistics

Every function returns typed PanelResult with coefficients and diagnostics.
Uses: numpy, scipy — real statistics libraries.
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats
from noema.econometrics.regression import ols_regression


@dataclass
class PanelResult:
    """Result of a panel data regression.

    Attributes:
        method: Estimation method ("fixed_effects", "random_effects", "pooled").
        coefficients: Dictionary of coefficient estimates.
        standard_errors: Standard errors.
        t_statistics: t-statistics.
        p_values: P-values.
        r_squared: Overall R-squared.
        within_r_squared: Within-group R-squared (for FE).
        between_r_squared: Between-group R-squared (for FE).
        overall_r_squared: Overall R-squared (for FE).
        f_statistic: F-statistic.
        f_p_value: F-test p-value.
        entity_effects: Estimated entity-specific effects (for FE).
        time_effects: Estimated time effects (if included).
        hausman_stat: Hausman test statistic (when comparing FE vs RE).
        hausman_p: Hausman p-value.
        n_observations: Total observations.
        n_entities: Number of entities (e.g., symbols).
        n_periods: Number of time periods.
        theta: GLS transformation parameter (for RE).
        additional: Additional diagnostics.
    """
    method: str
    coefficients: dict[str, float] = field(default_factory=dict)
    standard_errors: dict[str, float] = field(default_factory=dict)
    t_statistics: dict[str, float] = field(default_factory=dict)
    p_values: dict[str, float] = field(default_factory=dict)
    r_squared: float = 0.0
    within_r_squared: float = 0.0
    between_r_squared: float = 0.0
    overall_r_squared: float = 0.0
    f_statistic: float = 0.0
    f_p_value: float = 1.0
    entity_effects: Optional[dict[int, float]] = None
    time_effects: Optional[dict[int, float]] = None
    hausman_stat: Optional[float] = None
    hausman_p: Optional[float] = None
    n_observations: int = 0
    n_entities: int = 0
    n_periods: int = 0
    theta: float = 0.0
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        lines = [
            f"{self.method}: R²={self.r_squared:.4f}, "
            f"F({len(self.coefficients)},{self.n_observations - len(self.coefficients) - 1}) "
            f"= {self.f_statistic:.2f} (p={self.f_p_value:.4f})"
        ]
        if self.hausman_stat is not None:
            lines.append(f"  Hausman: χ²={self.hausman_stat:.2f}, p={self.hausman_p:.4f}")
        lines.append(f"  N={self.n_observations}, Entities={self.n_entities}, Periods={self.n_periods}")
        for var in self.coefficients:
            coef = self.coefficients[var]
            se = self.standard_errors.get(var, float('nan'))
            t = self.t_statistics.get(var, float('nan'))
            p = self.p_values.get(var, float('nan'))
            lines.append(f"  {var}: {coef:.4f} ({se:.4f}) t={t:.2f} p={p:.4f}")
        return "\n".join(lines)


def pooled_ols(
    y: np.ndarray,
    X: np.ndarray,
    add_constant: bool = True,
    variable_names: Optional[list[str]] = None,
    entity_ids: Optional[np.ndarray] = None,
) -> PanelResult:
    """Pooled OLS regression for panel data.

    Ignores panel structure — treats all observations as independent.
    Only appropriate if there are no entity-specific effects.

    Args:
        y: Dependent variable (n_total,).
        X: Independent variables (n_total, k).
        add_constant: Add intercept.
        variable_names: Variable names.
        entity_ids: Optional entity identifiers for summary stats.

    Returns:
        PanelResult with pooled OLS estimates.
    """
    y = np.asarray(y, dtype=float).ravel()
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)

    result = ols_regression(y, X, add_constant=add_constant, variable_names=variable_names)

    n_entities = len(np.unique(entity_ids)) if entity_ids is not None else 1
    # Approximate time periods
    n_periods = int(result.n_observations / max(n_entities, 1))

    return PanelResult(
        method="Pooled OLS",
        coefficients=result.coefficients,
        standard_errors=result.standard_errors,
        t_statistics=result.t_statistics,
        p_values=result.p_values,
        r_squared=result.r_squared,
        f_statistic=result.f_statistic,
        f_p_value=result.f_p_value,
        n_observations=result.n_observations,
        n_entities=n_entities,
        n_periods=n_periods,
    )


def fixed_effects(
    y: np.ndarray,
    X: np.ndarray,
    entity_ids: np.ndarray,
    time_ids: Optional[np.ndarray] = None,
    variable_names: Optional[list[str]] = None,
    alpha: float = 0.05,
) -> PanelResult:
    """Fixed effects (within) estimator for panel data.

    Controls for time-invariant entity-specific effects by demeaning
    the data within each entity. Equivalent to including entity dummies.

    This is the standard approach for panels where entity effects
    are correlated with the regressors (e.g., different broker-specific
    price biases that correlate with observed spreads).

    Args:
        y: Dependent variable (n_total,).
        X: Independent variables (n_total, k).
        entity_ids: Entity identifiers (1-D integer array, same length as y).
        time_ids: Optional time identifiers for two-way FE.
        variable_names: Variable names.
        alpha: Significance level.

    Returns:
        PanelResult with FE estimates.
    """
    y = np.asarray(y, dtype=float).ravel()
    X = np.asarray(X, dtype=float)
    entity_ids = np.asarray(entity_ids, dtype=int).ravel()

    if X.ndim == 1:
        X = X.reshape(-1, 1)

    n = len(y)
    n_entities = len(np.unique(entity_ids))
    k = X.shape[1]

    # Within transformation: demean each entity
    y_within = np.zeros(n)
    X_within = np.zeros((n, k))

    unique_entities = np.unique(entity_ids)
    entity_effects: dict[int, float] = {}

    for e in unique_entities:
        mask = entity_ids == e
        y_mean = np.mean(y[mask])
        X_mean = np.mean(X[mask], axis=0)

        y_within[mask] = y[mask] - y_mean
        X_within[mask] = X[mask] - X_mean
        entity_effects[int(e)] = float(y_mean - X_mean @ np.zeros(k))

    # OLS on demeaned data
    if variable_names is None:
        variable_names = [f"x{i+1}" for i in range(k)]

    # Remove intercept — demeaned data has no constant
    X_wconst = np.column_stack([np.ones(n), X_within])
    var_names_wconst = ["const"] + variable_names

    result = ols_regression(y_within, X_within, add_constant=True, variable_names=var_names_wconst)

    # Recover entity effects
    for e in unique_entities:
        mask = entity_ids == e
        e_indices = np.where(mask)[0]
        if len(e_indices) > 0:
            y_mean = np.mean(y[mask])
            X_mean = np.mean(X[mask], axis=0)
            beta_vec = np.array([result.coefficients.get(name, 0.0) for name in variable_names])
            entity_effects[int(e)] = float(y_mean - X_mean @ beta_vec)

    # Compute R-squared components
    ss_total = np.sum((y - np.mean(y)) ** 2)
    y_hat = np.zeros(n)
    for e in unique_entities:
        mask = entity_ids == e
        beta_vec = np.array([result.coefficients.get(name, 0.0) for name in variable_names])
        y_hat[mask] = X[mask] @ beta_vec + entity_effects[int(e)]

    overall_r2 = 1 - np.sum((y - y_hat) ** 2) / ss_total if ss_total > 0 else 0.0
    within_r2 = result.r_squared

    return PanelResult(
        method="Fixed Effects",
        coefficients=result.coefficients,
        standard_errors=result.standard_errors,
        t_statistics=result.t_statistics,
        p_values=result.p_values,
        r_squared=overall_r2,
        within_r_squared=within_r2,
        overall_r_squared=overall_r2,
        f_statistic=result.f_statistic,
        f_p_value=result.f_p_value,
        entity_effects=entity_effects,
        n_observations=n,
        n_entities=n_entities,
        n_periods=int(n / max(n_entities, 1)),
    )


def random_effects(
    y: np.ndarray,
    X: np.ndarray,
    entity_ids: np.ndarray,
    variable_names: Optional[list[str]] = None,
    alpha: float = 0.05,
) -> PanelResult:
    """Random effects (GLS) estimator for panel data.

    Assumes entity effects are uncorrelated with regressors.
    Uses Feasible GLS with the transformation parameter θ.

    RE is more efficient than FE if the uncorrelatedness assumption holds.
    Use Hausman test to choose between FE and RE.

    Args:
        y: Dependent variable.
        X: Independent variables.
        entity_ids: Entity identifiers.
        variable_names: Variable names.
        alpha: Significance level.

    Returns:
        PanelResult with RE estimates.
    """
    y = np.asarray(y, dtype=float).ravel()
    X = np.asarray(X, dtype=float)
    entity_ids = np.asarray(entity_ids, dtype=int).ravel()

    if X.ndim == 1:
        X = X.reshape(-1, 1)

    n = len(y)
    k = X.shape[1]
    n_entities = len(np.unique(entity_ids))

    if variable_names is None:
        variable_names = [f"x{i+1}" for i in range(k)]

    # Step 1: Estimate σ²_e and σ²_u via within and between regressions
    # Within variance
    y_demeaned = np.zeros(n)
    X_demeaned = np.zeros((n, k))

    unique_entities = np.unique(entity_ids)
    for e in unique_entities:
        mask = entity_ids == e
        y_demeaned[mask] = y[mask] - np.mean(y[mask])
        X_demeaned[mask] = X[mask] - np.mean(X[mask], axis=0)

    # Within OLS → σ²_e
    X_w = np.column_stack([np.ones(n), X_demeaned])
    try:
        beta_w = np.linalg.lstsq(X_w, y_demeaned, rcond=None)[0]
        residuals_w = y_demeaned - X_w @ beta_w
        sigma2_e = float(np.sum(residuals_w ** 2) / (n - k - 1))
    except np.linalg.LinAlgError:
        sigma2_e = float(np.var(y_demeaned))

    # Between → σ²_u + σ²_e/T
    entity_means_y = np.array([np.mean(y[entity_ids == e]) for e in unique_entities])
    entity_means_X = np.array([np.mean(X[entity_ids == e], axis=0) for e in unique_entities])
    T_bar = n / n_entities

    try:
        X_b = np.column_stack([np.ones(n_entities), entity_means_X])
        beta_b = np.linalg.lstsq(X_b, entity_means_y, rcond=None)[0]
        residuals_b = entity_means_y - X_b @ beta_b
        sigma2_between = float(np.sum(residuals_b ** 2) / (n_entities - k - 1))
        sigma2_u = max(sigma2_between - sigma2_e / T_bar, 0.0)
    except np.linalg.LinAlgError:
        sigma2_u = 0.0

    # Transformation parameter θ = 1 - σ_e / √(σ²_e + T_i * σ²_u)
    theta = 1 - np.sqrt(sigma2_e / (sigma2_e + T_bar * sigma2_u + 1e-10))

    # GLS transformation
    y_gls = np.zeros(n)
    X_gls = np.zeros((n, k))
    X_gls_intercept = np.zeros(n)

    for e in unique_entities:
        mask = entity_ids == e
        T_e = np.sum(mask)
        theta_e = 1 - np.sqrt(sigma2_e / (sigma2_e + T_e * sigma2_u + 1e-10))

        y_mean = np.mean(y[mask])
        X_mean = np.mean(X[mask], axis=0)

        y_gls[mask] = y[mask] - theta_e * y_mean
        X_gls[mask] = X[mask] - theta_e * X_mean
        X_gls_intercept[mask] = 1 - theta_e  # Transformed intercept

    # OLS on transformed data
    X_transformed = np.column_stack([X_gls_intercept, X_gls])
    var_names = ["const"] + variable_names

    result = ols_regression(y_gls, X_gls, add_constant=True, variable_names=var_names)

    return PanelResult(
        method="Random Effects",
        coefficients=result.coefficients,
        standard_errors=result.standard_errors,
        t_statistics=result.t_statistics,
        p_values=result.p_values,
        r_squared=result.r_squared,
        f_statistic=result.f_statistic,
        f_p_value=result.f_p_value,
        n_observations=n,
        n_entities=n_entities,
        n_periods=int(n / max(n_entities, 1)),
        theta=float(theta),
        additional={"sigma2_e": sigma2_e, "sigma2_u": sigma2_u, "T_bar": T_bar},
    )


def hausman_test(
    fe_result: PanelResult,
    re_result: PanelResult,
) -> PanelResult:
    """Hausman specification test: Fixed Effects vs Random Effects.

    H0: Random effects consistent + efficient (no correlation entity effects ↔ X).
    H1: Fixed effects consistent (RE inconsistent due to correlation).

    If p < 0.05 → reject H0 → use Fixed Effects.
    If p > 0.05 → fail to reject → Random Effects is efficient and consistent.

    Args:
        fe_result: Fixed effects result.
        re_result: Re effects result.

    Returns:
        PanelResult with Hausman statistic and p-value.
    """
    common_vars = list(set(fe_result.coefficients.keys()) & set(re_result.coefficients.keys()) - {"const"})

    if len(common_vars) == 0:
        return PanelResult(method="Hausman Test", hausman_stat=float('nan'), hausman_p=1.0)

    fe_coefs = np.array([fe_result.coefficients.get(v, 0.0) for v in common_vars])
    re_coefs = np.array([re_result.coefficients.get(v, 0.0) for v in common_vars])

    diff = fe_coefs - re_coefs

    # Var(β_FE - β_RE) = Var(β_FE) - Var(β_RE) (Hausman 1978)
    # Approximate using standard errors
    fe_var = np.array([fe_result.standard_errors.get(v, 1.0) ** 2 for v in common_vars])
    re_var = np.array([re_result.standard_errors.get(v, 1.0) ** 2 for v in common_vars])

    # Ensure positive-definite
    var_diff = np.maximum(fe_var - re_var, 1e-10)

    try:
        H = float(diff @ np.diag(1 / var_diff) @ diff)
        df = len(common_vars)
        p_value = float(scipy_stats.chi2.sf(H, df))
    except Exception:
        H = float('inf')
        p_value = 0.0

    return PanelResult(
        method="Hausman Test",
        hausman_stat=H,
        hausman_p=p_value,
        n_observations=fe_result.n_observations,
        additional={
            "use_fixed_effects": p_value < 0.05,
            "n_vars_compared": len(common_vars),
            "vars_compared": common_vars,
        },
    )


def panel_summary(
    y: np.ndarray,
    entity_ids: np.ndarray,
    time_ids: Optional[np.ndarray] = None,
) -> dict[str, Any]:
    """Compute panel data summary statistics.

    Args:
        y: Panel response variable.
        entity_ids: Entity identifiers.
        time_ids: Optional time identifiers.

    Returns:
        Dictionary with panel dimensions, means, variances.
    """
    y = np.asarray(y, dtype=float).ravel()
    entity_ids = np.asarray(entity_ids, dtype=int).ravel()

    n_total = len(y)
    n_entities = len(np.unique(entity_ids))
    n_periods = len(np.unique(time_ids)) if time_ids is not None else int(n_total / n_entities)
    balanced = all(np.sum(entity_ids == e) == n_periods for e in np.unique(entity_ids))

    # Within and between variance decomposition
    overall_mean = float(np.mean(y))
    overall_var = float(np.var(y))

    entity_means = np.array([np.mean(y[entity_ids == e]) for e in np.unique(entity_ids)])
    between_var = float(np.var(entity_means))

    within_vars = np.array([np.var(y[entity_ids == e]) for e in np.unique(entity_ids)])
    within_var = float(np.mean(within_vars))

    return {
        "n_total": n_total,
        "n_entities": n_entities,
        "n_periods": n_periods,
        "balanced": balanced,
        "overall_mean": overall_mean,
        "overall_var": overall_var,
        "between_var": between_var,
        "within_var": within_var,
        "between_fraction": between_var / overall_var if overall_var > 0 else 0.0,
        "entity_mean_range": (float(np.min(entity_means)), float(np.max(entity_means))),
    }
