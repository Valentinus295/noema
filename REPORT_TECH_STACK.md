# Noema Tech Stack Enterprise Readiness Assessment

**Date:** 2026-06-17  
**Verdict:** 🔴 **NOT enterprise-ready. The current stack is a prototype, not a trading system.**  
**Scope:** Full evaluation of every dependency, architectural pattern, and runtime characteristic against enterprise multi-agent trading requirements.

---

## The Core Question

> "Can this tech stack run a smart multi-agent forex trading system at enterprise level efficiently?"

**No.** Here's why, layer by layer, and what to replace each piece with.

---

## 1. Execution & Concurrency Layer

### Current: Raw `asyncio` with sequential execution

```python
# main.py — the entire trading loop
while self._running:
    await self._trading_cycle()        # processes ALL pairs SEQUENTIALLY
    await asyncio.sleep(60)            # sleeps 60 seconds between cycles
```

**Problems:**
- Agents run **one at a time**, not in parallel. A 7-agent pipeline for 5 pairs = 35 sequential calls per cycle.
- No `asyncio.gather()` anywhere in the codebase — zero parallelism.
- The 60-second sleep means the system checks the market **once per minute**. Forex moves in milliseconds.
- No task supervision, no cancellation propagation, no structured concurrency.

### Enterprise Requirement

| Requirement | Current | Needed |
|---|---|---|
| Agent parallelism | ❌ Sequential | ✅ Concurrent per-pair, parallel across pairs |
| Tick-level reaction | ❌ 60s polling | ✅ Sub-second event-driven |
| Task supervision | ❌ None | ✅ Structured concurrency with cancellation |
| Graceful degradation | ❌ Crash = halt | ✅ Per-agent isolation, fallback chains |

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **Async runtime** | Raw asyncio | **`asyncio` + `anyio`** | Structured concurrency, task groups, cancellation scopes |
| **Agent orchestration** | Sequential loop | **`asyncio.TaskGroup`** (Python 3.11+) | True parallel agent execution with error propagation |
| **Event system** | Dead message bus | **`asyncio.Queue` + pub/sub** or **Redis Streams** | Real-time event-driven architecture |
| **Scheduling** | `asyncio.sleep(60)` | **APScheduler** or **custom tick loop** | Precise cadence, jitter handling, missed-tick detection |

---

## 2. Data Pipeline

### Current: Pandas everywhere with Python loops

```python
# analysis/smc.py — Python loop over every bar
for i in range(lookback, len(df) - 3):
    if opens[i] > closes[i]:  # Bearish candle
        impulse = closes[i+3] - closes[i]
        if impulse > avg_range * min_impulse:
            # ...
```

**70 pandas references, 71 numpy references, 15+ Python for-loops over data.**

**Problems:**
- Python for-loops over OHLCV data are **100-1000x slower** than vectorized operations.
- No streaming data support — the system fetches a batch, processes it, then sleeps.
- `MarketDataFeed._cache` is a dict with no TTL, no invalidation, no size limit.
- `PaperBroker.get_rates()` uses `np.random.seed(42)` — generates identical data every call.

### Enterprise Requirement

| Requirement | Current | Needed |
|---|---|---|
| Data throughput | ~200 bars/batch | ✅ Tick-level streaming (1000+ events/sec) |
| Processing speed | Python loops | ✅ Vectorized (NumPy/Pandas) or compiled (Rust/C) |
| Caching | In-memory dict, no TTL | ✅ Redis/LRU with TTL and invalidation |
| Real-time data | Polling every 60s | ✅ WebSocket streaming from broker |

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **Data processing** | Pandas + Python loops | **Polars** (already in unused deps!) | 10-100x faster than Pandas, lazy evaluation, streaming |
| **OHLCV storage** | Pandas DataFrame | **Polars DataFrame** or **DuckDB** | Columnar, vectorized, memory-efficient |
| **Caching** | `dict[str, DataFrame]` | **Redis** or **`cachetools.TTLCache`** | TTL, eviction, shared across processes |
| **Real-time data** | Polling | **WebSocket** (MT5 / broker API) | Sub-second price updates |
| **Indicator compute** | Python loops | **TA-Lib** (vectorized C) + **Polars expressions** | 100x faster than pure Python |

### Critical: Vectorize the Hot Path

The SMC, candlestick, and swing-detection code all use Python for-loops. These run on every tick/candle. They MUST be vectorized:

```python
# BEFORE (current) — Python loop, O(n) with Python overhead
for i in range(lookback, len(df) - 3):
    if opens[i] > closes[i]:
        impulse = closes[i+3] - closes[i]

# AFTER (vectorized) — NumPy/Pandas, O(n) with C speed
bearish = opens > closes
impulse = closes.shift(-3) - closes
valid = bearish & (impulse > avg_range * min_impulse)
order_blocks = df[valid]
```

---

## 3. Broker Integration

### Current: RPyC over TCP to Wine/MT5

```python
# broker/fbs.py — RPyC remote procedure call
self._conn = await loop.run_in_executor(None, rpyc.connect, self._host, self._port)
data = await asyncio.get_event_loop().run_in_executor(None, self._conn.root.bars, ...)
```

**Problems:**
- **RPyC latency**: Every call is a TCP round-trip to a Wine process. ~5-50ms per call.
- **No connection pooling**: Single connection, no failover.
- **No reconnection logic**: If RPyC disconnects, the system crashes.
- **Security**: RPyC has had RCE vulnerabilities. Running over Wine adds attack surface.
- **`run_in_executor` on every call**: Thread pool exhaustion under load.

### Enterprise Requirement

| Requirement | Current | Needed |
|---|---|---|
| Latency | 5-50ms per RPyC call | ✅ <1ms for order send |
| Reconnection | ❌ None | ✅ Auto-reconnect with state reconciliation |
| Connection pooling | ❌ Single conn | ✅ Pool with health checks |
| Order deduplication | ❌ None | ✅ Idempotency keys |

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **MT5 bridge** | RPyC/Wine | **MetaTrader5 Python package** (native) or **FIX protocol** | 10x lower latency, no Wine dependency |
| **Connection mgmt** | Manual | **`aiohttp.ClientSession`** pattern or **connection pool** | Auto-reconnect, health checks |
| **Order execution** | Synchronous via executor | **Async native** with idempotency | Non-blocking, deduplicated |
| **Paper trading** | Custom (buggy) | **Backtrader** or **vectorbt** | Proven simulation engine |

**Note:** If Windows MT5 is mandatory, consider running the Python trading engine on Linux and connecting to MT5 on Windows via a proper FIX bridge or the `mt5linux` package (which was removed from deps but is actually needed for this use case).

---

## 4. LLM Integration ("Smart" Agents)

### Current: Zero LLM integration

Despite being called a "smart multi-agent system," there is **no LLM integration anywhere**. The `openai` package was declared but never imported. The `agents/fundamental.py` hardcodes yield values:

```python
yields = {"USD": 4.5, "EUR": 3.5, "GBP": 4.0, "JPY": 0.5}
```

The architecture doc says "Python computes, LLM narrates" but no LLM client exists.

### Enterprise Requirement

For a genuinely "smart" system, LLM integration is needed for:
- Fundamental analysis narration (news interpretation)
- Trade thesis generation (natural language reasoning)
- Devil's advocate reasoning (counter-arguments)
- Post-trade analysis (learning from outcomes)

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **LLM client** | None | **`openai`** (already declared) or **`litellm`** | Multi-provider support, retries, streaming |
| **LLM orchestration** | None | **LangChain** or **direct API** | Prompt management, output parsing |
| **Prompt management** | None | **Jinja2 templates** | Versioned, testable prompts |
| **Output validation** | None | **Pydantic** (already used) | Structured LLM output with schema validation |
| **Cost control** | None | **Token counting + budget limits** | Prevent runaway API costs |

**Architecture note:** The current design (ARCHITECTURE.md §2) correctly pins LLM as narrator-only, never on the critical path. This is good. But even the narrator needs a client.

---

## 5. Persistence & State

### Current: JSON files + dead SQLAlchemy module

```python
# models/knowledge.py — JSON file persistence
self.path.write_text(json.dumps(self.data, indent=2))

# database/ — SQLAlchemy models exist but are NEVER USED
```

**Problems:**
- JSON file storage has no transactions, no concurrency safety, no query capability.
- Knowledge base grows unbounded (appends every trade, never prunes).
- No state recovery on restart — the system loses all in-memory state.
- SQLAlchemy models exist but are disconnected from the rest of the system.

### Enterprise Requirement

| Requirement | Current | Needed |
|---|---|---|
| ACID transactions | ❌ JSON file | ✅ Database with transactions |
| Query capability | ❌ Load entire file | ✅ SQL queries for analytics |
| State recovery | ❌ Lost on restart | ✅ Persistent state with recovery |
| Trade journal | ❌ In-memory list | ✅ Append-only log with full context |

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **Primary DB** | JSON files | **SQLite** (via SQLAlchemy async) | ACID, queryable, zero-config |
| **Time-series data** | Pandas in memory | **DuckDB** or **TimescaleDB** | Fast OHLCV queries, compression |
| **Trade journal** | In-memory list | **Append-only SQLite table** | Durable, queryable, auditable |
| **State recovery** | None | **Checkpoint + WAL pattern** | Resume from last known state |
| **Knowledge base** | JSON file | **SQLite with periodic aggregation** | Bounded size, indexed queries |

---

## 6. Monitoring & Observability

### Current: structlog only

```python
structlog.configure(
    processors=[..., structlog.dev.ConsoleRenderer()],
)
```

**Problems:**
- Console-only output — no metrics, no alerts, no dashboards.
- `prometheus-client` was declared but never imported.
- No health checks, no readiness probes, no liveness probes.
- No trade-level metrics (win rate, drawdown, Sharpe — computed nowhere in real-time).

### Enterprise Requirement

| Requirement | Current | Needed |
|---|---|---|
| Metrics | ❌ None | ✅ Prometheus/StatsD with custom trade metrics |
| Alerting | ❌ None | ✅ Telegram/webhook on trade events |
| Health checks | ❌ None | ✅ HTTP endpoint for liveness/readiness |
| Trade dashboard | ❌ None | ✅ Real-time P&L, positions, agent status |

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **Logging** | structlog (ConsoleRenderer) | **structlog + JSON renderer** | Machine-parseable, ship to ELK/Loki |
| **Metrics** | None | **`prometheus_client`** (already declared) | Standard metrics format, Grafana integration |
| **Alerting** | None | **`python-telegram-bot`** (already declared) | Trade notifications, kill-switch alerts |
| **Health** | None | **`aiohttp` web server** | `/health`, `/ready`, `/metrics` endpoints |
| **Dashboard** | None | **Grafana** + Prometheus | Real-time trade visualization |

---

## 7. Backtesting & Strategy Validation

### Current: Zero backtesting capability

There is no backtesting engine. The system can only run forward (live or paper). This is a **critical gap** — no professional trading system deploys without backtesting.

### Recommended Stack

| Component | Current | Recommended | Why |
|---|---|---|---|
| **Backtesting engine** | None | **`backtrader`** or **`vectorbt`** | Event-driven or vectorized backtesting |
| **Walk-forward** | Config exists, no impl | **Custom with rolling windows** | Out-of-sample validation |
| **Permutation tests** | Config exists, no impl | **`arch` package** (already declared) | Stationary bootstrap |
| **Performance analytics** | None | **`pyfolio`** or **`quantstats`** | Sharpe, drawdown, tear sheets |

---

## 8. Configuration & Secrets

### Current: YAML + Pydantic (good foundation)

The config system after consolidation is actually reasonable:
- Pydantic validation ✓
- YAML file with env var overrides ✓
- Backward-compatible shim ✓

**Remaining issues:**
- Secrets (MT5 password) in env vars — should use a secrets manager in production.
- No config hot-reload — changing settings requires restart.
- No per-environment configs (dev/staging/prod).

### Recommended Additions

| Component | Recommended | Why |
|---|---|---|
| **Secrets** | **`python-dotenv`** for dev, **AWS SSM / Vault** for prod | Never hardcode secrets |
| **Config reload** | **`watchdog`** on YAML file | Hot-reload without restart |
| **Environments** | `config/settings.dev.yaml`, `config/settings.prod.yaml` | Per-env overrides |

---

## 9. Dependency Gap Analysis

### What's Declared but Unused (removed in cleanup)

| Dependency | Why It Should Be Re-Added |
|---|---|
| `polars` | **YES — replace Pandas** for 10-100x speedup on data processing |
| `httpx` | **YES — needed for API calls** (Finnhub, LLM, news) |
| `openai` | **YES — needed for LLM integration** |
| `python-telegram-bot` | **YES — needed for trade alerts** |
| `prometheus-client` | **YES — needed for metrics** |
| `rich` | **YES — needed for CLI dashboard** |
| `uvloop` | **MAYBE — 2-4x async speedup on Linux** |
| `pydantic-settings` | **MAYBE — better env var handling** |

### What's Missing Entirely

| Dependency | Purpose | Priority |
|---|---|---|
| `aiohttp` or `httpx` | Async HTTP for APIs | 🔴 Critical |
| `redis` | Caching, pub/sub, rate limiting | 🟠 High |
| `apscheduler` | Precise task scheduling | 🟠 High |
| `cachetools` | TTL cache for data feed | 🟡 Medium |
| `backtrader` or `vectorbt` | Backtesting engine | 🟠 High |
| `quantstats` | Performance analytics | 🟡 Medium |

---

## 10. Architecture Gaps

### What a Production Multi-Agent Trading System Needs

```
┌─────────────────────────────────────────────────────────────┐
│                    PRODUCTION ARCHITECTURE                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ WebSocket │  │ REST API │  │ Calendar │  │  News    │   │
│  │  (Ticks)  │  │ (Finnhub)│  │  Feed    │  │  Feed    │   │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘   │
│        │             │             │             │           │
│        └──────┬──────┴──────┬──────┴──────┬──────┘           │
│               ▼             ▼             ▼                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              EVENT BUS (Redis Streams)                │   │
│  └──────────────────────────────────────────────────────┘   │
│               │             │             │                  │
│        ┌──────┴──────┐ ┌───┴───┐ ┌──────┴──────┐           │
│        ▼             ▼ ▼       ▼ ▼             ▼           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Trend   │  │Structure │  │  Macro   │  │ Portfolio│   │
│  │  Agent   │  │  Agent   │  │  Agent   │  │  Agent   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │             │             │             │           │
│       └──────┬──────┴──────┬──────┴──────┬──────┘           │
│              ▼             ▼             ▼                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           CONFLUENCE AGGREGATOR                       │   │
│  └──────────────────────────────────────────────────────┘   │
│              │                                              │
│              ▼                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Guardian │  │  Risk    │  │Execution │                  │
│  │  Agent   │  │  Agent   │  │  Agent   │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │             │             │                         │
│       └──────┬──────┴──────┬──────┘                         │
│              ▼             ▼                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Trade Journal│  │  Metrics    │  │  Alerting   │      │
│  │  (SQLite)    │  │ (Prometheus)│  │  (Telegram) │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### What's Missing from Current Architecture

| Layer | Current State | What's Needed |
|---|---|---|
| **Event bus** | Dead code | Redis Streams or in-process asyncio.Queue with proper pub/sub |
| **Agent parallelism** | Sequential | `asyncio.TaskGroup` — run all analysis agents in parallel per pair |
| **Data streaming** | Batch polling | WebSocket connection to broker for real-time ticks |
| **State management** | In-memory dict | Persistent state store with checkpoint/recovery |
| **Circuit breakers** | Guardian only | Per-agent circuit breakers, global kill-switch |
| **Rate limiting** | None | Token bucket for API calls (Finnhub, LLM) |
| **Retry logic** | None | Exponential backoff with jitter for all external calls |
| **Health monitoring** | None | HTTP health endpoint, heartbeat monitoring |
| **Graceful shutdown** | Basic signal handler | Drain in-flight trades, close positions, persist state |

---

## 11. Revised Tech Stack Recommendation

### Production-Ready Stack

```
CORE RUNTIME
├── Python 3.11+ (current ✓)
├── asyncio + anyio (structured concurrency)
├── uvloop (Linux performance boost)
└── TaskGroup for parallel agents

DATA LAYER
├── Polars (replace Pandas — 10-100x faster)
├── DuckDB (OHLCV storage + analytics)
├── SQLite + aiosqlite (trade journal, knowledge base)
├── Redis (caching, pub/sub, rate limiting)
└── WebSocket (real-time market data)

AGENT FRAMEWORK
├── Pydantic v2 (type validation ✓)
├── structlog (logging ✓, add JSON renderer)
├── openai / litellm (LLM integration)
└── Custom agent protocol (keep current design)

BROKER INTEGRATION
├── MetaTrader5 Python package (native, not RPyC)
├── RPyC fallback (for Wine/Linux bridge)
├── FIX protocol (for institutional brokers)
└── PaperBroker (proper simulation engine)

OBSERVABILITY
├── prometheus_client (metrics)
├── python-telegram-bot (alerts)
├── Grafana + Prometheus (dashboards)
└── structlog JSON → Loki/ELK (log aggregation)

BACKTESTING
├── vectorbt or backtrader (strategy testing)
├── quantstats (performance analytics)
└── walk-forward validation (custom)

CONFIGURATION
├── Pydantic Settings (current ✓)
├── YAML + env vars (current ✓)
├── python-dotenv (secrets in dev)
└── Watchdog (hot-reload)

SECURITY
├── rpyc>=6.0 (RPyC hardening ✓)
├── detect-secrets (secrets scanning)
└── pip-audit (dependency scanning)
```

### Migration Priority

| Phase | Weeks | What | Impact |
|---|---|---|---|
| **Phase 1: Data** | 1-2 | Replace Pandas with Polars, vectorize hot paths | 10-100x speedup |
| **Phase 2: Concurrency** | 2-3 | `asyncio.TaskGroup` for parallel agents, event-driven pipeline | Real-time processing |
| **Phase 3: Persistence** | 3-4 | SQLite trade journal, state recovery, knowledge base | Reliability |
| **Phase 4: Observability** | 4-5 | Prometheus metrics, Telegram alerts, health endpoints | Production monitoring |
| **Phase 5: LLM** | 5-6 | OpenAI integration for fundamental narration | Intelligence |
| **Phase 6: Backtesting** | 6-8 | Vectorbt integration, walk-forward validation | Strategy validation |

---

## 12. Benchmark Expectations

### Current vs Target Performance

| Metric | Current (Estimated) | Target | Gap |
|---|---|---|---|
| **Cycle time** (5 pairs × 7 agents) | ~5-10 seconds (sequential) | <500ms (parallel) | 10-20x |
| **Data fetch** (200 bars × 5 pairs) | ~2-5 seconds (batch) | <100ms (cached/streaming) | 20-50x |
| **Indicator compute** (per pair) | ~100-500ms (Python loops) | <10ms (vectorized) | 10-50x |
| **Order execution** | ~50-100ms (RPyC) | <5ms (native MT5) | 10-20x |
| **Memory usage** | ~200MB (Pandas) | <50MB (Polars) | 4x |
| **Startup time** | ~2-5 seconds | <1 second | 2-5x |

---

## 13. Decision Matrix: Keep vs Replace

| Component | Decision | Reasoning |
|---|---|---|
| `structlog` | ✅ **KEEP** | Excellent choice, add JSON renderer |
| `pydantic` | ✅ **KEEP** | Perfect for type validation, already well-used |
| `numpy` | ✅ **KEEP** | Foundation for all numerical computation |
| `pyyaml` | ✅ **KEEP** | Config loading |
| `rpyc` | ✅ **KEEP** | Needed for MT5/Wine bridge |
| `pandas` | 🔄 **REPLACE with Polars** | 10-100x faster, better API, already declared |
| `scipy` | ✅ **KEEP** | Needed for econometrics |
| `statsmodels` | ✅ **KEEP** | ARIMA, cointegration, ADF |
| `arch` | ✅ **KEEP** | GARCH models |
| `scikit-learn` | ✅ **KEEP** | PCA, clustering |
| `TA-Lib` | ✅ **KEEP** | Fast indicator computation |
| `aiosqlite` | ✅ **KEEP** | Trade journal persistence |
| `sqlalchemy` | ✅ **KEEP** | Database ORM |
| `aiohttp` | ➕ **ADD** | Async HTTP for APIs |
| `httpx` | ➕ **ADD** | Modern async HTTP client |
| `openai` | ➕ **ADD** | LLM integration |
| `python-telegram-bot` | ➕ **ADD** | Trade alerts |
| `prometheus-client` | ➕ **ADD** | Metrics |
| `redis` | ➕ **ADD** | Caching, pub/sub |
| `polars` | ➕ **ADD** | Fast data processing |
| `uvloop` | ➕ **ADD** | Async performance |

---

## Verdict

The current tech stack is a **well-intentioned prototype** with good foundational choices (Pydantic, structlog, asyncio) but critical gaps for production use:

1. **No parallelism** — agents run sequentially
2. **No real-time data** — 60-second polling
3. **No LLM integration** — not actually "smart"
4. **No persistence** — JSON files, no recovery
5. **No observability** — console logging only
6. **No backtesting** — can't validate strategies

The good news: the architectural design (7-agent pipeline, pure functions, type-validated models) is sound. The foundation is solid. What's missing is the **infrastructure layer** beneath the agents.

**Bottom line:** This is a v0.1 prototype. With 6-8 weeks of focused infrastructure work (Phases 1-6 above), it can become a production-grade system. The agent logic is the easy part — the plumbing is what needs work.

---

*End of Tech Stack Assessment*
