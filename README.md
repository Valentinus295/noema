# 🧠 Noema

> *νόημα (nóēma) — "that which is thought, the object of thought"*
>
> **Multi-Agent Quantitative Forex & Crypto Trading Platform**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://python.org)
[![Rust](https://img.shields.io/badge/Rust-1.80%2B-orange?logo=rust&logoColor=white)](https://rust-lang.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Tests](https://img.shields.io/badge/tests-84%2F84-brightgreen)](./noema/tests)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-blue)](./CHANGELOG.md)
[![Phase](https://img.shields.io/badge/phase-6%20complete-8A2BE2)](./docs/ROADMAP.md)

---

## What is Noema?

Noema (from Greek νόημα, "object of thought") is an institutional-grade, **multi-agent quantitative trading platform** for forex and crypto markets. It combines a deterministic statistical/econometric core with LLM-based narrative interpretation — but the LLM **never controls trade decisions**.

The system processes every tick through a pipeline of specialized agents operating under an **actor-critic pattern with a debate engine**. Each agent votes independently; a conservative tiebreaker resolves disputes without any LLM involvement. Before any order reaches a broker, the Guardian agent runs 16+ kill-switches — drawdown limits, statistical edge checks (SPRT, KS-drift, Bayesian win-rate posterior), margin gates, and circuit breakers.

Noema is not a black-box chatbot that hallucinates trading decisions. It is statistical truth wrapped in agent consensus.

---

## Why Noema?

**The problem:** Most "AI trading bots" are wrappers around LLMs. They tokenize market data, feed it to a language model, and execute whatever the model spits out. This architecture has a fundamental flaw — language models hallucinate. They have no internal model of statistical significance, no concept of p-values, no understanding of cointegration. They are optimised for plausible text, not truth.

**The solution:** Noema inverts this paradigm. Statistics and econometrics produce the ground truth. 44 academic units — PCA, Johansen cointegration, GARCH volatility modelling, Monte Carlo simulation, bootstrap inference, survival analysis — compute quantitative evidence. Agents debate using this evidence. The LLM only narrates the conclusions for human readability. It has zero authority over any trade.

> **Statistical proof → Agent consensus → Guardian veto → Execution.**  
> No step involves an LLM on the critical path.

---

## Architecture

```
                        ┌───────────────┐
                        │   Brokers     │
                        │ (FxPesa, FBS, │
                        │   Custom)     │
                        └───────┬───────┘
                                │ Wine / Native
                                ▼
                        ┌───────────────┐
                        │     MT5       │
                        │ (headless)    │
                        └───────┬───────┘
                                │ RPyC / mt5linux (port 18812)
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                            NOEMA                                  │
│                                                                   │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────┐   │
│  │ Statistics   │    │ Econometrics │    │   Agent Teams      │   │
│  │             │    │              │    │                    │   │
│  │ • PCA       │    │ • ARIMA/GARCH│    │  Actor Agents (14) │   │
│  │ • Bootstrap │    │ • Johansen   │    │  ┌──────────────┐  │   │
│  │ • Monte     │───▶│ • Cointeg.   │───▶│  │ Structure    │  │   │
│  │   Carlo     │    │ • Panel      │    │  │ Momentum     │  │   │
│  │ • GOF Tests │    │ • Causal Inf.│    │  │ SR Zones     │  │   │
│  │ • Survival  │    │ • Volatility │    │  │ PriceAction  │  │   │
│  │ • SPRT      │    │ • Regression │    │  └──────────────┘  │   │
│  └─────────────┘    └──────────────┘    │                    │   │
│                                         │  Critic Agents (4)  │   │
│  ┌──────────────────────────────┐       │  ┌──────────────┐  │   │
│  │       Debate Engine          │       │  │ Devil's      │  │   │
│  │  Conservative Tiebreaker     │◄──────│  │   Advocate   │  │   │
│  │  (deterministic, no LLM)     │       │  │ CIO          │  │   │
│  └──────────────┬───────────────┘       │  │ Reflector    │  │   │
│                 │                       │  │ Thesis       │  │   │
│                 ▼                       │  └──────────────┘  │   │
│  ┌──────────────────────────────┐       └────────────────────┘   │
│  │     Guardian (16+ checks)    │                                │
│  │  • Drawdown freeze           │                                │
│  │  • Bayesian win-rate floor   │    ┌────────────────────┐     │
│  │  • SPRT edge check           │    │    Execution       │     │
│  │  • KS drift (live vs backtest)│   │                    │     │
│  │  • Margin / Spread / Lot     │    │  • Risk sizing     │     │
│  │  • Circuit breakers          │───▶│  • Order routing   │     │
│  │  • News blackout             │    │  • Partial closes  │     │
│  │  • Heartbeat watchdog        │    │  • Trailing stops  │     │
│  └──────────────────────────────┘    └────────────────────┘     │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                        DASHBOARD                                  │
│                                                                   │
│    ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐    │
│    │ P&L     │  │ Agent    │  │ Risk     │  │ TradingView  │    │
│    │ Charts  │  │ Votes    │  │ Monitor  │  │ Charts       │    │
│    │         │  │          │  │          │  │ (OB/FVG/BOS) │    │
│    └─────────┘  └──────────┘  └──────────┘  └──────────────┘    │
│                                                                   │
│    PostgreSQL ── Redis ── ChromaDB ── Prometheus ── Grafana       │
└───────────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 🧠 Multi-Agent Architecture
26 specialized agents operating under an **actor-critic pattern** with a deterministic debate engine. 14 actor agents scan for setups; 4 critic agents (Devil's Advocate, CIO, Reflector, Thesis) challenge every signal. The conservative tiebreaker resolves disputes without LLM involvement. Agent votes are weighted by historical accuracy.

### 📊 Statistical Core
**44 academic units** from economics and statistics mapped directly to Noema modules. PCA factor exposure, Johansen cointegration, GARCH(1,1) volatility modelling, Monte Carlo P(ruin) simulation, stationary bootstrap inference, survival analysis for trade duration, SPRT sequential testing, Benjamini-Hochberg FDR correction — all deterministic Python with typed outputs.

### 🔒 Anti-Hallucination Architecture
**Zero LLM in any trade decision.** The LLM (NVIDIA NIM via minimax-m3) provides narrative interpretation of statistical results — it explains *why* in human language. It cannot place orders, modify stops, or change any numeric score. If the LLM is unreachable, the system trades normally on statistical evidence alone. This is prompt-injection containment by design.

### 🛡️ Guardian — 16+ Kill-Switches
Real-time protection layer that checks every order before it reaches the broker:
- **Statistical:** Bayesian win-rate posterior floor (Beta prior), SPRT edge test, KS drift (live vs. backtest)
- **Financial:** Daily/weekly drawdown freeze, margin level gate, spread gate, max lot size cap
- **Operational:** Heartbeat watchdog, data staleness check, actor/critic team health, news blackout, LLM error circuit breaker, consecutive loss counter, learning-under-drawdown freeze

### 🏦 Broker-Agnostic
FxPesa, FBS, and any MT5 broker. Linux runs MT5 headless through Wine (mt5linux RPyC bridge on port 18812). Windows uses native MetaTrader5 package. Paper trading mode available everywhere. Swapping brokers changes one server name in `.env`.

### 📈 TradingView Charts
Next.js dashboard with real-time candlestick charts plus Smart Money Concepts (SMC) overlays: **order blocks, fair value gaps (FVG), liquidity sweeps, break of structure (BOS), and change of character (CHoCH)**. Live P&L, agent vote transparency, and risk monitor all in one web interface.

### 🧪 Self-Learning System
**4-layer memory architecture** (episodic, semantic, procedural, strategic) feeding 15 learning skills. Genetic strategy evolution via crossover and mutation of successful signal patterns. Post-trade reflection loop updates prior distributions and retrains thresholds. All learning is supervised by the Guardian — learning freezes during drawdowns.

### 🐳 One-Command Setup
Everything automated — Python venv, Rust crates, Node.js dashboard, Docker (PostgreSQL + Redis + Prometheus + Grafana), MT5 headless daemon, credential prompts, environment validation. Works on Pop!_OS 24.04, Ubuntu, Windows, and macOS.

---

## One-Command Install

```bash
curl -fsSL https://raw.githubusercontent.com/Valentinus295/noema/main/noema-setup | bash
```

This single command:
1. Clones the repository
2. Detects your OS and configures Wine/MT5 accordingly
3. Creates a Python virtual environment with all dependencies
4. Prompts for credentials (NIM API key, MT5 login, database URLs)
5. Builds Rust crates (noema-data, noema-backtest, noema-smc)
6. Installs Node.js dashboard dependencies
7. Sets up Docker services (PostgreSQL, Redis, Prometheus, Grafana)
8. Tests MT5 connectivity
9. Opens the dashboard in your browser

---

## Quick Start

After setup completes, one command runs everything:

```bash
noema start
```

MT5 starts headless → dashboard opens in browser → trading begins. That's it.

```bash
noema status   # Live positions, P&L, Guardian health, uptime
noema logs     # Tail real-time logs
noema stop     # Graceful shutdown (trading → dashboard → MT5)
```

**Manual control:**

```bash
noema dashboard       # Start dashboard only (if already running)
python -m noema.main --mode demo --mt5-auto   # Trading without CLI
python -m noema.main --mode analyze           # Read-only analysis
```

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **Statistics & Agents** | Python 3.11+ | Deterministic pipeline: stats, econometrics, agent debate, Guardian |
| **Performance** | Rust | Fast data ingestion (Arrow), backtesting engine, SMC pattern detection |
| **Dashboard** | TypeScript / Next.js | React frontend + TradingView charts + live P&L websocket |
| **Database** | PostgreSQL | Trade journal, config hashes, agent memory |
| **Cache & Pub/Sub** | Redis | Price caching, inter-agent messaging, rate limiting |
| **Vector Store** | ChromaDB | Market structure pattern similarity (v1.0) |
| **LLM** | NVIDIA NIM (minimax-m3) | Narrative interpretation only — zero decision authority |
| **Observability** | Prometheus + Grafana | Metrics, alerting, P&L dashboards |
| **Tracing** | OpenTelemetry + Langfuse | Agent decision traces, LLM token monitoring |
| **Container** | Docker Compose | PostgreSQL, Redis, Prometheus, Grafana |

---

## Governance

Noema operates under a formal governance structure. See [GOVERNANCE.md](./GOVERNANCE.md) for the full charter.

- **Board of Directors** — Valentine Owuor (Chairman & CEO), Atlas 🧠 (CSO, non-voting advisor), plus seats for independent directors in Strategy, Risk, and Technology
- **Executive Team** — C-suite leadership across Strategy, Technology, Risk, Quant, and Operations
- **Review Pipeline** — Idea → Research Report → Architecture Blueprint → Committee Approval → Engineering → QA Gate → Go-Live Authorization

All architecture changes flow through a **5-stage governance gate** before reaching production.

---

## Academic Foundation

Noema is built on Valentine Owuor's **44-unit BSc Economics & Statistics curriculum** at Masinde Muliro University of Science & Technology (MMUST). Every academic concept is mapped to a specific Noema module.

| Academic Domain | Noema Module | Techniques |
|----------------|-------------|------------|
| **Time Series & Econometrics** | `econometrics/time_series.py` | ADF, KPSS, ARIMA, Auto-ARIMA |
| **Cointegration** | `econometrics/cointegration.py` | Engle-Granger, Johansen test |
| **Volatility Modelling** | `econometrics/volatility.py` | GARCH(1,1), EWMA, Parkinson, Yang-Zhang |
| **Regression Analysis** | `econometrics/regression.py` | OLS, robust regression, logistic |
| **Panel Data** | `econometrics/panel.py` | Fixed/random effects, Hausman test |
| **Causal Inference** | `econometrics/causal_inference.py` | Diff-in-diff, IV, Granger causality |
| **Probability & Distributions** | `statistics/distributions.py` | 10 distributions, KS/AD/Chi-sq GOF |
| **Hypothesis Testing** | `statistics/hypothesis.py` | SPRT, permutation tests, FDR correction |
| **Multivariate Analysis** | `statistics/multivariate.py` | PCA, Mahalanobis distance, correlation |
| **Monte Carlo Methods** | `statistics/monte_carlo.py` | Bootstrap CI, VaR/CVaR, P(ruin) |
| **Nonparametric Statistics** | `statistics/nonparametric.py` | Mann-Whitney, Kruskal-Wallis, KS, Wilcoxon |
| **Survival Analysis** | `statistics/survival.py` | Kaplan-Meier, Cox PH, log-rank test |
| **Estimation Theory** | `statistics/estimation.py` | CI construction, standard error estimation |

See [docs/CURRICULUM_MAPPING.md](./docs/CURRICULUM_MAPPING.md) for the complete 44-unit mapping with version roadmap.

---

## Roadmap

### Now — v0.2.0 (Phases 1-6 Complete ✅)
- [x] Statistics module (8 files, ~3,000 lines)
- [x] Econometrics module (6 files, ~3,200 lines)
- [x] 26-agent actor-critic architecture with debate engine
- [x] Guardian with 16+ kill-switches
- [x] Conservative tiebreaker (deterministic, no LLM)
- [x] Typed message system (46 message types, 8 categories)
- [x] Compile-time lot protection
- [x] FxPesa + FBS broker support
- [x] MT5 headless daemon for Linux
- [x] Rust crates: noema-data, noema-backtest, noema-smc
- [x] Next.js dashboard with TradingView charts + SMC overlays
- [x] Docker services (PostgreSQL, Redis, Prometheus, Grafana)
- [x] One-command setup script
- [x] 84 passing tests covering core, agents, broker, analysis, data, backtest

### Next — v1.0
- [ ] Live MT5 paper trading on FxPesa demo (30-day validation)
- [ ] FundamentalBiasAgent v1: Taylor-rule delta, real-yield diff, Mundell-Fleming sign
- [ ] News blackout per high-impact events (NFP, CPI, FOMC)
- [ ] GARCH-driven position sizing (not stop placement)
- [ ] Full 44-unit curriculum wired into the pipeline
- [ ] Portfolio layer: PCA factor exposure gate, currency-strength rank
- [ ] Statistical go-live gates: bootstrap Sharpe CI, P(ruin) < 0.05, KS-drift pass

### Later — v2.0
- [ ] LangGraph orchestration layer (currently deferred — adds complexity without proven edge)
- [ ] NautilusTrader integration for multi-venue execution
- [ ] Walk-forward MLE parameter optimisation
- [ ] Live genetic strategy evolution (caretaker-supervised)
- [ ] Multi-broker spread routing (FBS + FxPesa, route by best spread)
- [ ] Crypto market integration
- [ ] External MCP tool server for programmatic consumption

---

## Modules (Deployed)

The following modules are operational and verified as of v0.2.0 (2026-06-24):

| Module | Files | Lines | Key Techniques |
|--------|-------|-------|---------------|
| **Statistics** | 8 | ~3,000 | Distributions, Hypothesis, Nonparametric, Multivariate, Monte Carlo, Estimation, Survival, Decorators |
| **Econometrics** | 6 | ~3,200 | Time Series, Cointegration, Volatility, Regression, Panel, Causal Inference |
| **Agents** | 20 | ~7,500 | Actor-critic, debate engine, conservative tiebreaker, 26 agents |
| **Guardian** | 1 | ~700 | 16+ kill-switches, drawdown freeze, statistical edge checks |
| **Core** | 4 | ~3,000 | Typed messages, types, configuration, Rust bridge |
| **Broker** | 6 | ~4,500 | MT5 Linux/Wine, FBS, paper trading, lot protection |
| **Dashboard** | — | — | Next.js, TradingView charts, SMC overlays, live P&L |
| **Rust Crates** | 3 | ~2,000 | Data ingestion (Arrow), backtesting engine, SMC pattern detection |

---

## License

MIT License. See [LICENSE](./LICENSE) for details.

---

## Disclaimer

**This software is for educational and research purposes only.** It is not financial advice. Trading forex, cryptocurrencies, and other financial instruments carries substantial risk of loss. Past performance does not guarantee future results. Trade at your own risk. Never trade with money you cannot afford to lose.

---

*Built with discipline. Governed by evidence. Defended by statistics.*
