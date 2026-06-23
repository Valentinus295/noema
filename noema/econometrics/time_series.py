"""Time series analysis — stationarity testing, ARIMA modeling.

Provides:
- ADF (Augmented Dickey-Fuller) test for unit roots
- KPSS test for stationarity around a trend
- ARIMA/SARIMAX model estimation and forecasting
- Automatic ARIMA order selection via AIC/BIC

Every function returns typed StationarityResult with test statistics and p-values.
Uses: numpy, scipy, statsmodels — real econometric libraries.
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


@dataclass
class StationarityResult:
    """Result of a stationarity/time series test.

    Attributes:
        test_name: Name of the test ("ADF", "KPSS", "ARIMA").
        statistic: Test statistic.
        p_value: P-value.
        critical_values: Critical values at 1%, 5%, 10%.
        is_stationary: True if series is stationary (p < alpha).
        alpha: Significance level.
        n_lags: Number of lags used.
        n_observations: Number of observations.
        model_params: Estimated model parameters (for ARIMA).
        information_criteria: AIC, BIC, HQIC.
        residuals: Model residuals (for ARIMA).
        forecast: Forecast values (for ARIMA forecast).
        additional: Test-specific additional results.
    """
    test_name: str
    statistic: float = 0.0
    p_value: float = 1.0
    critical_values: dict[str, float] = field(default_factory=dict)
    is_stationary: bool = False
    alpha: float = 0.05
    n_lags: int = 0
    n_observations: int = 0
    model_params: Optional[np.ndarray] = None
    information_criteria: dict[str, float] = field(default_factory=dict)
    residuals: Optional[np.ndarray] = None
    forecast: Optional[np.ndarray] = None
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def aic(self) -> float:
        """Akaike Information Criterion (convenience accessor)."""
        return self.information_criteria.get("AIC", float('inf'))

    @property
    def bic(self) -> float:
        """Bayesian Information Criterion (convenience accessor)."""
        return self.information_criteria.get("BIC", float('inf'))

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"{self.test_name}: stat={self.statistic:.4f}, "
            f"p={self.p_value:.4f}, "
            f"{'stationary' if self.is_stationary else 'non-stationary'} "
            f"at α={self.alpha}"
        ]
        if self.critical_values:
            crits = ", ".join(f"{k}={v:.4f}" for k, v in sorted(self.critical_values.items()))
            lines.append(f"Critical values: {crits}")
        if self.information_criteria:
            ics = ", ".join(f"{k}={v:.2f}" for k, v in self.information_criteria.items())
            lines.append(f"IC: {ics}")
        return "\n".join(lines)


def adf_test(
    series: np.ndarray,
    regression: str = "c",
    max_lags: Optional[int] = None,
    maxlag: Optional[int] = None,
    alpha: float = 0.05,
) -> StationarityResult:
    """Augmented Dickey-Fuller test for unit roots.

    H0: Series has a unit root (non-stationary).
    H1: Series is stationary.

    This is the standard test for determining whether a price series
    follows a random walk or is mean-reverting. Critical for pairs
    trading and mean-reversion strategies.

    Args:
        series: 1-D time series (e.g., log prices or returns).
        regression: "c" (constant only), "ct" (constant + trend),
                    "ctt" (constant + quadratic trend), "n" (none).
        max_lags: Maximum lags for ADF. If None, uses Schwert criterion.
        alpha: Significance level.

    Returns:
        StationarityResult with ADF statistic, p-value, and critical values.
    """
    # Merge maxlag alias into max_lags
    if maxlag is not None:
        max_lags = maxlag

    series = np.asarray(series, dtype=float).ravel()
    n = len(series)

    if n < 10:
        return StationarityResult(
            test_name="ADF",
            statistic=0.0,
            p_value=1.0,
            n_observations=n,
        )

    try:
        # Use statsmodels for robust ADF implementation
        from statsmodels.tsa.stattools import adfuller

        if max_lags is None:
            # Schwert criterion: lags = int(12 * (n/100)^(1/4))
            max_lags = int(12 * (n / 100) ** 0.25)
            max_lags = max(max_lags, 1)

        result = adfuller(series, maxlag=max_lags, regression=regression, autolag="AIC")
        stat = float(result[0])
        p_value = float(result[1])
        n_lags_used = int(result[2])
        n_obs_used = int(result[3])

        critical_values = {
            "1%": float(result[4]["1%"]),
            "5%": float(result[4]["5%"]),
            "10%": float(result[4]["10%"]),
        }

        is_stationary = p_value < alpha

        return StationarityResult(
            test_name="ADF",
            statistic=stat,
            p_value=p_value,
            critical_values=critical_values,
            is_stationary=is_stationary,
            alpha=alpha,
            n_lags=n_lags_used,
            n_observations=n_obs_used,
            additional={
                "regression": regression,
                "max_lags": max_lags,
                "icbest": float(result[5]) if len(result) > 5 else None,
            },
        )

    except ImportError:
        # Fallback implementation without statsmodels
        return _adf_test_fallback(series, regression, max_lags or 5, alpha)


def _adf_test_fallback(
    series: np.ndarray,
    regression: str = "c",
    nlags: int = 5,
    alpha: float = 0.05,
) -> StationarityResult:
    """Manual ADF implementation using OLS regression."""
    n = len(series)
    y = np.diff(series)
    y_lagged = series[:-1]  # y_{t-1}

    # Build regression matrix
    X_cols = []

    # Constant
    if regression in ("c", "ct", "ctt"):
        X_cols.append(np.ones(len(y)))

    # Trend
    if regression in ("ct", "ctt"):
        X_cols.append(np.arange(1, len(y) + 1, dtype=float))

    # Quadratic trend
    if regression == "ctt":
        X_cols.append(np.arange(1, len(y) + 1, dtype=float) ** 2)

    # Lagged level
    X_cols.append(y_lagged)

    # Lagged differences
    for lag in range(1, min(nlags, len(y)) + 1):
        X_cols.append(np.roll(y, lag))

    X = np.column_stack(X_cols)
    # Remove rows with NaN from lagging
    valid = ~np.isnan(X).any(axis=1)
    y = y[valid]
    X = X[valid]

    if len(y) < 10 or X.shape[0] <= X.shape[1]:
        return StationarityResult(
            test_name="ADF (fallback)",
            statistic=0.0,
            p_value=1.0,
            n_observations=n,
        )

    # OLS regression
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residuals = y - X @ beta
        sigma2 = np.sum(residuals ** 2) / (len(y) - X.shape[1])
        cov = sigma2 * np.linalg.inv(X.T @ X)

        # ADF t-statistic on gamma (last column before lagged diffs)
        # The coefficient is at position: constant + trend terms + lagged level
        gamma_idx = len(X_cols) - nlags - 1
        if 0 <= gamma_idx < len(beta):
            gamma = beta[gamma_idx]
            se_gamma = np.sqrt(cov[gamma_idx, gamma_idx])
            stat = gamma / se_gamma if se_gamma > 0 else 0.0
        else:
            stat = 0.0

        # Approximate p-value using MacKinnon (1994) critical values
        # These are rough approximations
        if regression == "c":
            crit_vals = {"1%": -3.43, "5%": -2.86, "10%": -2.57}
        elif regression == "ct":
            crit_vals = {"1%": -3.96, "5%": -3.41, "10%": -3.12}
        elif regression == "ctt":
            crit_vals = {"1%": -4.38, "5%": -3.86, "10%": -3.58}
        else:
            crit_vals = {"1%": -2.58, "5%": -1.95, "10%": -1.62}

        # Approximate p-value from critical values
        if stat < crit_vals["1%"]:
            p_value = 0.01
        elif stat < crit_vals["5%"]:
            p_value = 0.05
        elif stat < crit_vals["10%"]:
            p_value = 0.10
        else:
            p_value = 0.50

        is_stationary = stat < crit_vals[f"{int(alpha*100)}%"]

        return StationarityResult(
            test_name="ADF (fallback)",
            statistic=float(stat),
            p_value=float(p_value),
            critical_values=crit_vals,
            is_stationary=is_stationary,
            alpha=alpha,
            n_lags=nlags,
            n_observations=len(y),
            additional={"regression": regression, "method": "OLS"},
        )

    except np.linalg.LinAlgError:
        return StationarityResult(
            test_name="ADF (fallback)",
            statistic=0.0,
            p_value=1.0,
            n_observations=n,
        )


def kpss_test(
    series: np.ndarray,
    regression: str = "c",
    nlags: Optional[int] = None,
    alpha: float = 0.05,
) -> StationarityResult:
    """KPSS test for stationarity.

    H0: Series is trend-stationary.
    H1: Series has a unit root (non-stationary).

    Unlike ADF, KPSS tests the NULL of stationarity. Best practice:
    run BOTH ADF and KPSS. If ADF rejects unit root AND KPSS fails 
    to reject stationarity → consistent evidence of stationarity.

    Args:
        series: 1-D time series.
        regression: "c" (level stationarity), "ct" (trend stationarity).
        nlags: Number of lags for long-run variance. If None, uses 
               Schwert criterion.
        alpha: Significance level.

    Returns:
        StationarityResult with KPSS statistic and critical values.
    """
    series = np.asarray(series, dtype=float).ravel()
    n = len(series)

    if n < 10:
        return StationarityResult(
            test_name="KPSS",
            statistic=0.0,
            p_value=1.0,
            n_observations=n,
        )

    try:
        from statsmodels.tsa.stattools import kpss
        if nlags is None:
            nlags = int(12 * (n / 100) ** 0.25)

        result = kpss(series, regression=regression, nlags=max(nlags, 0))
        stat = float(result[0])
        p_value = float(result[1])
        n_lags_used = int(result[2])

        critical_values = {
            "10%": float(result[3]["10%"]),
            "5%": float(result[3]["5%"]),
            "2.5%": float(result[3]["2.5%"]),
            "1%": float(result[3]["1%"]),
        }

        is_stationary = p_value >= alpha  # KPSS: H0 is stationarity

        return StationarityResult(
            test_name="KPSS",
            statistic=stat,
            p_value=p_value,
            critical_values=critical_values,
            is_stationary=is_stationary,
            alpha=alpha,
            n_lags=n_lags_used,
            n_observations=n,
            additional={"regression": regression},
        )

    except ImportError:
        # Fallback KPSS using manual spectral computation
        return _kpss_test_fallback(series, regression, nlags or 5, alpha)


def _kpss_test_fallback(
    series: np.ndarray,
    regression: str = "c",
    nlags: int = 5,
    alpha: float = 0.05,
) -> StationarityResult:
    """Manual KPSS implementation."""
    n = len(series)

    # Detrend if needed
    if regression == "ct":
        t = np.arange(1, n + 1, dtype=float)
        X = np.column_stack([np.ones(n), t])
        beta = np.linalg.lstsq(X, series, rcond=None)[0]
        resid = series - X @ beta
    else:
        resid = series - np.mean(series)

    # Partial sum
    S = np.cumsum(resid)

    # Long-run variance (Newey-West)
    s2 = np.sum(resid ** 2) / n
    for j in range(1, nlags + 1):
        w = 1 - j / (nlags + 1)  # Bartlett kernel
        s2 += 2 * w * np.sum(resid[j:] * resid[:-j]) / n

    # KPSS statistic
    stat = np.sum(S ** 2) / (n ** 2 * s2) if s2 > 0 else 0.0

    # Critical values (Kwiatkowski et al., 1992)
    if regression == "c":
        crit_vals = {"1%": 0.739, "5%": 0.463, "10%": 0.347}
    else:
        crit_vals = {"1%": 0.216, "5%": 0.146, "10%": 0.119}

    # Estimate p-value
    if stat > crit_vals["1%"]:
        p_value = 0.01
    elif stat > crit_vals["5%"]:
        p_value = 0.05
    elif stat > crit_vals["10%"]:
        p_value = 0.10
    else:
        p_value = 0.50

    is_stationary = stat <= crit_vals[f"{int(alpha*100)}%"]

    return StationarityResult(
        test_name="KPSS (fallback)",
        statistic=float(stat),
        p_value=float(p_value),
        critical_values=crit_vals,
        is_stationary=is_stationary,
        alpha=alpha,
        n_lags=nlags,
        n_observations=n,
        additional={"regression": regression, "long_run_variance": s2},
    )


def arima_model(
    series: np.ndarray,
    order: tuple[int, int, int] = (1, 0, 1),
    seasonal_order: tuple[int, int, int, int] = (0, 0, 0, 0),
    alpha: float = 0.05,
) -> StationarityResult:
    """Fit an ARIMA (AutoRegressive Integrated Moving Average) model.

    ARIMA(p, d, q) models the time series as:
    (1 - φ₁B - ... - φₚBᵖ)(1 - B)ᵈ y_t = (1 + θ₁B + ... + θ_qB^q) ε_t

    Args:
        series: 1-D time series.
        order: (p, d, q) — AR order, differencing degree, MA order.
        seasonal_order: (P, D, Q, s) — seasonal components.
        alpha: Significance level.

    Returns:
        StationarityResult with model parameters, AIC/BIC, residuals.
    """
    series = np.asarray(series, dtype=float).ravel()
    n = len(series)

    if n < 20:
        return StationarityResult(
            test_name="ARIMA",
            statistic=0.0,
            p_value=1.0,
            n_observations=n,
        )

    try:
        from statsmodels.tsa.arima.model import ARIMA

        model = ARIMA(series, order=order, seasonal_order=seasonal_order)
        fit = model.fit(method_kwargs={"maxiter": 500})

        params = fit.params
        p, d, q = order
        P, D, Q, s = seasonal_order

        # Information criteria
        aic = float(fit.aic)
        bic = float(fit.bic)
        hqic = float(fit.hqic) if hasattr(fit, 'hqic') else float('inf')

        # Log-likelihood
        log_lik = float(fit.llf)

        # Parameter significance
        try:
            # Compute standard errors and p-values
            se = np.sqrt(np.diag(fit.cov_params()))
            z_scores = params / np.where(se > 1e-10, se, np.inf)
            param_p_values = 2 * scipy_stats.norm.sf(np.abs(z_scores))

            # Test if AR or MA terms are significant
            n_ar_ma = p + P + q + Q
            if n_ar_ma > 0:
                # Check if at least one AR/MA term is significant
                ar_ma_pvals = []
                # AR terms
                for i in range(min(p + P, len(params))):
                    ar_ma_pvals.append(float(param_p_values[i]))
                # MA terms
                ma_start = p + P + (1 if d + D > 0 else 0)  # Approximate
                for i in range(ma_start, min(ma_start + q + Q, len(params))):
                    ar_ma_pvals.append(float(param_p_values[i]))
                min_p = min(ar_ma_pvals) if ar_ma_pvals else 1.0
            else:
                min_p = 1.0
        except Exception:
            min_p = 0.5
            param_p_values = np.full(len(params), 0.5)

        # Compute stat and p_value from model fit
        stat = float(-log_lik)
        p_value = float(min_p)

        return StationarityResult(
            test_name="ARIMA",
            statistic=stat,
            p_value=p_value,
            model_params=params,
            information_criteria={"AIC": aic, "BIC": bic, "HQIC": hqic},
            residuals=fit.resid,
            is_stationary=min_p < alpha,
            alpha=alpha,
            n_lags=p + q + P + Q,
            n_observations=n,
            additional={
                "order": order,
                "seasonal_order": seasonal_order,
                "log_likelihood": log_lik,
                "param_p_values": [float(p) for p in param_p_values],
                "sigma2": float(fit.sigma2) if hasattr(fit, 'sigma2') else float(np.var(fit.resid)),
            },
        )

    except ImportError:
        # Fallback ARIMA using manual differencing and linear regression
        return _arima_fallback(series, order, alpha)


def _arima_fallback(
    series: np.ndarray,
    order: tuple[int, int, int] = (1, 0, 1),
    alpha: float = 0.05,
) -> StationarityResult:
    """Manual ARIMA using Yule-Walker for AR and innovation algorithm for MA."""
    p, d, q = order
    n = len(series)

    # Differencing
    y = series.copy()
    for _ in range(d):
        y = np.diff(y)
    n = len(y)

    if n < max(p, q) + 5:
        return StationarityResult(test_name="ARIMA (fallback)", n_observations=n)

    # Simple ARMA via OLS of AR terms + residuals
    # This is a simplified version — proper MLE would need innovation algorithm

    # Fit AR(p) via Yule-Walker
    from statsmodels.tsa.ar_model import AutoReg
    try:
        mod = AutoReg(y, lags=p, old_names=False)
        res = mod.fit()
        params = res.params
        residuals = res.resid
        sigma2 = float(np.var(residuals))
    except Exception:
        params = np.array([np.mean(y)])
        residuals = y - np.mean(y)
        sigma2 = float(np.var(residuals))

    # AIC approximation
    k = p + q + 1  # number of parameters
    log_lik = -0.5 * n * (np.log(2 * np.pi * sigma2) + 1)
    aic = float(2 * k - 2 * log_lik)
    bic = float(k * np.log(n) - 2 * log_lik)

    return StationarityResult(
        test_name="ARIMA (fallback)",
        statistic=sigma2,
        p_value=1.0,
        model_params=params,
        information_criteria={"AIC": aic, "BIC": bic},
        residuals=residuals,
        n_lags=p + q,
        n_observations=n,
        additional={"order": order, "sigma2": sigma2},
    )


def auto_arima(
    series: np.ndarray,
    max_p: int = 5,
    max_d: int = 2,
    max_q: int = 5,
    criterion: str = "aic",
    seasonal: bool = False,
    max_P: int = 2,
    max_D: int = 1,
    max_Q: int = 2,
    seasonal_period: int = 0,
    max_iter: int = 50,
) -> StationarityResult:
    """Automatic ARIMA order selection via grid search.

    Searches (p, d, q) space up to the given maxima and selects
    the model with the lowest AIC or BIC.

    Args:
        series: Time series data.
        max_p: Maximum AR order.
        max_d: Maximum differencing order.
        max_q: Maximum MA order.
        criterion: "aic" or "bic" for model selection.
        seasonal: Whether to include seasonal terms.
        max_P, max_D, max_Q: Seasonal order maxima.
        seasonal_period: Seasonal period (e.g., 5 for weekly in daily data).
        max_iter: Maximum number of models to try (default 50, prevents timeout).

    Returns:
        StationarityResult of the best model.
    """
    series = np.asarray(series, dtype=float).ravel()

    best_result = None
    best_criterion = float('inf')
    orders_tried = 0

    for d in range(max_d + 1):
        for p in range(max_p + 1):
            for q in range(max_q + 1):
                if p == 0 and q == 0:
                    continue
                if orders_tried >= max_iter:
                    break

                if seasonal:
                    for D in range(max_D + 1):
                        for P in range(max_P + 1):
                            for Q in range(max_Q + 1):
                                orders_tried += 1
                                result = arima_model(
                                    series,
                                    order=(p, d, q),
                                    seasonal_order=(P, D, Q, seasonal_period) if seasonal_period > 0 else (0, 0, 0, 0),
                                )
                                val = result.information_criteria.get(criterion.upper(), float('inf'))
                                if val < best_criterion:
                                    best_criterion = val
                                    best_result = result
                else:
                    orders_tried += 1
                    result = arima_model(series, order=(p, d, q))
                    val = result.information_criteria.get(criterion.upper(), float('inf'))
                    if val < best_criterion:
                        best_criterion = val
                        best_result = result

    if best_result is None:
        return StationarityResult(test_name="Auto-ARIMA", n_observations=len(series))

    best_result.test_name = "Auto-ARIMA"
    best_result.additional["orders_tried"] = orders_tried
    best_result.additional["criterion"] = criterion
    return best_result


def arima_forecast(
    series: np.ndarray,
    order: tuple[int, int, int] = (1, 0, 1),
    forecast_steps: int = 10,
    seasonal_order: tuple[int, int, int, int] = (0, 0, 0, 0),
    alpha: float = 0.05,
) -> StationarityResult:
    """Generate ARIMA forecasts with prediction intervals.

    Args:
        series: Time series data.
        order: (p, d, q) order.
        forecast_steps: Number of periods to forecast.
        seasonal_order: Seasonal order.
        alpha: Significance level for prediction intervals.

    Returns:
        StationarityResult with forecast array and prediction intervals.
    """
    series = np.asarray(series, dtype=float).ravel()
    n = len(series)

    if n < 20:
        return StationarityResult(test_name="ARIMA Forecast", n_observations=n)

    try:
        from statsmodels.tsa.arima.model import ARIMA

        model = ARIMA(series, order=order, seasonal_order=seasonal_order)
        fit = model.fit(method_kwargs={"maxiter": 500})

        forecast_result = fit.get_forecast(steps=forecast_steps)
        forecast_values = forecast_result.predicted_mean
        ci = forecast_result.conf_int(alpha=alpha)

        return StationarityResult(
            test_name="ARIMA Forecast",
            statistic=float(fit.aic),
            p_value=1.0,
            model_params=fit.params,
            information_criteria={"AIC": float(fit.aic), "BIC": float(fit.bic)},
            residuals=fit.resid,
            forecast=forecast_values,
            n_observations=n,
            additional={
                "forecast_steps": forecast_steps,
                "forecast_ci_lower": ci[:, 0].tolist() if ci is not None else None,
                "forecast_ci_upper": ci[:, 1].tolist() if ci is not None else None,
                "order": order,
            },
        )

    except ImportError:
        # Fallback forecast using naive approach
        fit = _arima_fallback(series, order, alpha)
        last_value = series[-1]
        naive_forecast = np.full(forecast_steps, last_value)
        return StationarityResult(
            test_name="ARIMA Forecast (fallback)",
            forecast=naive_forecast,
            n_observations=n,
            additional={"forecast_steps": forecast_steps, "method": "naive"},
        )
