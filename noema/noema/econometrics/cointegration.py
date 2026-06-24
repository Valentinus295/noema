"""Cointegration analysis — Engle-Granger, Johansen, VECM.

Provides:
- Engle-Granger two-step cointegration test
- Johansen trace/eigenvalue cointegration tests
- VECM estimation (simplified)
- Cointegration rank determination
- Spread/z-score analysis for pairs trading

Every function returns typed CointegrationResult with statistics and p-values.
Uses: numpy, scipy, statsmodels — real econometric libraries.
No LLM involvement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import stats as scipy_stats
from noema.econometrics.time_series import adf_test


@dataclass
class CointegrationResult:
    """Result of a cointegration test.

    Attributes:
        test_name: Test name ("Engle-Granger", "Johansen").
        is_cointegrated: True if cointegration detected.
        test_statistic: Test statistic.
        p_value: P-value (where available).
        critical_values: Critical values.
        cointegrating_vector: Estimated cointegrating vector(s).
        spread: The spread/error correction term (for pairs).
        half_life: Half-life of mean reversion (for pairs).
        z_score: Current z-score of the spread.
        n_observations: Number of observations.
        rank: Cointegration rank (for Johansen).
        additional: Additional diagnostics.
    """
    test_name: str
    is_cointegrated: bool = False
    test_statistic: float = 0.0
    p_value: float = 1.0
    critical_values: dict[str, float] = field(default_factory=dict)
    cointegrating_vector: Optional[np.ndarray] = None
    spread: Optional[np.ndarray] = None
    half_life: Optional[float] = None
    z_score: Optional[float] = None
    n_observations: int = 0
    rank: int = 0
    additional: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        lines = [
            f"{self.test_name}: "
            f"{'cointegrated' if self.is_cointegrated else 'not cointegrated'}, "
            f"stat={self.test_statistic:.4f}"
        ]
        if self.cointegrating_vector is not None:
            lines.append(f"  Cointegrating vector: {np.round(self.cointegrating_vector, 4).tolist()}")
        if self.half_life is not None:
            lines.append(f"  Half-life: {self.half_life:.1f} periods")
        if self.z_score is not None:
            lines.append(f"  Z-score: {self.z_score:.2f}")
        return "\n".join(lines)


def engle_granger(
    y: np.ndarray,
    x: np.ndarray,
    trend: str = "c",
    alpha: float = 0.05,
) -> CointegrationResult:
    """Engle-Granger two-step cointegration test.

    Tests whether two time series are cointegrated — whether a linear
    combination is stationary. Classic pairs trading foundation.

    Step 1: OLS regression y ~ x + constant
    Step 2: ADF test on residuals

    Args:
        y: Dependent time series (e.g., EURUSD).
        x: Independent time series (e.g., GBPUSD).
        trend: "c" (constant), "ct" (constant + trend), "n" (none).
        alpha: Significance level.

    Returns:
        CointegrationResult with cointegration status, hedge ratio, spread.
    """
    y = np.asarray(y, dtype=float).ravel()
    x = np.asarray(x, dtype=float).ravel()

    if len(y) != len(x):
        raise ValueError(f"Length mismatch: y={len(y)}, x={len(x)}")

    n = len(y)
    if n < 30:
        return CointegrationResult(test_name="Engle-Granger", n_observations=n)

    # Step 1: OLS regression
    if trend == "c":
        X = np.column_stack([np.ones(n), x])
    elif trend == "ct":
        t = np.arange(1, n + 1, dtype=float).reshape(-1, 1)
        X = np.column_stack([np.ones(n), t, x])
    else:  # "n" — no constant
        X = x.reshape(-1, 1)

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residuals = y - X @ beta
    except np.linalg.LinAlgError:
        return CointegrationResult(test_name="Engle-Granger", n_observations=n)

    # Step 2: ADF test on residuals (with no constant)
    adf = adf_test(residuals, regression="n", alpha=alpha)

    # Cointegrating vector
    if trend == "c":
        coint_vec = np.array([beta[-1], -1.0])  # [hedge_ratio, -1] for spread = y - β*x
        spread = y - beta[-1] * x
    elif trend == "ct":
        coint_vec = np.array([beta[-1], -1.0])
        spread = y - beta[-1] * x
    else:
        coint_vec = np.array([beta[0], -1.0])
        spread = y - beta[0] * x

    # Strip constant from spread for half-life computation
    spread_centered = spread - np.mean(spread)

    # Half-life of mean reversion (Ornstein-Uhlenbeck)
    half_life = _compute_half_life(spread_centered)

    # Current z-score
    z_score = (spread[-1] - np.mean(spread)) / np.std(spread) if np.std(spread) > 0 else 0.0

    # Critical values for Engle-Granger (MacKinnon 2010)
    if trend == "c":
        crits = {"1%": -3.90, "5%": -3.34, "10%": -3.04}
    elif trend == "ct":
        crits = {"1%": -4.32, "5%": -3.78, "10%": -3.50}
    else:
        crits = {"1%": -3.51, "5%": -2.89, "10%": -2.58}

    is_cointegrated = adf.is_stationary

    return CointegrationResult(
        test_name="Engle-Granger",
        is_cointegrated=is_cointegrated,
        test_statistic=adf.statistic,
        p_value=adf.p_value,
        critical_values=crits,
        cointegrating_vector=coint_vec,
        spread=spread,
        half_life=half_life,
        z_score=float(z_score),
        n_observations=n,
        rank=1 if is_cointegrated else 0,
        additional={
            "hedge_ratio": float(coint_vec[0]),
            "residual_std": float(np.std(residuals)),
            "r_squared": float(1 - np.var(residuals) / np.var(y) if np.var(y) > 0 else 0),
            "trend": trend,
        },
    )


def johansen_test(
    data: np.ndarray,
    det_order: int = 0,
    k_ar_diff: int = 1,
    alpha: float = 0.05,
) -> CointegrationResult:
    """Johansen cointegration test.

    Tests for multiple cointegrating vectors in a multivariate system.
    More powerful than Engle-Granger for >2 series.

    Args:
        data: (n_obs, n_vars) matrix of time series (columns = variables).
        det_order: -1=no deterministic, 0=constant, 1=linear trend.
        k_ar_diff: Number of lagged differences in VAR.
        alpha: Significance level.

    Returns:
        CointegrationResult with trace/eigenvalue statistics and rank.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    n_obs, n_vars = data.shape
    if n_obs < 30:
        return CointegrationResult(test_name="Johansen", n_observations=n_obs)

    try:
        from statsmodels.tsa.vector_ar.vecm import coint_johansen

        result = coint_johansen(data, det_order, k_ar_diff)

        trace_stat = result.lr1
        trace_crit = result.cvt  # shape (n_vars, 3) for 90%, 95%, 99%

        # Determine rank: first r where H0 cannot be rejected
        # trace_stat[i] tests H0: r <= i vs H1: r = n_vars
        rank = 0
        for i in range(n_vars):
            if trace_stat[i] > trace_crit[i, 1]:  # 5% critical value
                rank = i + 1
            else:
                break

        is_cointegrated = rank > 0

        return CointegrationResult(
            test_name="Johansen",
            is_cointegrated=is_cointegrated,
            test_statistic=float(trace_stat[-1]),
            critical_values={
                "trace_5%": trace_crit[:, 1].tolist(),
                "trace_1%": trace_crit[:, 2].tolist(),
            },
            cointegrating_vector=result.evec[:, :rank] if rank > 0 else None,
            n_observations=n_obs,
            rank=rank,
            additional={
                "trace_statistics": trace_stat.tolist(),
                "max_eigen_statistics": result.lr2.tolist() if hasattr(result, 'lr2') else None,
                "det_order": det_order,
                "k_ar_diff": k_ar_diff,
                "n_vars": n_vars,
            },
        )

    except ImportError:
        return _johansen_fallback(data, det_order, k_ar_diff, alpha)


def _johansen_fallback(
    data: np.ndarray,
    det_order: int = 0,
    k_ar_diff: int = 1,
    alpha: float = 0.05,
) -> CointegrationResult:
    """Simplified Johansen implementation when statsmodels isn't available."""
    n_obs, n_vars = data.shape

    # Johansen test simplified: compute eigenvalues of companion matrix
    # and compare to asymptotic critical values

    # Step 1: First differences and lagged levels
    dy = np.diff(data, axis=0)
    y_lag = data[:-1]

    # Step 2: OLS regressions
    # Regress dy on lags, then y_lag on lags
    # Simplified: use ADF on residuals of each pair
    results = []
    for i in range(n_vars):
        for j in range(n_vars):
            if i < j:
                eg = engle_granger(data[:, j], data[:, i])
                results.append(eg.is_cointegrated)

    n_cointegrated = sum(results)

    # Critical values approximation (Osterwald-Lenum 1992)
    if n_vars == 2:
        trace_crit = {"1%": 15.41, "5%": 12.25, "10%": 10.50}
    elif n_vars == 3:
        trace_crit = {"1%": 29.75, "5%": 24.14, "10%": 21.30}
    else:
        trace_crit = {"1%": 6.65 * n_vars, "5%": 5.50 * n_vars, "10%": 4.90 * n_vars}

    return CointegrationResult(
        test_name="Johansen (fallback)",
        is_cointegrated=n_cointegrated > 0,
        test_statistic=float(n_cointegrated),
        critical_values=trace_crit,
        n_observations=n_obs,
        rank=n_cointegrated,
        additional={"pairwise_eg_tests": n_cointegrated, "total_pairs": len(results)},
    )


def vecm_model(
    data: np.ndarray,
    coint_rank: int = 1,
    k_ar_diff: int = 1,
    det_order: int = 0,
) -> CointegrationResult:
    """Estimate a VECM (Vector Error Correction Model).

    VECM(p) is a restricted VAR with cointegration:
    ΔY_t = Π Y_{t-1} + Γ_1 ΔY_{t-1} + ... + ε_t
    where Π = α β' and β is the cointegrating vector.

    Args:
        data: (n_obs, n_vars) matrix.
        coint_rank: Number of cointegrating relationships.
        k_ar_diff: Number of lagged differences.
        det_order: Deterministic terms.

    Returns:
        CointegrationResult with VECM parameters.
    """
    data = np.asarray(data, dtype=float)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    n_obs, n_vars = data.shape

    try:
        from statsmodels.tsa.vector_ar.vecm import VECM

        model = VECM(data, k_ar_diff=k_ar_diff, coint_rank=coint_rank,
                     deterministic=f"c{'l' if det_order > 0 else 'o'}")
        fit = model.fit()

        # Extract adjustment coefficients (alpha) and cointegrating vectors (beta)
        alpha = fit.alpha
        beta = fit.beta

        return CointegrationResult(
            test_name="VECM",
            is_cointegrated=True,
            cointegrating_vector=beta,
            n_observations=n_obs,
            rank=coint_rank,
            additional={
                "adjustment_coefficients": alpha.tolist() if alpha is not None else None,
                "k_ar_diff": k_ar_diff,
                "aic": float(fit._aic) if hasattr(fit, '_aic') else None,
            },
        )

    except ImportError:
        return CointegrationResult(
            test_name="VECM (unavailable)",
            n_observations=n_obs,
            rank=coint_rank,
            additional={"error": "statsmodels not available"},
        )


def cointegration_rank(
    data: np.ndarray,
    k_ar_diff: int = 1,
    alpha: float = 0.05,
) -> int:
    """Determine cointegration rank via Johansen trace test.

    Convenience wrapper that returns just the rank.

    Args:
        data: (n_obs, n_vars) matrix.
        k_ar_diff: Lag length.
        alpha: Significance level.

    Returns:
        Cointegration rank (0 = no cointegration).
    """
    result = johansen_test(data, k_ar_diff=k_ar_diff, alpha=alpha)
    return result.rank


def spread_analysis(
    y: np.ndarray,
    x: np.ndarray,
    lookback: int = 20,
) -> dict[str, Any]:
    """Analyze the spread between two cointegrated series.

    Computes dynamic z-score, roll statistics, and trading signals
    for mean-reversion pairs trading.

    Args:
        y: First time series.
        x: Second time series.
        lookback: Rolling window for z-score computation.

    Returns:
        Dictionary with spread, z-score, rolling mean/std, signals.
    """
    y = np.asarray(y, dtype=float).ravel()
    x = np.asarray(x, dtype=float).ravel()

    if len(y) != len(x):
        raise ValueError("y and x must have same length")

    # Estimate hedge ratio via OLS
    X = np.column_stack([np.ones(len(y)), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    hedge_ratio = beta[1]
    spread = y - hedge_ratio * x

    # Rolling statistics
    n = len(spread)
    rolling_mean = np.full(n, np.nan)
    rolling_std = np.full(n, np.nan)
    z_score = np.full(n, np.nan)

    for i in range(lookback, n):
        window = spread[max(0, i - lookback):i]
        rolling_mean[i] = float(np.mean(window))
        rolling_std[i] = float(np.std(window, ddof=1))
        if rolling_std[i] > 0:
            z_score[i] = (spread[i] - rolling_mean[i]) / rolling_std[i]

    # Trading signals based on z-score
    signals = np.zeros(n)
    signals[z_score > 2.0] = -1  # Short spread (spread too wide)
    signals[z_score < -2.0] = 1   # Long spread (spread too narrow)
    signals[np.abs(z_score) < 0.5] = 0  # Exit

    return {
        "spread": spread.tolist(),
        "z_score": [float(z) if not np.isnan(z) else None for z in z_score],
        "rolling_mean": [float(m) if not np.isnan(m) else None for m in rolling_mean],
        "rolling_std": [float(s) if not np.isnan(s) else None for s in rolling_std],
        "signals": signals.tolist(),
        "hedge_ratio": float(hedge_ratio),
        "current_z_score": float(z_score[-1]) if not np.isnan(z_score[-1]) else None,
        "spread_volatility": float(np.std(spread)),
        "lookback": lookback,
    }


def _compute_half_life(spread: np.ndarray) -> Optional[float]:
    """Compute half-life of mean reversion using OLS on lagged spread.

    Models spread_t = α + ρ * spread_{t-1} + ε_t.
    Half-life = -ln(2) / ln(ρ).
    """
    n = len(spread)
    if n < 10:
        return None

    y = spread[1:]
    x = spread[:-1]

    # OLS: y = ρ * x + α
    X = np.column_stack([np.ones(len(x)), x])
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        rho = beta[1]
        if rho <= 0 or rho >= 1:
            return float('inf')
        return float(-np.log(2) / np.log(rho))
    except np.linalg.LinAlgError:
        return None
