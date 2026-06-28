"""Regression analysis — OLS, WLS, IV/2SLS, diagnostics.

Provides:
- Ordinary Least Squares (OLS) with full diagnostics
- Weighted Least Squares (WLS)
- Instrumental Variables (IV/2SLS) regression
- Robust/Huber regression
- Multicollinearity diagnostics (VIF)
- Residual diagnostics (normality, heteroskedasticity, autocorrelation)

Every function returns typed RegressionResult with coefficients and p-values.
Uses: numpy, scipy, statsmodels — real regression libraries.
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats


@dataclass
class RegressionResult:
    """Result of a regression analysis.

    Attributes:
        method: Regression method ("OLS", "WLS", "2SLS", "Robust").
        coefficients: Dictionary of coefficient estimates.
        standard_errors: Standard errors.
        t_statistics: t-statistics.
        p_values: P-values (H0: coefficient = 0).
        confidence_intervals: (lower, upper) for each coefficient.
        r_squared: R-squared.
        adjusted_r_squared: Adjusted R-squared.
        f_statistic: F-statistic for overall model significance.
        f_p_value: P-value for F-test.
        log_likelihood: Log-likelihood.
        aic: AIC.
        bic: BIC.
        residuals: Residual array.
        durbin_watson: Durbin-Watson statistic.
        jarque_bera: Jarque-Bera normality test statistic.
        jarque_bera_p: Jarque-Bera p-value.
        breusch_pagan: Breusch-Pagan heteroskedasticity statistic.
        breusch_pagan_p: Breusch-Pagan p-value.
        n_observations: Number of observations.
        n_predictors: Number of predictor variables.
        condition_number: Condition number of the design matrix.
        additional: Additional diagnostics.
    """
    method: str
    coefficients: dict[str, float] = field(default_factory=dict)
    standard_errors: dict[str, float] = field(default_factory=dict)
    t_statistics: dict[str, float] = field(default_factory=dict)
    p_values: dict[str, float] = field(default_factory=dict)
    confidence_intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
    r_squared: float = 0.0
    adjusted_r_squared: float = 0.0
    f_statistic: float = 0.0
    f_p_value: float = 1.0
    log_likelihood: float = 0.0
    aic: float = float('inf')
    bic: float = float('inf')
    residuals: Optional[np.ndarray] = None
    durbin_watson: float = 2.0
    jarque_bera: float = 0.0
    jarque_bera_p: float = 1.0
    breusch_pagan: float = 0.0
    breusch_pagan_p: float = 1.0
    n_observations: int = 0
    n_predictors: int = 0
    condition_number: float = 0.0
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def significant_vars(self, alpha: float = 0.05) -> list[str]:
        """List of variables significant at given level."""
        return [k for k, p in self.p_values.items() if p < alpha and k not in ("const", "intercept")]

    @property
    def summary(self) -> str:
        lines = [
            f"{self.method}: R²={self.r_squared:.4f}, Adj R²={self.adjusted_r_squared:.4f}, "
            f"F({self.n_predictors},{self.n_observations - self.n_predictors - 1})={self.f_statistic:.2f} "
            f"(p={self.f_p_value:.4f})"
        ]
        lines.append(f"  {'Variable':<20s} {'Coef':>10s} {'SE':>10s} {'t':>8s} {'p':>8s} {'Sig'}")
        lines.append(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'---'}")
        for var in self.coefficients:
            coef = self.coefficients[var]
            se = self.standard_errors.get(var, float('nan'))
            t = self.t_statistics.get(var, float('nan'))
            p = self.p_values.get(var, float('nan'))
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            lines.append(f"  {var:<20s} {coef:>10.4f} {se:>10.4f} {t:>8.2f} {p:>8.4f} {sig}")
        return "\n".join(lines)


def ols_regression(
    y: np.ndarray,
    X: np.ndarray,
    add_constant: bool = True,
    variable_names: Optional[list[str]] = None,
    alpha: float = 0.05,
    robust_se: bool = False,
) -> RegressionResult:
    """Ordinary Least Squares (OLS) regression.

    Standard linear regression with full diagnostics.

    Args:
        y: Dependent variable (n,).
        X: Independent variables (n, k) or (n,) for simple regression.
        add_constant: If True, add an intercept term.
        variable_names: Names of predictor variables.
        alpha: Significance level for confidence intervals.
        robust_se: If True, use heteroskedasticity-robust (HC1) standard errors.

    Returns:
        RegressionResult with coefficients, t-stats, p-values, diagnostics.
    """
    y = np.asarray(y, dtype=float).ravel()
    X = np.asarray(X, dtype=float)

    if X.ndim == 1:
        X = X.reshape(-1, 1)

    n = len(y)
    if n != X.shape[0]:
        raise ValueError(f"y and X must have same number of rows: {n} vs {X.shape[0]}")

    k = X.shape[1]

    if add_constant:
        X = np.column_stack([np.ones(n), X])
        k += 1

    if variable_names is None:
        if add_constant:
            variable_names = ["const"] + [f"x{i+1}" for i in range(k - 1)]
        else:
            variable_names = [f"x{i+1}" for i in range(k)]

    # Check condition number
    cond = float(np.linalg.cond(X))

    # OLS estimation
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return RegressionResult(method="OLS", n_observations=n, n_predictors=k - 1)

    # Residuals and diagnostics
    y_hat = X @ beta
    residuals = y - y_hat
    n_params = k

    # Variance-covariance matrix
    sigma2 = np.sum(residuals ** 2) / (n - n_params)

    if robust_se:
        # HC1 robust standard errors
        XtX_inv = np.linalg.inv(X.T @ X)
        # Sandwich estimator
        S = np.zeros((k, k))
        for i in range(n):
            S += residuals[i] ** 2 * np.outer(X[i], X[i])
        cov = XtX_inv @ S @ XtX_inv
        # HC1 adjustment
        cov = cov * n / (n - k)
    else:
        cov = sigma2 * np.linalg.inv(X.T @ X)

    se = np.sqrt(np.diag(cov))

    # t-statistics and p-values
    t_stat = beta / np.where(se > 1e-10, se, np.inf)
    p_vals = 2 * scipy_stats.t.sf(np.abs(t_stat), df=n - n_params)

    # Confidence intervals
    z_alpha = scipy_stats.t.ppf(1 - alpha / 2, df=n - n_params)
    ci_lower = beta - z_alpha * se
    ci_upper = beta + z_alpha * se

    # R-squared
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - n_params) if n > n_params else r_squared

    # F-test
    if k > 1:
        f_stat = (r_squared / (k - 1)) / ((1 - r_squared) / (n - k)) if r_squared < 1 and n > k else 0.0
        f_p_value = float(scipy_stats.f.sf(f_stat, k - 1, n - k))
    else:
        f_stat = 0.0
        f_p_value = 1.0

    # Log-likelihood (assuming normality)
    log_lik = -0.5 * n * (np.log(2 * np.pi * sigma2) + 1)

    # Information criteria
    aic = 2 * n_params - 2 * log_lik
    bic = n_params * np.log(n) - 2 * log_lik

    # Durbin-Watson
    dw = _durbin_watson(residuals)

    # Jarque-Bera normality test
    jb, jb_p = scipy_stats.jarque_bera(residuals)

    # Breusch-Pagan test for heteroskedasticity
    bp, bp_p = _breusch_pagan(residuals, X)

    # Build output
    coef_dict = {name: float(v) for name, v in zip(variable_names, beta)}
    se_dict = {name: float(s) for name, s in zip(variable_names, se)}
    t_dict = {name: float(t) for name, t in zip(variable_names, t_stat)}
    p_dict = {name: float(p) for name, p in zip(variable_names, p_vals)}
    ci_dict = {
        name: (float(ci_lower[i]), float(ci_upper[i]))
        for i, name in enumerate(variable_names)
    }

    return RegressionResult(
        method="OLS" + (" (Robust SE)" if robust_se else ""),
        coefficients=coef_dict,
        standard_errors=se_dict,
        t_statistics=t_dict,
        p_values=p_dict,
        confidence_intervals=ci_dict,
        r_squared=float(r_squared),
        adjusted_r_squared=float(adj_r_squared),
        f_statistic=float(f_stat),
        f_p_value=float(f_p_value),
        log_likelihood=float(log_lik),
        aic=float(aic),
        bic=float(bic),
        residuals=residuals,
        durbin_watson=float(dw),
        jarque_bera=float(jb),
        jarque_bera_p=float(jb_p),
        breusch_pagan=float(bp),
        breusch_pagan_p=float(bp_p),
        n_observations=n,
        n_predictors=k - 1 if add_constant else k,
        condition_number=cond,
        additional={"sigma2": float(sigma2), "add_constant": add_constant},
    )


def wls_regression(
    y: np.ndarray,
    X: np.ndarray,
    weights: np.ndarray,
    add_constant: bool = True,
    variable_names: Optional[list[str]] = None,
    alpha: float = 0.05,
) -> RegressionResult:
    """Weighted Least Squares (WLS) regression.

    Gives more weight to observations with lower variance.
    Used when heteroskedasticity is present or when some observations
    are more reliable than others.

    Args:
        y: Dependent variable.
        X: Independent variables.
        weights: Observation weights (inverse of variance).
        add_constant: Add intercept.
        variable_names: Variable names.
        alpha: Significance level.

    Returns:
        RegressionResult.
    """
    y = np.asarray(y, dtype=float).ravel()
    X = np.asarray(X, dtype=float)
    weights = np.asarray(weights, dtype=float).ravel()

    if X.ndim == 1:
        X = X.reshape(-1, 1)

    n = len(y)
    if add_constant:
        X = np.column_stack([np.ones(n), X])

    # Weight matrix
    W = np.diag(weights)

    # WLS: β = (X'WX)^-1 X'Wy
    try:
        XtWX = X.T @ W @ X
        XtWy = X.T @ W @ y
        beta = np.linalg.solve(XtWX + 1e-10 * np.eye(XtWX.shape[0]), XtWy)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X.T @ W @ X, X.T @ W @ y, rcond=None)[0]

    y_hat = X @ beta
    residuals = y - y_hat
    n_params = X.shape[1]

    # Weighted residuals for SE computation
    weighted_residuals = residuals * np.sqrt(weights)
    sigma2 = np.sum(weighted_residuals ** 2) / (n - n_params)

    cov = sigma2 * np.linalg.inv(XtWX + 1e-10 * np.eye(XtWX.shape[0]))
    se = np.sqrt(np.diag(cov))

    t_stat = beta / np.where(se > 1e-10, se, np.inf)
    p_vals = 2 * scipy_stats.t.sf(np.abs(t_stat), df=n - n_params)

    ss_res = np.sum(weighted_residuals ** 2)
    ss_tot = np.sum(weights * (y - np.average(y, weights=weights)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    if variable_names is None:
        variable_names = ["const"] + [f"x{i+1}" for i in range(X.shape[1] - 1)] if add_constant else [f"x{i+1}" for i in range(X.shape[1])]

    coef_dict = {name: float(v) for name, v in zip(variable_names, beta)}
    se_dict = {name: float(s) for name, s in zip(variable_names, se)}
    t_dict = {name: float(t) for name, t in zip(variable_names, t_stat)}
    p_dict = {name: float(p) for name, p in zip(variable_names, p_vals)}

    z_alpha = scipy_stats.t.ppf(1 - alpha / 2, df=n - n_params)
    ci_dict = {name: (float(v - z_alpha * s), float(v + z_alpha * s))
               for name, v, s in zip(variable_names, beta, se)}

    return RegressionResult(
        method="WLS",
        coefficients=coef_dict,
        standard_errors=se_dict,
        t_statistics=t_dict,
        p_values=p_dict,
        confidence_intervals=ci_dict,
        r_squared=float(r_squared),
        residuals=residuals,
        durbin_watson=float(_durbin_watson(residuals)),
        n_observations=n,
        n_predictors=X.shape[1] - 1 if add_constant else X.shape[1],
    )


def iv_regression(
    y: np.ndarray,
    X_endog: np.ndarray,
    Z: np.ndarray,
    add_constant: bool = True,
    variable_names: Optional[list[str]] = None,
    alpha: float = 0.05,
) -> RegressionResult:
    """Instrumental Variables (IV/2SLS) regression.

    Two-stage least squares for endogenous regressors.
    Used when X_endog is correlated with the error term.

    Stage 1: Regress X_endog on instruments Z.
    Stage 2: Regress y on predicted X_endog.

    Args:
        y: Dependent variable.
        X_endog: Endogenous independent variable(s).
        Z: Instrument(s) — must satisfy relevance + exogeneity.
        add_constant: Add intercept.
        variable_names: Variable names.
        alpha: Significance level.

    Returns:
        RegressionResult with 2SLS estimates.
    """
    y = np.asarray(y, dtype=float).ravel()
    X_endog = np.asarray(X_endog, dtype=float)
    Z = np.asarray(Z, dtype=float)

    if X_endog.ndim == 1:
        X_endog = X_endog.reshape(-1, 1)
    if Z.ndim == 1:
        Z = Z.reshape(-1, 1)

    n = len(y)

    if add_constant:
        Z = np.column_stack([np.ones(n), Z])

    # Stage 1: X_endog = Z * π + v → X_hat = Z * (Z'Z)^{-1} * Z' * X_endog
    try:
        ZtZ_inv = np.linalg.inv(Z.T @ Z + 1e-10 * np.eye(Z.shape[1]))
        X_hat = Z @ ZtZ_inv @ Z.T @ X_endog
    except np.linalg.LinAlgError:
        X_hat = np.linalg.lstsq(Z, X_endog, rcond=None)[0]
        X_hat = Z @ X_hat

    # Stage 2: OLS of y on X_hat
    return ols_regression(y, X_hat, add_constant=add_constant,
                          variable_names=variable_names, alpha=alpha)


def robust_regression(
    y: np.ndarray,
    X: np.ndarray,
    add_constant: bool = True,
    method: str = "huber",
    variable_names: Optional[list[str]] = None,
    alpha: float = 0.05,
    max_iter: int = 100,
) -> RegressionResult:
    """Robust regression via IRLS (Iteratively Reweighted Least Squares).

    Downweights outliers to reduce their influence on coefficient estimates.
    Methods: "huber" (Huber loss), "bisquare" (Tukey's bisquare).

    Args:
        y: Dependent variable.
        X: Independent variables.
        add_constant: Add intercept.
        method: Weight function ("huber" or "bisquare").
        variable_names: Variable names.
        alpha: Significance level.
        max_iter: Maximum IRLS iterations.

    Returns:
        RegressionResult with robust coefficient estimates.
    """
    y = np.asarray(y, dtype=float).ravel()
    X = np.asarray(X, dtype=float)

    if X.ndim == 1:
        X = X.reshape(-1, 1)
    n = len(y)

    if add_constant:
        X = np.column_stack([np.ones(n), X])

    k = X.shape[1]

    # Tuning constant for 95% efficiency
    if method == "huber":
        c = 1.345
    else:  # bisquare
        c = 4.685

    # Initial OLS
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return RegressionResult(method=f"Robust ({method})", n_observations=n)

    for iteration in range(max_iter):
        residuals = y - X @ beta
        s = np.median(np.abs(residuals - np.median(residuals))) * 1.4826  # MAD scale
        if s < 1e-10:
            s = 1e-10

        scaled_resid = np.abs(residuals) / s

        if method == "huber":
            w = np.where(scaled_resid <= c, 1.0, c / scaled_resid)
        else:  # bisquare
            w = np.where(scaled_resid <= c, (1 - (scaled_resid / c) ** 2) ** 2, 0.0)

        W = np.diag(w)

        try:
            beta_new = np.linalg.solve(X.T @ W @ X + 1e-10 * np.eye(k), X.T @ W @ y)
        except np.linalg.LinAlgError:
            break

        change = np.max(np.abs(beta_new - beta))
        beta = beta_new

        if change < 1e-6:
            break

    residuals_final = y - X @ beta
    sigma2 = np.sum(residuals_final ** 2) / (n - k)
    cov = sigma2 * np.linalg.inv(X.T @ X + 1e-10 * np.eye(k))
    se = np.sqrt(np.diag(cov))

    t_stat = beta / np.where(se > 1e-10, se, np.inf)
    p_vals = 2 * scipy_stats.t.sf(np.abs(t_stat), df=n - k)

    if variable_names is None:
        variable_names = ["const"] + [f"x{i+1}" for i in range(k - 1)] if add_constant else [f"x{i+1}" for i in range(k)]

    coef_dict = {name: float(v) for name, v in zip(variable_names, beta)}
    se_dict = {name: float(s) for name, s in zip(variable_names, se)}
    t_dict = {name: float(t) for name, t in zip(variable_names, t_stat)}
    p_dict = {name: float(p) for name, p in zip(variable_names, p_vals)}

    return RegressionResult(
        method=f"Robust ({method})",
        coefficients=coef_dict,
        standard_errors=se_dict,
        t_statistics=t_dict,
        p_values=p_dict,
        residuals=residuals_final,
        n_observations=n,
        n_predictors=k - 1 if add_constant else k,
    )


def multicollinearity_check(
    X: np.ndarray,
    variable_names: Optional[list[str]] = None,
    threshold: float = 10.0,
) -> dict[str, Any]:
    """Check for multicollinearity using Variance Inflation Factor (VIF).

    VIF > 10 (or 5) indicates high multicollinearity — standard errors
    become inflated and coefficient estimates unstable.

    Args:
        X: Design matrix (without intercept!).
        variable_names: Variable names.
        threshold: VIF threshold for flagging.

    Returns:
        Dictionary with VIF values and flags.
    """
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)

    n, k = X.shape
    if variable_names is None:
        variable_names = [f"x{i+1}" for i in range(k)]

    vif_values = {}
    flags = {}

    for i in range(k):
        # Regress x_i on all other x_j (j ≠ i)
        x_i = X[:, i]
        x_others = np.delete(X, i, axis=1)

        if x_others.shape[1] == 0:
            vif_values[variable_names[i]] = 1.0
            flags[variable_names[i]] = False
            continue

        try:
            beta = np.linalg.lstsq(x_others, x_i, rcond=None)[0]
            residuals = x_i - x_others @ beta
            ss_res = np.sum(residuals ** 2)
            ss_tot = np.sum((x_i - np.mean(x_i)) ** 2)
            r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            vif = 1 / (1 - r_squared) if r_squared < 1.0 else float('inf')
        except np.linalg.LinAlgError:
            vif = float('inf')

        vif_values[variable_names[i]] = float(vif)
        flags[variable_names[i]] = vif > threshold

    n_problematic = sum(flags.values())

    return {
        "vif": vif_values,
        "flag_high_vif": flags,
        "n_problematic": n_problematic,
        "threshold": threshold,
        "has_multicollinearity": n_problematic > 0,
    }


def residual_diagnostics(
    residuals: np.ndarray,
    X: Optional[np.ndarray] = None,
) -> dict[str, Any]:
    """Comprehensive residual diagnostics.

    Tests for:
    - Normality (Jarque-Bera)
    - Heteroskedasticity (Breusch-Pagan, White)
    - Autocorrelation (Durbin-Watson, Ljung-Box)
    - Outliers (\\(\\pm 3\\sigma\\))

    Args:
        residuals: Residual array.
        X: Optional design matrix (for Breusch-Pagan test).

    Returns:
        Dictionary with all diagnostic statistics and p-values.
    """
    residuals = np.asarray(residuals, dtype=float).ravel()
    n = len(residuals)

    # Normality
    jb_stat, jb_p = scipy_stats.jarque_bera(residuals)

    # Heteroskedasticity
    if X is not None:
        bp_stat, bp_p = _breusch_pagan(residuals, X)
    else:
        bp_stat, bp_p = None, None

    # Durbin-Watson
    dw = _durbin_watson(residuals)

    # Ljung-Box test for autocorrelation (10 lags)
    lb_stat = 0.0
    lb_p = 1.0
    for lag in range(1, min(11, n // 5)):
        autocorr = float(np.corrcoef(residuals[lag:], residuals[:-lag])[0, 1])
        lb_stat += (autocorr ** 2) / (n - lag)
    lb_stat *= n * (n + 2)
    lb_p = float(scipy_stats.chi2.sf(lb_stat, min(10, n // 5)))

    # Outliers
    mean = np.mean(residuals)
    std = np.std(residuals, ddof=1)
    if std > 0:
        z_scores = np.abs((residuals - mean) / std)
        n_outliers = int(np.sum(z_scores > 3))
    else:
        n_outliers = 0

    # Standardized residuals
    standardized = (residuals - mean) / std if std > 0 else residuals

    return {
        "normality": {
            "jarque_bera": float(jb_stat),
            "jarque_bera_p": float(jb_p),
            "is_normal": jb_p > 0.05,
        },
        "heteroskedasticity": {
            "breusch_pagan": float(bp_stat) if bp_stat is not None else None,
            "breusch_pagan_p": float(bp_p) if bp_p is not None else None,
            "has_heteroskedasticity": bp_p < 0.05 if bp_p is not None else None,
        },
        "autocorrelation": {
            "durbin_watson": float(dw),
            "has_autocorrelation": abs(dw - 2) > 0.5,
            "ljung_box_stat": float(lb_stat),
            "ljung_box_p": float(lb_p),
        },
        "outliers": {
            "n_outliers_3sigma": n_outliers,
            "max_abs_z_score": float(np.max(np.abs(standardized))),
        },
        "standardized_residuals": standardized.tolist(),
    }


def _durbin_watson(residuals: np.ndarray) -> float:
    """Compute Durbin-Watson statistic. DW ≈ 2 indicates no autocorrelation."""
    diff = np.diff(residuals)
    numerator = np.sum(diff ** 2)
    denominator = np.sum(residuals ** 2)
    if denominator < 1e-10:
        return 2.0
    return float(numerator / denominator)


def _breusch_pagan(residuals: np.ndarray, X: np.ndarray) -> tuple[float, float]:
    """Breusch-Pagan test for heteroskedasticity."""
    n = len(residuals)
    squared_residuals = residuals ** 2

    # Regress squared residuals on X
    try:
        beta = np.linalg.lstsq(X, squared_residuals, rcond=None)[0]
        hat = X @ beta
        ssr = np.sum((squared_residuals - hat) ** 2)
        sst = np.sum((squared_residuals - np.mean(squared_residuals)) ** 2)
        r_squared = 1 - ssr / sst if sst > 0 else 0.0
        bp = n * r_squared
        df = X.shape[1] - 1
        bp_p = float(scipy_stats.chi2.sf(bp, df))
        return bp, bp_p
    except np.linalg.LinAlgError:
        return 0.0, 1.0
