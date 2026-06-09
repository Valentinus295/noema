# VMPM Swarm Research Outputs — full record for review

This file consolidates all 8 swarm research agents' verbatim outputs.
Engineering team uses this as the source-of-truth for which curriculum
concept maps to which VMPM component. Nothing here is code yet —
this is the design brief that security + quality must sign off on.

---

## Agent 1 — Time-Series & Econometrics (STA 244, ECO 414, ECO 424)

### TOP 5 SHIP-NOW (v1 P0 picks)
1. **ADF regime detector** — decides momentum-vs-fade logic per pair per H4 bar.
2. **Granger DXY→pair** — gives the fundamental-bias agent statistical teeth.
3. **GARCH volatility** — replaces ATR for stops and position sizing.
4. **OLS fundamental-beta score + news dummies** — turns macro into a number and blocks NFP/CPI suicide entries.
5. **Johansen cointegration overlay** — adds a second, uncorrelated edge (mean-reversion) on top of the trend stack.

Full P0 mapping:
- ACF/PACF on returns → entry-timing filter (autocorr lag 1-5)
- ADF/KPSS stationarity on H4 closes → trend-regime detector
- Seasonal decomposition (STL) on hourly returns by session → session-bias module
- OLS of pair returns on DXY/yields/commodity returns → fundamental-bias score
- White/BP heteroscedasticity + robust SE → volatility regime flag
- Dummy variables for NFP/CPI/FOMC → news-blackout module
- Granger causality DXY→EURUSD (gold→AUDUSD, oil→CAD) → bias confirmation
- Engle-Granger / Johansen cointegration → pairs/basket mean-reversion overlay
- GARCH(1,1) → dynamic stop/lot sizing

Deferred (P1/P2): ARIMA forecast cone, Holt-Winters, Chow break test, VIF dedup, ECM speed timer, VAR cross-pair, Logit/Probit setup classifier. VECM/SimEq/Panel/Tobit/IV rejected.

---

## Agent 2 — Probability & Measure Theory (STA 142, 241, 443)

### TOP 5 SHIP-NOW (P0)
1. **Conditional expectation gate** — `E[R | full confluence] > τ` is THE trade trigger.
2. **Bayesian bias updater** — running posterior P(bullish | news stream).
3. **Conditional-prob confluence scorer** — quantifies each filter's marginal lift.
4. **Expectation/variance position sizer** — Kelly-fraction on per-setup E[R], σ[R].
5. **Joint/conditional multi-timeframe state** — formalizes D1→H4→H1 stack as one conditional distribution.

Deferred: CLT z-score overextension, LLN sample-size gate, location-scale ATR normalization, sigma-algebra/lookahead bookkeeping, walk-forward convergence checks. MGFs, Fubini, Lebesgue, Radon-Nikodym rejected (not directional spot FX).

---

## Agent 3 — Estimation & Hypothesis Testing (STA 341, 342)

### TOP 5 SHIP-NOW
1. **Neyman-Pearson LR zone-edge filter** — kills dead zones at the gate.
2. **BH-FDR multi-pair correction** — makes 28-pair scanning honest.
3. **Per-pair MLE RSI thresholds** — ends the fixed 30/70 nonsense.
4. **Beta-posterior win-rate kill-switch** — the only acceptable drawdown defense.
5. **UMP one-sided edge-threshold gate** — final pre-trade go/no-go, provably optimal.

Other P0s: MLE on zone-bounce returns per pair; conjugate Beta prior on win-rate.
Deferred (P1): t-test on candlestick patterns, F-test variance shifts, chi-square drift,
power analysis, SPRT online edge monitor, paired t retest-vs-breakout.

---

## Agent 4 — Multivariate (STA 442)

### TOP 5 SHIP-NOW (P0)
1. **PCA factor exposure** — kills correlated double-bets across pairs.
2. **Currency-strength PCA** — picks the right pair, not the first one screened.
3. **K-means/GMM regime classifier** — kill switch for chop.
4. **Mahalanobis overextension invalidator** — drops into VMPM's existing invalidation list.
5. **Hierarchical correlation clustering** — portfolio-level risk cap before any single trade fires.

Deferred (P1+): GMM soft-regime sizing, LDA bounce-vs-continuation classifier, factor analysis. Rejected: multivariate-normality tests on returns, biplots, candlestick clustering.

---

## Agent 5 — Macro / Fundamentals (ECO 102, 205, 209, 305/313, 322)

### TOP 5 SHIP-NOW (P0 rules in FundamentalBiasAgent)
1. **Taylor-rule scoring of every CPI/jobs/GDP print** — data → rate-path delta.
2. **2Y real-yield differential ranking across G10** — the master FX bias signal.
3. **Mundell-Fleming sign-flip on fiscal vs monetary news** — opposite reactions to stimulus vs cuts.
4. **NAIRU + wage-growth check pre-CB-meeting** — front-runs decision by 2 weeks.
5. **Carry-on/off regime gate (VIX + rate differential)** — kills carry longs before risk-off blows the book.

Deferred (P1): BoP/CA, inflation expectations 5Y5Y, CB balance sheet (QT/QE), geopolitical safe-haven. Solow/Ricardian/OCA: P2.

---

## Agent 6 — Ops Research, QC, Stats Computing, Non-Parametrics (ECO 210, STA 346, 347, 444)

### TOP 5 SHIP-NOW (P0, in build order)
1. **Permutation test vs shuffled bars** — gate before strategy reaches demo.
2. **Bootstrap CI on Sharpe + bootstrap max-DD** — sizes the bet honestly.
3. **Monte Carlo equity simulation → P(ruin)** — go/no-go on live capital.
4. **X-bar/R + p-chart on live PnL & win-rate → kill-switch** — runtime guardrail.
5. **KS test: live vs backtest return distributions** — daily drift alarm.

Other P0s: LP position sizing across N concurrent setups; Cp/Cpk on R-multiple; jackknife influence; Wilcoxon filter-additivity test; bootstrap max-DD ceiling.

---

## Agent 7 — Architecture

24 files under `~/vmpm/`. 10 agents (RetestAgent merged into StructureAgent).
Event-driven backtest (not vectorized) for path-dependent fidelity with live.
Single asyncio loop; MT5 calls behind executor (blocking API).
Cadence: per-tick = Guardian + Execution only; per-M15-close = full agent chain;
news loop = independent 5-min cadence writing to a Bias cache.
LLM only on borderline confluence (0.55-0.70) and only when feature flag ON; shadow-mode first.

Open questions flagged:
- News data source brittleness (resolved: Finnhub primary, TradingEconomics fallback)
- Order-block definition (must be pinned in `indicators/structure.py` docstring)
- MT5 on Linux path (resolved: Wine + mt5linux RPyC bridge)
- M15-close latency vs live retest watcher
- MT5 single-connection serialization via lock
- Time zone: UTC internally, Africa/Nairobi only at UI/TTS edges

---

## Agent 8 — Tech Stack (web-verified May 2026)

| # | Concern | Pick | Version |
|---|---------|------|---------|
| 1 | MT5 on Linux | mt5linux (RPyC bridge to Wine MT5) | 1.0.3 |
| 2 | Agent orchestration | LangGraph | ≥0.4 |
| 3 | Indicators | TA-Lib (Python wrapper) | 0.6.x + system libta-lib |
| 4 | Backtest engine | NautilusTrader | ≥1.200 |
| 5 | News calendar | Finnhub (primary) + TradingEconomics (fallback) + ForexFactory XML (offline cache) | — |
| 6 | Data | polars / pyarrow / duckdb (journal); sqlite (live writes) | 1.10 / 17 / 1.1 |
| 7 | Async | asyncio + uvloop | 0.22.1 |
| 8 | Observability | structlog + prometheus-client + Grafana/Loki | 24 / 0.21 |
| 9 | Config | pydantic-settings + python-dotenv | 2.6 / 1.0 |
| 10 | Econ/stats | numpy, scipy, statsmodels, arch, scikit-learn | 2 / 1.14 / 0.14 / 7 / 1.5 |
| 11 | Control surface | python-telegram-bot + Rich TUI | 21 / 13 |
| 12 | Testing | pytest + pytest-asyncio + hypothesis | 8 / 0.24 / 6 |
| 13 | Packaging | uv (Astral) | ≥0.5 |
