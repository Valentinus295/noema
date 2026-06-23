# Noema — Phase 1

## Project Identity
- **Full Name:** Noema
- **Version:** 0.1.0 (Phase 1: Statistical & Econometric Core)
- **Repository:** git@github.com:Valentinus295/noema.git (private)
- **Owner:** Valentine Owuor
- **Language:** Python 3.11+ with Rust extensions (PyO3)
- **Build System:** Hatchling (pyproject.toml), uv package manager

## What This Is
A **multi-agent forex trading system** that replicates institutional trading discipline. Noema uses a 5-layer wave-based parallel orchestrator, deterministic-first analysis (TA-Lib, econometrics, Rust-backed SMC), NVIDIA NIM LLM integration for decision-layer debate, and 14 Guardian kill-switches for safety.

## Owner Background
- **BSc Economics & Statistics** (Masinde Muliro University of Science & Technology — MMUST, graduating December 2026)
- Strong in: Econometrics, Time Series Analysis, Hypothesis Testing, Multivariate Analysis, Probability Theory
- This background is woven into the statistical core (`noema/statistics/`, `noema/econometrics/`)

## Architecture Overview — 5-Layer Wave Model

```
Layer 1 (Data)          Layer 2 (Analysis)          Layer 3 (Decision)    Layer 4 (Exec)   Layer 5 (Learn)
┌─────────────────┐    ┌──────────────────────┐    ┌────────────────┐    ┌──────────┐    ┌───────────┐
│ MacroEconomic    │    │ MarketStructure       │    │ TradeThesis    │    │ RiskMgr  │    │ Learning  │
│ CurrencyStrength │───▶│ InstitutionalFootprint│───▶│ DevilsAdvocate │───▶│ Execution│───▶│ Agent     │
│ SessionIntel     │    │ SupportResistance     │    │ CIOAgent       │    │          │    │           │
│                  │    │ Momentum              │    │                │    │          │    │           │
│  (parallel)      │    │ PriceAction           │    │  (sequential)  │    │ (seq.)   │    │ (bg)      │
└─────────────────┘    └──────────────────────┘    └────────────────┘    └──────────┘    └───────────┘
         │                       │                       │                    │               │
         └───────────────────────┴───────────────────────┴────────────────────┴───────────────┘
                                              │
                                    ┌─────────┴─────────┐
                                    │   GuardianAgent    │ ← 14 kill-switches on EVERY cycle
                                    │   (pre-trade +     │
                                    │    runtime checks) │
                                    └───────────────────┘
```

## Layer 1: Data Agents (parallel, deterministic)

| Agent | File | Purpose |
|-------|------|---------|
| MacroEconomicAgent | agents/macro.py | Economic calendar, fundamental bias |
| CurrencyStrengthAgent | agents/currency.py | Ranks currencies by relative strength |
| SessionIntelligenceAgent | agents/session.py | Trading session awareness, probability scoring |

## Layer 2: Analysis Agents (parallel, deterministic + LLM)

| Agent | File | Purpose |
|-------|------|---------|
| MarketStructureAgent | agents/structure.py | HH/HL/LH/LL, BOS, CHoCH, trend identification |
| InstitutionalFootprintAgent | agents/institutional.py | Order Blocks, FVG, Liquidity Sweeps (Rust-backed) |
| SupportResistanceAgent | agents/sr.py | Session/D/W/M/Y high/low zone mapping |
| MomentumAgent | agents/momentum.py | RSI confirmation across M15/H1/D1 |
| PriceActionAgent | agents/price_action.py | Candlestick pattern detection (8 reversal patterns) |

## Layer 3: Decision Agents (sequential LLM debate)

| Agent | File | Purpose |
|-------|------|---------|
| TradeThesisAgent | agents/thesis.py | Builds comprehensive case for/against trade |
| DevilsAdvocateAgent | agents/devil.py | Critical analysis to destroy bad trades |
| CIOAgent | agents/cio.py | Final decision maker (BUY/SELL/WAIT/REJECT) |

## Layer 4: Execution Agents (sequential, deterministic)

| Agent | File | Purpose |
|-------|------|---------|
| RiskManagerAgent | agents/risk.py | Position sizing, loss limits, portfolio correlation |
| ExecutionAgent | agents/execution.py | Order placement via MT5 (platform-agnostic) |

## Layer 5: Learning Agent (background LLM)

| Agent | File | Purpose |
|-------|------|---------|
| LearningAgent | agents/learning.py | Post-trade pattern learning, knowledge updates |

## Companion Services

| Component | File | Purpose |
|-----------|------|---------|
| GuardianAgent | agents/guardian.py | 14 kill-switches: pre-trade vetos + runtime monitors |
| ReflectorAgent | agents/reflector.py | Self-learning: reviews closed trades, updates priors |
| TradeJournal | database/journal.py | DuckDB append-only trade journal |
| TelegramBot | agents/telegram_bot.py | Telegram control surface + alerts |

## Orchestrator

| Component | File | Purpose |
|-----------|------|---------|
| ModernOrchestrator | core/orchestrator_modern.py | Wave-based parallel execution, layer coordination, broker health |
| Settings | core/settings.py | Pydantic-settings unified config (YAML + env var overrides) |
| NIMClient | core/nim_client.py | NVIDIA NIM LLM client (OpenAI-compatible API) |

## Statistical & Econometric Core

| Module | Path | Contents |
|--------|------|----------|
| Hypothesis Testing | statistics/hypothesis.py | t-tests, Mann-Whitney, Wilcoxon, Kruskal-Wallis, chi-squared, F-test, Shapiro-Wilk, etc. |
| Distributions | statistics/distributions.py | Normal, t, chi-squared, F, lognormal, gamma, beta, Poisson, binomial, multivariate normal, Dirichlet, Wishart |
| Time Series | econometrics/time_series.py | ADF, KPSS, ARMA/ARIMA, SARIMA, GARCH(1,1), EGARCH, ACF/PACF, Ljung-Box, Granger, Johansen, VAR/VECM, HP filter, Hurst, fractional differencing |
| Copulas | econometrics/copulas.py | Gaussian, Student's t, Clayton, Gumbel, Frank (pair-vine, AIC selection) |

## Rust Extensions

| Crate | Path | Purpose |
|-------|------|---------|
| noema-smc | rust/noema-smc/ | SMC computation: Order Blocks, FVG, Liquidity Sweeps, BOS/CHoCH (native speed) |
| noema-data | rust/noema-data/ | PyO3 OHLCV aggregation, stationary bootstrap |
| noema-backtest | rust/noema-backtest/ | Walk-forward engine with slippage/spread modeling |

## Dashboard

| Component | Path | Tech |
|-----------|------|------|
| Frontend | dashboard/src/ | React 18 + TypeScript + Vite |
| Backend | dashboard/server/ | FastAPI + WebSocket |
| Charts | — | TradingView-style SMC candlestick charts |

## Broker Integration

- **Platform-agnostic**: Auto-detects Linux (Wine + mt5linux RPyC), Windows (native MT5), macOS (paper)
- **MT5 headless**: Zero-click xvfb auto-start (`Noema_MT5_HEADLESS=true`)
- **Lot protection**: Compile-time `Noema_MAX_LOT_SIZE` enforced on ALL order paths
- **Broker disconnect alerting**: Telegram notifications on disconnect > 15s
- **Supported brokers**: FX Pesa, FBS (any MT5 broker)

## Key Config (`config/settings.yaml`)

- Risk per trade: 0.25% (conservative default)
- Daily loss limit: 1.0%
- Spread cap: 3.0 pips
- SL method: ATR(14)
- Confluence threshold: 0.70
- RSI: 14-period, oversold ≤30, overbought ≥70
- Pairs: EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD
- Decision timeframe: M15
- Guardian: heartbeat 30s, drawdown EWMA, Beta win-rate gate, SPRT, KS drift

## Guardian Kill-Switches (14 total)

| Category | Switches |
|----------|----------|
| Pre-trade | daily_loss_limit, weekly_loss_limit, news_blackout, max_spread, max_concurrent_positions, lot_size_cap |
| Runtime | drawdown_ewma_throttle, drawdown_ewma_halt, beta_winrate_gate, sprt_edge_monitor, ks_drift_detection, learning_freeze |
| Infrastructure | heartbeat_timeout, broker_data_stale |

## How to Run

```bash
# Setup (one command)
./noema-setup

# Activate environment
source .venv/bin/activate

# Run modes
python -m noema.main --mode demo          # Demo trading (default)
python -m noema.main --mode live          # Live trading (requires MT5)
python -m noema.main --mode analyze EURUSD # Single-pair analysis

# Dashboard
cd dashboard && npm run dev               # Dev mode (localhost:3000)
python dashboard/server/api.py            # API backend (localhost:8000)
```

## Current Status (June 23, 2026)

- ✅ 5-layer wave-based orchestrator
- ✅ 14 Guardian kill-switches wired into pipeline
- ✅ Statistical core: hypothesis tests, distributions, time series, copulas
- ✅ Rust SMC, data, and backtest crates
- ✅ Platform-agnostic broker (Linux/Windows/macOS)
- ✅ MT5 headless daemon
- ✅ React dashboard with FastAPI backend
- ✅ Docker Compose (PostgreSQL + Redis + Grafana)
- ✅ NVIDIA NIM LLM integration
- ✅ CI/CD pipeline (GitHub Actions)
- ✅ Structured logging (structlog)
- ✅ DuckDB trade journal
- ⬜ Backtesting validation (≥200 trades before live)
- ⬜ Windows VPS for live MT5 deployment
- ⬜ Multi-broker routing
- ⬜ Advanced portfolio optimization

## Todo Tracker

- [ ] Run backtest validation on ≥2 years historical data
- [ ] Deploy to Windows VPS for live MT5 trading
- [ ] Achieve ≥200 live trades for Beta-posterior win-rate gate
- [ ] Add multi-symbol portfolio optimization
- [ ] Implement LLM fundamental bias shadow mode
- [ ] Grafana dashboard for production monitoring
- [ ] Telegram trade alerts in production
