# Curriculum → VMPM Component Mapping

Every academic concept that survives into the v1 build, with the file it lives in.
Items marked **(v0.1)** ship in the scaffold; **(v0.x)** ship per `ROADMAP.md`.

## STA 244 Time Series + ECO 414/424 Econometrics
- ADF/KPSS stationarity → trend-regime detector → `indicators/regime.py` (v0.2)
- STL seasonal decomp on hourly returns → session-bias module → `indicators/sessions.py` (v0.2)
- OLS pair-return on DXY/yields/commodities → fundamental-beta score → `agents/fundamental.py` (v1.0)
- White/BP heteroscedasticity → volatility regime flag → `agents/risk.py` (v1.0)
- Dummy variables for NFP/CPI/FOMC → news-blackout module → `agents/guardian.py` (v0.3)
- Granger DXY→pair → bias confirmation → `agents/fundamental.py` (v1.0)
- Engle-Granger / Johansen cointegration → second-edge overlay → `agents/cointegration.py` (v1.0)
- GARCH(1,1) → vol regime → RiskAgent size throttle (NOT SL) → `agents/risk.py` (v1.0)

## STA 142 / 241 / 443 Probability + Measure
- Bayes' theorem → fundamental-bias sequential updater → `agents/fundamental.py` (v1.0)
- Conditional probability multi-layer scorer → `agents/confluence.py` (v0.2)
- Kelly-fraction sizing on E[R], σ[R] → `agents/risk.py` (v0.2)
- Joint multi-TF distribution → **deferred**, weighted-vote in v1, joint model P1 — see ARCHITECTURE.md §1

## STA 341 / 342 Estimation + Testing
- BH-FDR within-bar pair scan → `agents/confluence.py` (v0.2)
- SPRT (promoted from P1 per quality review) → `agents/guardian.py` (v0.3)
- Beta posterior win-rate kill-switch (prior Beta(4.5, 5.5)) → `agents/guardian.py` (v0.3)
- Per-pair MLE RSI thresholds → **deferred** to walk-forward-only build (v2.0)
- Neyman-Pearson LR zone-edge filter → `indicators/structure.py` (v0.2)

## STA 442 Multivariate
- PCA factor exposure → `agents/portfolio.py` (v1.0)
- Currency-strength PCA → `agents/portfolio.py` (v1.0)
- Hierarchical correlation clustering (Ward) → `agents/portfolio.py` (v1.0)
- K-means/GMM regime classifier → `indicators/regime.py` (v1.0)
- Mahalanobis overextension (Ledoit-Wolf covariance) → `agents/confluence.py` invalidator (v1.0)

## ECO 102 / 205 / 209 / 305 / 322 Macro
All compute in Python; LLM narrates only (see ARCHITECTURE.md §2).
- Taylor-rule delta scoring → `agents/fundamental.py::taylor_score` (v1.0)
- 2Y real-yield differential → `agents/fundamental.py::real_yield_diff` (v1.0)
- Mundell-Fleming sign flip → `agents/fundamental.py::mf_sign` (v1.0)
- NAIRU + wage check → `agents/fundamental.py::nairu_check` (v1.0)
- Carry-on/off gate (VIX + rate diff) → `agents/fundamental.py::carry_gate` (v1.0)

## ECO 210 / STA 346 / 347 / 444 Ops/QC/Computing/Non-Parametric
- Permutation test via stationary bootstrap → `backtest/significance.py` (v0.2)
- Bootstrap CI on Sharpe + bootstrap max-DD → `backtest/metrics.py` (v0.2)
- Monte Carlo equity sim → P(ruin) → `backtest/montecarlo.py` (v0.2)
- X-bar/R + p-chart on live PnL → `agents/guardian.py` (v0.3)
- KS test live-vs-backtest → `agents/guardian.py` (v0.3)
- Linear programming position sizing → `agents/portfolio.py` (v1.0)
- Cp/Cpk on R-multiple → `agents/guardian.py` (v0.3)
- Wilcoxon paired filter-additivity test → `research/filter_audit.py` (research-only)
