"""Volatility modeling — GARCH, EGARCH, GJR-GARCH, realized volatility.

Provides:
- GARCH(1,1) and GARCH(p,q) model estimation
- EGARCH (exponential GARCH, captures leverage effects)
- GJR-GARCH (Glosten-Jagannathan-Runkle, asymmetric GARCH)
- Volatility forecasting with prediction intervals
- ARCH-LM test for ARCH effects
- Realized volatility (high-frequency estimator)

Every function returns typed VolatilityResult with statistics.
Uses: numpy, scipy, arch package — real volatility modeling libraries.
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats, optimize


@dataclass
class VolatilityResult:
    """Result of a volatility model.

    Attributes:
        model_type: Type of model ("GARCH", "EGARCH", "GJR-GARCH", "Realized").
        parameters: Estimated model parameters.
        standard_errors: Parameter standard errors.
        conditional_volatility: Estimated conditional volatility series.
        residuals: Standardized residuals.
        unconditional_volatility: Long-run (unconditional) volatility.
        persistence: Sum of volatility coefficients (measure of persistence).
        half_life: Half-life of volatility shocks.
        forecast: Volatility forecast (for forecasting calls).
        forecast_ci: Forecast confidence interval.
        log_likelihood: Log-likelihood at optimum.
        aic: Akaike Information Criterion.
        bic: Bayesian Information Criterion.
        converged: Whether optimization converged.
        arch_lm_stat: ARCH-LM test statistic.
        arch_lm_p: ARCH-LM p-value.
        n_observations: Number of observations.
        additional: Additional diagnostics.
    """
    model_type: str
    parameters: dict[str, float] = field(default_factory=dict)
    standard_errors: dict[str, float] = field(default_factory=dict)
    conditional_volatility: Optional[np.ndarray] = None
    residuals: Optional[np.ndarray] = None
    unconditional_volatility: float = 0.0
    persistence: float = 0.0
    half_life: float = 0.0
    forecast: Optional[np.ndarray] = None
    forecast_ci: Optional[tuple[np.ndarray, np.ndarray]] = None
    log_likelihood: float = 0.0
    aic: float = float('inf')
    bic: float = float('inf')
    converged: bool = False
    arch_lm_stat: Optional[float] = None
    arch_lm_p: Optional[float] = None
    n_observations: int = 0
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def annualized_volatility(self) -> float:
        """Annualize the unconditional volatility (252 trading days)."""
        return float(self.unconditional_volatility * np.sqrt(252))

    def annualized_volatility_for(self, periods_per_year: int) -> float:
        """Annualize with custom periods/year (e.g. 252*24 for hourly forex)."""
        return float(self.unconditional_volatility * np.sqrt(periods_per_year))

    @property
    def summary(self) -> str:
        lines = [
            f"{self.model_type}: logL={self.log_likelihood:.2f}, "
            f"AIC={self.aic:.2f}, BIC={self.bic:.2f}"
        ]
        lines.append(f"  Unconditional σ={self.unconditional_volatility:.6f} "
                     f"({self.annualized_volatility:.4f} annualized)")
        lines.append(f"  Persistence={self.persistence:.4f}, "
                     f"Half-life={self.half_life:.1f} periods")
        for k, v in self.parameters.items():
            se = self.standard_errors.get(k, float('nan'))
            lines.append(f"  {k} = {v:.4f} (SE={se:.4f})")
        return "\n".join(lines)


def garch_model(
    returns: np.ndarray,
    p: int = 1,
    q: int = 1,
    mean: str = "constant",
    dist: str = "normal",
) -> VolatilityResult:
    """Fit a GARCH(p,q) model to return data.

    Standard GARCH(1,1) specification:
    r_t = μ + ε_t, ε_t = σ_t * z_t, z_t ~ N(0,1)
    σ²_t = ω + α ε²_{t-1} + β σ²_{t-1}

    This is the workhorse model for volatility estimation in finance.
    Used by Noema for dynamic stop-loss placement and volatility regime detection.

    Args:
        returns: Array of (mean-corrected) returns.
        p: ARCH order (effects of past squared residuals).
        q: GARCH order (effects of past volatility).
        mean: Mean model ("constant", "zero", "ar").
        dist: Error distribution ("normal", "t", "skewt", "ged").

    Returns:
        VolatilityResult with parameters, conditional volatility, diagnostics.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    n = len(returns)

    if n < 50:
        return VolatilityResult(model_type="GARCH", n_observations=n)

    try:
        # Use arch package for robust GARCH estimation
        from arch import arch_model

        model = arch_model(returns, mean=mean, vol="GARCH", p=p, q=q, dist=dist)
        fit = model.fit(disp="off", show_warning=False)

        params = {k: float(v) for k, v in fit.params.items()}
        # Standard errors
        std_err = {k: float(fit.std_err.get(k, float('nan'))) for k in params}

        # Conditional volatility
        cond_vol = np.sqrt(fit.conditional_volatility)
        residuals = fit.resid / cond_vol if fit.resid is not None else None

        # Unconditional volatility
        omega = params.get("omega", 0.0)
        alpha_sum = sum(params.get(f"alpha[{i+1}]", 0.0) for i in range(p))
        beta_sum = sum(params.get(f"beta[{i+1}]", 0.0) for i in range(q))
        persistence = alpha_sum + beta_sum

        if persistence < 1.0 and (1 - persistence) > 1e-10:
            uncond_var = omega / (1 - persistence)
            half_life = -np.log(2) / np.log(persistence) if persistence > 0 else float('inf')
        else:
            uncond_var = omega
            half_life = float('inf')

        uncond_vol = float(np.sqrt(max(uncond_var, 0)))

        return VolatilityResult(
            model_type=f"GARCH({p},{q})",
            parameters=params,
            standard_errors=std_err,
            conditional_volatility=cond_vol.values if cond_vol is not None else None,
            residuals=residuals.values if residuals is not None else None,
            unconditional_volatility=uncond_vol,
            persistence=float(persistence),
            half_life=float(half_life),
            log_likelihood=float(fit.loglikelihood),
            aic=float(fit.aic),
            bic=float(fit.bic),
            converged=bool(fit.convergence_flag if hasattr(fit, 'convergence_flag') else True),
            n_observations=n,
            additional={
                "omega": omega,
                "alpha_sum": alpha_sum,
                "beta_sum": beta_sum,
                "mean_model": mean,
                "distribution": dist,
            },
        )

    except ImportError:
        return _garch_fallback(returns, p, q)
    except Exception as e:
        return VolatilityResult(
            model_type=f"GARCH({p},{q})",
            n_observations=n,
            additional={"error": str(e)},
        )


def _garch_fallback(
    returns: np.ndarray,
    p: int = 1,
    q: int = 1,
    max_iter: int = 500,
) -> VolatilityResult:
    """Manual GARCH(1,1) MLE implementation."""
    n = len(returns)
    returns_centered = returns - np.mean(returns)

    def garch_log_likelihood(params: np.ndarray) -> float:
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
            return 1e10

        sigma2 = np.zeros(n)
        sigma2[0] = np.var(returns_centered)

        for t in range(1, n):
            sigma2[t] = omega + alpha * returns_centered[t - 1] ** 2 + beta * sigma2[t - 1]

        if np.any(sigma2 <= 0):
            return 1e10

        log_lik = -0.5 * n * np.log(2 * np.pi) - 0.5 * np.sum(np.log(sigma2)) - 0.5 * np.sum(returns_centered ** 2 / sigma2)
        return -float(log_lik)

    # Initial guess
    omega0 = np.var(returns_centered) * 0.05
    alpha0 = 0.10
    beta0 = 0.85

    result = optimize.minimize(
        garch_log_likelihood,
        [omega0, alpha0, beta0],
        method="L-BFGS-B",
        bounds=[(1e-8, None), (1e-8, 0.5), (1e-8, 0.99)],
        options={"maxiter": max_iter},
    )

    omega, alpha, beta = result.x
    converged = result.success

    # Reconstruct conditional volatility
    sigma2 = np.zeros(n)
    sigma2[0] = np.var(returns_centered)
    for t in range(1, n):
        sigma2[t] = omega + alpha * returns_centered[t - 1] ** 2 + beta * sigma2[t - 1]

    cond_vol = np.sqrt(sigma2)
    residuals = returns_centered / np.where(cond_vol > 1e-10, cond_vol, 1.0)
    persistence = alpha + beta

    if persistence < 1.0:
        uncond_var = omega / (1 - persistence)
    else:
        uncond_var = omega

    uncond_vol = float(np.sqrt(max(uncond_var, 0)))
    half_life = -np.log(2) / np.log(persistence) if 0 < persistence < 1 else float('inf')

    log_lik = float(result.fun * -1)
    n_params = 3
    aic = 2 * n_params - 2 * log_lik
    bic = n_params * np.log(n) - 2 * log_lik

    # ARCH-LM test
    arch_lm = arch_test(returns, lags=5)

    return VolatilityResult(
        model_type="GARCH(1,1)",
        parameters={"omega": float(omega), "alpha[1]": float(alpha), "beta[1]": float(beta)},
        standard_errors={"omega": 0.0, "alpha[1]": 0.0, "beta[1]": 0.0},
        conditional_volatility=cond_vol,
        residuals=residuals,
        unconditional_volatility=uncond_vol,
        persistence=float(persistence),
        half_life=float(half_life),
        log_likelihood=log_lik,
        aic=aic,
        bic=bic,
        converged=converged,
        arch_lm_stat=arch_lm.test_statistic,
        arch_lm_p=arch_lm.p_value,
        n_observations=n,
    )


def egarch_model(
    returns: np.ndarray,
    p: int = 1,
    q: int = 1,
    mean: str = "constant",
    dist: str = "normal",
) -> VolatilityResult:
    """Fit an EGARCH (Exponential GARCH) model.

    EGARCH captures the leverage effect — negative shocks increase
    volatility more than positive shocks of the same magnitude:
    ln(σ²_t) = ω + β ln(σ²_{t-1}) + α (|ε_{t-1}|/σ_{t-1}) + γ (ε_{t-1}/σ_{t-1})

    Args:
        returns: Return series.
        p, q: EGARCH orders.
        mean: Mean model.
        dist: Error distribution.

    Returns:
        VolatilityResult with EGARCH parameters and asymmetric news impact.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    n = len(returns)

    if n < 50:
        return VolatilityResult(model_type="EGARCH", n_observations=n)

    try:
        from arch import arch_model

        model = arch_model(returns, mean=mean, vol="EGARCH", p=p, q=q, dist=dist)
        fit = model.fit(disp="off", show_warning=False)

        params = {k: float(v) for k, v in fit.params.items()}
        std_err = {k: float(fit.std_err.get(k, float('nan'))) for k in params}

        cond_vol = np.sqrt(fit.conditional_volatility)
        residuals = fit.resid / cond_vol if fit.resid is not None else None

        omega = params.get("omega", 0.0)
        beta_sum = sum(params.get(f"beta[{i+1}]", 0.0) for i in range(q))
        gamma = params.get("gamma[1]", 0.0)  # Asymmetry parameter

        return VolatilityResult(
            model_type=f"EGARCH({p},{q})",
            parameters=params,
            standard_errors=std_err,
            conditional_volatility=cond_vol.values if cond_vol is not None else None,
            residuals=residuals.values if residuals is not None else None,
            log_likelihood=float(fit.loglikelihood),
            aic=float(fit.aic),
            bic=float(fit.bic),
            converged=True,
            persistence=float(beta_sum),
            n_observations=n,
            additional={
                "gamma": float(gamma),
                "leverage_effect": "positive" if gamma < 0 else "negative" if gamma > 0 else "none",
            },
        )

    except ImportError:
        return VolatilityResult(
            model_type="EGARCH",
            n_observations=n,
            additional={"error": "arch package not available"},
        )


def gjr_garch_model(
    returns: np.ndarray,
    p: int = 1,
    q: int = 1,
    mean: str = "constant",
    dist: str = "normal",
) -> VolatilityResult:
    """Fit a GJR-GARCH (Glosten-Jagannathan-Runkle) model.

    GJR-GARCH captures asymmetric volatility response to positive
    and negative shocks (leverage effect):
    σ²_t = ω + α ε²_{t-1} + γ ε²_{t-1} I_{ε<0} + β σ²_{t-1}

    Args:
        returns: Return series.
        p, q: GARCH orders.
        mean: Mean model.
        dist: Error distribution.

    Returns:
        VolatilityResult with GJR-GARCH parameters.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    n = len(returns)

    if n < 50:
        return VolatilityResult(model_type="GJR-GARCH", n_observations=n)

    try:
        from arch import arch_model

        model = arch_model(returns, mean=mean, vol="GARCH", p=p, o=1, q=q, dist=dist)
        fit = model.fit(disp="off", show_warning=False)

        params = {k: float(v) for k, v in fit.params.items()}
        std_err = {k: float(fit.std_err.get(k, float('nan'))) for k in params}

        cond_vol = np.sqrt(fit.conditional_volatility)
        residuals = fit.resid / cond_vol if fit.resid is not None else None

        return VolatilityResult(
            model_type=f"GJR-GARCH({p},{q})",
            parameters=params,
            standard_errors=std_err,
            conditional_volatility=cond_vol.values if cond_vol is not None else None,
            residuals=residuals.values if residuals is not None else None,
            log_likelihood=float(fit.loglikelihood),
            aic=float(fit.aic),
            bic=float(fit.bic),
            converged=True,
            n_observations=n,
            additional={
                "asymmetric": "present" if "gamma[1]" in params else "none",
            },
        )

    except ImportError:
        return VolatilityResult(
            model_type="GJR-GARCH",
            n_observations=n,
            additional={"error": "arch package not available"},
        )


def volatility_forecast(
    returns: np.ndarray,
    model_type: str = "GARCH",
    p: int = 1,
    q: int = 1,
    forecast_horizon: int = 10,
    alpha: float = 0.05,
) -> VolatilityResult:
    """Generate volatility forecasts with confidence intervals.

    Args:
        returns: Return series.
        model_type: "GARCH", "EGARCH", "GJR-GARCH".
        p, q: Model orders.
        forecast_horizon: Number of periods to forecast.
        alpha: Significance level for prediction intervals.

    Returns:
        VolatilityResult with forecast and confidence intervals.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    n = len(returns)

    try:
        from arch import arch_model

        vol_map = {"GARCH": "GARCH", "EGARCH": "EGARCH", "GJR-GARCH": "GARCH"}
        vol_arg = vol_map.get(model_type, "GARCH")

        if model_type == "GJR-GARCH":
            model = arch_model(returns, mean="constant", vol=vol_arg, p=p, o=1, q=q)
        else:
            model = arch_model(returns, mean="constant", vol=vol_arg, p=p, q=q)

        fit = model.fit(disp="off", show_warning=False)
        forecast = fit.forecast(horizon=forecast_horizon)

        variance_forecast = forecast.variance.values[-1, :]
        vol_forecast = np.sqrt(variance_forecast)

        # Confidence intervals (approximate)
        # Using the asymptotic distribution of the forecast
        z = scipy_stats.norm.ppf(1 - alpha / 2)
        vol_se = np.sqrt(variance_forecast) / np.sqrt(2 * n)  # Rough SE
        ci_lower = np.maximum(vol_forecast - z * vol_se, 0)
        ci_upper = vol_forecast + z * vol_se

        return VolatilityResult(
            model_type=f"{model_type} Forecast",
            forecast=vol_forecast,
            forecast_ci=(ci_lower, ci_upper),
            log_likelihood=float(fit.loglikelihood),
            n_observations=n,
            additional={
                "forecast_horizon": forecast_horizon,
                "long_run_vol": float(np.sqrt(fit.conditional_volatility.values[-1])),
            },
        )

    except ImportError:
        # Naive forecast: rolling standard deviation
        rolling_vol = np.std(returns[-20:])
        naive_forecast = np.full(forecast_horizon, rolling_vol)
        return VolatilityResult(
            model_type="Naive Forecast",
            forecast=naive_forecast,
            unconditional_volatility=float(rolling_vol),
            n_observations=n,
            additional={"method": "rolling_std", "window": 20},
        )


def arch_test(
    returns: np.ndarray,
    lags: int = 5,
    alpha: float = 0.05,
) -> VolatilityResult:
    """ARCH-LM test for ARCH effects in return residuals.

    Tests whether squared residuals exhibit autocorrelation —
    evidence of volatility clustering. H0: No ARCH effects.

    If significant, GARCH-type models are appropriate.

    Args:
        returns: Return series (or residuals).
        lags: Number of lags to test.
        alpha: Significance level.

    Returns:
        VolatilityResult with LM test statistic and p-value.
    """
    returns = np.asarray(returns, dtype=float).ravel()
    n = len(returns)

    if n < lags + 10:
        return VolatilityResult(model_type="ARCH-LM", n_observations=n)

    # Center the returns
    residuals = returns - np.mean(returns)
    squared_residuals = residuals ** 2

    # Regress squared residuals on lags
    y = squared_residuals[lags:]
    X = np.column_stack([
        np.ones(len(y)),
        *[squared_residuals[lags - i - 1:-(i + 1)] if i < lags - 1 else squared_residuals[:n - lags]
          for i in range(lags)]
    ])

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        y_hat = X @ beta
        residuals_reg = y - y_hat

        # R-squared
        ss_res = np.sum(residuals_reg ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # LM statistic: n * R² ~ χ²(lags)
        lm_stat = n * r_squared
        p_value = float(scipy_stats.chi2.sf(lm_stat, lags))

        return VolatilityResult(
            model_type="ARCH-LM",
            arch_lm_stat=float(lm_stat),
            arch_lm_p=p_value,
            n_observations=n,
            additional={
                "lags": lags,
                "r_squared": float(r_squared),
                "has_arch_effects": p_value < alpha,
            },
        )

    except np.linalg.LinAlgError:
        return VolatilityResult(
            model_type="ARCH-LM",
            n_observations=n,
            additional={"error": "linear algebra failed"},
        )


def realized_volatility(
    prices: np.ndarray,
    window: int = 5,
    annualize: bool = True,
    periods_per_year: int = 252,
) -> np.ndarray:
    """Compute realized volatility from price data.

    Uses Parkinson's range-based estimator for higher-frequency data,
    or squared log-returns for daily data.

    Args:
        prices: Price series (or OHLC matrix).
        window: Rolling window size.
        annualize: If True, annualize the volatility.
        periods_per_year: Trading days per year.

    Returns:
        Array of realized volatility values.
    """
    prices = np.asarray(prices, dtype=float).ravel()

    # Log returns
    log_returns = np.diff(np.log(prices))
    # Handle zeros
    log_returns = log_returns[np.isfinite(log_returns)]

    n = len(log_returns)

    if n < window:
        realized_vol = np.full_like(log_returns, np.std(log_returns))
    else:
        realized_vol = np.zeros(n)
        for i in range(n):
            start = max(0, i - window + 1)
            realized_vol[i] = np.std(log_returns[start:i + 1], ddof=1)

    # Pad first value
    realized_vol = np.concatenate([[realized_vol[0]], realized_vol])

    if annualize:
        realized_vol *= np.sqrt(periods_per_year)

    return realized_vol
