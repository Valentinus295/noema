# Noema Code Quality Review Report

**Date:** 2026-06-17  
**Scope:** Full codebase audit — 58 Python files, ~6,729 LOC  
**Reviewer:** Automated Quality Analysis Agent  

---

## Executive Summary

The Noema codebase has **significant structural problems** that go beyond typical early-project technical debt. There are **two parallel, incompatible architectures** running simultaneously, **critical import errors** that would crash at runtime, a **complete absence of tests**, and **documentation that contradicts the actual code**. The system cannot currently run as written.

**Severity Scale:** 🔴 Critical | 🟠 Major | 🟡 Moderate | 🔵 Minor

| Category | Critical | Major | Moderate | Minor |
|---|---|---|---|---|
| Architecture | 3 | 4 | 2 | 1 |
| Code Quality | 1 | 3 | 4 | 3 |
| Testing | 2 | 2 | 1 | 0 |
| Dependencies | 2 | 2 | 1 | 0 |
| Documentation | 1 | 2 | 1 | 1 |

---

## 1. Code Quality Assessment

### 1.1 Code Organization and Module Structure

The project is organized into a reasonable directory structure:

```
noema/
├── agents/          (21 files, 2,458 LOC) — 17 agents + orchestrator + helpers
├── analysis/        (5 files, 1,725 LOC)  — econometrics, technical, SMC, candlestick, fundamental
├── broker/          (4 files, 676 LOC)    — base, mt5, fbs, paper
├── core/            (5 files, 634 LOC)    — agent, config, settings, message_bus, state_machine, types
├── config/          (2 YAML files)        — settings.yaml, symbols.yaml
├── data/            (2 files, 248 LOC)    — feed, calendar
├── database/        (2 files, 100 LOC)    — init (SQLAlchemy), models
├── indicators/      (3 files, 104 LOC)    — rsi, macd, candlestick
├── models/          (3 files, 193 LOC)    — trade, position, knowledge
├── scripts/         (1 file, 52 LOC)      — run_live.py
├── main.py          (425 LOC)             — orchestrator (17-agent version)
└── docs/, research/, config/
```

**Issues Found:**

- 🟠 **Duplicate orchestration layers**: `main.py` (425 LOC) contains a `NoemaOrchestrator` class that runs the 17-agent pipeline. `agents/orchestrator.py` (126 LOC) contains a *different* `Orchestrator` class that runs a 7-agent pipeline. These are completely separate, incompatible systems.
- 🟠 **Duplicate indicator modules**: `indicators/rsi.py`, `indicators/macd.py`, `indicators/candlestick.py` are pure-function versions used by the 7-agent system. `analysis/technical.py` and `analysis/candlestick.py` are class-based versions used by the 17-agent system. Both compute the same indicators differently.
- 🟡 **Duplicate data models**: `models/trade.py` defines `Trade` dataclass. `database/models.py` defines `TradeRecord` SQLAlchemy model. `broker/base.py` defines `Position` dataclass. `models/position.py` defines `PositionInfo` dataclass. Four different representations of overlapping concepts.

### 1.2 Naming Conventions

Generally consistent with Python conventions:

- ✅ Classes: PascalCase (`MarketStructureAgent`, `TradingPipeline`)
- ✅ Functions/methods: snake_case (`detect_order_blocks`, `_build_reasoning`)
- ✅ Constants: UPPER_SNAKE (`SESSIONS`, `OVERLAPS`, `TIMEFRAME_MAP`)
- ✅ Private methods: prefixed with `_`
- 🟡 Mixed agent naming: some use class-based agents inheriting from `Agent`, others are pure functions (`analyze_trend`, `conflate`, `guardian_guard`). This is a style inconsistency across the two architectures.

### 1.3 Type Hints Coverage

- ✅ All modules use `from __future__ import annotations`
- ✅ Function signatures consistently use type hints
- ✅ Pydantic v2 models in `core/types.py` with `Field` constraints and `ConfigDict`
- ✅ Dataclass fields annotated throughout
- 🟡 Return types on some agent `analyze()` methods return `AgentReport` (good) but the `data` dict inside is `dict[str, Any]` — no structural typing for what each agent actually returns
- 🟡 `core/config.py` uses plain dataclasses while `core/settings.py` uses Pydantic — inconsistent validation approach

### 1.4 Docstring Quality

- ✅ Every module has a module-level docstring
- ✅ All classes have docstrings explaining purpose
- ✅ All public methods have docstrings
- ✅ Good use of "Answers:" pattern in agent docstrings to clarify role
- 🔵 Some docstrings are generic ("Calculates position sizing") rather than documenting parameters, return values, or side effects
- 🔵 No docstrings follow a formal standard (Google, NumPy, or Sphinx style)

### 1.5 Error Handling Patterns

- 🟠 **Inconsistent error handling across the two architectures:**
  - 17-agent system: `Agent.process()` wraps `analyze()` in try/except, returns an ERROR signal report. This is good.
  - 7-agent system: Functions like `conflate()`, `analyze_trend()` return `None` on invalid input but callers don't always check. `Orchestrator.run_cycle()` catches all exceptions with a bare `print()`.
- 🟡 `EconometricsEngine` methods silently catch `ImportError` for optional deps (arch, talib) — this is reasonable but the fallback behavior should be more clearly documented.
- 🟡 `PaperBroker` has no error handling for invalid operations (e.g., closing a non-existent position silently returns False).
- 🔵 `KnowledgeBase._load()` catches all exceptions silently — could mask JSON corruption.

### 1.6 Logging Consistency

- ✅ All modules import and use `structlog` consistently
- ✅ Good use of structured logging with keyword arguments: `self._logger.info("analysis_complete", signal=report.signal, ...)`
- ✅ Agent base class binds agent name: `self._logger = logger.bind(agent=self.name)`
- 🟠 **structlog configured in `__init__` of `NoemaOrchestrator`** — this means every instantiation reconfigures logging. Should be done once at startup.
- 🟡 `agents/orchestrator.py` uses bare `print()` instead of structlog for error reporting
- 🔵 No log level differentiation — most things are logged at INFO

---

## 2. Architecture Smell Detection

### 🔴 CRITICAL: Two Incompatible Architectures Coexist

This is the single most important finding. The codebase contains **two completely separate trading systems** that share the same repository:

**Architecture A — 17-Agent System (`main.py`):**
- Uses `core/agent.Agent` base class
- Uses `core/config.NoemaConfig` (dataclasses)
- Uses `core/message_bus.MessageBus`
- Uses `core/state_machine.TradingPipeline`
- Uses `analysis/*` modules (class-based)
- Uses `broker/base.BrokerBase` (ABC)
- Orchestrated by `main.py:NoemaOrchestrator`

**Architecture B — 7-Agent System (`agents/orchestrator.py`):**
- Uses pure functions, NOT the Agent base class
- Uses `core/types.*` (Pydantic models: `Bar`, `Setup`, `Verdict`, `Bias`)
- Uses `indicators/*` modules (pure functions)
- Uses `broker/base.BrokerProtocol` (which **does not exist** in `broker/base.py`)
- Orchestrated by `agents/orchestrator.py:Orchestrator`

**Evidence:**
- `CLAUDE.md` documents 17 agents with their files
- `docs/ARCHITECTURE.md` §1 pins 7 agents as the "final" roster
- `main.py` imports all 17 agents from `agents/*.py`
- `agents/orchestrator.py` imports `from noema.agents.trend import analyze_trend` — a pure function, not the `MarketStructureAgent` class
- `agents/confluence.py` imports from `noema.indicators.rsi` and `noema.indicators.candlestick` — completely separate from the `analysis/` modules

### 🔴 CRITICAL: Broken Imports — System Cannot Run

Multiple files import symbols that **do not exist** in their source modules:

1. **`broker/fbs.py` line 13**: `from noema.broker.base import BrokerProtocol, Bar, Tick, AccountState, OrderRequest, Position`
   - `BrokerProtocol` does not exist in `broker/base.py` — only `BrokerBase` (ABC) exists
   - `Bar`, `Tick`, `AccountState`, `OrderRequest` do not exist in `broker/base.py`
   - `Position` exists but as a dataclass with different fields than what FBSBroker expects

2. **`agents/orchestrator.py` line 22**: `from noema.broker.base import BrokerProtocol, OrderRequest`
   - Same issue — `BrokerProtocol` and `OrderRequest` don't exist

3. **`agents/fundamental.py` line 14**: `from noema.broker.base import BrokerProtocol`
   - Same issue

4. **`agents/orchestrator.py` line 16**: `from noema.core.types import Bar, Bias, Direction, Setup, Verdict`
   - `Bar` does not exist in `core/types.py` — only `Bias`, `Verdict`, `Setup`, `Direction`, `Timeframe` are defined

5. **`scripts/run_live.py`**: Instantiates `MT5Broker` with `host`, `port`, `password` constructor args — but `MT5Broker.__init__` in `broker/mt5.py` takes `config: Any`, not those kwargs.

**These are not latent bugs — they are import-time crashes.** `scripts/run_live.py` and `agents/orchestrator.py` will fail with `ImportError` on startup.

### 🔴 CRITICAL: Dual Configuration System

Two completely separate config systems exist:

| Aspect | `core/config.py` | `core/settings.py` |
|---|---|---|
| **Framework** | Plain dataclasses | Pydantic BaseModel |
| **Loader** | `load_config()` → `NoemaConfig` | `load_settings()` → `Settings` |
| **Risk config** | `RiskConfig(risk_per_trade=0.01)` | `RiskConfig(risk_pct_per_trade=0.25)` |
| **Pairs** | 7 pairs (EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD) | 5 pairs (EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD) |
| **Default path** | `config/default.yaml` | `/home/valentinetech/noema/config/settings.yaml` (hardcoded absolute!) |
| **Used by** | 17-agent system (`main.py`) | 7-agent system (via `settings.yaml`) |

**The risk parameters are dangerously different:**
- `core/config.py`: `risk_per_trade = 0.01` (1%)
- `core/settings.py`: `risk_pct_per_trade = 0.25` (25%!)

If the wrong config is loaded, a single trade could risk 25% of capital instead of 1%.

### 🟠 Message Bus — Partially Dead Code

The `MessageBus` in `core/message_bus.py` is fully implemented (115 LOC) but:
- `NoemaOrchestrator` creates it and passes it to agents
- Agents call `self.message_bus.register()` in `start()` but **no agent subscribes to any topics**
- No agent calls `self.publish()` anywhere in the codebase
- The 7-agent system (`agents/orchestrator.py`) doesn't use the message bus at all
- The router loop runs but dispatches to zero handlers

**Verdict:** The message bus is initialized and running but is completely unused — dead code.

### 🟠 State Machine — Bypassed in Practice

The `TradingPipeline` state machine in `core/state_machine.py` is well-designed with 12 phases and strict transition rules. However:
- In `main.py:_analyze_pair()`, `self.pipeline.advance(report=None)` is called — passing `None` for the required `PhaseResult` argument. This will raise `AttributeError` when trying to access `result.success`.
- The pipeline state is never checked to determine which agents to run — the orchestrator runs all agents sequentially regardless of pipeline state.
- The 7-agent system doesn't use the state machine at all.

### 🟡 Agent Base Class Underutilization

The `Agent` base class provides:
- State management (IDLE/PROCESSING/WAITING/ERROR/STOPPED)
- `process()` wrapper with error handling and timing
- Message bus integration
- Report history

However:
- No agent overrides `start()` or `stop()` with meaningful logic
- No agent uses `subscribe()` or `publish()`
- No agent uses `_task` for background work
- The `priority` field is set but never used for ordering
- The `WAITING` state is never used

### 🟡 Database Module — Orphaned

`database/__init__.py` and `database/models.py` define SQLAlchemy async models (TradeRecord, KnowledgeEntry, DailyStats) but:
- `main.py` imports `KnowledgeBase` from `models/knowledge.py` (JSON file storage), NOT from the database module
- No code ever creates a `DatabaseEngine` instance
- `aiosqlite` is not in `pyproject.toml` dependencies
- The database module is completely disconnected from the rest of the system

---

## 3. Testing Gap Analysis

### 🔴 Zero Test Files Exist

There are **no test files anywhere** in the repository. No `tests/` directory, no `test_*.py` files, no `conftest.py`. This is despite:
- `pyproject.toml` declaring `pytest>=8.0`, `pytest-asyncio>=0.24`, `hypothesis>=6.0` in dev deps
- `pyproject.toml` configuring `testpaths = ["tests"]` and `asyncio_mode = "auto"`

### Priority Test Plan (Ordered by Criticality)

#### Phase 1: Smoke Tests (Week 1) — Prevent Regressions

| Priority | Test Target | File | What to Test |
|---|---|---|---|
| P0 | Import smoke | `tests/test_imports.py` | Every module imports without error. **Currently many will fail.** |
| P0 | Config loading | `tests/test_config.py` | `load_config()` and `load_settings()` produce valid configs |
| P0 | PaperBroker | `tests/test_paper_broker.py` | Full order lifecycle: place → modify → close |
| P0 | Agent base | `tests/test_agent_base.py` | `process()` error handling, state transitions |
| P0 | RSI calculation | `tests/test_indicators.py` | RSI values match known expected outputs |

#### Phase 2: Unit Tests (Weeks 2-3) — Core Logic

| Priority | Test Target | What to Test |
|---|---|---|
| P1 | CandlestickDetector | Each pattern detector with known candle sequences |
| P1 | SMCForecaster | Order block, FVG, liquidity sweep detection |
| P1 | TechnicalAnalyzer | EMA, RSI, MACD, ADX, ATR calculations |
| P1 | TradingPipeline | State transitions, rejection, reset |
| P1 | EconometricsEngine | ADF test, GARCH, cointegration with known datasets |
| P1 | RiskManagerAgent | Position sizing, loss limit enforcement |
| P1 | GuardianAgent | Daily/weekly loss limits, heartbeat checks |

#### Phase 3: Integration Tests (Weeks 3-4) — Agent Coordination

| Priority | Test Target | What to Test |
|---|---|---|
| P2 | ConfluenceAgent | End-to-end: trend + structure → setup generation |
| P2 | Full pipeline | 17-agent pipeline with PaperBroker and synthetic data |
| P2 | PortfolioAgent | Correlation caps, PCA factors with known setups |
| P2 | Orchestrator | Full cycle: fetch → analyze → trade → record |

#### Phase 4: Property-Based Tests (Weeks 4-5) — Edge Cases

| Priority | Test Target | Properties to Test |
|---|---|---|
| P3 | RSI | Output always in [0, 100]; monotonic with gains/losses |
| P3 | ATR | Always ≥ 0; increases with volatility |
| P3 | Position sizing | Lot size always > 0; never exceeds account balance |
| P3 | Candlestick detection | No false positives on random data; symmetric bullish/bearish |
| P3 | Confluence score | Always in [0, 1]; monotonic with more confirming signals |
| P3 | State machine | Cannot skip phases; always reaches terminal state |

### Recommended Test Structure

```
tests/
├── conftest.py              # Fixtures: synthetic OHLCV, mock broker, config
├── test_imports.py           # Smoke: every module imports
├── test_config.py            # Config loading, env overrides, validation
├── test_indicators/
│   ├── test_rsi.py
│   ├── test_macd.py
│   └── test_candlestick.py
├── test_analysis/
│   ├── test_technical.py
│   ├── test_smc.py
│   ├── test_econometrics.py
│   └── test_candlestick.py
├── test_agents/
│   ├── test_agent_base.py
│   ├── test_trend.py
│   ├── test_structure.py
│   ├── test_confluence.py
│   ├── test_risk.py
│   └── test_guardian.py
├── test_broker/
│   ├── test_paper_broker.py
│   └── test_mt5_broker.py   # Unit tests with mocked MT5
├── test_core/
│   ├── test_message_bus.py
│   ├── test_state_machine.py
│   └── test_types.py
├── test_integration/
│   ├── test_full_pipeline.py
│   └── test_orchestrator.py
└── test_property/
    └── test_indicator_properties.py
```

### Hypothesis Opportunities

```python
# Example: RSI is always bounded
@given(st.lists(st.floats(min_value=0.01, max_value=100.0), min_size=15))
def test_rsi_bounded(closes):
    bars = [Bar(close=c, open=c, high=c, low=c, volume=1, time=0) for c in closes]
    result = rsi(bars)
    assert 0 <= result <= 100

# Example: Position sizing never exceeds risk budget
@given(st.floats(min_value=100, max_value=1_000_000), st.floats(min_value=0.001, max_value=0.1))
def test_position_size_within_risk(balance, risk_pct):
    # ... assert lot_size * pip_value * sl_pips <= balance * risk_pct
```

---

## 4. Dependency Health

### 🔴 Missing Dependencies in pyproject.toml

| Dependency | Used In | Status |
|---|---|---|
| `sqlalchemy` | `database/__init__.py`, `database/models.py` | **NOT in pyproject.toml** |
| `aiosqlite` | `database/__init__.py` (async SQLite) | **NOT in pyproject.toml** |
| `aiohttp` | `data/calendar.py` (HTTP fetch) | **NOT in pyproject.toml** |
| `pandas` | Nearly every file | **NOT in pyproject.toml** (implicit via other deps?) |
| `requests` | Not directly used, but httpx is listed | OK |

### 🟠 Unused Dependencies in pyproject.toml

| Dependency | Declared | Actually Imported | Used? |
|---|---|---|---|
| `mt5linux>=1.0.3` | ✅ | ❌ Never imported | ❌ Unused |
| `rpyc>=6.0` | ✅ | `broker/fbs.py` | ✅ Used |
| `TA-Lib>=0.6.0` | ✅ | `analysis/technical.py` (conditional) | ✅ Used (optional) |
| `polars>=1.10` | ✅ | ❌ Never imported | ❌ Unused |
| `pyarrow>=17.0` | ✅ | ❌ Never imported | ❌ Unused |
| `duckdb>=1.1` | ✅ | ❌ Never imported | ❌ Unused |
| `uvloop>=0.22` | ✅ | ❌ Never imported | ❌ Unused |
| `prometheus-client>=0.21` | ✅ | ❌ Never imported | ❌ Unused |
| `rich>=13.0` | ✅ | ❌ Never imported | ❌ Unused |
| `pydantic-settings>=2.6` | ✅ | ❌ Never imported | ❌ Unused |
| `python-dotenv>=1.0` | ✅ | ❌ Never imported | ❌ Unused |
| `finnhub-python>=2.4` | ✅ | ❌ Never imported | ❌ Unused |
| `httpx>=0.27` | ✅ | ❌ Never imported | ❌ Unused |
| `openai>=1.40` | ✅ | ❌ Never imported | ❌ Unused |
| `python-telegram-bot>=21.0` | ✅ | ❌ Never imported | ❌ Unused |
| `pendulum>=3.0` | ✅ | ❌ Never imported | ❌ Unused |

**13 out of 18 declared runtime dependencies are unused.** The `pandas` dependency is missing but used everywhere (likely pulled in transitively by `statsmodels` or `scikit-learn`, but this is fragile).

### 🟠 Version Pinning Strategy

- ✅ Lower bounds are specified (`>=`) — good for minimum compatibility
- 🔵 No upper bounds — risky for breaking changes in major versions
- 🟡 `rpyc>=6.0` is correctly pinned per security review (RCE history in <5.3)
- 🔵 No lock file (`uv.lock` or `requirements.txt`) committed — reproducibility risk

### Supply Chain Risk Assessment

- **`MetaTrader5`**: Windows-only proprietary package. The `mt5linux` bridge uses RPyC to connect through Wine. RPyC has had RCE vulnerabilities (addressed by `>=6.0` pin).
- **`arch`**: GARCH models. Maintained by Kevin Sheppard (Oxford). Low risk.
- **`finnhub-python`**: Free tier API client. Not imported anywhere despite being declared.
- **`openai`**: Declared for LLM integration but not imported. Will be a significant supply chain surface when activated.

---

## 5. Technical Debt Inventory

### 5.1 TODO/FIXME/HACK/XXX Markers

**None found.** A search for TODO, FIXME, HACK, XXX, STUB, PLACEHOLDER across all `.py` files returned zero results. This is concerning — it suggests either:
- The codebase was generated without iterative development, or
- Debt markers were deliberately removed

### 5.2 Incomplete / Stub Implementations

| Module | Issue | Severity |
|---|---|---|
| `agents/fundamental.py:89-92` | `fetch_news_events()` returns empty list — no actual news fetching | 🟠 |
| `agents/fundamental.py:94` | `compute_fundamental_bias()` uses hardcoded yield values: `{"USD": 4.5, "EUR": 3.5, "GBP": 4.0, "JPY": 0.5}` | 🟠 |
| `agents/management.py` | `TradeManagementAgent.analyze()` — stub that returns NEUTRAL with no management logic | 🟠 |
| `agents/performance.py` | `PerformanceAnalystAgent.analyze()` — reads `trade_history` from context but no code populates it | 🟠 |
| `agents/learning.py` | `LearningAgent.analyze()` — writes to JSON file but doesn't actually learn anything | 🟡 |
| `agents/orchestrator.py:46` | `_run_agents()` hardcodes `rsi_val = 50.0` and `candle_pat = None` instead of computing them | 🟠 |
| `agents/portfolio.py:29-31` | `_compute_currency_strength()` computes strength as deviation from mean — not actual currency strength methodology | 🟡 |
| `broker/paper.py:62-63` | `get_rates()` uses `np.random.seed(42)` — generates identical data every call regardless of symbol/timeframe | 🟠 |
| `broker/paper.py:88-89` | `place_order()` always fills at price `1.1001` regardless of symbol | 🟠 |
| `data/calendar.py` | `_fetch_from_api()` tries `aiohttp` which isn't installed. Falls back to random synthetic events | 🟡 |
| `main.py:310` | SL/TP calculation: `atr = 0.0010` hardcoded instead of computed from data | 🔴 |
| `main.py:308` | `current_price` extraction: `float(prices.get("H1", prices.get("H4")).close.iloc[-1])` — fragile, will crash if both are None | 🟠 |
| `database/` module | Entire module is orphaned — never instantiated, never used | 🟠 |
| `core/message_bus.py` | Fully implemented but zero subscribers — dead code | 🟠 |

### 5.3 Documentation vs Code Inconsistencies

| Document | Claims | Reality | Severity |
|---|---|---|---|
| `CLAUDE.md` | 17 agents | Code has 17 agent classes + separate 7-function system | 🔴 |
| `docs/ARCHITECTURE.md` §1 | 7 agents (final) | 17 agent classes still exist and are used by `main.py` | 🔴 |
| `CLAUDE.md` | `python -m noema.main --mode paper` | Module structure doesn't support this (no `noema/` package dir) | 🟠 |
| `docs/ARCHITECTURE.md` §2 | FundamentalBiasAgent: Python computes, LLM narrates | `agents/fundamental.py` has no LLM integration; hardcoded yields | 🟠 |
| `docs/ARCHITECTURE.md` §9 | `BrokerProtocol` (Pydantic/typing.Protocol) | Does not exist in `broker/base.py` — only `BrokerBase` (ABC) | 🟠 |
| `docs/ARCHITECTURE.md` §10 | Guardian heartbeat every 5s, ExecutionAgent checks | Guardian heartbeat exists but ExecutionAgent never checks it | 🟡 |
| `config/settings.yaml` | 5 pairs (EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD) | `core/config.py` default has 7 pairs (includes USDCHF, NZDUSD, USDCAD, excludes XAUUSD) | 🟡 |
| `pyproject.toml` | `packages = ["noema"]` | No `noema/` directory — code lives at repo root | 🟠 |
| `CLAUDE.md` | Version 1.0.0 | `pyproject.toml` says 0.1.0 | 🔵 |

### 5.4 Dead Code Detection

| Item | Location | Why Dead |
|---|---|---|
| `MessageBus` | `core/message_bus.py` | No agent subscribes or publishes |
| `TradingPipeline` | `core/state_machine.py` | Bypassed by orchestrator (passes `None` to `advance()`) |
| `DatabaseEngine` | `database/__init__.py` | Never instantiated |
| `TradeRecord`, `KnowledgeEntry`, `DailyStats` | `database/models.py` | Never queried or written |
| `TradingConfig.asian_session_*` | `core/config.py` | Never referenced by any agent |
| `EconometricsConfig` | `core/config.py` | Instantiated but never read by econometrics engine |
| `AgentState.WAITING` | `core/agent.py` | Never set by any code |
| `Agent._task` | `core/agent.py` | Never assigned |
| `Agent.subscribe()` / `Agent.publish()` | `core/agent.py` | Never called by any agent |
| `PaperBroker.trade_history` property | `broker/paper.py` | Never read |
| `MarketDataFeed._cache` | `data/feed.py` | Cache is never invalidated, could serve stale data |
| `mt5linux` dependency | `pyproject.toml` | Never imported |

---

## 6. Restructuring Recommendations

### Priority 1: Resolve the Dual Architecture (🔴 CRITICAL — Week 1)

**The system must choose ONE architecture.** Recommendation: adopt the 7-agent system from `docs/ARCHITECTURE.md` as it's the documented "pinned" design, then:

1. **Delete or archive `main.py`** and the 17-agent orchestrator
2. **Delete the 17 agent classes** that are replaced by pure functions (keep `agents/__init__.py` exports only if needed for backward compat)
3. **Create the missing types** that the 7-agent system needs:
   - Add `Bar` dataclass to `core/types.py`
   - Add `BrokerProtocol`, `OrderRequest`, `Tick`, `AccountState` to `broker/base.py`
4. **Delete `core/config.py`** (dataclass version) and standardize on `core/settings.py` (Pydantic version)
5. **Fix `scripts/run_live.py`** to match the actual broker constructor signatures

### Priority 2: Fix Broken Imports (🔴 CRITICAL — Week 1)

1. Define `Bar` in `core/types.py`:
   ```python
   @dataclass(frozen=True, slots=True)
   class Bar:
       time: int
       open: float
       high: float
       low: float
       close: float
       volume: float
   ```

2. Define `BrokerProtocol` in `broker/base.py` (as `typing.Protocol`):
   ```python
   class BrokerProtocol(Protocol):
       async def connect(self) -> None: ...
       async def disconnect(self) -> None: ...
       async def bars(self, symbol: str, timeframe: str, count: int) -> Sequence[Bar]: ...
       # ... etc
   ```

3. Define `OrderRequest`, `Tick`, `AccountState` in `broker/base.py`

### Priority 3: Consolidate Configuration (🟠 — Week 2)

1. Delete `core/config.py` entirely
2. Move all settings into `config/settings.yaml` with Pydantic validation via `core/settings.py`
3. Remove hardcoded absolute path: `/home/valentinetech/noema/config/settings.yaml` → `Path("config/settings.yaml")`
4. Unify pair lists: use `symbols.yaml` as single source of truth
5. Add `aiosqlite` and `sqlalchemy` to `pyproject.toml` if database module is kept, or delete it

### Priority 4: Write Critical Tests (🟠 — Weeks 2-4)

Follow the test plan in §3. Start with import smoke tests (they'll reveal all the broken imports), then indicator unit tests, then integration tests.

### Priority 5: Clean Up Dependencies (🟠 — Week 2)

1. Remove 13 unused dependencies from `pyproject.toml`
2. Add missing dependencies: `pandas`, `sqlalchemy`, `aiosqlite`, `aiohttp`
3. Commit a lock file (`uv.lock`)
4. Document which deps are optional vs required

### Priority 6: Implement Stub Agents (🟡 — Weeks 3-6)

1. `agents/management.py` — implement trailing stop, breakeven, partial close logic
2. `agents/performance.py` — connect to database/knowledge base for trade history
3. `agents/learning.py` — implement actual pattern learning from trade outcomes
4. `agents/fundamental.py` — integrate Finnhub API for real news events
5. `broker/paper.py` — make synthetic data vary by symbol and timeframe

### Priority 7: Interface Standardization (🟡 — Week 3)

1. Decide: should agents be classes or pure functions? The 7-agent system uses functions; if that's the choice, delete the Agent base class.
2. If keeping the Agent base class, make agents actually use it (publish/subscribe, background tasks, state management).
3. Standardize the `context: dict[str, Any]` pattern — define typed context objects per agent.

### Priority 8: Module Consolidation (🔵 — Week 4)

1. Merge `models/` into `core/` — `Trade`, `PositionInfo`, `KnowledgeBase` are core domain types
2. Delete `database/` module if not being used, or connect it properly
3. Consider merging `indicators/` into `analysis/` — having two separate indicator systems is confusing

---

## 7. Code Metrics

### 7.1 Lines of Code per Module

| Module | Files | LOC | Avg LOC/File |
|---|---|---|---|
| `agents/` | 21 | 2,458 | 117 |
| `analysis/` | 5 | 1,725 | 345 |
| `main.py` | 1 | 425 | 425 |
| `broker/` | 4 | 676 | 169 |
| `core/` | 5 | 634 | 127 |
| `data/` | 2 | 248 | 124 |
| `models/` | 3 | 193 | 64 |
| `database/` | 2 | 100 | 50 |
| `indicators/` | 3 | 104 | 35 |
| `scripts/` | 1 | 52 | 52 |
| `__init__.py` (root) | 1 | 4 | 4 |
| **Total** | **58** | **6,729** | **116** |

### 7.2 Complexity Assessment

| File | LOC | Functions | Complexity Rating |
|---|---|---|---|
| `analysis/econometrics.py` | 502 | 11 | 🟡 High — many statistical methods, good separation |
| `main.py` | 425 | 8 | 🟠 High — monolithic orchestrator, `_analyze_pair` is 130+ LOC |
| `analysis/smc.py` | 372 | 8 | 🟡 Medium — well-structured pattern detection |
| `broker/mt5.py` | 315 | 12 | 🟢 Medium — straightforward API wrapper |
| `analysis/technical.py` | 312 | 13 | 🟢 Medium — clean indicator calculations |
| `analysis/candlestick.py` | 290 | 11 | 🟢 Low — pattern matching, well-decomposed |
| `agents/orchestrator.py` | 126 | 8 | 🟢 Low — clean async orchestration |
| `core/state_machine.py` | 187 | 10 | 🟢 Low — clear state machine |

### 7.3 Coupling Analysis

**High Coupling (problematic):**
- `main.py` → imports ALL 17 agents + all infrastructure modules (fan-out dependency)
- `agents/orchestrator.py` → imports from 6 different modules
- All 17 agent classes → depend on `core/agent.py` (expected, not problematic)

**Low Coupling (good):**
- `analysis/*` modules are self-contained — no cross-imports between analysis modules
- `indicators/*` modules are pure functions with zero dependencies
- `core/types.py` has no internal dependencies (only pydantic)

**Circular Dependencies:** None detected. The dependency graph is a DAG.

---

## Appendix A: File-by-File Import Errors

| File | Line | Import | Problem |
|---|---|---|---|
| `broker/fbs.py` | 13 | `from noema.broker.base import BrokerProtocol` | Does not exist |
| `broker/fbs.py` | 13 | `from noema.broker.base import Bar` | Does not exist |
| `broker/fbs.py` | 13 | `from noema.broker.base import Tick` | Does not exist |
| `broker/fbs.py` | 13 | `from noema.broker.base import AccountState` | Does not exist |
| `broker/fbs.py` | 13 | `from noema.broker.base import OrderRequest` | Does not exist |
| `agents/orchestrator.py` | 16 | `from noema.core.types import Bar` | Does not exist |
| `agents/orchestrator.py` | 22 | `from noema.broker.base import BrokerProtocol` | Does not exist |
| `agents/orchestrator.py` | 22 | `from noema.broker.base import OrderRequest` | Does not exist |
| `agents/fundamental.py` | 14 | `from noema.broker.base import BrokerProtocol` | Does not exist |
| `scripts/run_live.py` | 38-44 | `MT5Broker(host=..., port=..., password=...)` | Wrong constructor signature |

## Appendix B: Dependency Usage Matrix

| Dependency | Declared | Imported | Actually Used |
|---|---|---|---|
| `mt5linux` | ✅ | ❌ | ❌ |
| `rpyc` | ✅ | ✅ `broker/fbs.py` | ✅ |
| `TA-Lib` | ✅ | ✅ `analysis/technical.py` (conditional) | ✅ |
| `polars` | ✅ | ❌ | ❌ |
| `pyarrow` | ✅ | ❌ | ❌ |
| `duckdb` | ✅ | ❌ | ❌ |
| `uvloop` | ✅ | ❌ | ❌ |
| `structlog` | ✅ | ✅ All modules | ✅ |
| `prometheus-client` | ✅ | ❌ | ❌ |
| `rich` | ✅ | ❌ | ❌ |
| `pydantic` | ✅ | ✅ `core/types.py`, `core/settings.py` | ✅ |
| `pydantic-settings` | ✅ | ❌ | ❌ |
| `python-dotenv` | ✅ | ❌ | ❌ |
| `numpy` | ✅ | ✅ Many modules | ✅ |
| `scipy` | ✅ | ✅ `analysis/econometrics.py` | ✅ |
| `statsmodels` | ✅ | ✅ `analysis/econometrics.py` | ✅ |
| `arch` | ✅ | ✅ `analysis/econometrics.py` (conditional) | ✅ |
| `scikit-learn` | ✅ | ✅ `analysis/econometrics.py`, `agents/portfolio.py` | ✅ |
| `finnhub-python` | ✅ | ❌ | ❌ |
| `httpx` | ✅ | ❌ | ❌ |
| `openai` | ✅ | ❌ | ❌ |
| `python-telegram-bot` | ✅ | ❌ | ❌ |
| `pyyaml` | ✅ | ✅ `core/config.py`, `core/settings.py` | ✅ |
| `pendulum` | ✅ | ❌ | ❌ |
| `pandas` | ❌ | ✅ Nearly everywhere | ✅ MISSING |
| `sqlalchemy` | ❌ | ✅ `database/` | ✅ MISSING |
| `aiosqlite` | ❌ | ❌ (needed by database/) | MISSING |
| `aiohttp` | ❌ | ❌ (needed by data/calendar.py) | MISSING |

---

## Appendix C: Recommended Next Steps (Ordered)

1. **Decide the architecture.** 7-agent (ARCHITECTURE.md) or 17-agent (CLAUDE.md)? This is a business decision, not a technical one.
2. **Fix all import errors** (Appendix A). The system literally cannot start.
3. **Delete dead code** — the unused architecture, orphaned database module, dead message bus.
4. **Consolidate to one config system** — Pydantic settings, single YAML source.
5. **Write import smoke tests** — they'll catch future breakage immediately.
6. **Clean dependencies** — remove 13 unused, add 4 missing.
7. **Write indicator unit tests** — these are pure functions, easiest to test.
8. **Implement stub agents** — management, performance, learning.
9. **Add integration tests** with PaperBroker.
10. **Set up CI** — ruff lint + mypy + pytest on every commit.

---

*End of Quality Review Report*
