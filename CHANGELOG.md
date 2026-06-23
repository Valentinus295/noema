# Changelog

All notable changes to Noema are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-06-23 — Phase 1: Statistical & Econometric Core

### 🏗️ Architecture Restructuring

- **Wave-based parallel orchestrator** (`ModernOrchestrator`) replacing sequential 12-phase pipeline
- **5-layer agent execution model**: Data → Analysis → Decision → Execution → Learning
- **Layer 1 (Data)** — parallel, deterministic: MacroEconomic, CurrencyStrength, SessionIntelligence
- **Layer 2 (Analysis)** — parallel, deterministic + LLM: MarketStructure, InstitutionalFootprint, SupportResistance, Momentum, PriceAction
- **Layer 3 (Decision)** — sequential LLM debate: TradeThesis → DevilsAdvocate → CIOAgent
- **Layer 4 (Execution)** — deterministic: RiskManager, ExecutionAgent
- **Layer 5 (Learning)** — background LLM reflection: LearningAgent
- **Companion services**: ReflectorAgent (self-learning), TradeJournal (DuckDB), TelegramBot

### 🛡️ Guardian Kill-Switch System

- **GuardianAgent** with 14 registered kill-switches
- Pre-trade checks: daily/weekly loss limits, news blackout, heartbeat timeout, spread thresholds
- Runtime monitors: drawdown EWMA control chart, Beta-posterior win-rate gate, SPRT sequential edge monitor
- KS drift detection for live-vs-backtest distribution drift
- Learning freeze on drawdown > configurable threshold
- Broker health monitor with data-stale detection

### 📊 Statistical & Econometric Core

- **Hypothesis testing**: Student's t (one/paired/independent), Welch's t, Mann-Whitney U, Wilcoxon, Kruskal-Wallis, Friedman, chi-squared, F-test, Levene, Shapiro-Wilk, normality tests, proportion z-tests
- **Distributions**: Normal, Student's t, chi-squared, F, lognormal, gamma, beta, exponential, Poisson, binomial, negative binomial, geometric, multivariate normal, Dirichlet, Wishart
- **Time series**: ADF, KPSS stationarity tests, ARMA/ARIMA (BIC-based order selection), SARIMA, GARCH(1,1), EGARCH, ACF/PACF, Ljung-Box, Granger causality, Johansen cointegration, VAR/VECM, HP filter, Hurst exponent, fractional differencing
- **Copulas**: Gaussian, Student's t, Clayton, Gumbel, Frank (pair-vine with AIC selection)

### 🔬 SMC Analysis (Rust-backed)

- **Rust crate `noema-smc`**: Order Blocks, Fair Value Gaps, Liquidity Sweeps, BOS/CHoCH, Premium/Discount zones — all computed at native speed
- **TradingView-style candlestick charts** with SMC overlays (OB, FVG, LS, BOS)
- OB invalidation: close-through detection, minimum displacement ATR filter, configurable lookback

### 🚀 Performance Infrastructure (Rust)

- **`noema-data`**: PyO3-backed OHLCV aggregation with Polars DataFrame output, stationary bootstrap for permutation tests
- **`noema-backtest`**: Walk-forward engine with train/test splits, explicit slippage + spread modeling, session-aware spread multipliers

### 🔧 Broker Resilience

- **Platform-agnostic broker auto-detection**: Linux (Wine + mt5linux RPyC), Windows (native MT5), macOS (paper)
- **MT5 headless daemon**: Zero-click auto-start using xvfb, no window needed
- **Lot protection**: Compile-time `Noema_MAX_LOT_SIZE` enforcement on ALL order paths
- **Broker disconnect alerting**: Telegram notifications on disconnect > 15s and reconnect
- **Reconnection logic**: Automatic retry with exponential backoff
- **`read -s` silent credential input** in `noema-setup`

### 🖥️ Dashboard

- **React/TypeScript** frontend with Vite
- **FastAPI** backend with configurable CORS (`Noema_CORS_ORIGIN`)
- WebSocket real-time updates with auth
- Health check endpoints, metrics, trade journal

### 🔐 Security Hardening

- GitHub PAT purged from `.git/config` (now SSH)
- All credentials in `.env` (chmod 600, gitignored)
- Comprehensive `.gitignore` (secrets, databases, logs, caches)
- CI pipeline with security scanning (bandit, cargo audit)
- Docker resource limits on all services

### 📦 Infrastructure

- **Docker Compose**: Noema app + PostgreSQL + Redis + Grafana + Prometheus
- **Pydantic-settings** unified config system (`noema/core/settings.py`)
- **Structured logging** via structlog with agent binding
- **DuckDB** trade journal with append-only event log
- **NVIDIA NIM** integration via OpenAI-compatible client (Llama 3.3 70B / Llama 3.1 8B)
- **uv** package manager with `uv.lock`

### 🧪 Testing

- Unit tests for statistical core: hypothesis tests, distributions, time series
- Guardian kill-switch tests (all 14 switches)
- Broker lot protection tests
- CI/CD via GitHub Actions

### 🗑️ Removed

- Dead 12-phase state machine (`core/state_machine.py`)
- Unused message bus v1
- Dual-architecture cruft (old 7-agent function-based agents: trend.py, confluence.py, fundamental.py, portfolio.py)
- VMPM migration artifacts: `MASTER_RESTRUCTURING_PLAN.md`, `REPORT_ARCHITECTURE.md`, `REPORT_MODERN_AGENTS.md`, `REPORT_RESEARCH.md`, `REPORT_TECH_STACK.md`, `RESEARCH_SWARM_RESULTS.md`

---

## [0.0.1] — 2026-06-09

### Initial Scaffold

- 17-agent blueprint (pre-restructuring)
- 12-phase sequential trading pipeline
- Basic MT5 broker integration
- YAML-based configuration
- Analysis modules: econometrics, technical, SMC, candlestick patterns

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 0.1.0 | 2026-06-23 | Phase 1: Statistical core, Guardian, Rust, Dashboard, Broker resilience |
| 0.0.1 | 2026-06-09 | Initial scaffold (pre-restructuring) |

---

## Contributors

- **Valentine** — Creator and Lead Developer
