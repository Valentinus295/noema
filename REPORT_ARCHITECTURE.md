# Noema Architecture & Tech Stack Analysis Report

**Date:** 2026-06-17
**Analyst:** Architecture Analysis Agent
**Repository:** noema (v0.1.0)
**Codebase:** ~6,700 lines Python across 40+ source files

---

## Executive Summary

Noema is a well-conceived multi-agent forex trading system with strong domain modeling rooted in ICT-style Smart Money Concepts and institutional-grade econometrics. The architecture shows evidence of thoughtful review iterations (quality review, security review) documented in `docs/ARCHITECTURE.md`. However, there is a **critical disconnect** between the two competing architecture documents, the code contains **two parallel implementations** that don't converge, and there are **zero tests** in a system that manages real money. This report identifies 23 specific findings and provides actionable recommendations organized by severity.

---

## 1. Current Architecture Assessment

### 1.1 The Agent Roster Discrepancy (CRITICAL)

**Finding:** The repository contains **two incompatible architectures** operating simultaneously.

| Document | Agent Count | Design Philosophy |
|----------|-------------|-------------------|
| `CLAUDE.md` (root) | 17 agents | Granular, one-responsibility-per-agent |
| `docs/ARCHITECTURE.md` | 7+2 agents | Consolidated, deterministic sub-scorers merged |

**The 17-agent design** (`CLAUDE.md`, implemented in `agents/`) has:
- `MacroEconomicAgent`, `CurrencyStrengthAgent`, `MarketStructureAgent`, `InstitutionalFootprintAgent`, `SupportResistanceAgent`, `SessionIntelligenceAgent` (analysis)
- `OpportunitySurveillanceAgent`, `MomentumAgent`, `PriceActionAgent` (signal)
- `TradeThesisAgent`, `DevilsAdvocateAgent`, `CIOAgent` (decision)
- `RiskManagerAgent`, `ExecutionAgent`, `TradeManagementAgent` (execution)
- `PerformanceAnalystAgent`, `LearningAgent` (learning)

**The 7-agent design** (`docs/ARCHITECTURE.md`, partially implemented in `agents/trend.py`, `agents/confluence.py`, `agents/fundamental.py`, `agents/portfolio.py`, `agents/guardian.py`, `agents/orchestrator.py`) has:
- `TrendAgent`, `StructureAgent`, `FundamentalBiasAgent`, `ConfluenceAgent`, `PortfolioAgent`, `RiskAgent`, `ExecutionAgent`, `GuardianAgent`, `Orchestrator`

**Impact:** `main.py` imports and orchestrates the 17-agent system. The 7-agent system has a separate `agents/orchestrator.py` with its own `Orchestrator` class that uses `analyze_trend()` and `analyze_structure()` as pure functions. These two systems share the `core/` infrastructure but are otherwise **parallel codebases that don't interact**. A developer opening this repo will be confused about which is canonical.

**Root Cause:** The quality review recommended consolidation (10→7 agents), and `docs/ARCHITECTURE.md` documents the post-consolidation design. But the original 17 agents were never removed from `agents/`, and `main.py` was never updated to use the new orchestrator.

### 1.2 Message Bus Design

**Location:** `core/message_bus.py` (89 lines)

**Assessment:** Adequate for current scale, but has design issues:

- **Positive:** Clean async pub/sub with topic-based routing, wildcard subscriptions (`*`), and structured error handling per handler.
- **Issue 1 — No backpressure:** The `_queue` is an unbounded `asyncio.Queue`. If a handler is slow, messages accumulate silently. For a trading system, a dropped or delayed message could mean a missed exit.
- **Issue 2 — No message persistence:** All messages are fire-and-forget. If the system restarts, the entire event history is lost. This matters for the learning agent and performance tracking.
- **Issue 3 — Unused by main.py:** The orchestrator in `main.py` calls agents sequentially via `await agent.process(context)` and passes context as a dict. The message bus is initialized but never actually used for inter-agent communication. Agents publish/subscribe, but `main.py` doesn't route through the bus.
- **Issue 4 — No ordering guarantees:** Multiple handlers for the same topic run sequentially in the for-loop, but there's no guarantee about ordering across topics.

### 1.3 State Machine

**Location:** `core/state_machine.py` (158 lines)

**Assessment:** Well-designed but misaligned with the actual pipeline execution.

- **Positive:** Clean enum-based states, explicit transition table, proper rejection/reset flow, and audit trail via `_history`.
- **Issue 1 — Not used in main.py:** The `TradingPipeline` is instantiated in `NoemaOrchestrator.__init__()` but `main.py`'s `_analyze_pair()` calls `self.pipeline.advance(report=None)` — passing `None` instead of a `PhaseResult`. The pipeline's `advance()` method expects a `PhaseResult` and would fail on `None` (AttributeError on `result.success`). This means the state machine is effectively dead code in the current orchestrator.
- **Issue 2 — Linear-only transitions:** The transition table allows `RSI_CONFIRMATION → WAITING_FOR_PRICE` (good, for re-waiting), but the actual pipeline in `main.py` runs agents sequentially without checking state. If the state machine were active, a rejection at any phase would halt the pipeline, but `main.py` doesn't check for rejections between phases.
- **Issue 3 — No concurrent pair support:** The state machine is per-pipeline, but the system analyzes 5-7 pairs. Each pair needs its own pipeline state, but only one `TradingPipeline` instance exists.

### 1.4 Data Flow

**Actual flow in `main.py`:**
```
MT5/synthetic data → MarketDataFeed.get_multi_tf() → context dict
  → MacroEconomicAgent.process(context) → context update
  → MarketStructureAgent.process(context) → context update
  → SupportResistanceAgent.process(context) → context update
  → ... (sequential, 17 agents) ...
  → CIOAgent.process(context) → decision
  → RiskManagerAgent.process(context) → lot_size
  → ExecutionAgent.process(context) → order
```

**Design flow in docs/ARCHITECTURE.md:**
```
MT5 bars → TrendAgent → ConfluenceAgent → PortfolioAgent → RiskAgent → ExecutionAgent
                                                       ↓
                                                  GuardianAgent (veto)
```

**Finding:** The actual data flow is a linear sequential pipeline passing a mutable `context` dict. Each agent reads from and writes to this dict. There's no isolation — any agent can read any other agent's output, and mutation order matters. The designed flow with ConfluenceAgent combining verdicts and PortfolioAgent gating is not implemented in `main.py`.

---

## 2. Tech Stack Evaluation

### 2.1 Core Runtime: Python 3.11+ / asyncio / uvloop

**Verdict: ✅ Correct choice.**

- Python 3.11+ gives performance improvements (~25% faster than 3.10) and better error messages.
- asyncio is the right concurrency model for I/O-bound work (broker calls, API fetches, LLM calls).
- uvloop provides ~2-4x faster event loop, worthwhile for a system processing multiple pairs on timer cadences.
- **Note:** uvloop is conditionally installed (`sys_platform != 'win32'`), which is correct since the MT5 bridge runs under Wine on Linux.

### 2.2 Data Layer: polars + pyarrow + duckdb

**Verdict: ⚠️ Partially appropriate — dependencies declared but unused.**

- `polars>=1.10` is declared as a dependency but **never imported anywhere in the codebase**. All data manipulation uses `pandas` (via `pd.DataFrame`) and `numpy`.
- `pyarrow>=17.0` is a polars dependency, also unused directly.
- `duckdb>=1.1` is declared but **never imported**. The database layer uses SQLAlchemy with SQLite (`sqlite+aiosqlite:///noema.db`).
- The `analysis/econometrics.py` and `analysis/technical.py` modules use `pandas` exclusively.
- The `database/` module uses SQLAlchemy ORM with SQLite.

**Assessment:** The intent to use polars and duckdb is documented in `pyproject.toml` but not executed. For the current data volumes (200 bars × 5-7 pairs × 4-6 timeframes), pandas is perfectly adequate. Polars would matter at backtesting scale (millions of bars).

### 2.3 Technical Analysis: TA-Lib

**Verdict: ⚠️ Appropriate but with caveats.**

- `TA-Lib>=0.6.0` requires the C library `libta-lib` to be installed at the system level. This is a significant deployment dependency, especially in a Docker/Wine environment.
- The codebase already has fallback implementations in `analysis/technical.py` (the `_check_talib()` method falls back to pandas-based calculations). This is good defensive coding.
- The custom `indicators/` module (`rsi.py`, `macd.py`, `candlestick.py`) provides pure-Python implementations that work on `Bar` objects rather than DataFrames. This creates **two parallel indicator implementations** — one in `analysis/technical.py` (DataFrame-based, TA-Lib preferred) and one in `indicators/` (sequence-based, pure Python).

**Recommendation:** TA-Lib is fine for production (C speed), but the dual implementation should be consolidated. If TA-Lib installation is problematic, the pure-Python fallbacks are sufficient for the data volumes involved.

### 2.4 Econometrics: scipy + statsmodels + arch + scikit-learn

**Verdict: ✅ Excellent fit for the domain.**

- `statsmodels` for ARIMA, ADF tests, cointegration — correctly used in `analysis/econometrics.py`.
- `arch` for GARCH(1,1) — correctly used with proper fallback to EWMA.
- `scipy` for hypothesis testing (t-tests, Jarque-Bera) — correctly used.
- `scikit-learn` for PCA in currency factor analysis — correctly used.
- The `EconometricsEngine` is the strongest module in the codebase, well-implemented with proper statistical rigor.

**Minor issue:** The ARIMA grid search in `fit_arima()` iterates over all (p,q) combinations up to (3,2,3) = 16 models per call. This is fine for on-demand analysis but would be slow in a backtesting loop.

### 2.5 LLM Integration: openai + LiteLLM proxy

**Verdict: ✅ Well-architected.**

- The `openai` SDK pointing at a LiteLLM proxy (`localhost:4000`) is the correct pattern. LiteLLM provides unified API across providers, rate limiting, and fallbacks.
- The design in `docs/ARCHITECTURE.md` §2 correctly constrains LLM involvement: Python computes the bias score, LLM only narrates. The LLM is never on the critical path.
- **Issue:** LLM integration is documented but not implemented. No agent in `agents/` actually calls the LLM. `FundamentalBiasAgent` (`agents/fundamental.py`) and `agents/fundamental.py` exist but don't contain LLM call code.

### 2.6 MT5 Bridge: mt5linux (RPyC/Wine)

**Verdict: ⚠️ Functional but fragile.**

- `mt5linux` wraps the `MetaTrader5` Python package via RPyC, running the MT5 terminal under Wine on Linux. This is the standard approach for headless MT5 on Linux.
- **Security concerns (documented in ARCHITECTURE.md §12):**
  - RPyC has had RCE vulnerabilities in versions <5.3. The `rpyc>=6.0` pin is correct.
  - `allow_public_attrs=False`, `allow_pickle=False` are documented but not enforced in code (the `MT5Broker` class doesn't configure RPyC server settings — it's a client).
  - Binding to `127.0.0.1` only is documented but depends on the RPyC server configuration, which is external to this codebase.
- **Reliability concern:** RPyC over localhost is generally reliable, but any Wine crash kills the connection. The disconnect policy (§11) is documented but not implemented in `broker/mt5.py` — there's no reconnection logic, no position reconciliation, and no halt-on-disconnect behavior.

### 2.7 Configuration: YAML + pydantic

**Verdict: ⚠️ Dual config systems.**

The codebase has **two independent configuration systems:**

1. **`core/config.py`** — Uses dataclasses + YAML + manual field-by-field override + env var parsing. Loads `config/default.yaml`. Used by `main.py`.
2. **`core/settings.py`** — Uses Pydantic `BaseModel` + YAML. Loads `config/settings.yaml`. Used by `agents/orchestrator.py` and the 7-agent system.

These are different files with different schemas. `config/settings.yaml` exists and is comprehensive (guardian, backtest, confluence, portfolio sections). `config/default.yaml` does not exist (the loader falls back to `NoemaConfig()` defaults). This means:
- `main.py` uses hardcoded defaults, ignoring `settings.yaml`.
- The 7-agent system uses `settings.yaml` but isn't wired into `main.py`.

### 2.8 Build System: hatchling + uv

**Verdict: ✅ Modern and correct.**

- `hatchling` is a solid PEP 517 build backend.
- `uv` for dependency management is the fastest option available.
- The `pyproject.toml` is well-structured with optional dependency groups (`dev`, `v2`).

### 2.9 Observability: structlog + prometheus-client + rich

**Verdict: ✅ Good foundation, partially implemented.**

- `structlog` is used throughout for structured logging with agent/component binding. Well done.
- `prometheus-client` is declared but **never imported or used**. No metrics are exported.
- `rich` is declared but **never imported**. The CLI output in `main.py` uses plain `print()` and `logger.info()`.

---

## 3. Recommended Right Architecture

### 3.1 Monolith vs. Microservices vs. Event-Sourced

**Recommendation: Stay monolithic with event-sourcing-lite.**

| Approach | Fit | Reason |
|----------|-----|--------|
| Microservices | ❌ Poor | Single-developer project, 6,700 lines. Network overhead between agents would add latency with zero benefit. |
| Full Event Sourcing | ⚠️ Overkill | The 12-phase pipeline is stateful but short-lived (one analysis cycle per pair per minute). Full event sourcing with replay is unnecessary. |
| **Monolith + Event Log** | ✅ Best | Keep everything in-process. Add a lightweight event log (append-only file or DuckDB table) for trade decisions, agent outputs, and pipeline state transitions. This gives auditability without architectural complexity. |

### 3.2 Agent Consolidation: 17 → 7

**Recommendation: Yes, consolidate. The ARCHITECTURE.md design is correct.**

The 17-agent system has significant overhead:
- 17 `Agent` instances each with their own state, subscriptions, and lifecycle.
- `main.py` calls them sequentially — there's no parallelism benefit from having separate agents.
- Several agents are thin wrappers that could be pure functions:
  - `MomentumAgent` → just computes RSI. This is a function, not an agent.
  - `PriceActionAgent` → just calls `detect_pattern()`. Function, not agent.
  - `SessionIntelligenceAgent` → checks the clock. Function, not agent.
  - `CurrencyStrengthAgent` → computes rankings. Function, not agent.
  - `TradeThesisAgent` → aggregates other agents' outputs. This IS ConfluenceAgent's job.
  - `DevilsAdvocateAgent` → argues against trade. This is a function inside ConfluenceAgent.
  - `CIOAgent` → final decision. This IS ConfluenceAgent's threshold check.

**Proposed consolidation map:**

| Current Agent(s) | Target | Rationale |
|-------------------|--------|-----------|
| `MacroEconomicAgent` | `FundamentalBiasAgent` | Already exists as `agents/fundamental.py` |
| `MarketStructureAgent` | `TrendAgent` + `StructureAgent` | Trend detection + structural analysis, already in `agents/trend.py` |
| `InstitutionalFootprintAgent` | `StructureAgent` (merge) | Order blocks are structural analysis |
| `SupportResistanceAgent` | `StructureAgent` (merge) | S/R levels are structural analysis |
| `MomentumAgent` | `ConfluenceAgent` (sub-scorer) | RSI is a deterministic input to confluence |
| `PriceActionAgent` | `ConfluenceAgent` (sub-scorer) | Candlestick patterns are deterministic inputs |
| `SessionIntelligenceAgent` | `Orchestrator` (filter) | Session check is a scheduling concern |
| `OpportunitySurveillanceAgent` | `Orchestrator` (scheduling) | Zone monitoring is a scheduling concern |
| `TradeThesisAgent` + `DevilsAdvocateAgent` + `CIOAgent` | `ConfluenceAgent` | All three are confluence scoring + threshold |
| `CurrencyStrengthAgent` | `PortfolioAgent` | Already exists as `agents/portfolio.py` |
| `RiskManagerAgent` | `RiskAgent` | Already exists in the 7-agent design |
| `ExecutionAgent` | `ExecutionAgent` | Keep as-is |
| `TradeManagementAgent` | `Orchestrator` (post-fill) | SL/TP management is orchestration |
| `PerformanceAnalystAgent` + `LearningAgent` | `Journal` module | Not agents — they're data recording, best as a module |

**Result:** 7 agents + 1 orchestrator + 1 journal module. Cleaner, less overhead, same functionality.

### 3.3 Message Bus: Keep or Replace?

**Recommendation: Keep the in-process bus, but make it actually work.**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Current asyncio bus | Zero dependencies, fast, simple | Not used, no persistence | Fix it |
| Redis Streams | Persistence, consumer groups, scaling | External dependency, overkill for single-process | ❌ Not now |
| NATS | Ultra-low latency, clustering | External dependency, overkill | ❌ Not now |
| **asyncio.Queue + DuckDB log** | In-process speed + persistence | Limited to single process | ✅ Best fit |

The in-process bus is the right choice for a single-process trading system. The fix is:
1. Actually wire agents through the bus (currently `main.py` bypasses it).
2. Add a DuckDB-backed event log that records every message for auditability.
3. Add backpressure (bounded queue with `put_nowait` + overflow handling).

### 3.4 State Machine: Keep or Replace?

**Recommendation: Keep, but fix the integration.**

The 12-phase state machine is a good pattern for this domain — it enforces the disciplined trader workflow. But it needs:
1. One instance per pair (not a singleton).
2. Actual integration with `main.py` (currently bypassed).
3. The ability to persist state for crash recovery (if the system restarts mid-pipeline).

---

## 4. Recommended Tech Stack Changes

### 4.1 Dependencies to Add

| Dependency | Purpose | Priority |
|------------|---------|----------|
| `aiohttp` | Economic calendar already imports it but it's not in `pyproject.toml` | P0 — Bug |
| `sqlalchemy[asyncio]` | `database/__init__.py` uses `create_async_engine` but only `sqlalchemy` is implicitly available (not in deps) | P0 — Bug |
| `aiosqlite` | Required by `sqlite+aiosqlite:///` URL | P0 — Bug |
| `cryptography` | For encrypting MT5 credentials at rest | P1 |
| `pytest-cov` | Test coverage reporting | P1 |

### 4.2 Dependencies to Remove or Defer

| Dependency | Status | Recommendation |
|------------|--------|----------------|
| `polars` | Unused | Remove from core deps, move to `v2` extras |
| `pyarrow` | Unused | Remove (polars pulls it in if needed) |
| `duckdb` | Unused | Keep in deps — plan to use for event log and journal |
| `python-telegram-bot` | Unused in code | Keep — Telegram integration is planned |

### 4.3 TA-Lib: Keep or Replace?

**Recommendation: Keep TA-Lib, improve the fallback.**

- TA-Lib's C implementation is 10-100x faster than pure Python for batch indicator calculations. For a system processing 5-7 pairs × 4-6 timeframes every 60 seconds, this matters less than for backtesting.
- **For v1 (live trading):** TA-Lib is fine. The deployment environment (Linux VPS) can install `libta-lib-dev`.
- **For backtesting (v2):** TA-Lib becomes essential. Processing millions of bars with pure Python would be too slow.
- **Action:** Consolidate the dual implementation. The `indicators/` module (pure Python, Bar-sequence-based) and `analysis/technical.py` (DataFrame-based, TA-Lib-preferred) should be merged into one module with a clean interface.

### 4.4 polars vs pandas

**Recommendation: Stay with pandas for v1, migrate to polars for backtesting in v2.**

- Current data volumes (~200 bars × 30 symbol-timeframe combinations per cycle) are trivial for pandas.
- Polars' lazy evaluation and zero-copy design shine with millions of rows (backtesting).
- The migration cost is low since polars has a pandas-compatible API.

### 4.5 duckdb for Journal

**Recommendation: Yes, use DuckDB for the trade journal and event log.**

- DuckDB is already a declared dependency. Use it instead of SQLite for:
  - Trade journal (append-only, analytical queries for performance stats).
  - Event log (pipeline state transitions, agent outputs).
  - Backtest results (columnar storage is ideal for time-series analysis).
- **Why not SQLite:** SQLite is row-oriented and struggles with analytical queries on time-series data. DuckDB is columnar and optimized for exactly this workload.
- **Why not PostgreSQL:** Overkill for a single-process system. DuckDB requires zero infrastructure.

### 4.6 ORM: SQLAlchemy or Raw SQL?

**Recommendation: Keep SQLAlchemy for the ORM layer, add raw DuckDB for analytics.**

- `database/models.py` uses SQLAlchemy ORM for `TradeRecord`, `KnowledgeEntry`, `DailyStats`. This is fine for transactional writes.
- For analytical reads (performance queries, backtest analysis), use DuckDB directly with SQL. ORM overhead is unnecessary for read-heavy analytics.
- The current `KnowledgeBase` in `models/knowledge.py` uses a JSON file. This should migrate to DuckDB.

---

## 5. Tools & Infrastructure Recommendations

### 5.1 Testing Framework

**Current state: ZERO tests exist.**

The `pyproject.toml` declares `pytest>=8.0`, `pytest-asyncio>=0.24`, and `hypothesis>=6.0` in dev dependencies. The `tests/` directory doesn't exist.

**This is the single highest-priority gap.** A trading system without tests is a liability.

**Recommended test pyramid:**

| Layer | Tool | Coverage Target | Priority |
|-------|------|-----------------|----------|
| Unit tests | `pytest` | All agents, indicators, econometrics | P0 |
| Property tests | `hypothesis` | Indicator invariants (RSI ∈ [0,100], etc.) | P0 |
| Integration tests | `pytest` + `PaperBroker` | Full pipeline from data to execution | P1 |
| Contract tests | `pytest` | AgentReport schema, Setup schema, Verdict schema | P1 |
| Backtest validation | Custom | Walk-forward, permutation tests | P2 |

**Critical tests to write first:**
1. `test_rsi_bounds()` — RSI must be in [0, 100] for any input.
2. `test_confluence_neutral_on_no_data()` — ConfluenceAgent must return None when inputs are missing.
3. `test_guardian_blocks_on_daily_loss()` — GuardianAgent must reject when daily loss limit hit.
4. `test_risk_position_sizing()` — Lot size calculation must match expected formula.
5. `test_state_machine_transitions()` — Only valid transitions allowed.
6. `test_paper_broker_round_trip()` — Open → modify → close must update balance correctly.

### 5.2 CI/CD Pipeline

**Current state: No CI/CD configuration exists.**

**Recommended pipeline (GitHub Actions):**

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --extra dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy noema/ --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --extra dev
      - run: uv run pytest tests/ -v --cov=noema --cov-report=xml

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install detect-secrets pip-audit
      - run: detect-secrets scan --all-files
      - run: pip-audit
```

### 5.3 Monitoring & Observability

**Current state:** `structlog` is well-integrated. `prometheus-client` is unused.

**Recommendations:**

1. **Prometheus metrics (implement):**
   - `noema_trades_total{symbol, direction, outcome}` — trade counter
   - `noema_pnl_dollars{symbol}` — running P&L
   - `noema_agent_latency_seconds{agent}` — per-agent processing time
   - `noema_pipeline_state{state}` — current pipeline state per pair
   - `noema_guardian_heartbeat_age_seconds` — time since last guardian heartbeat

2. **Structured logging (already done):**
   - The logging event taxonomy in `docs/ARCHITECTURE.md` §8 is well-defined.
   - **Action:** Implement the canonical event list. Currently, agents log ad-hoc events.

3. **Dashboard:**
   - Grafana + Prometheus for metrics visualization.
   - A simple web dashboard (FastAPI + HTMX) for trade journal review.

### 5.4 Deployment: Wine + RPyC Sustainability

**Verdict: Functional but needs hardening.**

| Concern | Current State | Recommendation |
|---------|---------------|----------------|
| Wine crashes | No recovery logic | Implement reconnection with exponential backoff |
| MT5 terminal hangs | No watchdog | Implement `scripts/watchdog.py` (documented in ARCHITECTURE.md §10 but not written) |
| RPyC security | Documented but not enforced | Pin RPyC server config in deployment scripts |
| Position reconciliation | Not implemented | On reconnect, compare MT5 positions with internal state |
| Duplicate orders | No idempotency | Use magic number + comment hash for deduplication |

**Alternative to consider for v2:** `mt5linux` is one option, but running MT5 under Wine on a Linux VPS is inherently fragile. Consider:
- A dedicated Windows VPS for MT5 (more reliable, native MetaTrader5 package).
- A Docker container with Wine pre-configured (reproducible deployment).
- Cloud-based MT5 gateway services (if available for your broker).

---

## 6. Restructuring Recommendations

### 6.1 Package Structure

**Current structure:**
```
noema/
├── agents/          # 17 agent files + __init__.py
├── analysis/        # 5 analysis modules
├── broker/          # base, mt5, paper, fbs
├── config/          # settings.yaml, symbols.yaml
├── core/            # agent, config, message_bus, settings, state_machine, types
├── data/            # feed, calendar
├── database/        # models, __init__.py
├── docs/            # ARCHITECTURE, CURRICULUM_MAPPING, ROADMAP, SECURITY
├── indicators/      # rsi, macd, candlestick
├── models/          # knowledge, position, trade
├── research/        # REVIEWS.md
├── main.py
└── pyproject.toml
```

**Issues:**
1. `core/config.py` and `core/settings.py` are two different config systems.
2. `analysis/` and `indicators/` overlap (technical analysis in both).
3. `models/` has `knowledge.py`, `position.py`, `trade.py` — but `database/models.py` also has `TradeRecord`. Two trade model systems.
4. `agents/__init__.py` exports all 17 agents. After consolidation, this needs cleanup.
5. No `noema/` package directory — files are at the repo root, which means `from noema.core.agent import Agent` only works if the repo root is in `sys.path`.

**Recommended structure (post-consolidation):**
```
noema/
├── __init__.py
├── __main__.py              # CLI entry point (replaces main.py)
├── agents/
│   ├── __init__.py
│   ├── base.py              # Agent base class (from core/agent.py)
│   ├── trend.py             # TrendAgent (MA-cross + HH/HL)
│   ├── structure.py         # StructureAgent (S/R + order blocks + FVG)
│   ├── fundamental.py       # FundamentalBiasAgent (deterministic + LLM narrator)
│   ├── confluence.py        # ConfluenceAgent (scoring + RSI/candle sub-scorers)
│   ├── portfolio.py         # PortfolioAgent (PCA + currency strength + clustering)
│   ├── risk.py              # RiskAgent (SL/TP/sizing)
│   ├── execution.py         # ExecutionAgent (order send/modify/close)
│   └── guardian.py          # GuardianAgent (veto + kill-switches)
├── orchestration/
│   ├── __init__.py
│   ├── orchestrator.py      # Main orchestration loop
│   ├── pipeline.py          # State machine (from core/state_machine.py)
│   └── message_bus.py       # Async pub/sub (from core/message_bus.py)
├── analysis/
│   ├── __init__.py
│   ├── indicators.py        # All indicators (merged from indicators/ + analysis/technical.py)
│   ├── econometrics.py      # ARIMA, GARCH, cointegration, PCA
│   ├── smc.py               # Smart Money Concepts
│   └── candlestick.py       # Pattern detection
├── broker/
│   ├── __init__.py
│   ├── protocol.py          # BrokerProtocol (typing.Protocol)
│   ├── mt5.py               # MT5 via RPyC/Wine
│   ├── paper.py             # Simulated broker
│   └── reconciliation.py    # Position reconciliation (new)
├── data/
│   ├── __init__.py
│   ├── feed.py              # OHLCV data feed
│   └── calendar.py          # Economic calendar
├── journal/
│   ├── __init__.py
│   ├── models.py            # Trade, Knowledge, DailyStats (SQLAlchemy)
│   ├── engine.py            # DuckDB journal engine
│   └── event_log.py         # Append-only event log
├── config/
│   ├── settings.yaml        # Strategy parameters
│   ├── symbols.yaml         # Symbol-specific overrides
│   └── macro_priors.yaml    # Economic priors (new)
├── types.py                 # Shared domain types (from core/types.py)
├── settings.py              # Pydantic settings (single config system)
└── logging.py               # Structured logging + event taxonomy
```

### 6.2 Dependency Injection

**Current pattern:** Agents receive `config` and `message_bus` via constructor kwargs. The orchestrator in `main.py` passes them uniformly.

**Issue:** Tight coupling. Agents import broker-specific code directly (`import MetaTrader5 as mt5` in `execution.py`). Testing requires mocking the entire MT5 module.

**Recommendation:** Use protocol-based DI:

```python
# broker/protocol.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class BrokerProtocol(Protocol):
    async def bars(self, symbol: str, tf: str, count: int) -> list[Bar]: ...
    async def send_order(self, order: OrderRequest) -> OrderResult: ...
    async def account_state(self) -> AccountState: ...
    async def positions(self) -> list[Position]: ...
```

This already partially exists in `docs/ARCHITECTURE.md` §9 but is not implemented. The `broker/base.py` uses ABC, not Protocol. Switching to Protocol enables structural subtyping (duck typing with type checking).

### 6.3 Configuration Management

**Recommendation: Unify into a single Pydantic-settings system.**

```python
# noema/settings.py
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """Single source of truth for all Noema configuration."""
    
    model_config = SettingsConfigDict(
        yaml_file="config/settings.yaml",
        env_prefix="Noema_",
        env_file=".env",
    )
    
    broker: BrokerSettings = BrokerSettings()
    risk: RiskSettings = RiskSettings()
    trading: TradingSettings = TradingSettings()
    guardian: GuardianSettings = GuardianSettings()
    # ... etc
```

This eliminates:
- `core/config.py` (dataclass-based, manual YAML parsing)
- `core/settings.py` (Pydantic-based, separate YAML loader)
- Manual env var parsing in `load_config()`
- The `config/default.yaml` vs `config/settings.yaml` confusion

### 6.4 Critical Bug Fixes (Immediate)

| # | File | Bug | Severity |
|---|------|-----|----------|
| 1 | `main.py` | `self.pipeline.advance(report=None)` passes None instead of PhaseResult | 🔴 Runtime crash |
| 2 | `main.py` | `prices.get("H1", prices.get("H4")).close.iloc[-1]` — no null check, crashes if both are None | 🔴 Runtime crash |
| 3 | `pyproject.toml` | Missing `aiohttp`, `sqlalchemy[asyncio]`, `aiosqlite` in dependencies | 🔴 Import error |
| 4 | `database/__init__.py` | References `self._logger` before assignment (assigned in `initialize()`) | 🟡 AttributeError |
| 5 | `agents/execution.py` | Directly imports `MetaTrader5` — fails on Linux without Wine/mt5linux | 🟡 ImportError |
| 6 | `data/calendar.py` | Uses `aiohttp` which isn't in dependencies | 🟡 ImportError |
| 7 | `agents/__init__.py` | Imports all 17 agents including those that don't exist yet (e.g., some files may be stubs) | 🟡 Various |

---

## 7. Summary: Priority Action Items

### P0 — Do Before Any Live Trading

1. **Resolve the dual-architecture problem.** Pick one design (recommend 7-agent from ARCHITECTURE.md), delete the other, update `main.py`.
2. **Write tests.** Minimum: unit tests for all indicators, confluence scoring, risk calculations, guardian vetoes, and the state machine.
3. **Fix runtime bugs** (items 1-3 from §6.4).
4. **Implement Guardian heartbeat** — the 5-second heartbeat with 30-second timeout is documented but not coded.
5. **Implement MT5 disconnect handling** — no reconnection logic exists.

### P1 — Do Before Backtesting

6. **Unify configuration** into single Pydantic-settings system.
7. **Consolidate indicators** — merge `indicators/` and `analysis/technical.py`.
8. **Add Prometheus metrics** — the dependency is declared, just wire it up.
9. **Set up CI/CD** — lint + test + security scan on every push.
10. **Implement DuckDB journal** — replace JSON file knowledge base.

### P2 — Do Before Scaling

11. **Add message bus persistence** — DuckDB-backed event log.
12. **Implement backtesting engine** — use polars for data, DuckDB for results.
13. **Add Telegram notifications** — dependency declared, just implement.
14. **Build monitoring dashboard** — Grafana + FastAPI.
15. **Evaluate Windows VPS** for MT5 — Wine is fragile for production.

---

## Appendix: Code Quality Metrics

| Metric | Value | Assessment |
|--------|-------|------------|
| Total lines of code | ~6,700 | Appropriate for scope |
| Files | 40+ source files | Reasonable |
| Test coverage | 0% | 🔴 Critical gap |
| Type hints | Partial (core types use Pydantic, agents use `dict[str, Any]`) | 🟡 Needs improvement |
| Docstrings | Present on all modules, most classes | ✅ Good |
| Error handling | Basic try/except in agents, no custom exceptions | 🟡 Needs improvement |
| Logging | Structured via structlog, agent-bound | ✅ Good |
| Config validation | Pydantic in types.py, raw YAML elsewhere | 🟡 Inconsistent |
| Dead code | `core/state_machine.py`, message bus, 8 unused agents | 🔴 Significant |
| Security | Documented in SECURITY.md, partially enforced | 🟡 Gaps in code |

---

*End of report.*
