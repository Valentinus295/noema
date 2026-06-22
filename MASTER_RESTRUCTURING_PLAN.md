# Noema Master Restructuring Plan

**Date:** 2026-06-17
**Based on:** 5 parallel analysis teams (Architecture, Quality, Security, Research, Modern Agent Patterns)
**Codebase:** ~6,700 lines Python, 40+ files, v0.1.0 scaffold

---

## Executive Summary

Noema is a well-designed multi-agent forex trading system with strong domain knowledge (ICT Smart Money Concepts, institutional-grade econometrics) but **poor execution**. The codebase has two incompatible architectures running in parallel, zero tests, broken imports, dead code, and only 3 of 11 documented kill-switches actually implemented. The good news: the design documents (ARCHITECTURE.md, SECURITY.md) are excellent — they just need to be implemented.

**The core problem:** The system was designed by review committees (security + quality) but the implementation diverged from the design. Two parallel codebases exist — a 17-agent system in `main.py` and a 7-agent system in `agents/orchestrator.py` — that never interact.

**The fix:** Pick one architecture (the 7-agent system from ARCHITECTURE.md), delete the dead code, adopt modern agentic patterns from OpenClaw/Claude Code/PydanticAI, and integrate NVIDIA NIM as the LLM brain.

---

## Part 1: Current State Assessment

### 🔴 Critical Issues (Must Fix Before Any Code Runs)

| # | Issue | Impact | Source |
|---|-------|--------|--------|
| 1 | **Two incompatible architectures** — 17-agent system in `main.py` vs 7-agent system in `agents/orchestrator.py` | System cannot function coherently | Architecture + Quality |
| 2 | **Broken imports** — `BrokerProtocol`, `Bar`, `Tick`, `AccountState`, `OrderRequest` imported but never defined | System cannot start | Quality |
| 3 | **Dual configuration** — `core/config.py` (1% risk) vs `core/settings.py` (25% risk) with conflicting values | Could blow up account | Quality |
| 4 | **Zero tests** — money-managing system with 0% coverage | Unacceptable financial risk | Quality |
| 5 | **GitHub PAT exposed** in `.git/config` remote URL | Credential compromise | Security |
| 6 | **Only 3 of 11 kill-switches implemented** | Documented safety controls don't exist | Security |

### 🟠 Major Issues (Must Fix Before Live Trading)

| # | Issue | Source |
|---|-------|--------|
| 7 | State machine bypassed (`advance(None)` in main.py) | Architecture |
| 8 | Message bus initialized but never used (dead code) | Architecture |
| 9 | 13 of 18 declared dependencies unused; 4 needed ones missing | Quality |
| 10 | Telegram auth documented but zero Telegram code exists | Security |
| 11 | Guardian heartbeat never wired into order approval flow | Security |
| 12 | Watchdog process doesn't exist | Security |
| 13 | structlog redaction processor missing (secrets could leak to logs) | Security |
| 14 | Live-mode triple-confirm not coded | Security |
| 15 | `settings_hash` and `git_sha` hardcoded to empty strings | Security |
| 16 | Database module orphaned (never instantiated) | Quality |
| 17 | Hardcoded absolute path `/home/valentinetech/noema/` in config | Quality |

### 🟢 What's Working Well

| Item | Assessment |
|------|------------|
| Domain knowledge | Excellent — ICT Smart Money Concepts, econometrics, institutional trading logic |
| Architecture docs | ARCHITECTURE.md is thorough, well-reviewed, security-conscious |
| Security docs | SECURITY.md covers all the right concerns |
| Config design | `settings.yaml` is comprehensive and well-structured |
| Econometrics engine | Best module — ARIMA, GARCH, cointegration, PCA, hypothesis testing |
| Tech stack choices | Python 3.11+, asyncio, uvloop, structlog, pydantic — all correct |
| Structured logging | structlog with agent binding — well done |

---

## Part 2: Target Architecture

### 2.1 Architecture Pattern: Modern Agentic Pipeline

Based on studying OpenClaw, Claude Code, Devin, and Strands SDK, the recommended pattern is:

**Deterministic Pipeline + Advisory LLM Layer + Supervisor Orchestration**

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUPERVISOR (Orchestrator)                      │
│  Modern agent loop: OBSERVE → THINK → PLAN → EXECUTE → REFLECT │
│  Delegates to specialist agents, synthesizes results             │
└──────────┬──────────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────┐
    │              LAYER 1: DATA COLLECTION (no LLM)               │
    │  MarketDataFeed → EconomicCalendar → SessionDetector         │
    └──────┬──────────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────┐
    │              LAYER 2: DETERMINISTIC ANALYSIS (no LLM)        │
    │  TrendAgent → StructureAgent → PortfolioAgent                │
    │  (MA-cross, HH/HL, S/R, order blocks, PCA, clustering)     │
    └──────┬──────────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────┐
    │              LAYER 3: CONFLUENCE + LLM ADVISORY              │
    │  ┌─────────────────────┐  ┌─────────────────────────────┐   │
    │  │ ConfluenceAgent     │→│ FundamentalBiasAgent (LLM)   │   │
    │  │ (deterministic      │  │ (NVIDIA NIM via PydanticAI) │   │
    │  │  RSI + candle +     │  │ Python computes score,      │   │
    │  │  weighted verdicts) │  │ LLM narrates only           │   │
    │  └─────────────────────┘  └─────────────────────────────┘   │
    └──────┬──────────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────┐
    │              LAYER 4: RISK + EXECUTION (no LLM)              │
    │  GuardianAgent (veto) → RiskAgent (SL/TP/size) → Execution  │
    └──────┬──────────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────┐
    │              LAYER 5: LEARNING (optional LLM)                │
    │  Journal (DuckDB) → KnowledgeBase → PerformanceAnalyzer     │
    └──────────────────────────────────────────────────────────────┘
```

### 2.2 Agent Roster (Final — 7 Agents + Orchestrator)

Per ARCHITECTURE.md (the reviewed, canonical design):

| Agent | Layer | LLM? | Responsibility |
|-------|-------|------|----------------|
| **Orchestrator** | Control | No | Supervisor agent — delegates, schedules, synthesizes |
| **TrendAgent** | Analysis | No | D1/H4/H1 trend via MA(50)/MA(200) + HH/HL or LH/LL |
| **StructureAgent** | Analysis | No | Session/D/W/M/Y highs+lows + ICT order blocks + retest |
| **FundamentalBiasAgent** | Analysis | **Advisory** | Python computes bias, LLM narrates (NVIDIA NIM) |
| **ConfluenceAgent** | Decision | Optional | Combines verdicts + RSI/candle sub-scorers + optional LLM review |
| **PortfolioAgent** | Risk | No | PCA factor exposure + currency-strength + hierarchical clustering |
| **RiskAgent** | Execution | No | SL/TP/position sizing + GARCH regime throttle |
| **ExecutionAgent** | Execution | No | MT5 order send/modify/close via RPyC |
| **GuardianAgent** | Safety | No | Pre-trade AND pre-order veto + all kill-switches |

**Delete:** All 17-agent files in `agents/` that don't match the 7-agent design. The following are dead code:
- `agents/macro.py`, `agents/currency.py`, `agents/institutional.py`, `agents/sr.py`
- `agents/session.py`, `agents/opportunity.py`, `agents/momentum.py`, `agents/price_action.py`
- `agents/thesis.py`, `agents/devil.py`, `agents/cio.py`, `agents/management.py`
- `agents/performance.py`, `agents/learning.py`

### 2.3 Modern Agent Pattern (from OpenClaw/Claude Code)

Each agent follows the **ReAct loop** pattern used by Claude Code, Cursor, and OpenClaw:

```python
class ModernAgent(ABC):
    """Base class for Noema agents — inspired by OpenClaw/Claude Code patterns."""
    
    name: str
    role: str
    tools: list[Tool]  # Typed tool definitions with JSON Schema
    
    async def run(self, context: PipelineContext) -> AgentReport:
        """Execute the agent loop."""
        # 1. OBSERVE — gather relevant data from context
        observation = self._observe(context)
        
        # 2. THINK — reason about what to do (deterministic or LLM)
        if self.needs_llm:
            plan = await self._think_with_llm(observation)
        else:
            plan = self._think_deterministic(observation)
        
        # 3. ACT — execute the plan
        result = await self._act(plan, context)
        
        # 4. VERIFY — check the result (safety pattern from OpenClaw)
        verified = self._verify(result)
        
        # 5. REPORT — structured output via Pydantic
        return AgentReport(
            agent=self.name,
            signal=verified.signal,
            confidence=verified.confidence,
            data=verified.data,
        )
```

### 2.4 NVIDIA NIM Integration

**Model Selection:**
| Agent | Model | Why |
|-------|-------|-----|
| FundamentalBiasAgent | `nvidia/llama-3.3-70b-instruct` | Complex financial reasoning, function calling |
| ConfluenceAgent (borderline review) | `nvidia/llama-3.1-8b-instruct` | Simple yes/no evaluation, fast |
| LearningAgent (pattern analysis) | `nvidia/llama-3.3-70b-instruct` | Deep analysis of trade outcomes |

**Integration via PydanticAI:**
```python
from pydantic_ai import Agent
from pydantic import BaseModel

class BiasNarration(BaseModel):
    """LLM output — narration only, cannot change numeric bias."""
    direction: Literal["bullish", "bearish", "neutral"]
    explanation: str = Field(max_length=2000)

# PydanticAI agent with NVIDIA NIM
narrator = Agent(
    'nvidia/llama-3.3-70b-instruct',
    result_type=BiasNarration,
    system_prompt="You are a forex analyst. Narrate the given bias score...",
)

# LLM is NEVER on the critical path
async def get_narration(bias_score: float, news: str) -> BiasNarration:
    result = await narrator.run(f"Bias score: {bias_score}. News: {news}")
    return result.data  # Pydantic-validated, guaranteed schema
```

**Caching:** Same market state → same LLM response. Cache by `(symbol, session, news_hash)` with 60s TTL.

### 2.5 Tech Stack (Final Recommendation)

| Component | Current | Recommended | Action |
|-----------|---------|-------------|--------|
| Python 3.11+ | ✅ | Keep | — |
| asyncio + uvloop | ✅ | Keep | — |
| pydantic | ✅ | Keep | — |
| structlog | ✅ | Keep | — |
| TA-Lib | ✅ | Keep | — |
| polars | Unused | Keep (use for backtesting) | Actually import it |
| duckdb | Unused | Use for journal + event log | Actually import it |
| prometheus-client | Unused | Wire up metrics | Implement |
| rich | Unused | Wire up CLI output | Implement |
| **PydanticAI** | — | **Add** | LLM interaction layer |
| **NVIDIA NIM** | — | **Add** | LLM provider |
| **Langfuse** | — | **Add** | LLM observability |
| **Docker Compose** | — | **Add** | Deployment |
| **GitHub Actions** | — | **Add** | CI/CD |
| pandas | Used | Replace with polars for backtesting | Migrate |
| aiohttp | Missing dep | Add to pyproject.toml | P0 fix |
| sqlalchemy | Implicit | Add explicit dep | P0 fix |
| aiosqlite | Missing dep | Add to pyproject.toml | P0 fix |

---

## Part 3: Implementation Plan

### Phase 0: Emergency Fixes (Week 1) — DO THIS FIRST

- [ ] **Revoke exposed GitHub PAT** — `ghp_KPWD7...` is in `.git/config`
- [ ] **Fix broken imports** — define `BrokerProtocol`, `Bar`, `Tick`, `AccountState`, `OrderRequest` in `core/types.py`
- [ ] **Add missing deps** to `pyproject.toml`: `aiohttp`, `sqlalchemy[asyncio]`, `aiosqlite`, `pandas`
- [ ] **Delete dead 17-agent code** — remove all files in `agents/` that aren't part of the 7-agent design
- [ ] **Unify configuration** — delete `core/config.py`, keep `core/settings.py` (Pydantic-based)
- [ ] **Fix `main.py`** — wire it through `agents/orchestrator.py` instead of the 17-agent sequential chain
- [ ] **Fix hardcoded path** in `config/settings.yaml`
- [ ] **Write import smoke tests** — just verify all modules can be imported without errors

### Phase 1: Foundation (Week 2-3)

- [ ] **Implement missing kill-switches** (currently only 3 of 11 exist):
  - [ ] Drawdown EWMA throttle/halt
  - [ ] Beta-posterior win-rate gate
  - [ ] SPRT sequential edge monitor
  - [ ] KS drift test
  - [ ] Guardian heartbeat → ExecutionAgent veto
  - [ ] Watchdog process
- [ ] **Implement Telegram control surface** (auth + commands)
- [ ] **Wire structlog redaction** for secrets
- [ ] **Implement `settings_hash` and `git_sha`** on journal rows
- [ ] **Write unit tests** for all agents, indicators, risk calculations
- [ ] **Set up CI/CD** — GitHub Actions with lint + test + security scan

### Phase 2: Modern Agent Pattern (Week 4-5)

- [ ] **Refactor agent base class** to follow ReAct loop pattern
- [ ] **Add PydanticAI dependency** and create NIM client wrapper
- [ ] **Implement FundamentalBiasAgent** with NVIDIA NIM narration
- [ ] **Implement decision caching** for LLM deduplication
- [ ] **Add Langfuse** for LLM tracing
- [ ] **Implement feature flags** for gradual LLM rollout
- [ ] **Add Prometheus metrics** (trade counter, P&L, agent latency, pipeline state)

### Phase 3: Data Layer (Week 6-7)

- [ ] **Implement DuckDB journal** (replace JSON knowledge base)
- [ ] **Implement event log** (append-only, for auditability)
- [ ] **Consolidate indicators** — merge `indicators/` and `analysis/technical.py`
- [ ] **Wire up polars** for data processing (currently declared but unused)
- [ ] **Implement message bus persistence** — DuckDB-backed event log

### Phase 4: Production Hardening (Week 8-10)

- [ ] **Docker Compose** setup (main + mt5bridge + prometheus + grafana)
- [ ] **MT5 disconnect handling** — reconnection + position reconciliation
- [ ] **RPyC hardening** — enforce `allow_public_attrs=False`, `allow_pickle=False`
- [ ] **Paper trading** for 30+ days with all kill-switches active
- [ ] **Backtesting engine** — walk-forward validation, permutation tests
- [ ] **Grafana dashboards** — trade journal, system health, LLM costs

### Phase 5: Live Trading (Week 11+)

- [ ] **FxPesa CMA confirmation** filed (regulatory launch gate)
- [ ] **Live-mode dual-confirm** implemented and tested
- [ ] **200+ paper trades** with Beta posterior P(WR≥0.45) > 0.95
- [ ] **KS-drift test** passing
- [ ] **Start with 0.25%/trade, 1.0% daily, 5 symbols**

---

## Part 4: Package Structure (Target)

```
noema/
├── noema/                          # Main package (CREATE THIS)
│   ├── __init__.py
│   ├── __main__.py                # CLI entry point
│   │
│   ├── agents/                    # 7 agents + orchestrator
│   │   ├── __init__.py
│   │   ├── base.py                # ModernAgent base (ReAct loop)
│   │   ├── tools.py               # Tool definitions + registry
│   │   ├── memory.py              # Agent memory (short/long-term)
│   │   ├── orchestrator.py        # Supervisor agent
│   │   ├── trend.py               # TrendAgent
│   │   ├── structure.py           # StructureAgent (S/R + order blocks)
│   │   ├── fundamental.py         # FundamentalBiasAgent (LLM advisory)
│   │   ├── confluence.py          # ConfluenceAgent (scoring)
│   │   ├── portfolio.py           # PortfolioAgent (PCA + clustering)
│   │   ├── risk.py                # RiskAgent (SL/TP/sizing)
│   │   ├── execution.py           # ExecutionAgent (MT5 orders)
│   │   └── guardian.py            # GuardianAgent (kill-switches)
│   │
│   ├── analysis/                  # Analysis modules
│   │   ├── __init__.py
│   │   ├── indicators.py          # All indicators (merged)
│   │   ├── econometrics.py        # ARIMA, GARCH, cointegration
│   │   ├── smc.py                 # Smart Money Concepts
│   │   └── candlestick.py         # Pattern detection
│   │
│   ├── broker/                    # Broker abstraction
│   │   ├── __init__.py
│   │   ├── protocol.py            # BrokerProtocol (typing.Protocol)
│   │   ├── mt5.py                 # MT5 via RPyC/Wine
│   │   ├── paper.py               # Simulated broker
│   │   └── reconciliation.py      # Position reconciliation
│   │
│   ├── llm/                       # LLM integration (NEW)
│   │   ├── __init__.py
│   │   ├── client.py              # NVIDIA NIM client (PydanticAI)
│   │   ├── cache.py               # Decision cache
│   │   └── guardrails.py          # Output validation
│   │
│   ├── journal/                   # Trade journal (NEW)
│   │   ├── __init__.py
│   │   ├── engine.py              # DuckDB journal engine
│   │   ├── event_log.py           # Append-only event log
│   │   └── models.py              # Trade, Knowledge, DailyStats
│   │
│   ├── data/                      # Data feeds
│   │   ├── __init__.py
│   │   ├── feed.py                # OHLCV data feed
│   │   └── calendar.py            # Economic calendar
│   │
│   ├── orchestration/             # Pipeline control
│   │   ├── __init__.py
│   │   ├── pipeline.py            # State machine
│   │   ├── message_bus.py         # Async pub/sub
│   │   └── context.py             # PipelineContext (shared state)
│   │
│   ├── types.py                   # Shared domain types (Pydantic)
│   ├── settings.py                # Unified Pydantic-settings config
│   ├── logging.py                 # Structured logging + event taxonomy
│   ├── metrics.py                 # Prometheus metrics
│   └── feature_flags.py           # Feature flag system
│
├── config/                        # Configuration files
│   ├── settings.yaml              # Strategy parameters
│   ├── symbols.yaml               # Symbol overrides
│   └── macro_priors.yaml          # Economic priors
│
├── scripts/                       # Operational scripts
│   ├── run_live.py                # Live trading entry point
│   ├── run_backtest.py            # Backtesting engine
│   ├── watchdog.py                # Process watchdog
│   └── backup_journal.sh          # Journal backup
│
├── tests/                         # Test suite (CREATE THIS)
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_indicators.py
│   │   ├── test_agents.py
│   │   ├── test_risk.py
│   │   ├── test_confluence.py
│   │   └── test_guardian.py
│   ├── integration/
│   │   ├── test_pipeline.py
│   │   └── test_broker.py
│   └── property/
│       └── test_indicator_invariants.py
│
├── docker/                        # Docker configs
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── mt5-wine/
│
├── .github/workflows/ci.yml       # CI/CD
├── pyproject.toml
├── README.md
├── CLAUDE.md                      # Delete (superseded by ARCHITECTURE.md)
├── docs/
│   ├── ARCHITECTURE.md            # Canonical architecture
│   ├── SECURITY.md
│   ├── ROADMAP.md
│   └── CURRICULUM_MAPPING.md
└── research/
    ├── REVIEWS.md
    └── SWARM_OUTPUTS.md
```

---

## Part 5: Key Architectural Decisions

### Decision 1: Keep Monolithic (Don't Go Microservices)
- Single-developer project, 6,700 lines. Microservices add network overhead with zero benefit.
- Keep everything in-process. Use the message bus for audit logging, not for inter-process communication.

### Decision 2: Deterministic-First, LLM-Advisory
- 90% of the system is deterministic (TA-Lib, econometrics, risk math).
- LLM only narrates fundamental bias and optionally reviews borderline setups.
- LLM is NEVER on the critical path. If NIM is down, the system trades on Python-computed bias.

### Decision 3: PydanticAI for LLM Layer (Not LangChain/LangGraph)
- LangChain: overkill, unstable APIs, rejected by the project's own reviews.
- CrewAI: wrong paradigm (LLM-first, Noema is deterministic-first).
- PydanticAI: type-safe, lightweight, Pydantic-native, model-agnostic. Perfect fit.

### Decision 4: NVIDIA NIM via OpenAI-Compatible Client
- NIM supports OpenAI-compatible API (function calling, structured output, JSON mode).
- Use `openai` SDK or PydanticAI directly. No need for LiteLLM proxy (adds latency).
- Model routing: Llama 3.3 70B for complex analysis, Llama 3.1 8B for simple tasks.

### Decision 5: DuckDB for Journal (Not SQLite/PostgreSQL)
- Columnar storage optimized for analytical queries on time-series data.
- Zero infrastructure. Already a declared dependency.
- Use for: trade journal, event log, backtest results, knowledge base.

### Decision 6: Keep Hand-Rolled Orchestration (No Framework)
- The 7-agent pipeline is a simple sequential chain with conditional branching.
- Adding LangGraph/CrewAI/AutoGen adds complexity without value.
- The orchestrator should be ~200 lines of clean Python, not a framework dependency.

### Decision 7: Docker Compose for Deployment
- Main container: Noema application
- MT5 bridge container: Wine + MT5 terminal + RPyC server
- Monitoring: Prometheus + Grafana
- Easy to develop, test, and deploy.

---

## Part 6: Cost Estimates

| Item | Monthly Cost |
|------|-------------|
| NVIDIA NIM API (Llama 3.3 70B) | $1-2 (free tier: 1000 calls/day) |
| VPS (Linux, 4GB RAM) | $10-20 |
| Windows VPS (MT5, if Wine unstable) | $10-30 |
| Grafana Cloud (free tier) | $0 |
| Langfuse (self-hosted) | $0 |
| GitHub Actions (free tier) | $0 |
| **Total** | **$11-52/month** |

---

## Part 7: Report Index

All detailed reports are available in the repository:

| Report | File | Lines | Focus |
|--------|------|-------|-------|
| Architecture & Tech Stack | `REPORT_ARCHITECTURE.md` | ~500 | Design evaluation, restructuring, dependency analysis |
| Code Quality Review | `REPORT_QUALITY.md` | 625 | Code smells, testing gaps, tech debt, metrics |
| Security Audit | `REPORT_SECURITY.md` | 481 | Kill-switches, LLM safety, secrets, compliance |
| Research (Frameworks + NIM) | `REPORT_RESEARCH.md` | 1,079 | PydanticAI, NIM integration, observability, deployment |
| Modern Agent Patterns | `REPORT_MODERN_AGENTS.md` | 1,325 | OpenClaw/Claude Code patterns, agent loop, function calling |

---

*This master plan synthesizes findings from 5 parallel analysis teams. Each report contains detailed implementation code, specific file locations, and line-by-line fix instructions.*
