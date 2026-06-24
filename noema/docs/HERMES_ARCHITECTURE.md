# Noema × Hermes Agent Architecture — Deep Adaptation

**Date:** 2026-06-17  
**Status:** Architectural design document  
**Source:** [Hermes Agent](https://hermes-agent.nousresearch.com) by NousResearch  
**Target:** Noema multi-agent trading system

---

## Why Hermes Patterns Matter for Trading

Hermes Agent isn't just another chatbot framework. It's a **production system** that handles:
- Tool dispatch with safety gating (approval callbacks for dangerous operations)
- Subagent delegation with isolated contexts (no cascade failures)
- Session persistence that survives crashes (SQLite + FTS5)
- Context compression when memory fills up (lossy summarization)
- Cron scheduling as first-class citizens (not shell crontab)
- Cross-platform gateway with auth (20+ messaging adapters)

Your trading system needs **every one of these patterns**, but for a different domain: instead of "user asks question, agent uses tools, returns answer", it's "market ticks, agents analyze, execute trade, manage position, survive crash."

This document maps Hermes internals to Noema's specific needs. Every pattern below is battle-tested in Hermes at scale — not theoretical.

---

## 1. Agent Loop → Trading Loop

### Hermes Pattern

Hermes's `AIAgent` (in `run_agent.py`) is a single orchestration class that:
1. Builds the system prompt (identity + tools + skills + memory + context)
2. Makes an API call (interruptible — user can cancel mid-flight)
3. Parses tool calls → dispatches them (sequential or concurrent)
4. Loops back to step 2 with tool results
5. On final text response: persist session, flush memory, return

Key properties:
- **Interruptible** — API calls and tool execution can be cancelled mid-flight
- **Budget-tracked** — iteration counter, stops at 90 turns
- **Fallback-aware** — if primary model fails (429, 5xx), try fallback providers
- **Compression-aware** — when context > 50%, summarize middle turns

### Noema Adaptation

```python
# core/trading_loop.py — Noema's equivalent of AIAgent.run_conversation()

class TradingLoop:
    """The core trading loop. Equivalent to Hermes's AIAgent.run_conversation().
    
    Instead of: user message → LLM → tool calls → response
    It does:    market tick → agents analyze → policy check → order send → manage
    """

    def __init__(
        self,
        broker: BrokerProtocol,
        agents: dict[str, Agent],
        policy: ExecutionPolicy,
        guardian: GuardianState,
        memory: TradeMemory,
        config: Settings,
    ):
        self.broker = broker
        self.agents = agents
        self.policy = policy
        self.guardian = guardian
        self.memory = memory
        self.config = config
        self._interrupt = asyncio.Event()
        self._iteration_budget = IterationBudget(max_turns=config.max_cycle_turns)
        self._compression_threshold = 0.5  # compress when journal > 50% capacity

    async def run_cycle(self, symbol: str) -> CycleResult:
        """One complete trading cycle. Equivalent to one agent conversation turn.
        
        Hermes pattern: interruptible, budget-tracked, fallback-aware.
        """
        flow = self.memory.create_flow(symbol)
        
        try:
            # Phase 1: Build context (like Hermes's prompt_builder)
            context = await self._build_context(symbol)
            
            # Phase 2: Run agents (like Hermes's tool dispatch)
            # Hermes runs tools sequentially or concurrently via ThreadPoolExecutor
            # Noema does the same with agent fan-out
            analysis = await self._run_analysis(context)
            
            # Phase 3: Decision (like Hermes's LLM reasoning)
            decision = self._make_decision(analysis)
            
            # Phase 4: Policy check (like Hermes's approval.py)
            # Hermes checks "is this command dangerous?" before executing
            # Noema checks "is this order safe?" before sending
            if decision.action == "TRADE":
                policy_result = await self.policy.evaluate(decision.order, context)
                if not policy_result.allowed:
                    await self.memory.record_blocked(flow, policy_result)
                    return CycleResult(blocked=True, reason=policy_result.reason)
                
                # Phase 5: Execute (like Hermes's tool handler)
                result = await self._execute_order(decision.order)
                
                # Phase 6: Persist (like Hermes's session save)
                await self.memory.record_trade(flow, result)
            
            return CycleResult(flow=flow, decision=decision)
            
        except asyncio.CancelledError:
            # Hermes pattern: interruptible. User can cancel mid-flight.
            # Noema: Guardian can cancel mid-cycle.
            await self.memory.record_cancelled(flow, "interrupted")
            raise
        except Exception as e:
            # Hermes pattern: graceful error handling, session persists
            await self.memory.record_error(flow, str(e))
            return CycleResult(error=str(e))
        finally:
            self._iteration_budget.reset()

    async def _build_context(self, symbol: str) -> MarketContext:
        """Build the context for this cycle. Like Hermes's prompt_builder.
        
        Hermes assembles: identity → tools → skills → memory → context → timestamp
        Noema assembles: market data → news → positions → guardian state → memory
        """
        bars = await self.broker.bars(symbol, "H1", 200)
        positions = await self.broker.positions()
        account = await self.broker.account_state()
        news = await self._fetch_news(symbol)
        recent_trades = await self.memory.recent_trades(symbol, days=7)
        
        return MarketContext(
            symbol=symbol,
            bars=bars,
            positions=positions,
            account=account,
            news=news,
            recent_trades=recent_trades,
            guardian_state=self.guardian,
            mode=self.config.mode,
            # Hermes pattern: versioning in context
            git_sha=get_git_sha(),
            settings_hash=self.config.hash(),
            run_id=self._run_id,
        )

    async def _run_analysis(self, context: MarketContext) -> dict[str, AgentReport]:
        """Run analysis agents. Like Hermes's tool dispatch.
        
        Hermes dispatches tools sequentially (single) or concurrently (multiple).
        Noema does the same: independent agents run in parallel, dependent ones sequential.
        """
        # Independent agents — run concurrently (like Hermes ThreadPoolExecutor)
        independent = ["trend", "structure", "fundamental", "currency"]
        parallel_results = await self._run_parallel(independent, context)
        
        # Dependent agents — run sequentially
        context.update(parallel_results)
        sequential_results = await self._run_sequential(
            ["confluence", "portfolio", "risk"],
            context,
        )
        
        return {**parallel_results, **sequential_results}
```

### What Noema Gets From This

| Hermes Pattern | Noema Application |
|---|---|
| Interruptible API calls | Guardian can cancel a cycle mid-flight |
| Iteration budget (90 turns) | Max cycle iterations, prevents runaway loops |
| Fallback model switching | If Finnhub fails, try TradingEconomics; if LLM fails, use Python-only bias |
| Context compression | When journal grows large, summarize old trades for memory |
| Session persistence | Every cycle state saved to DuckDB, survives crash |

---

## 2. Tool Registry → Agent Registry

### Hermes Pattern

Hermes has a central `tools/registry.py`. Every tool file self-registers at import time:

```python
# tools/terminal_tool.py
from tools.registry import registry

def terminal_handler(args):
    ...

registry.register(
    name="terminal",
    description="Execute shell commands",
    parameters={...},
    handler=terminal_handler,
    dangerous=True,  # triggers approval callback
)
```

The registry is the **single source of truth** for all tool schemas, dispatch, and availability. No manual import list — any file with `registry.register()` is auto-discovered.

### Noema Adaptation

```python
# agents/registry.py — Noema's equivalent of tools/registry.py

class AgentRegistry:
    """Central registry for all trading agents. Self-registration at import time.
    
    Like Hermes's tools/registry.py but for trading analysis agents.
    """
    _agents: dict[str, AgentDef] = {}
    
    @classmethod
    def register(
        cls,
        name: str,
        description: str,
        phase: str,                    # "analysis", "decision", "execution", "guardian"
        dependencies: list[str] = [],  # which agents must run first
        timeout_ms: int = 5000,
        critical: bool = False,        # if True, failure halts the cycle
        dangerous: bool = False,       # if True, requires policy approval
    ):
        def decorator(agent_class):
            cls._agents[name] = AgentDef(
                name=name,
                description=description,
                phase=phase,
                dependencies=dependencies,
                timeout_ms=timeout_ms,
                critical=critical,
                dangerous=dangerous,
                cls=agent_class,
            )
            return agent_class
        return decorator
    
    @classmethod
    def discover(cls) -> dict[str, AgentDef]:
        """Auto-discover all registered agents. Import triggers registration."""
        import noema.agents.structure
        import noema.agents.macro
        import noema.agents.risk
        import noema.agents.execution
        import noema.agents.guardian
        # ... any file with @AgentRegistry.register() is now registered
        return cls._agents.copy()
    
    @classmethod
    def get_dag(cls) -> dict[str, list[str]]:
        """Build dependency DAG for parallel execution."""
        dag = {}
        for name, agent in cls._agents.items():
            dag[name] = agent.dependencies
        return dag

# Usage in agent files:
# agents/trend.py
@AgentRegistry.register(
    name="trend",
    description="D1/H4/H1 trend via MA(50)/MA(200) + HH/HL",
    phase="analysis",
    dependencies=[],           # no dependencies — runs first
    timeout_ms=2000,
    critical=False,
)
class TrendAgent(Agent):
    ...

# agents/confluence.py
@AgentRegistry.register(
    name="confluence",
    description="Combines all verdicts into a setup",
    phase="analysis",
    dependencies=["trend", "structure", "fundamental"],  # must wait for these
    timeout_ms=3000,
    critical=True,  # failure halts the cycle
)
class ConfluenceAgent(Agent):
    ...

# agents/execution.py
@AgentRegistry.register(
    name="execution",
    description="Sends order to MT5",
    phase="execution",
    dependencies=["risk"],     # must wait for risk approval
    timeout_ms=10000,
    critical=True,
    dangerous=True,            # triggers policy approval (like Hermes's approval.py)
)
class ExecutionAgent(Agent):
    ...
```

### What Noema Gets From This

| Hermes Pattern | Noema Application |
|---|---|
| Self-registration at import time | Add new agent = add file with decorator. No editing orchestrator. |
| `dangerous=True` flag | ExecutionAgent triggers policy check before order_send |
| `critical=True` flag | ConfluenceAgent failure halts cycle (no trade without confluence) |
| `dependencies` list | DAG-based parallel execution instead of hardcoded order |
| Auto-discovery | `AgentRegistry.discover()` finds all agents at startup |

---

## 3. delegate_task → Subagent Spawning

### Hermes Pattern

Hermes's `delegate_task` spawns child agents with:
- **Isolated context** — child gets fresh conversation, no parent history
- **Restricted toolsets** — child can only use tools explicitly passed to it
- **Depth limit** — MAX_DEPTH=2 (parent→child OK, child→grandchild blocked)
- **Independent budget** — child has its own iteration counter
- **Result return** — child returns summary to parent

Key property: **subagent isolation prevents cascade failures**. If a child crashes, the parent survives.

### Noema Adaptation

```python
# core/delegate.py

class TradeDelegator:
    """Spawn subagents for parallel work. Like Hermes's delegate_task.
    
    Use cases:
    - Fetch news from 3 sources in parallel
    - Run LLM narration while Python computes bias
    - Analyze multiple symbols concurrently
    """

    def __init__(self, max_depth: int = 2, max_children: int = 5):
        self.max_depth = max_depth
        self.max_children = max_children
        self._active: dict[str, SubagentTask] = {}

    async def delegate_analysis(
        self,
        parent_context: MarketContext,
        tasks: list[DelegationTask],
        synthesis: str | None = None,
    ) -> dict[str, Any]:
        """Delegate multiple analysis tasks to subagents.
        
        Like Hermes's delegate_task with batch mode + synthesis.
        """
        # Validate depth
        if parent_context.depth >= self.max_depth:
            raise MaxDepthError(f"Cannot delegate beyond depth {self.max_depth}")

        # Spawn children with isolated context (like Hermes)
        children = []
        for task in tasks[:self.max_children]:
            child_context = parent_context.fork(
                # Isolated: child gets only what it needs (like Hermes's restricted toolsets)
                tools=task.required_tools,
                depth=parent_context.depth + 1,
                budget=min(task.timeout_ms, 5000),
            )
            children.append(self._spawn_child(task, child_context))

        # Run all children concurrently (like Hermes's ThreadPoolExecutor batch)
        results = await asyncio.gather(*children, return_exceptions=True)

        # Synthesize (like Hermes's synthesis parameter)
        if synthesis:
            synthesis_result = await self._synthesize(synthesis, results)
            return {"synthesis": synthesis_result, "raw": results}

        return {"raw": results}

    async def _spawn_child(self, task: DelegationTask, context: MarketContext) -> Any:
        """Spawn a single child agent. Isolated context, restricted tools."""
        child_id = f"{context.run_id}:child:{task.name}"
        subtask = SubagentTask(id=child_id, task=task)
        self._active[child_id] = subtask

        try:
            # Like Hermes: fresh AIAgent with own conversation
            agent = task.agent_cls(context=context)
            result = await asyncio.wait_for(
                agent.analyze(context.to_dict()),
                timeout=task.timeout_ms / 1000,
            )
            subtask.complete(result)
            return result
        except asyncio.TimeoutError:
            subtask.timeout()
            return AgentReport(signal="TIMEOUT", reasoning=f"Subagent {task.name} exceeded budget")
        except Exception as e:
            subtask.fail(str(e))
            return AgentReport(signal="ERROR", reasoning=str(e))
        finally:
            del self._active[child_id]
```

### Hermes's Failure Recovery (from Issue #344)

Hermes is evolving delegate_task with a 3-level failure escalation:

```
Retry → Replan → Decompose Further
```

- **Retry** — Same agent, same task, try again (transient failure)
- **Replan** — Meta-agent rewrites the task based on failure reason
- **Decompose** — Break failed task into smaller subtasks

### Noema Adaptation: Trade-Aware Failure Recovery

```python
class TradeFailureRecovery:
    """Three-level failure escalation for trading agents.
    
    Retry → Replan → Decompose + Emergency Flatten
    """

    async def handle_failure(
        self,
        agent_name: str,
        task: DelegationTask,
        error: Exception,
        attempt: int,
    ) -> RecoveryAction:
        if attempt < 2:
            # Level 1: Retry (transient failure — network blip, rate limit)
            return RecoveryAction.RETRY
            
        if attempt < 3:
            # Level 2: Replan (modify approach — switch data source, reduce scope)
            if "timeout" in str(error).lower():
                # Timeout → reduce analysis scope
                task.timeout_ms *= 2
                task.context_limit = "minimal"
                return RecoveryAction.RETRY_WITH_MODS
                
            if "connection" in str(error).lower():
                # Connection lost → switch to degraded mode
                return RecoveryAction.SWITCH_DEGRADED

        # Level 3: Decompose or Escalate
        if agent_name == "execution":
            # CRITICAL: If execution agent fails, do NOT retry
            # Flatten everything and alert (like Hermes's escalation to user)
            return RecoveryAction.EMERGENCY_FLATTEN
            
        if agent_name in ("trend", "structure", "fundamental"):
            # Non-critical analysis failure → skip this cycle
            return RecoveryAction.SKIP_CYCLE
            
        # Unknown failure → escalate to Telegram alert
        return RecoveryAction.ESCALATE
```

---

## 4. Tool Gateway → Broker Gateway

### Hermes Pattern

Hermes's Tool Gateway provides:
- **Unified interface** to 70+ tools across 28 toolsets
- **Platform backends** — Terminal (6 backends), Browser (5), Web (4), MCP (dynamic)
- **Self-registration** — tools register at import time
- **Approval callbacks** — dangerous tools require user confirmation

### Noema Adaptation: Broker Gateway

```python
# broker/gateway.py

class BrokerGateway:
    """Unified broker interface. Like Hermes's Tool Gateway but for trading.
    
    Supports: MT5 (FxPesa), MT5 (FBS), Paper, Backtest
    Each backend self-registers (like Hermes's tools).
    """

    _backends: dict[str, type[BrokerProtocol]] = {}
    
    @classmethod
    def register_backend(cls, name: str, broker_cls: type[BrokerProtocol]):
        cls._backends[name] = broker_cls
    
    @classmethod
    def resolve(cls, name: str, config: dict) -> BrokerProtocol:
        """Resolve broker backend. Like Hermes's runtime_provider resolution."""
        if name not in cls._backends:
            raise UnknownBrokerError(f"Unknown broker: {name}. Available: {list(cls._backends.keys())}")
        return cls._backends[name](config)

# Self-registration (like Hermes's tools/*.py)
# broker/mt5.py
BrokerGateway.register_backend("fxpesa", MT5Broker)
BrokerGateway.register_backend("fbs", FBSBroker)
BrokerGateway.register_backend("paper", PaperBroker)
```

---

## 5. Approval Patterns → Execution Safety

### Hermes Pattern

Hermes's `tools/approval.py` detects dangerous commands:
- Pattern matching on command strings (rm, sudo, git push --force)
- Approval callback invoked when danger detected
- User sees the exact command and approves/rejects
- `allow-once` is single-command only

### Noema Adaptation

```python
# core/approval.py — Noema's equivalent of tools/approval.py

# Dangerous patterns that require approval
DANGER_PATTERNS = {
    "large_lot": lambda req: req.volume > 0.5,
    "no_stop_loss": lambda req: req.sl == 0,
    "high_spread": lambda ctx: ctx.spread > ctx.max_spread * 1.5,
    "news_blackout": lambda ctx: ctx.news_blackout_active,
    "correlated_trade": lambda ctx: ctx.correlated_positions >= 2,
    "weekend_trade": lambda ctx: ctx.is_weekend,
    "drawdown_trade": lambda ctx: ctx.drawdown_pct > 2.0,
}

class TradeApproval:
    """Detect dangerous order conditions. Like Hermes's approval.py.
    
    Hermes pattern: pattern match → callback → user approves → execute.
    Noema adaptation: pattern match → policy check → Telegram alert → auto-reject.
    """

    def __init__(self, telegram_notifier: TelegramNotifier | None = None):
        self.notifier = telegram_notifier
        self._auto_approve_patterns: set[str] = set()

    async def check(self, request: OrderRequest, context: MarketContext) -> ApprovalResult:
        """Check if order matches any danger patterns."""
        triggered = []
        
        for pattern_name, check_fn in DANGER_PATTERNS.items():
            if check_fn(context) or (hasattr(request, '__dict__') and check_fn(request)):
                triggered.append(pattern_name)
        
        if not triggered:
            return ApprovalResult(approved=True)
        
        # Like Hermes: notify user of dangerous command
        if self.notifier:
            await self.notifier.send_alert(
                f"⚠️ Dangerous order detected:\n"
                f"  Symbol: {request.symbol}\n"
                f"  Volume: {request.volume}\n"
                f"  Patterns: {', '.join(triggered)}\n"
                f"  Auto-rejected (no override without explicit /approve)"
            )
        
        # Noema default: auto-reject dangerous orders
        # (unlike Hermes where user can approve, trading system should be conservative)
        return ApprovalResult(
            approved=False,
            reason=f"Danger patterns triggered: {', '.join(triggered)}",
            patterns=triggered,
        )
```

---

## 6. Session Persistence → Trade Journal

### Hermes Pattern

Hermes uses SQLite + FTS5 for session storage:
- Every message saved after each turn
- Sessions have lineage tracking (parent/child across compressions)
- Per-platform isolation
- Atomic writes with contention handling
- Full-text search across all sessions

### Noema Adaptation

```python
# journal/store.py — Noema's equivalent of hermes_state.py

class TradeJournal:
    """SQLite-based trade journal. Like Hermes's session storage.
    
    Every trade, every decision, every kill-switch event persisted.
    FTS5 for searching trade history.
    """

    def __init__(self, db_path: Path = Path("data/journal.db")):
        self.db = sqlite3.connect(str(db_path))
        self._init_schema()

    def _init_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS flows (
                flow_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                settings_hash TEXT,
                git_sha TEXT,
                run_id TEXT,
                result TEXT  -- JSON: final outcome
            );
            
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flow_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                event_type TEXT NOT NULL,  -- 'analysis', 'decision', 'order', 'fill', 'veto', 'killswitch'
                agent TEXT,
                signal TEXT,
                confidence REAL,
                data TEXT,  -- JSON
                created_at TEXT NOT NULL,
                FOREIGN KEY (flow_id) REFERENCES flows(flow_id)
            );
            
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flow_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                volume REAL NOT NULL,
                price REAL,
                sl REAL,
                tp REAL,
                ticket INTEGER,
                status TEXT NOT NULL,  -- 'pending', 'filled', 'rejected', 'cancelled'
                policy_checks TEXT,  -- JSON: which checks passed/failed
                created_at TEXT NOT NULL,
                filled_at TEXT,
                FOREIGN KEY (flow_id) REFERENCES flows(flow_id)
            );
            
            -- FTS5 for full-text search (like Hermes)
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                flow_id, agent, signal, data,
                content=events,
                content_rowid=id
            );
            
            -- Lineage tracking (like Hermes's session lineage)
            CREATE TABLE IF NOT EXISTS flow_lineage (
                child_flow_id TEXT PRIMARY KEY,
                parent_flow_id TEXT,
                relationship TEXT,  -- 'retry', 'replan', 'decompose'
                created_at TEXT NOT NULL
            );
        """)

    async def search_events(self, query: str, limit: int = 50) -> list[dict]:
        """Full-text search across all trade events. Like Hermes's FTS5 search."""
        cursor = self.db.execute(
            "SELECT * FROM events_fts WHERE events_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        )
        return [dict(row) for row in cursor.fetchall()]
```

---

## 7. Context Compression → Trade Memory Compression

### Hermes Pattern

Hermes compresses conversation history when it exceeds the context window:
- Triggers at 50% (preflight) or 85% (gateway auto)
- Middle turns summarized into a compact summary
- Last N messages preserved intact
- Tool call/result pairs kept together
- New session lineage ID generated

### Noema Adaptation

```python
# memory/compressor.py

class TradeMemoryCompressor:
    """Compress old trade data for memory efficiency. Like Hermes's context_compressor.
    
    When the journal grows too large for LLM context or memory analysis,
    summarize old trades while preserving recent ones intact.
    """

    def __init__(self, protect_last_n: int = 50):
        self.protect_last_n = protect_last_n

    async def compress_journal(
        self,
        journal: TradeJournal,
        symbol: str,
        max_entries: int = 500,
    ) -> CompressionResult:
        """Compress old journal entries. Like Hermes's lossy summarization."""
        total = await journal.count_events(symbol)
        
        if total <= max_entries:
            return CompressionResult(compressed=False, reason="under_threshold")
        
        # Keep last N entries intact (like Hermes's protect_last_n)
        recent = await journal.get_recent_events(symbol, self.protect_last_n)
        old = await journal.get_events(symbol, offset=self.protect_last_n)
        
        # Summarize old entries
        summary = self._summarize_trades(old)
        
        # Create compressed record (like Hermes's child session)
        compressed_id = f"compressed:{symbol}:{datetime.now(timezone.utc).isoformat()}"
        await journal.create_compressed_record(
            compressed_id=compressed_id,
            symbol=symbol,
            summary=summary,
            original_count=len(old),
            preserved_count=len(recent),
        )
        
        # Create lineage (like Hermes's session lineage)
        await journal.create_lineage(
            child=compressed_id,
            parent=symbol,
            relationship="compression",
        )
        
        return CompressionResult(
            compressed=True,
            entries_compressed=len(old),
            entries_preserved=len(recent),
            summary=summary,
        )

    def _summarize_trades(self, trades: list[dict]) -> dict:
        """Summarize old trades into statistics. Lossy but useful."""
        if not trades:
            return {}
        
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) < 0]
        
        return {
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades) if trades else 0,
            "avg_win_pnl": sum(t["pnl"] for t in wins) / len(wins) if wins else 0,
            "avg_loss_pnl": sum(t["pnl"] for t in losses) / len(losses) if losses else 0,
            "best_trade": max((t["pnl"] for t in trades), default=0),
            "worst_trade": min((t["pnl"] for t in trades), default=0),
            "period_start": min(t["created_at"] for t in trades),
            "period_end": max(t["created_at"] for t in trades),
            # Preserve notable trades (big wins, big losses)
            "notable": [t for t in trades if abs(t.get("pnl", 0)) > 100][:10],
        }
```

---

## 8. Cron → Market Scheduler

### Hermes Pattern

Hermes's cron is first-class:
- Jobs stored in JSON (not crontab)
- Each job is an **agent task** (not a shell command)
- Jobs can attach skills and scripts
- Jobs deliver to any platform (Discord, Telegram, etc.)
- Scheduler ticks independently, loads due jobs

### Noema Adaptation

```python
# scheduler/market_cron.py

class MarketCron:
    """Market-aware scheduler. Like Hermes's cron but for trading.
    
    Instead of: "run this shell command at 9am"
    It does:    "analyze EURUSD at London open" / "check news at 1:30pm" / "flatten at 4:55pm"
    """

    def __init__(self, journal: TradeJournal, config: SessionConfig):
        self.jobs: list[CronJob] = []
        self.journal = journal
        self.sessions = config.sessions

    def schedule(self, job: CronJob):
        """Register a cron job. Like Hermes's cron/scheduler.py."""
        self.jobs.append(job)

    async def tick(self):
        """Called every second. Check for due jobs. Like Hermes's scheduler tick."""
        now = datetime.now(timezone.utc)
        for job in self.jobs:
            if job.is_due(now):
                await self._run_job(job, now)

    async def _run_job(self, job: CronJob, now: datetime):
        """Run a due job. Like Hermes's cron execution."""
        try:
            # Hermes pattern: fresh agent, no history
            result = await job.execute(now)
            
            # Persist result
            await self.journal.record_cron_event(job.name, result)
            
            # Deliver to platform (like Hermes's delivery)
            if job.notify:
                await job.deliver(result)
                
        except Exception as e:
            await self.journal.record_cron_error(job.name, str(e))

# Built-in jobs
def setup_market_cron(cron: MarketCron):
    """Standard trading cron jobs."""
    
    # London open: increase analysis frequency
    cron.schedule(SessionOpenJob("london", actions=["enable_trading", "alert"]))
    
    # NY open: maximum activity
    cron.schedule(SessionOpenJob("new_york", actions=["enable_trading", "alert"]))
    
    # NY close: flatten if needed
    cron.schedule(SessionCloseJob("new_york", actions=["review_positions"]))
    
    # Friday 4:55 PM EAT: flatten everything (weekend risk)
    cron.schedule(WeeklyFlattenJob(day="friday", hour=16, minute=55))
    
    # Every 5 minutes during active sessions: run analysis cycle
    cron.schedule(AnalysisCycleJob(interval_minutes=5, sessions=["london", "new_york"]))
    
    # Every 30 minutes: check news calendar
    cron.schedule(NewsCheckJob(interval_minutes=30))
    
    # Daily: export journal for KRA
    cron.schedule(DailyExportJob(hour=23, minute=0))
    
    # Weekly: run pip-audit
    cron.schedule(SecurityScanJob(day="monday", hour=6, minute=0))
```

---

## 9. Inter-Agent Communication → Agent Cooperation Levels

### Hermes Pattern (from Issue #344)

Hermes defines 4 levels of inter-agent communication:

| Level | Mechanism | Use Case |
|---|---|---|
| L0 | Isolated (current) | Simple delegation — no sharing |
| L1 | Result passing | Upstream results injected into downstream context |
| L2 | Shared scratchpad | Read/write shared key-value store |
| L3 | Live dialogue | Turn-based agent-to-agent conversation |

### Noema Adaptation

```python
# core/communication.py

class AgentCommunication:
    """Inter-agent communication with 4 levels. From Hermes Issue #344.
    
    Most Noema agents use L0 (isolated) or L1 (result passing).
    Guardian uses L2 (shared scratchpad for kill-switch state).
    Devil's Advocate vs Trade Thesis uses L3 (adversarial debate).
    """

    # L0: Isolated — each agent gets its own context (default)
    # Used by: trend, structure, fundamental, currency, session
    
    # L1: Result passing — upstream results flow downstream
    # Used by: trend → confluence, structure → confluence, confluence → risk → execution
    
    # L2: Shared scratchpad — agents read/write shared state
    # Used by: guardian (kill-switch state), risk (position limits)
    
    def __init__(self):
        self._scratchpad: dict[str, Any] = {}  # L2 shared state
        self._debate_log: list[dict] = []        # L3 dialogue log

    def scratchpad_write(self, agent: str, key: str, value: Any):
        """L2: Write to shared scratchpad. Guardian writes kill-switch state here."""
        self._scratchpad[f"{agent}:{key}"] = {
            "value": value,
            "written_by": agent,
            "written_at": datetime.now(timezone.utc).isoformat(),
        }

    def scratchpad_read(self, key: str) -> Any | None:
        """L2: Read from shared scratchpad. Any agent can read guardian state."""
        entry = self._scratchpad.get(key)
        return entry["value"] if entry else None

    async def adversarial_debate(
        self,
        proponent: Agent,
        opponent: Agent,
        topic: MarketContext,
        max_rounds: int = 3,
    ) -> DebateResult:
        """L3: Two-agent iterative refinement. From Hermes Issue #376.
        
        Trade Thesis (proponent) argues FOR the trade.
        Devil's Advocate (opponent) argues AGAINST.
        They iterate until consensus or max rounds.
        """
        proponent_case = await proponent.build_case(topic)
        
        for round_num in range(max_rounds):
            # Opponent critiques
            critique = await opponent.critique(proponent_case, topic)
            
            if critique.verdict == "ACCEPT":
                return DebateResult(
                    accepted=True,
                    rounds=round_num + 1,
                    final_case=proponent_case,
                    final_critique=critique,
                )
            
            # Proponent responds to critique
            response = await proponent.respond_to_critique(critique, topic)
            
            if response.verdict == "CONCEDE":
                return DebateResult(
                    accepted=False,
                    rounds=round_num + 1,
                    reason=response.concession_reason,
                )
            
            proponent_case = response.updated_case
        
        # Max rounds reached — CIO decides
        return DebateResult(
            accepted=None,  # undecided
            rounds=max_rounds,
            final_case=proponent_case,
            final_critique=critique,
            escalated_to="cio",
        )
```

---

## 10. Gas Town Patterns → Durable Trading Work

### Pattern (from Steve Yegge's Gas Town, cited in Hermes Issue #344)

Gas Town is a 348K LOC Go system orchestrating 20-50+ concurrent coding agents. Key patterns:

- **GUPP (Gastown Universal Propulsion Principle)**: "If you find work on your hook, YOU RUN IT." Work is durable — separate from process state. When an agent dies, work is recoverable.
- **Hierarchical health monitoring**: 3-layer watchdog: Daemon (heartbeat) → Boot (ephemeral checker) → Deacon (persistent monitor)
- **Idle Town Principle**: Skip health checks when no active work
- **Mail vs Nudge**: Persistent messages (survive crashes) vs ephemeral reminders (zero-cost)

### Noema Adaptation

```python
# core/durable_work.py

class DurableWorkQueue:
    """Durable work queue for trading tasks. From Gas Town's GUPP principle.
    
    "If you find work on your hook, YOU RUN IT."
    Work survives process crashes. On restart, unfinished work is picked up.
    """

    def __init__(self, journal: TradeJournal):
        self.journal = journal
        self._queue: asyncio.Queue[WorkItem] = asyncio.Queue()

    async def submit(self, item: WorkItem):
        """Submit work to the durable queue. Persisted to DB immediately."""
        await self.journal.persist_work_item(item)
        await self._queue.put(item)

    async def claim(self, worker_id: str) -> WorkItem | None:
        """Claim the next work item. Atomic — no double-claim."""
        item = await self._queue.get()
        claimed = await self.journal.claim_work_item(item.id, worker_id)
        return claimed

    async def complete(self, item_id: str, result: Any):
        """Mark work as completed."""
        await self.journal.complete_work_item(item_id, result)

    async def recover(self, worker_id: str) -> list[WorkItem]:
        """On restart, recover unclaimed work. GUPP principle."""
        return await self.journal.get_unclaimed_work(worker_id)


class ThreeLayerWatchdog:
    """Hierarchical health monitoring. From Gas Town.
    
    Layer 1 (Daemon): Heartbeat every 5s — "am I alive?"
    Layer 2 (Boot):   Process check every 30s — "is the main process alive?"
    Layer 3 (Deacon): State check every 60s — "is the system actually working?"
    """

    def __init__(self, config: GuardianConfig):
        self.daemon = DaemonHeartbeat(interval=5.0, max_age=30.0)
        self.boot = BootChecker(interval=30.0)
        self.deacon = DeaconMonitor(interval=60.0)

    async def run(self):
        """Main watchdog loop. Idle Town Principle: skip checks when no active work."""
        while True:
            # Idle Town: if no active flows, reduce check frequency
            active_flows = await self._count_active_flows()
            
            if active_flows == 0:
                # Idle mode: only daemon heartbeat
                await self.daemon.tick()
                await asyncio.sleep(30.0)  # slower tick when idle
                continue

            # Active mode: all layers
            await self.daemon.tick()
            
            if self.daemon.is_stale():
                await self._emergency_flatten("Daemon heartbeat stale")
                continue
            
            await self.boot.tick()
            if self.boot.process_dead():
                await self._emergency_flatten("Main process dead")
                continue
            
            await self.deacon.tick()
            if self.deacon.system_stuck():
                await self._alert("System stuck — no progress on active flows")
            
            await asyncio.sleep(1.0)

    async def _emergency_flatten(self, reason: str):
        """Emergency: flatten all positions. Mail (persistent) not nudge (ephemeral)."""
        # Mail: persists even if this process crashes
        await self.journal.record_emergency(reason)
        
        # Flatten
        await self.broker.close_all_positions(reason=f"EMERGENCY: {reason}")
        
        # Alert via Telegram
        await self.notifier.send_alert(f"🚨 EMERGENCY FLATTEN: {reason}")
```

---

## 11. Adversarial Debate → Thesis vs Devil's Advocate

### Hermes Pattern (from Issue #376)

Hermes's adversarial debate mode:
- Two agents iterate on a problem
- Proponent argues FOR, opponent argues AGAINST
- Each round: opponent critiques → proponent responds
- Convergence: opponent ACCEPTS or proponent CONCEDES
- Max rounds prevent infinite loops

### Noema Adaptation

This directly maps to your existing `TradeThesisAgent` vs `DevilsAdvocateAgent`:

```python
# Currently in v0.1: Thesis builds case → Devil critiques → CIO decides (one-shot)
# With Hermes pattern: Thesis and Devil iterate until convergence

class AdversarialTradeValidator:
    """Trade Thesis vs Devil's Advocate debate. From Hermes Issue #376.
    
    Instead of one-shot decision, they iterate:
    Round 1: Thesis builds case → Devil finds weaknesses
    Round 2: Thesis addresses weaknesses → Devil finds more (or accepts)
    Round 3: Final state → CIO decides
    """

    async def validate(
        self,
        thesis: TradeThesisAgent,
        devil: DevilsAdvocateAgent,
        context: MarketContext,
        max_rounds: int = 3,
    ) -> Validation:
        
        # Round 1: Thesis builds initial case
        case = await thesis.analyze(context.to_dict())
        
        for round_num in range(max_rounds):
            # Devil critiques
            critique = await devil.analyze({
                **context.to_dict(),
                "thesis_case": case.data,
                "debate_round": round_num + 1,
            })
            
            # If Devil approves (few weaknesses), accept
            if critique.signal == "APPROVE" and len(critique.data.get("weaknesses", [])) <= 1:
                return Validation(
                    accepted=True,
                    rounds=round_num + 1,
                    final_case=case,
                    final_critique=critique,
                    confidence=case.confidence * 0.9 + critique.confidence * 0.1,
                )
            
            # Thesis responds to critique
            case = await thesis.analyze({
                **context.to_dict(),
                "devil_critique": critique.data,
                "debate_round": round_num + 1,
                "address_weaknesses": critique.data.get("weaknesses", []),
            })
        
        # Max rounds — escalate to CIO with full debate history
        return Validation(
            accepted=None,
            rounds=max_rounds,
            final_case=case,
            final_critique=critique,
            escalated=True,
        )
```

---

## 12. Shared Memory Pools → Cross-Agent State

### Hermes Pattern (from Issue #377)

Shared memory pools allow subagents to:
- Read/write to a shared key-value store
- See each other's contributions in real-time
- Build on each other's work

### Noema Adaptation

```python
# core/shared_state.py

class TradingSharedState:
    """Shared state pool for all agents. From Hermes Issue #377.
    
    Agents can read/write shared state. Guardian writes kill-switch state.
    All agents can check if the system is healthy before proceeding.
    """

    def __init__(self):
        self._state: dict[str, StateEntry] = {}
        self._watchers: dict[str, list[asyncio.Event]] = defaultdict(list)

    def put(self, agent: str, key: str, value: Any, ttl_seconds: float = 300):
        """Write to shared state with TTL."""
        self._state[f"{agent}:{key}"] = StateEntry(
            value=value,
            written_by=agent,
            written_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        # Notify watchers
        for event in self._watchers.get(key, []):
            event.set()

    def get(self, key: str, default: Any = None) -> Any:
        """Read from shared state. Returns default if expired or missing."""
        entry = self._state.get(key)
        if entry and entry.expires_at > datetime.now(timezone.utc):
            return entry.value
        return default

    async def wait_for(self, key: str, timeout: float = 10.0) -> Any:
        """Wait for a key to be written. Like asyncio.Event but with value."""
        event = asyncio.Event()
        self._watchers[key].append(event)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self.get(key)
        except asyncio.TimeoutError:
            return None
        finally:
            self._watchers[key].remove(event)

# Usage:
state = TradingSharedState()

# Guardian writes kill-switch state
state.put("guardian", "kill_switches", {"daily_loss": False, "heartbeat": True}, ttl_seconds=10)

# ExecutionAgent reads before sending order
switches = state.get("guardian:kill_switches")
if switches.get("daily_loss"):
    raise KillSwitchActiveError("Daily loss limit hit")

# ExecutionAgent waits for guardian heartbeat before proceeding
await state.wait_for("guardian:heartbeat", timeout=30.0)
```

---

## 13. Acceptance Criteria & Judge → Trade Quality Gates

### Hermes Pattern (from Issue #356)

Hermes adds acceptance criteria and an independent judge for delegation quality:
- Define what "good" looks like before delegating
- Judge evaluates subagent output against criteria
- Failed criteria trigger retry or rejection

### Noema Adaptation

```python
# core/quality_gates.py

class TradeQualityGates:
    """Quality gates for trade decisions. From Hermes Issue #356.
    
    Define acceptance criteria BEFORE the trade. Judge evaluates AFTER.
    """

    @staticmethod
    def define_criteria(setup: Setup) -> TradeCriteria:
        """Define what a good trade looks like before we execute."""
        return TradeCriteria(
            min_confluence_score=0.70,
            min_rr_ratio=2.0,
            max_spread_pips=3.0,
            required_agents=["trend", "structure"],  # must have these signals
            forbidden_signals=["BEARISH"] if setup.direction == "bullish" else ["BULLISH"],
            min_sources_count=2,  # for fundamental bias
        )

    @staticmethod
    def judge(setup: Setup, reports: dict[str, AgentReport], criteria: TradeCriteria) -> GateResult:
        """Evaluate trade against acceptance criteria."""
        failures = []
        
        if setup.score < criteria.min_confluence_score:
            failures.append(f"Score {setup.score:.2f} < {criteria.min_confluence_score}")
        
        for required in criteria.required_agents:
            if required not in reports:
                failures.append(f"Missing required agent: {required}")
            elif reports[required].signal in criteria.forbidden_signals:
                failures.append(f"{required} signal {reports[required].signal} is forbidden")
        
        if not failures:
            return GateResult(passed=True, confidence=setup.score)
        
        return GateResult(
            passed=False,
            failures=failures,
            confidence=0.0,
        )
```

---

## Summary: Hermes → Noema Pattern Map

| # | Hermes Pattern | Noema Equivalent | Status |
|---|---|---|---|
| 1 | AIAgent.run_conversation() | TradingLoop.run_cycle() | To build |
| 2 | tools/registry.py | agents/registry.py | To build |
| 3 | delegate_task | TradeDelegator | To build |
| 4 | Tool Gateway | BrokerGateway | Partial (MT5Broker exists) |
| 5 | tools/approval.py | core/approval.py | To build |
| 6 | hermes_state.py (SQLite) | journal/store.py | To build |
| 7 | context_compressor.py | memory/compressor.py | To build |
| 8 | cron/scheduler.py | scheduler/market_cron.py | To build |
| 9 | L0-L3 communication | core/communication.py | To build |
| 10 | Gas Town GUPP | core/durable_work.py | To build |
| 11 | Adversarial Debate (#376) | Thesis vs Devil iteration | To build |
| 12 | Shared Memory Pools (#377) | core/shared_state.py | To build |
| 13 | Acceptance Criteria (#356) | core/quality_gates.py | To build |
| 14 | 3-layer watchdog (Gas Town) | ThreeLayerWatchdog | To build |
| 15 | Failure Recovery: Retry→Replan→Decompose | TradeFailureRecovery | To build |
| 16 | Session lineage tracking | Flow lineage in journal | To build |
| 17 | Inception Prompting (#375) | Hardened agent prompts | To build |

---

## The Big Picture

```
Hermes Agent                          Noema Trading System
─────────────                         ───────────────────
User message           →              Market tick / candle close
AIAgent.run_conversation()   →        TradingLoop.run_cycle()
Prompt Builder         →              MarketContext assembly
Tool Registry          →              Agent Registry (self-registering)
Tool Dispatch          →              Agent Fan-Out (parallel + sequential)
Approval (dangerous)   →              Execution Policy (order safety)
delegate_task          →              TradeDelegator (subagent spawning)
Session Storage        →              Trade Journal (SQLite + FTS5)
Context Compression    →              Trade Memory Compressor
Cron Jobs              →              Market Cron (session-aware)
Gateway (20 platforms) →              Telegram Bot (control surface)
Memory (MEMORY.md)     →              Strategy Memory (YAML + lessons)
Skills (SKILL.md)      →              Agent Skills (interface contracts)
Subagent isolation     →              Analysis isolation (no cascade)
Failure recovery       →              Retry → Replan → Decompose + Flatten
Adversarial debate     →              Thesis vs Devil's Advocate iteration
Shared memory pools    →              Guardian shared state
Acceptance criteria    →              Trade quality gates
3-layer watchdog       →              Daemon → Boot → Deacon monitoring
```

**The fundamental insight:** Hermes treats every user interaction as an agent loop with tool dispatch, safety gating, session persistence, and failure recovery. Noema should treat every market tick the same way — an agent loop with analysis dispatch, execution policy, journal persistence, and crash recovery.

The code changes. The architecture doesn't.

---

*Document follows the architectural patterns from [Hermes Agent](https://github.com/NousResearch/hermes-agent) by NousResearch, adapted for real-money forex trading.*
