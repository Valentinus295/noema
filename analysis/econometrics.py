"""Econometrics engine — the statistical brain of VMPM.

Leverages your economics and statistics background:
- ARIMA/GARCH for volatility forecasting
- Cointegration analysis for currency pair relationships
- Hypothesis testing for trade signal validation
- Multivariate analysis for currency correlation
- Regime detection (bull/bear/range markets)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


class MarketRegime(Enum):
    """Classified market regime."""
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


@dataclass
class EconometricsResult:
    """Output from econometric analysis."""
    regime: MarketRegime
    volatility_forecast: float          # Predicted next-period vol
    trend_strength: float               # 0-1, strength of current trend
    mean_reversion_score: float         # 0-1, likelihood of mean reversion
    confidence_interval: tuple[float, float]  # CI for next move
    hypothesis_test: dict[str, Any]     # H0/H1/p-value for key hypotheses
    cointegration: dict[str, Any]       # Cointegration test results
    factor_loadings: dict[str, float]   # PCA factor loadings for currencies
    reasoning: str = ""


class EconometricsEngine:
    """Statistical analysis engine using econometric methods.

    Implements:
    - ARIMA(p,d,q) for price forecasting
    - GARCH(1,1) for volatility clustering
    - Engle-Granger cointegration for pair relationships
    - ADF test for stationarity
    - Rolling PCA for currency factor analysis
    - Bootstrap hypothesis testing for signal validation
    """

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self._logger = logger.bind(component="econometrics")

    # ------------------------------------------------------------------
    # Time Series Analysis
    # ------------------------------------------------------------------

    def test_stationarity(self, series: pd.Series) -> dict[str, Any]:
        """Augmented Dickey-Fuller test for stationarity.

        H0: Series has a unit root (non-stationary)
        H1: Series is stationary
        """
        from statsmodels.tsa.stattools import adfuller

        result = adfuller(series.dropna(), autolag="AIC")
        is_stationary = result[1] < 0.05  # p-value < 0.05

        return {
            "test": "ADF",
            "statistic": float(result[0]),
            "p_value": float(result[1]),
            "lags_used": int(result[2]),
            "is_stationary": is_stationary,
            "critical_values": {
                k: float(v) for k, v in result[4].items()
            },
            "interpretation": (
                "Series is stationary (reject H0)"
                if is_stationary
                else "Series has unit root (fail to reject H0)"
            ),
        }

    def fit_arima(
        self, series: pd.Series, max_order: tuple[int, int, int] = (3, 2, 3)
    ) -> dict[str, Any]:
        """Fit ARIMA(p,d,q) model with automatic order selection.

        Uses AIC/BIC to select best order within bounds.
        """
        from statsmodels.tsa.arima.model import ARIMA
        from statsmodels.tsa.stattools import adfuller

        # Determine differencing order d
        d = 0
        temp = series.copy()
        for i in range(max_order[1] + 1):
            adf = adfuller(temp.dropna(), autolag="AIC")
            if adf[1] < 0.05:
                break
            temp = temp.diff().dropna()
            d += 1

        best_aic = float("inf")
        best_order = (0, d, 0)
        best_model = None

        for p in range(max_order[0] + 1):
            for q in range(max_order[2] + 1):
                if p == 0 and q == 0:
                    continue
                try:
                    model = ARIMA(series, order=(p, d, q))
                    fitted = model.fit()
                    if fitted.aic < best_aic:
                        best_aic = fitted.aic
                        best_order = (p, d, q)
                        best_model = fitted
                except Exception:
                    continue

        if best_model is None:
            return {"order": (0, d, 0), "aic": None, "forecast": None}

        # Forecast next period
        forecast = best_model.forecast(steps=1)
        conf_int = best_model.get_forecast(steps=1).conf_int()

        return {
            "order": best_order,
            "aic": float(best_aic),
            "bic": float(best_model.bic),
            "forecast": float(forecast.iloc[0]) if len(forecast) > 0 else None,
            "confidence_interval": (
                float(conf_int.iloc[0, 0]),
                float(conf_int.iloc[0, 1]),
            ) if len(conf_int) > 0 else None,
            "residuals_normal": self._test_residuals_normal(best_model.resid),
        }

    def fit_garch(
        self, returns: pd.Series, order: tuple[int, int] = (1, 1)
    ) -> dict[str, Any]:
        """Fit GARCH(p,q) model for volatility clustering.

        Essential for risk management — predicts next-period volatility.
        """
        try:
            from arch import arch_model

            model = arch_model(
                returns.dropna() * 100,  # Scale for numerical stability
                vol="Garch",
                p=order[0],
                q=order[1],
                dist="normal",
            )
            fitted = model.fit(disp="off")

            forecast = fitted.forecast(horizon=1)
            predicted_var = forecast.variance.values[-1, 0]
            predicted_vol = np.sqrt(predicted_var) / 100  # Scale back

            return {
                "order": order,
                "omega": float(fitted.params.get("omega", 0)),
                "alpha": float(fitted.params.get("alpha[1]", 0)),
                "beta": float(fitted.params.get("beta[1]", 0)),
                "persistence": float(
                    fitted.params.get("alpha[1]", 0) + fitted.params.get("beta[1]", 0)
                ),
                "current_vol": float(fitted.conditional_volatility.iloc[-1]) / 100,
                "forecast_vol": float(predicted_vol),
                "is_persistent": (
                    fitted.params.get("alpha[1]", 0) + fitted.params.get("beta[1]", 0)
                ) > 0.95,
            }
        except ImportError:
            self._logger.warning("arch_not_installed")
            # Fallback: simple EWMA volatility
            vol = returns.ewm(span=20).std().iloc[-1]
            return {
                "order": order,
                "forecast_vol": float(vol),
                "method": "ewma_fallback",
            }

    # ------------------------------------------------------------------
    # Hypothesis Testing
    # ------------------------------------------------------------------

    def validate_signal(
        self,
        prices: pd.Series,
        direction: str = "long",
        lookback: int = 20,
        significance: float = 0.05,
    ) -> dict[str, Any]:
        """Bootstrap hypothesis test for trade signal validity.

        H0: Mean return is zero (no edge)
        H1: Mean return is positive (for long) or negative (for short)
        """
        returns = prices.pct_change().dropna().tail(lookback)

        if len(returns) < 5:
            return {
                "test": "bootstrap",
                "valid": False,
                "reason": "Insufficient data",
            }

        # One-sample t-test
        from scipy import stats

        if direction == "long":
            stat, p_value = stats.ttest_1samp(returns, 0, alternative="greater")
        else:
            stat, p_value = stats.ttest_1samp(returns, 0, alternative="less")

        # Bootstrap confidence interval
        n_bootstrap = 1000
        bootstrap_means = np.array([
            returns.sample(n=len(returns), replace=True).mean()
            for _ in range(n_bootstrap)
        ])
        ci_lower = np.percentile(bootstrap_means, 2.5)
        ci_upper = np.percentile(bootstrap_means, 97.5)

        return {
            "test": "t_test",
            "direction": direction,
            "statistic": float(stat),
            "p_value": float(p_value),
            "significant": p_value < significance,
            "mean_return": float(returns.mean()),
            "std_return": float(returns.std()),
            "sharpe": float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0,
            "bootstrap_ci": (float(ci_lower), float(ci_upper)),
            "lookback": lookback,
            "interpretation": (
                f"Signal {'VALIDATED' if p_value < significance else 'NOT validated'} "
                f"(p={p_value:.4f}, α={significance})"
            ),
        }

    # ------------------------------------------------------------------
    # Cointegration Analysis
    # ------------------------------------------------------------------

    def test_cointegration(
        self, series1: pd.Series, series2: pd.Series
    ) -> dict[str, Any]:
        """Engle-Granger cointegration test for currency pairs.

        Tests if two non-stationary series have a long-run equilibrium.
        Critical for mean-reversion strategies on correlated pairs.
        """
        from statsmodels.tsa.stattools import coint

        score, p_value, crit_values = coint(series1.dropna(), series2.dropna())

        is_cointegrated = p_value < 0.05

        # Calculate hedge ratio
        from numpy.linalg import lstsq

        X = np.column_stack([series2.dropna().values, np.ones(len(series2.dropna()))])
        y = series1.dropna().values[:len(X)]
        hedge_ratio = lstsq(X[:len(y)], y, rcond=None)[0][0]

        # Calculate spread
        spread = series1 - hedge_ratio * series2
        spread_mean = spread.mean()
        spread_std = spread.std()
        current_z_score = (spread.iloc[-1] - spread_mean) / spread_std if spread_std > 0 else 0

        return {
            "test": "engle_granger",
            "statistic": float(score),
            "p_value": float(p_value),
            "is_cointegrated": is_cointegrated,
            "critical_values": {
                "1%": float(crit_values[0]),
                "5%": float(crit_values[1]),
                "10%": float(crit_values[2]),
            },
            "hedge_ratio": float(hedge_ratio),
            "spread_mean": float(spread_mean),
            "spread_std": float(spread_std),
            "current_z_score": float(current_z_score),
            "interpretation": (
                f"Pairs are cointegrated (p={p_value:.4f}). "
                f"Z-score={current_z_score:.2f} — "
                f"{'OVERSOLD' if current_z_score < -2 else 'OVERBOUGHT' if current_z_score > 2 else 'NEUTRAL'}"
            ),
        }

    # ------------------------------------------------------------------
    # Regime Detection
    # ------------------------------------------------------------------

    def detect_regime(
        self, prices: pd.Series, lookback: int = 60
    ) -> dict[str, Any]:
        """Classify current market regime using rolling statistics.

        Uses:
        - Hurst exponent for trend vs mean-reversion
        - Rolling volatility for vol regime
        - ADX-like trend strength
        """
        returns = prices.pct_change().dropna().tail(lookback)

        if len(returns) < 20:
            return {"regime": MarketRegime.UNKNOWN, "confidence": 0.0}

        # Hurst exponent (simplified R/S method)
        hurst = self._compute_hurst(returns)

        # Volatility regime
        vol = returns.std()
        vol_mean = returns.rolling(60).std().mean()
        vol_ratio = vol / vol_mean if vol_mean > 0 else 1.0

        # Trend strength (directional efficiency)
        net_move = abs(prices.iloc[-1] - prices.iloc[-lookback])
        total_move = abs(prices.diff().tail(lookback)).sum()
        efficiency = net_move / total_move if total_move > 0 else 0

        # Classify
        if vol_ratio > 1.5:
            regime = MarketRegime.HIGH_VOLATILITY
        elif vol_ratio < 0.6:
            regime = MarketRegime.LOW_VOLATILITY
        elif hurst > 0.55 and efficiency > 0.3:
            # Trending
            if returns.mean() > 0:
                regime = MarketRegime.TRENDING_BULL
            else:
                regime = MarketRegime.TRENDING_BEAR
        elif hurst < 0.45:
            regime = MarketRegime.MEAN_REVERTING
        else:
            regime = MarketRegime.UNKNOWN

        return {
            "regime": regime,
            "hurst_exponent": float(hurst),
            "volatility_ratio": float(vol_ratio),
            "directional_efficiency": float(efficiency),
            "mean_return": float(returns.mean()),
            "annualized_vol": float(returns.std() * np.sqrt(252)),
            "interpretation": (
                f"Market regime: {regime.value}. "
                f"Hurst={hurst:.3f} (>{'0.55=trending' if hurst > 0.55 else '<0.45=mean-reverting'}). "
                f"Vol ratio={vol_ratio:.2f}x normal."
            ),
        }

    # ------------------------------------------------------------------
    # Multivariate Analysis
    # ------------------------------------------------------------------

    def currency_factor_analysis(
        self, returns_df: pd.DataFrame, n_components: int = 5
    ) -> dict[str, Any]:
        """PCA-based currency factor analysis.

        Decomposes currency returns into principal components
        to identify latent factors driving the market.
        """
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler

        clean = returns_df.dropna()
        if len(clean) < 30:
            return {"error": "Insufficient data for PCA"}

        scaler = StandardScaler()
        scaled = scaler.fit_transform(clean)

        pca = PCA(n_components=min(n_components, len(clean.columns)))
        components = pca.fit_transform(scaled)

        # Factor loadings
        loadings = pd.DataFrame(
            pca.components_.T,
            index=clean.columns,
            columns=[f"PC{i+1}" for i in range(pca.n_components_)],
        )

        # Interpret
        pc1_direction = "risk-on" if loadings.get("PC1") is not None and loadings["PC1"].mean() > 0 else "risk-off"

        return {
            "n_components": pca.n_components_,
            "explained_variance": pca.explained_variance_ratio_.tolist(),
            "cumulative_variance": np.cumsum(pca.explained_variance_ratio_).tolist(),
            "loadings": loadings.to_dict(),
            "interpretation": (
                f"PC1 explains {pca.explained_variance_ratio_[0]*100:.1f}% of variance. "
                f"Direction: {pc1_direction}"
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_hurst(self, series: pd.Series) -> float:
        """Compute Hurst exponent using rescaled range (R/S) method."""
        n = len(series)
        if n < 20:
            return 0.5

        max_k = int(np.floor(n / 2))
        rs_list = []

        for k in range(10, max_k + 1):
            subseries = series.iloc[:k]
            mean = subseries.mean()
            deviations = subseries - mean
            cumulative = deviations.cumsum()
            R = cumulative.max() - cumulative.min()
            S = subseries.std()
            if S > 0:
                rs_list.append((k, R / S))

        if len(rs_list) < 3:
            return 0.5

        log_n = np.log([x[0] for x in rs_list])
        log_rs = np.log([x[1] for x in rs_list])

        # Linear regression: log(R/S) = H * log(n) + c
        slope = np.polyfit(log_n, log_rs, 1)[0]
        return float(np.clip(slope, 0.0, 1.0))

    def _test_residuals_normal(self, residuals: pd.Series) -> dict[str, Any]:
        """Jarque-Bera test for normality of residuals."""
        from scipy import stats

        jb_stat, jb_p = stats.jarque_bera(residuals.dropna())
        return {
            "jarque_bera_stat": float(jb_stat),
            "p_value": float(jb_p),
            "is_normal": jb_p > 0.05,
        }

    def full_analysis(
        self, prices: pd.Series, returns: pd.Series | None = None
    ) -> EconometricsResult:
        """Run complete econometric analysis pipeline."""
        if returns is None:
            returns = prices.pct_change().dropna()

        # Stationarity
        adf = self.test_stationarity(prices)

        # Regime detection
        regime_result = self.detect_regime(prices)

        # Volatility forecast
        garch = self.fit_garch(returns)

        # ARIMA forecast
        arima = self.fit_arima(prices)

        ci = arima.get("confidence_interval", (None, None))
        if ci[0] is not None:
            confidence_interval = (ci[0], ci[1])
        else:
            last_price = float(prices.iloc[-1])
            vol = garch.get("forecast_vol", 0.01)
            confidence_interval = (
                last_price * (1 - 1.96 * vol),
                last_price * (1 + 1.96 * vol),
            )

        return EconometricsResult(
            regime=regime_result.get("regime", MarketRegime.UNKNOWN),
            volatility_forecast=garch.get("forecast_vol", 0.0),
            trend_strength=regime_result.get("directional_efficiency", 0.0),
            mean_reversion_score=max(0, 1 - regime_result.get("hurst_exponent", 0.5)),
            confidence_interval=confidence_interval,
            hypothesis_test={},  # Populated per-trade
            cointegration={},     # Populated for pair analysis
            factor_loadings={},   # Populated for currency analysis
            reasoning=regime_result.get("interpretation", ""),
        )
