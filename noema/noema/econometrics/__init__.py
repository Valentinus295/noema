"""Noema Econometrics Module — Higher-order econometric methods.

Provides rigorous econometric functions for:
- Time series analysis (ADF, KPSS, ARIMA/SARIMAX)
- Cointegration analysis (Engle-Granger, Johansen)
- Volatility modeling (GARCH, EGARCH, GJR-GARCH)
- Regression analysis (OLS, WLS, IV/2SLS)
- Panel data analysis (Fixed/Random effects)
- Causal inference (DiD, RDD, IV)

All functions return typed dataclasses with test statistics and p-values.
Uses: numpy, scipy, statsmodels, arch — real econometric libraries.
No LLM involvement — purely deterministic statistical computation.
"""

from noema.econometrics.time_series import (
    StationarityResult,
    adf_test,
    kpss_test,
    arima_model,
    auto_arima,
    arima_forecast,
)
from noema.econometrics.cointegration import (
    CointegrationResult,
    engle_granger,
    johansen_test,
    vecm_model,
    cointegration_rank,
    spread_analysis,
)
from noema.econometrics.volatility import (
    VolatilityResult,
    garch_model,
    egarch_model,
    gjr_garch_model,
    volatility_forecast,
    arch_test,
    realized_volatility,
)
from noema.econometrics.regression import (
    RegressionResult,
    ols_regression,
    wls_regression,
    iv_regression,
    robust_regression,
    multicollinearity_check,
    residual_diagnostics,
)
from noema.econometrics.panel import (
    PanelResult,
    fixed_effects,
    random_effects,
    hausman_test,
    pooled_ols,
    panel_summary,
)
from noema.econometrics.causal_inference import (
    CausalResult,
    difference_in_differences,
    regression_discontinuity,
    instrumental_variables,
    propensity_score_matching,
    granger_causality,
)

__all__ = [
    # Time Series
    "StationarityResult", "adf_test", "kpss_test",
    "arima_model", "auto_arima", "arima_forecast",
    # Cointegration
    "CointegrationResult", "engle_granger", "johansen_test",
    "vecm_model", "cointegration_rank", "spread_analysis",
    # Volatility
    "VolatilityResult", "garch_model", "egarch_model",
    "gjr_garch_model", "volatility_forecast", "arch_test",
    "realized_volatility",
    # Regression
    "RegressionResult", "ols_regression", "wls_regression",
    "iv_regression", "robust_regression", "multicollinearity_check",
    "residual_diagnostics",
    # Panel
    "PanelResult", "fixed_effects", "random_effects",
    "hausman_test", "pooled_ols", "panel_summary",
    # Causal Inference
    "CausalResult", "difference_in_differences",
    "regression_discontinuity", "instrumental_variables",
    "propensity_score_matching", "granger_causality",
]
