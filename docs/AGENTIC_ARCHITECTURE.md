# VMPM Architecture v0.2 — Agentic Adaptation

**From OpenClaw / Hermes / Modern Agent Patterns → Trading System**

Date: 2026-06-17  
Status: Design proposal  
Supersedes: ARCHITECTURE.md where conflicts exist

---

## Why This Document Exists

VMPM v0.1 was designed as a **linear pipeline** — 12 phases, sequential execution, one orchestrator driving everything. That works for a prototype. But a real-money trading system needs patterns that modern agent platforms (OpenClaw, Hermes, LangGraph) have battle-tested:

- **Durable orchestration** that survives crashes and can resume
- **Parallel agent execution** instead of serial bottleneck
- **Heartbeat-driven health monitoring** instead of fire-and-forget
- **Skill-based modularity** instead of monolithic agents
- **Memory architecture** for learning and drift detection
- **Safety layer** with policy-filtered tool calls
- **Subagent delegation** for parallel analysis

This document maps each pattern to VMPM's specific needs.

---

## 1. TaskFlow → Durable Trade Orchestration

### The Problem

VMPM v0.1's `Orchestrator.run_cycle()` is a single async function. If it crashes mid-cycle, all state is lost. There's no way to know if an order was sent but not confirmed, or if a kill-switch tripped during execution.

### The Pattern (from OpenClaw TaskFlow)

OpenClaw's TaskFlow is a durable orchestrator for multi-step work:

```
createManaged → runTask → setWaiting → resume → finish/fail
```

Key properties:
- **One owner session** per flow — clear accountability
- **Persisted state** (`stateJson`) — survives restarts
- **Revision tracking** — conflict-safe mutations
- **Waiting states** — explicitly models "waiting for external input"
- **Child tasks** — linked sub-work with parent orchestration

### VMPM Adaptation: `TradeFlow`

```python
# core/trade_flow.py

@dataclass
class TradeFlow:
    """Durable trade orchestration. Survives crashes. Resumes on restart."""
    flow_id: str                    # UUID, unique per trade attempt
    symbol: str
    state: TradeFlowState           # enum: ANALYZING, WAITING_ZONE, CONFIRMING, SIZING, EXECUTING, MANAGING, CLOSED
    current_phase: str              # which agent is running
    state_json: dict                # persisted analysis results, partial verdicts
    revision: int                   # conflict-safe mutation counter
    created_at: datetime
    updated_at: datetime
    owner_session: str              # which orchestrator instance owns this
    child_tasks: list[str]          # IDs of spawned sub-tasks (news fetch, LLM narrate)
    wait_json: dict | None          # {"kind": "price_zone", "zone": 1.0850, "symbol": "EURUSD"}

class TradeFlowManager:
    """Persists TradeFlow state to DuckDB. Resumes on restart."""

    def create(self, symbol: str) -> TradeFlow: ...
    def run_phase(self, flow_id: str, phase: str, agent_fn: Callable) -> TradeFlow: ...
    def set_waiting(self, flow_id: str, wait_json: dict) -> TradeFlow: ...
    def resume(self, flow_id: str) -> TradeFlow: ...
    def finish(self, flow_id: str, result: dict) -> TradeFlow: ...
    def fail(self, flow_id: str, reason: str) -> TradeFlow: ...
    def cancel(self, flow_id: str, reason: str) -> TradeFlow: ...
    def active_flows(self) -> list[TradeFlow]: ...
```

### What This Fixes

| v0.1 Problem | TaskFlow Solution |
|---|---|
| Crash mid-cycle loses all state | `state_json` persisted to DuckDB after each phase |
| No way to know if order was sent | `EXECUTING` state with `child_task` for order_send |
| Can't resume after restart | `active_flows()` on startup, resume from last persisted phase |
| No audit trail | Every state transition logged with revision |
| Can't cancel in-flight trades | `cancel()` with reason, Guardian can cancel any flow |

### Implementation Priority: **P0** (before live trading)

---

## 2. Skill-Based Agent Architecture

### The Problem

VMPM v0.1 has 17 agents, each a class with an `analyze()` method. But they're tightly coupled — the orchestrator imports all of them, knows their names, and calls them in a fixed order. Adding a new agent means editing `main.py`.

### The Pattern (from OpenClaw Skills)

OpenClaw skills are:
- **Self-contained** — each has its own `SKILL.md` with interface contract
- **Discoverable** — listed in a registry, loaded on demand
- **Composable** — one skill can invoke another
- **Versioned** — each skill has its own lifecycle

### VMPM Adaptation: Agent Skills

```
agents/
├── __init__.py              # Agent registry + discovery
├── _base.py                 # Agent base class (exists)
├── skills/
│   ├── trend/
│   │   ├── SKILL.md         # Interface contract
│   │   ├── agent.py         # TrendAgent
│   │   ├── indicators.py    # MA cross, HH/HL
│   │   └── tests.py
│   ├── structure/
│   │   ├── SKILL.md
│   │   ├── agent.py
│   │   ├── order_blocks.py
│   │   └── tests.py
│   ├── fundamental/
│   │   ├── SKILL.md
│   │   ├── agent.py
│   │   ├── taylor_rule.py
│   │   ├── narrator.py      # LLM narrator (future)
│   │   └── tests.py
│   ├── guardian/
│   │   ├── SKILL.md
│   │   ├── agent.py
│   │   ├── killswitches.py  # All kill-switch logic
│   │   ├── heartbeat.py
│   │   └── tests.py
│   └── ...
```

Each `SKILL.md` defines:
```markdown
# TrendAgent Skill

## Interface
- Input: `dict[str, pd.DataFrame]` (OHLCV per timeframe)
- Output: `Verdict` (direction, strength, rationale)
- Dependencies: none (pure function of OHLCV)

## Kill conditions
- Returns `NEUTRAL` on insufficient data (< 200 bars)
- Never raises exceptions (returns ERROR verdict instead)

## Performance budget
- Must complete in < 50ms per symbol
```

### What This Fixes

| v0.1 Problem | Skill Architecture |
|---|---|
| All agents imported in main.py | Registry discovers agents at runtime |
| Can't test agents in isolation | Each skill has own tests, own interface |
| Adding agent = editing orchestrator | Register new skill, orchestrator auto-discovers |
| No interface contracts | SKILL.md is the contract, validated at startup |

### Implementation Priority: **P1** (refactor after v0.1 ships)

---

## 3. Heartbeat-Driven Health Monitoring

### The Problem

VMPM v0.1's Guardian emits a heartbeat every 5s, but it's a simple `asyncio.Event` that nobody checks. The security audit found `check_heartbeat()` exists but is never called.

### The Pattern (from OpenClaw)

OpenClaw's heartbeat system:
- **Periodic poll** — agent receives a heartbeat message on a schedule
- **Stateful checks** — tracks `lastChecks` in a JSON state file
- **Proactive actions** — on heartbeat, check emails, calendar, system health
- **Quiet when healthy** — `HEARTBEAT_OK` when nothing to report
- **Loud when not** — proactive alerts on anomalies

### VMPM Adaptation: Multi-Layer Heartbeat

```python
# core/heartbeat.py

class HeartbeatManager:
    """Three-layer heartbeat system for a trading bot."""

    def __init__(self, config: HeartbeatConfig):
        self.layers = {
            "guardian": HeartbeatLayer(interval=5.0, max_age=30.0),
            "broker": HeartbeatLayer(interval=10.0, max_age=60.0),
            "market_data": HeartbeatLayer(interval=15.0, max_age=45.0),
        }
        self._state_file = Path("data/heartbeat_state.json")
        self._state = self._load_state()

    async def run(self):
        """Main heartbeat loop. Runs forever."""
        while True:
            now = datetime.now(timezone.utc)
            for name, layer in self.layers.items():
                if (now - layer.last_beat).total_seconds() > layer.interval:
                    status = await layer.check()
                    self._state[name] = {"last": now.isoformat(), "status": status}
                    if status == "STALE":
                        await self._on_stale(name, layer)
            self._save_state()
            await asyncio.sleep(1.0)

    async def _on_stale(self, layer_name: str, layer: HeartbeatLayer):
        """What happens when a layer goes stale."""
        if layer_name == "guardian":
            # CRITICAL: Guardian dead → flatten everything
            await self._emergency_flatten("Guardian heartbeat stale")
        elif layer_name == "broker":
            # HIGH: Broker dead → halt new entries, attempt reconnect
            await self._halt_entries("Broker heartbeat stale")
        elif layer_name == "market_data":
            # MEDIUM: Data stale → switch to degraded mode
            await self._degrade_mode("Market data stale")

class HeartbeatLayer:
    """One heartbeat layer with check/emit/age logic."""
    interval: float      # How often to emit
    max_age: float       # How old before considered stale
    last_beat: datetime
    last_check: datetime
    consecutive_failures: int

    async def check(self) -> str:
        """Returns OK, STALE, or DEGRADED."""
        ...
```

### Heartbeat State File

```json
{
  "guardian": {"last": "2026-06-17T18:30:00Z", "status": "OK", "consecutive_failures": 0},
  "broker": {"last": "2026-06-17T18:29:55Z", "status": "OK", "consecutive_failures": 0},
  "market_data": {"last": "2026-06-17T18:29:50Z", "status": "OK", "consecutive_failures": 0},
  "last_flatten_reason": null,
  "last_halt_reason": null,
  "checks_today": {"flatten": 0, "halt": 0, "degrade": 0}
}
```

### What This Fixes

| v0.1 Problem | Heartbeat System |
|---|---|
| `check_heartbeat()` never called | Three layers, all actively checked |
| No broker health monitoring | Dedicated broker heartbeat layer |
| No market data freshness check | Market data heartbeat layer |
| No state persistence | JSON state file survives restart |
| Silent failures | Escalating: OK → DEGRADED → STALE → EMERGENCY_FLATTEN |

### Implementation Priority: **P0** (before live trading)

---

## 4. Subagent Delegation → Parallel Analysis

### The Problem

VMPM v0.1 runs agents sequentially:
```python
for pair in pairs:
    await self.agents["macro"].process(context)    # 200ms
    await self.agents["structure"].process(context) # 150ms
    await self.agents["sr"].process(context)        # 100ms
    ...
```

For 5 pairs × 9 agents = 45 sequential calls. At ~100ms each = 4.5 seconds per cycle. On M15 candles that's fine, but it's wasteful — most agents are independent.

### The Pattern (from OpenClaw Subagents)

OpenClaw spawns subagents for parallel work:
- Each subagent runs in its own context
- Results auto-announce back to the parent
- Parent can yield and wait for completion
- Failed subagents don't crash the parent

### VMPM Adaptation: Parallel Agent Fan-Out

```python
# core/parallel.py

class AgentFanOut:
    """Run independent agents in parallel. Collect results with timeout."""

    def __init__(self, agents: dict[str, Agent], timeout_ms: int = 5000):
        self.agents = agents
        self.timeout = timeout_ms / 1000

    async def run_phase(
        self,
        phase_agents: list[str],
        context: dict[str, Any],
    ) -> dict[str, AgentReport]:
        """Run specified agents in parallel. Return results dict."""
        tasks = {}
        for name in phase_agents:
            if name in self.agents:
                tasks[name] = asyncio.create_task(
                    self._run_with_timeout(name, context)
                )

        results = {}
        done, pending = await asyncio.wait(
            tasks.values(),
            timeout=self.timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        for name, task in tasks.items():
            if task in done:
                results[name] = task.result()
            else:
                task.cancel()
                results[name] = AgentReport(
                    agent_name=name, signal="TIMEOUT",
                    reasoning=f"Agent {name} exceeded {self.timeout}s budget"
                )

        return results

    async def _run_with_timeout(self, name: str, context: dict) -> AgentReport:
        try:
            return await asyncio.wait_for(
                self.agents[name].process(context),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            return AgentReport(agent_name=name, signal="TIMEOUT")
        except Exception as e:
            return AgentReport(agent_name=name, signal="ERROR", reasoning=str(e))
```

### Pipeline Phases (Parallel Groups)

```
Phase 1 (parallel):  [macro, currency, session]           — independent fundamentals
Phase 2 (parallel):  [structure, sr, institutional]        — independent technicals  
Phase 3 (sequential): opportunity                          — depends on zones from phase 2
Phase 4 (parallel):  [momentum, price_action]              — independent confirmations
Phase 5 (sequential): thesis → devil → cio                 — sequential decision chain
Phase 6 (sequential): risk → execution                     — must be sequential
```

**Estimated speedup:** 5 pairs × 6 parallel groups (instead of 9 sequential) = ~60% faster.

### Implementation Priority: **P1** (after v0.1, before scaling to 28 pairs)

---

## 5. Memory Architecture → Learning & Drift Detection

### The Problem

VMPM v0.1 has `LearningAgent` and `KnowledgeBase` but no actual memory system. The SPRT, beta-posterior, and KS-drift kill-switches need historical trade outcomes, but there's no journal to query.

### The Pattern (from OpenClaw Memory)

OpenClaw uses a two-tier memory:
- **Daily logs** (`memory/YYYY-MM-DD.md`) — raw events, decisions, observations
- **Long-term memory** (`MEMORY.md`) — curated insights, lessons, patterns

### VMPM Adaptation: Trade Memory System

```python
# memory/trade_memory.py

class TradeMemory:
    """Two-tier memory for trading system learning."""

    def __init__(self, journal_path: Path, memory_path: Path):
        self.journal = TradeJournal(journal_path)    # DuckDB — every trade, every fill
        self.memory = StrategyMemory(memory_path)    # YAML — curated lessons

    # --- Daily Journal (raw, every event) ---

    async def record_trade(self, trade: TradeRecord):
        """Record every trade with full context."""
        ...

    async def record_decision(self, flow_id: str, phase: str, decision: dict):
        """Record every agent decision for post-mortem."""
        ...

    async def record_killswitch(self, switch: str, reason: str, state: dict):
        """Record every kill-switch activation."""
        ...

    # --- Long-Term Memory (curated, periodic review) ---

    async def review_period(self, start: date, end: date) -> PeriodReview:
        """Analyze a period's trades. Extract lessons."""
        trades = await self.journal.get_trades(start, end)
        return PeriodReview(
            total_trades=len(trades),
            win_rate=...,
            avg_rr=...,
            best_session=...,
            worst_session=...,
            lessons=self._extract_lessons(trades),
        )

    async def update_memory(self, review: PeriodReview):
        """Curate lessons into long-term memory."""
        ...

    # --- Drift Detection (feeds SPRT, KS, beta-posterior) ---

    async def compute_live_stats(self, window_days: int = 30) -> LiveStats:
        """Compute live trading statistics for kill-switch evaluation."""
        trades = await self.journal.get_recent(window_days)
        returns = [t.pnl / t.risk_amount for t in trades]
        return LiveStats(
            n=len(trades),
            mean_r=np.mean(returns),
            std_r=np.std(returns),
            win_rate=sum(1 for r in returns if r > 0) / len(returns),
            expectancy=np.mean(returns),
        )

    async def backtest_distribution(self) -> np.ndarray:
        """Load backtest return distribution for KS comparison."""
        ...

class StrategyMemory:
    """Curated long-term memory. YAML file, periodically reviewed."""

    def __init__(self, path: Path):
        self.path = path
        self.data = yaml.safe_load(path.read_text()) if path.exists() else {
            "lessons": [],
            "patterns": {},
            "regime_notes": {},
            "session_performance": {},
            "last_review": None,
        }

    def add_lesson(self, lesson: str, context: dict):
        self.data["lessons"].append({
            "date": datetime.now(timezone.utc).isoformat(),
            "lesson": lesson,
            "context": context,
        })
        self._save()

    def get_session_bias(self, session: str) -> dict:
        """What does memory say about trading this session?"""
        return self.data["session_performance"].get(session, {})
```

### What This Fixes

| v0.1 Problem | Memory System |
|---|---|
| SPRT/beta-posterior have no data | `compute_live_stats()` feeds from journal |
| KS drift test has no baseline | `backtest_distribution()` loads reference |
| No post-mortem capability | `record_decision()` captures every agent's reasoning |
| No session learning | `session_performance` tracks per-session win rates |
| No strategy evolution | Periodic `review_period()` + `update_memory()` |

### Implementation Priority: **P0** (journal at least, before live trading)

---

## 6. Safety Layer → Policy-Filtered Execution

### The Problem

VMPM v0.1's `ExecutionAgent` directly calls `mt5.order_send()`. There's no policy layer between "decision made" and "order sent". The Guardian check happens before execution, but the actual `order_send` call has no guardrails.

### The Pattern (from OpenClaw Tool Policy)

OpenClaw filters tool calls through policy:
- Every tool call passes through a policy filter
- Sensitive operations require approval
- Destructive actions use `trash` over `rm`
- Allow-once is single-command only

### VMPM Adaptiation: Execution Policy Layer

```python
# core/execution_policy.py

class ExecutionPolicy:
    """Policy layer between decision and order_send. Nothing bypasses this."""

    def __init__(self, config: RiskConfig, guardian: GuardianState):
        self.config = config
        self.guardian = guardian
        self._daily_orders: list[OrderRecord] = []

    async def evaluate(self, request: OrderRequest, context: dict) -> PolicyDecision:
        """Evaluate an order request against all policies. Returns ALLOW or DENY."""

        checks = [
            self._check_max_lot_size(request),
            self._check_daily_order_count(),
            self._check_position_count(context),
            self._check_duplicate_order(request, context),
            self._check_guardian_heartbeat(),
            self._check_spread(context),
            self._check_news_blackout(request.symbol),
            self._check_sl_tp_sanity(request),
            self._check_live_mode(),
        ]

        results = await asyncio.gather(*checks)
        denials = [r for r in results if r.denied]

        if denials:
            return PolicyDecision(
                allowed=False,
                reason="; ".join(d.reason for d in denials),
                checks_run=len(checks),
                checks_failed=len(denials),
            )

        return PolicyDecision(allowed=True, checks_run=len(checks))

    async def _check_max_lot_size(self, req: OrderRequest) -> CheckResult:
        max_lot = self.config.max_lot_size  # NEW: hard cap
        if req.volume > max_lot:
            return CheckResult(denied=True, reason=f"Lot {req.volume} > max {max_lot}")
        return CheckResult(denied=False)

    async def _check_guardian_heartbeat(self) -> CheckResult:
        if not self.guardian.last_heartbeat:
            return CheckResult(denied=True, reason="No Guardian heartbeat ever received")
        age = (datetime.now(timezone.utc) - self.guardian.last_heartbeat).total_seconds()
        if age > self.guardian.heartbeat_timeout:
            return CheckResult(denied=True, reason=f"Guardian heartbeat {age:.0f}s old (max {self.guardian.heartbeat_timeout})")
        return CheckResult(denied=False)

    async def _check_live_mode(self) -> CheckResult:
        """Triple-confirm: env + CLI flag + daily interactive."""
        if os.getenv("VMPM_MODE") != "live":
            return CheckResult(denied=True, reason="VMPM_MODE != live")
        if not self._live_cli_flag:
            return CheckResult(denied=True, reason="--live flag not set")
        if not self._daily_confirmation:
            return CheckResult(denied=True, reason="Daily interactive confirmation not received")
        return CheckResult(denied=False)
```

### The Golden Rule

```python
# broker/mt5.py — the ONLY place order_send is called

async def place_order(self, request: OrderRequest, policy: ExecutionPolicy) -> OrderResult:
    """Every order must pass through policy. No exceptions."""
    decision = await policy.evaluate(request, self._context)
    if not decision.allowed:
        logger.warning("order_denied_by_policy", reason=decision.reason, symbol=request.symbol)
        return OrderResult(success=False, error=f"Policy denied: {decision.reason}")

    # Only NOW send to MT5
    result = self._mt5.order_send(request.to_mt5_format())
    ...
```

### What This Fixes

| v0.1 Problem | Execution Policy |
|---|---|
| No max lot size cap | `_check_max_lot_size()` |
| No duplicate order detection | `_check_duplicate_order()` |
| Guardian heartbeat not checked | `_check_guardian_heartbeat()` |
| Live mode not enforced at execution | `_check_live_mode()` triple-confirm |
| No daily order count limit | `_check_daily_order_count()` |
| No spread check at execution | `_check_spread()` |

### Implementation Priority: **P0** (before live trading)

---

## 7. Inbound Context → Market Context Metadata

### The Problem

VMPM agents receive raw context dicts with no metadata about data freshness, source reliability, or confidence.

### The Pattern (from OpenClaw Inbound Context)

OpenClaw attaches trusted metadata to every inbound message:
```json
{
  "schema": "openclaw.inbound_meta.v2",
  "channel": "webchat",
  "provider": "webchat",
  "chat_type": "direct"
}
```

This metadata is **trusted** (generated by the system, not the user). Agents use it to make routing decisions.

### VMPM Adaptiation: Market Context Envelope

```python
# core/market_context.py

@dataclass
class MarketContext:
    """Trusted metadata about market data. Attached to every agent call."""

    # Data freshness
    data_timestamp: datetime          # When was the data last updated?
    data_age_seconds: float           # How old is it?
    data_source: str                  # "mt5_live", "mt5_cached", "synthetic"

    # Broker state
    broker_connected: bool
    broker_latency_ms: float
    broker_last_heartbeat: datetime

    # System state
    guardian_alive: bool
    kill_switches_active: list[str]   # ["daily_loss", "spread_cap"]
    mode: str                         # "paper", "live"

    # Versioning
    git_sha: str
    settings_hash: str
    run_id: str

    def is_stale(self, max_age: float = 30.0) -> bool:
        return self.data_age_seconds > max_age

    def is_degraded(self) -> bool:
        return (
            self.data_source != "mt5_live" or
            not self.broker_connected or
            not self.guardian_alive or
            len(self.kill_switches_active) > 0
        )
```

### Usage in Agents

```python
class TrendAgent(Agent):
    async def analyze(self, context: dict) -> AgentReport:
        ctx: MarketContext = context["market_context"]

        if ctx.is_stale(max_age=60):
            return AgentReport(signal="STALE", reasoning="Data too old")

        if ctx.is_degraded():
            # Reduce confidence when system is degraded
            confidence_multiplier = 0.5
        else:
            confidence_multiplier = 1.0

        # ... normal analysis, scaled by confidence_multiplier
```

### Implementation Priority: **P1** (after v0.1)

---

## 8. Cron + Heartbeat → Scheduled Market Checks

### The Problem

VMPM v0.1 runs a single loop: analyze → sleep 60s → repeat. It doesn't know about trading sessions, news calendars, or scheduled events.

### The Pattern (from OpenClaw Cron + Heartbeat)

OpenClaw uses:
- **Cron jobs** for exact-timing tasks ("check calendar at 9am")
- **Heartbeat** for periodic batch checks ("every 30 min, check email + calendar + weather")

### VMPM Adaptiation: Session-Aware Scheduling

```python
# core/scheduler.py

class TradingScheduler:
    """Session-aware scheduler. Knows when markets are open, when news hits."""

    def __init__(self, config: SessionConfig):
        self.sessions = config.sessions
        self.news_calendar = NewsCalendar()

    async def run(self):
        while True:
            now = datetime.now(timezone.utc)
            active = self.active_sessions(now)

            if not active:
                # Market closed — low-frequency checks only
                await self._run_cadence("idle", interval=300)  # 5 min
            else:
                # Market open — high-frequency analysis
                upcoming_news = self.news_calendar.next_high_impact(minutes=30)
                if upcoming_news:
                    # Pre-news: slow down, prepare blackout
                    await self._run_cadence("pre_news", interval=30)
                else:
                    # Normal trading
                    await self._run_cadence("active", interval=15)  # 15s

    def active_sessions(self, now: datetime) -> list[str]:
        """Which trading sessions are currently open?"""
        active = []
        for name, (open_h, close_h) in self.sessions.items():
            if open_h <= now.hour < close_h:
                active.append(name)
        return active
```

### What This Fixes

| v0.1 Problem | Scheduler |
|---|---|
| Same 60s loop whether market open or closed | Session-aware cadence |
| No pre-news preparation | 30s cadence before high-impact news |
| Wastes CPU when market closed | 5-min idle cadence |
| No session-aware analysis | Agents know which session is active |

### Implementation Priority: **P1** (after v0.1)

---

## 9. Spike Pattern → Strategy Validation

### The Problem

VMPM has no way to quickly test a hypothesis before committing to a strategy change.

### The Pattern (from OpenClaw Spike)

Spike pattern: Question → Research → Build minimal → Stress test → Verdict

### VMPM Adaptiation: Strategy Spikes

```python
# spikes/runner.py

class StrategySpike:
    """Quick prototype to validate a strategy hypothesis."""

    def __init__(self, question: str):
        self.question = question
        self.workspace = Path(f"spikes/{slugify(question)}")

    async def run(self) -> SpikeVerdict:
        # 1. Load minimal data
        data = await self._load_data()

        # 2. Build smallest testable variant
        result = await self._test_hypothesis(data)

        # 3. Stress one edge case
        edge = await self._stress_test(result)

        # 4. Verdict
        return SpikeVerdict(
            question=self.question,
            verdict="VALIDATED" if result.significant else "INVALIDATED",
            evidence=result.stats,
            recommendation="ship" if result.significant else "avoid",
        )
```

### Example Spike Questions

- "Does RSI divergence add edge on EURUSD H1?"
- "Is the London-NY overlap really the best session?"
- "Does the order block definition actually predict reversals?"
- "Would a tighter SL (1.0 ATR instead of 2.0) improve Sharpe?"

### Implementation Priority: **P2** (nice-to-have)

---

## 10. Implementation Roadmap

### Phase 0: Fix Security Gaps (Week 1)
- [ ] Revoke GitHub PAT, purge from history
- [ ] Create `core/logging.py` with redaction
- [ ] Wire Guardian heartbeat into `guardian_guard()`
- [ ] Implement live-mode triple-confirm
- [ ] Add max lot size hard cap

### Phase 1: Agentic Core (Weeks 2-4)
- [ ] Implement `TradeFlow` (durable orchestration)
- [ ] Implement `HeartbeatManager` (three-layer)
- [ ] Implement `ExecutionPolicy` (policy layer)
- [ ] Implement `TradeMemory` (journal + stats)
- [ ] Wire SPRT/beta-posterior/KS from journal stats

### Phase 2: Performance & Scale (Weeks 5-8)
- [ ] Implement `AgentFanOut` (parallel execution)
- [ ] Implement `TradingScheduler` (session-aware)
- [ ] Implement `MarketContext` (metadata envelope)
- [ ] Refactor agents into skill-based architecture

### Phase 3: Intelligence (Weeks 9-12)
- [ ] Implement LLM narrator (with full sanitization)
- [ ] Implement `StrategySpike` framework
- [ ] Implement `StrategyMemory` (curated learning)
- [ ] Implement P&L export for KRA

---

## Summary: What Changes in v0.2

| Component | v0.1 | v0.2 (this doc) |
|---|---|---|
| Orchestration | Linear async loop | Durable TradeFlow with state persistence |
| Agent architecture | 17 monolithic classes | Skill-based, discoverable, composable |
| Health monitoring | Single asyncio.Event | Three-layer heartbeat with escalation |
| Execution | Direct order_send | Policy-filtered, triple-confirmed |
| Memory | None | Two-tier: journal (raw) + memory (curated) |
| Scheduling | Fixed 60s loop | Session-aware, news-aware cadence |
| Parallelism | Sequential per-pair | Parallel fan-out for independent agents |
| Context | Raw dict | Enriched MarketContext with metadata |
| Validation | None | Spike framework for hypothesis testing |

---

*This document is the architectural bridge between VMPM v0.1 (scaffold) and a production-grade agentic trading system. Each pattern is borrowed from systems that handle real users at scale — adapted for a system that handles real money.*
