# VMPM Roadmap

Honest scoping per quality review §Major (#11).

## v0.1 — Skeleton + ride a bicycle (this commit)

**Goal**: walking-skeleton repo that lints, type-checks, and runs an event-driven
backtest end-to-end on cached bars with all 7 agents stubbed.

- [x] Repo scaffold, deps, configs, docs, .gitignore
- [x] Security + quality review applied
- [ ] `BrokerProtocol` + `MockBroker` implementation
- [ ] Core types (`Bias`, `Verdict`, `Setup`, `Order`)
- [ ] Settings loader with hash + git SHA stamping
- [ ] Stub agents emitting deterministic verdicts
- [ ] Event-driven backtest engine over polars DataFrames (custom, NOT NautilusTrader in v0.1)
- [ ] Smoke-test: `uv run scripts/run_backtest.py --symbol EURUSD --days 30`

No LLM, no MT5, no live anything in v0.1. The point is the chassis.

## v0.2 — Real indicators + real backtest

- MA-cross + HH/HL trend detector (deterministic Python, no LangGraph)
- Session/Daily/Weekly/Monthly/Yearly highs+lows
- ICT order blocks per pinned definition
- Retest state machine inside StructureAgent
- RSI + candlestick sub-scorers inside ConfluenceAgent
- ATR-based RiskAgent (SL, TP, size)
- Backtest metrics: Sharpe, Sortino, MaxDD, expectancy, profit factor
- **Statistical gates** for go/no-go on v0.3:
  - Bootstrap CI on Sharpe (Politis-Romano)
  - Bootstrap max-DD
  - Monte Carlo P(ruin) from bootstrapped trades
  - Permutation test via stationary bootstrap

## v0.3 — FxPesa MT5 paper + Guardian

- `mt5linux` RPyC bridge, MT5Broker implementation
- GuardianAgent with all kill-switches wired
- Guardian heartbeat + watchdog process
- Reconnect + reconciliation policy
- Telegram control surface (`/status`, `/flatten`, `/halt`)
- structlog event taxonomy
- DuckDB journal with config-hash + git-SHA on every row
- 30-day paper trading on FxPesa demo
- v0.3 exit criteria: 200+ paper trades, Beta posterior P(WR≥0.45) > 0.95, KS-drift OK

## v0.4 — FxPesa live (small size)

- FxPesa CMA confirmation filed (launch gate)
- Live mode dual-confirm
- Initial size: 0.25%/trade, 1.0% daily, 5 symbols
- 30-day live observation, all kill-switches active

## v1.0 — Full curriculum

- **FundamentalBiasAgent v1**: Python computes Taylor-rule delta, 2Y real-yield diff,
  Mundell-Fleming sign, NAIRU, carry gate. LLM narrates only.
- Finnhub primary + TradingEconomics fallback + ForexFactory offline cache
- News blackout per high-impact event
- PortfolioAgent: PCA factor exposure + currency-strength + hierarchical clusters
- GARCH(1,1) regime flag → RiskAgent throttle (not SL)
- Granger DXY→pair causality
- Johansen cointegration overlay (second uncorrelated edge)

## v2.0 — Multi-broker + adaptive

- Add FBSBroker, route by best spread
- MLE-tuned RSI thresholds per pair (walk-forward only)
- LDA bounce-vs-continuation classifier on S/R touches
- LangGraph orchestration **iff** LLM grows tool-use loops; otherwise keep asyncio chain
- NautilusTrader migration **iff** multi-venue or HFT-cadence ever becomes a goal; otherwise skip

## Deferred (no commitment)

- ARIMA forecast cones, ECM reversion timer, VAR cross-pair signals
- 28-pair scanning (BH-FDR is N-agnostic but PortfolioAgent O(N²) caps grow)
- Pairs/basket mean-reversion trading
- HMM regime classifier via EM
- Bayesian Sharpe with credible intervals
- Six Sigma DMAIC governance wrapper
- Flask web dashboard
