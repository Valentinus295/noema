# Modern AI Agent Architectures: A Research Report for VMPM

**Date:** 2026-06-17
**Purpose:** Study how the most successful agentic systems (2025-2026) are architected, extract design patterns, and recommend how to align VMPM with these proven approaches.

---

## Table of Contents

1. [How Modern Agentic Systems Actually Work](#1-how-modern-agentic-systems-actually-work)
2. [Extracted Design Patterns](#2-extracted-design-patterns)
3. [NVIDIA NIM Specific Integration](#3-nvidia-nim-specific-integration)
4. [Recommended Architecture for VMPM](#4-recommended-architecture-for-vmpm)
5. [Performance Optimization for Trading](#5-performance-optimization-for-trading)

---

## 1. How Modern Agentic Systems Actually Work

### 1.1 OpenClaw Architecture

OpenClaw is an open-source autonomous AI agent framework that gained 100K GitHub stars rapidly. Its architecture reveals the state of the art in production agent systems.

**Agent Structure:**
- Each agent is a **persistent process** with its own session, memory, and tool set
- Agents run a continuous **Observe → Orient → Decide → Act (OODA)** loop
- The system uses a **supervisor-worker pattern** where a main agent delegates to subagents
- Subagents are spawned for specific tasks and report results back to the parent

**Tool-Use Pattern:**
- Tools are defined as typed functions with JSON Schema descriptions
- The LLM selects tools via **function calling** (OpenAI-compatible API)
- Tools include: file I/O, shell execution, web search, code execution, node control
- Tool execution is **sandboxed** — agents run in isolated environments
- Tools are **policy-filtered** — not all tools are available to all agents

**Multi-Agent Coordination:**
- **Hierarchical delegation**: Main agent spawns subagents with specific tasks
- **Subagent context**: Each subagent receives a task description and relevant context
- **Auto-completion**: Subagent results are automatically announced back to the parent
- **Session isolation**: Each agent session is independent with its own context window
- **No shared state by default**: Agents communicate through explicit message passing

**Context/Memory Management:**
- **Workspace files**: AGENTS.md, SOUL.md, USER.md provide persistent context
- **Daily memory files**: `memory/YYYY-MM-DD.md` for session continuity
- **Long-term memory**: MEMORY.md for curated, distilled knowledge
- **Memory search**: Semantic search across memory corpus
- **Context injection**: Key files are loaded at session start automatically

**Session Management:**
- Sessions are **ephemeral** — each conversation starts fresh
- Memory files provide **continuity across sessions**
- **Heartbeat polling** for proactive background work
- **Cron jobs** for scheduled, isolated tasks

**Safety/Guardrails:**
- **Red lines**: Hard-coded prohibitions (no data exfiltration, no destructive commands)
- **Approval gates**: Destructive operations require explicit user approval
- **Sandboxing**: Tool execution in isolated environments
- **Input sanitization**: External content treated as untrusted
- **No self-replication**: Agents cannot modify their own prompts or safety rules

**Key Insight for VMPM:** OpenClaw demonstrates that production agents need (1) clear tool interfaces with schema enforcement, (2) hierarchical delegation with automatic result propagation, (3) persistent memory across sessions, and (4) hard safety guardrails that cannot be overridden.

*Source: [Towards AI — OpenClaw Architecture Deep Dive, Feb 2026](https://pub.towardsai.net/openclaw-architecture-deep-dive-building-production-ready-ai-agents-from-scratch-e693c1002ae8); [VisionClaw arXiv, Apr 2026](https://arxiv.org/html/2604.03486v2)*

---

### 1.2 Claude Code / Cursor / Coding Agent Architecture

Claude Code, Cursor, Windsurf, and similar coding agents represent the most battle-tested agent architectures in production use.

**The Agent Loop:**
The core loop across all modern coding agents follows a consistent pattern (identified in a 2026 source-code taxonomy of 13 open-source coding agents):

```
REACT LOOP (most common):
  1. Observe: Read current state (file contents, test results, error messages)
  2. Think: LLM reasons about what to do next
  3. Act: Execute a tool call (edit file, run command, search codebase)
  4. Observe: Read the result of the action
  5. Repeat until task complete or max iterations reached
```

**Five Loop Primitives Found Across Agents:**
1. **ReAct** — Think-Act-Observe cycle (most common: Claude Code, Cursor, Aider)
2. **Generate-Test-Repair** — Generate code → run tests → fix failures
3. **Plan-Execute** — Create plan → execute steps → verify
4. **Multi-attempt Retry** — Try approach, on failure try alternative
5. **Tree Search** — Monte Carlo Tree Search for exploring solution space (SWE-agent, AutoCodeRover)

**Claude Code Specifics (from Anthropic's own research):**
- Claude Code works **autonomously for increasingly long periods** — from 25 min to 45+ min sessions without human intervention (measured Sep 2025 to Feb 2026)
- Uses a **TodoWrite tool** to nudge the LLM into creating and tracking task lists
- Implements **subagent delegation** — spawning child agents for subtasks
- Uses **context compaction** — summarizing long conversations to stay within context window
- Experienced users auto-approve ~40% of actions, interrupting only when needed

**Context Window Management (Critical Finding):**
From the 2026 source-code taxonomy ([arXiv:2604.03515](https://arxiv.org/html/2604.03515v1)):
- **Seven distinct context compaction strategies** found across agents
- Gemini CLI uses a **verification probe** to check if context is still useful
- Cline uses **LLM-initiated compaction** — the LLM itself decides when to compress
- SWE-agent uses a **polling parameter** to control how often context is refreshed
- Context compaction is described as an **"architectural requirement"**, not an optimization

**Error Recovery Pattern:**
- **Automatic retry** with backoff on transient failures (API timeouts, rate limits)
- **Graceful degradation** — if one tool fails, try alternative approaches
- **Self-correction** — the agent reads error messages and adjusts its approach
- **Human-in-the-loop** — agent stops and asks for clarification when stuck

**Key Insight for VMPM:** Coding agents converge on a simple but powerful pattern: a ReAct loop with typed tool calls, context management, and self-correction. The loop itself is trivial — the sophistication is in the tool definitions and context strategy.

*Source: [Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures, Apr 2026](https://arxiv.org/html/2604.03515v1); [Anthropic — Measuring Agent Autonomy, Feb 2026](https://www.anthropic.com/research/measuring-agent-autonomy); [How Claude Code is Built — Pragmatic Engineer, Sep 2025](https://newsletter.pragmaticengineer.com/p/how-claude-code-is-built)*

---

### 1.3 Devin / OpenManus / Fully Autonomous Agents

**Devin (Cognition AI):**
- Full autonomous software engineer with browser, code editor, and terminal
- Uses a **planning board** — maintains a visible task list that it updates as it works
- Implements **long-running task management** — can work for hours on a single task
- Has **persistent environment** — maintains state across the entire task lifecycle
- Uses **self-verification** — runs its own code and checks results before proceeding

**OpenManus:**
- Open-source framework for building general AI agents
- Uses **reinforcement learning (GRPO) for agent tuning**
- Implements tool use with sandboxed execution environments
- Focuses on **general-purpose agent capabilities** rather than domain-specific agents

**Strands Agents SDK (AWS, used in production by Amazon Q, Kiro, AWS Glue):**
- **Model-driven approach**: Agent = LLM + System Prompt + Tools
- The LLM autonomously decides when and how to use tools
- Supports **Agent-to-Agent (A2A)** protocol — agents can call each other as tools
- Supports **Model Context Protocol (MCP)** — standardized tool interface
- **Hot-reloading** of tools during development
- Used in production at AWS for Amazon Q, AWS Glue, VPC Reachability Analyzer

**Common Patterns Across Autonomous Agents:**
1. **Task Decomposition**: Break complex tasks into atomic subtasks
2. **State Persistence**: Maintain environment state across long-running tasks
3. **Self-Verification**: Agents verify their own outputs before proceeding
4. **Episodic Memory**: Store what worked and what didn't for future reference
5. **Human Escalation**: Know when to ask for help

*Source: [Strands Agents SDK — AWS Blog, Jul 2025](https://aws.amazon.com/blogs/machine-learning/strands-agents-sdk-a-technical-deep-dive-into-agent-architectures-and-observability/); [OpenManus GitHub](https://github.com/FoundationAgents/OpenManus); [AgentOrchestra arXiv, Jun 2025](https://arxiv.org/html/2506.12508v1)*

---

### 1.4 The Reflexion Framework (Learning from Failure)

A critical pattern from AI research that maps directly to trading:

**Three-Component Architecture:**
1. **Actor**: Generates actions based on current state and memory (the LLM + tools)
2. **Evaluator**: Assesses trajectory quality — did the action achieve the goal?
3. **Self-Reflection Module**: Verbally reflects on failures, generates natural language summaries of what went wrong and how to improve

**Memory Architecture:**
- **Short-term memory**: Current trajectory (conversation history)
- **Long-term memory**: Outputs from self-reflection (lessons learned)
- This dual structure enables **cross-session learning** without weight updates

**Why This Matters for Trading:**
- After a losing trade, the agent doesn't just log the loss — it **reflects on why** it entered, what signals were misleading, and what to watch for next time
- These reflections persist and inform future decisions
- This is fundamentally different from just tracking win/loss statistics

*Source: [Agent Feedback Loops: From OODA to Self-Reflection — Tao An, Nov 2025](https://tao-hpu.medium.com/agent-feedback-loops-from-ooda-to-self-reflection-92eb9dd204f6)*

---

## 2. Extracted Design Patterns

### Pattern 1: Agent Loop (Plan-Act-Observe-Reflect)

**How Modern Agents Use It:**
Every successful agent system in 2025-2026 uses some variant of a reasoning loop. The most common is ReAct (Reasoning + Acting):

```python
# The universal agent loop (simplified from Claude Code, Cursor, Strands)
while not task_complete:
    # OBSERVE: Gather current state
    observation = get_current_state()
    
    # THINK: LLM reasons about what to do
    thought = llm.think(observation, memory, tools)
    
    # ACT: Execute the chosen tool
    action = thought.select_action()
    result = tools.execute(action)
    
    # OBSERVE: Read the result
    observation = result
    
    # REFLECT (optional, at key moments):
    if should_reflect(result):
        reflection = llm.reflect(trajectory, outcome)
        memory.store(reflection)
```

**How This Maps to a Trading Decision Loop:**

```python
# VMPM Trading Agent Loop
class TradingAgentLoop:
    async def run(self, symbol: str) -> TradeDecision:
        # OBSERVE: Current market state
        market = await self.tools.get_market_data(symbol)
        positions = await self.tools.get_open_positions()
        news = await self.tools.get_recent_news(symbol)
        
        # THINK: LLM analyzes the situation
        analysis = await self.llm.analyze(
            market=market,
            positions=positions,
            news=news,
            memory=self.memory.relevant(symbol),
            system_prompt=self.system_prompt
        )
        
        # PLAN: What actions to take
        plan = analysis.action_plan  # e.g., "Buy EURUSD at 1.0850 with SL 1.0820"
        
        # EXECUTE: Broker API calls
        if plan.has_trade:
            result = await self.tools.execute_trade(plan.trade_params)
            
            # OBSERVE: What happened
            execution_report = result
            
            # REFLECT: Did this work?
            if execution_report.filled:
                self.memory.store_trade_outcome(plan, execution_report)
        
        return analysis.decision
```

**Implementation in Python for VMPM:**

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class AgentLoop(ABC):
    """Modern agent loop for VMPM agents."""
    
    def __init__(self, llm_client, tools: list[Tool], memory: Memory):
        self.llm = llm_client
        self.tools = {t.name: t for t in tools}
        self.memory = memory
    
    async def run(self, context: dict[str, Any]) -> AgentReport:
        """Execute the agent loop: Observe → Think → Act → Observe → Reflect."""
        # Phase 1: OBSERVE
        observation = await self._observe(context)
        
        # Phase 2: THINK (LLM reasoning)
        thought = await self._think(observation)
        
        # Phase 3: ACT (tool calls)
        actions = thought.planned_actions
        results = []
        for action in actions:
            result = await self._act(action)
            results.append(result)
        
        # Phase 4: OBSERVE results
        final_observation = self._synthesize(observation, results)
        
        # Phase 5: REFLECT (learn from outcome)
        await self._reflect(thought, results, final_observation)
        
        return final_observation
    
    async def _observe(self, context: dict) -> Observation:
        """Gather all relevant market data and state."""
        ...
    
    async def _think(self, observation: Observation) -> Thought:
        """LLM reasoning about what to do."""
        ...
    
    async def _act(self, action: Action) -> Result:
        """Execute a tool call."""
        tool = self.tools[action.tool_name]
        return await tool.execute(action.params)
    
    async def _reflect(self, thought, results, observation):
        """Store lessons learned for future reference."""
        ...
```

---

### Pattern 2: Tool Use / Function Calling

**How Agents Define and Use Tools:**

All modern agent systems define tools with a consistent pattern:

```python
# Tool definition pattern (universal across Strands, OpenClaw, LangChain, etc.)
class Tool:
    name: str           # Unique identifier
    description: str    # What the tool does (LLM reads this to decide when to use it)
    parameters: dict    # JSON Schema for parameters
    function: Callable  # The actual implementation
```

The LLM receives tool definitions as part of the system prompt and uses **function calling** to invoke them. The key insight: **the quality of tool descriptions directly determines agent performance**. A vague description leads to misuse; a precise description leads to correct invocation.

**How This Maps to VMPM:**

```python
# VMPM Trading Tools
tools = [
    Tool(
        name="get_ohlcv",
        description="Get OHLCV candlestick data for a symbol. Returns last N candles on the specified timeframe.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Forex pair, e.g. EURUSD"},
                "timeframe": {"type": "string", "enum": ["M1", "M5", "M15", "H1", "H4", "D1"]},
                "count": {"type": "integer", "description": "Number of candles", "default": 100}
            },
            "required": ["symbol", "timeframe"]
        },
        function=mt5.get_ohlcv
    ),
    Tool(
        name="place_order",
        description="Place a market or pending order. Always requires stop loss. Returns execution report.",
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "direction": {"type": "string", "enum": ["BUY", "SELL"]},
                "lot_size": {"type": "number", "description": "Position size in lots"},
                "stop_loss": {"type": "number", "description": "Stop loss price (required)"},
                "take_profit": {"type": "number", "description": "Take profit price (optional)"},
                "order_type": {"type": "string", "enum": ["MARKET", "LIMIT", "STOP"], "default": "MARKET"}
            },
            "required": ["symbol", "direction", "lot_size", "stop_loss"]
        },
        function=broker.place_order
    ),
    Tool(
        name="calculate_risk",
        description="Calculate position size based on account risk percentage and stop loss distance.",
        parameters={...},
        function=risk_calc.calculate_position_size
    ),
    Tool(
        name="get_economic_calendar",
        description="Get upcoming high-impact economic events for the next N hours.",
        parameters={...},
        function=calendar.get_upcoming_events
    ),
]
```

**NVIDIA NIM Function Calling:**
NIM supports OpenAI-compatible function calling via the `/v1/chat/completions` endpoint. You define tools in the request and NIM returns `tool_calls` in the response. Supported models include Nemotron, Llama 3.x, and Mixtral variants.

---

### Pattern 3: Structured Output / Schema Enforcement

**How Agents Ensure Outputs Match Expected Schemas:**

Modern agents **never trust free-text LLM output for critical decisions**. They enforce schemas at multiple levels:

1. **JSON Mode**: Force the LLM to output valid JSON (NIM supports this via `response_format: {"type": "json_object"}`)
2. **Tool Use Mode**: The LLM outputs structured function calls instead of free text
3. **Pydantic Validation**: Parse LLM output into Pydantic models; reject if validation fails
4. **Retry on Invalid**: If output doesn't match schema, retry with error feedback

**Pydantic Model Validation for VMPM:**

```python
from pydantic import BaseModel, Field, validator
from enum import Enum
from typing import Optional

class TradeDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"

class TradeDecision(BaseModel):
    """Schema-enforced trade decision from LLM."""
    direction: TradeDirection
    symbol: str = Field(pattern=r"^[A-Z]{6}$")
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    lot_size: Optional[float] = Field(None, gt=0, le=10.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=10, max_length=500)
    
    @validator("stop_loss")
    def stop_loss_required_for_trades(cls, v, values):
        if values.get("direction") != TradeDirection.NO_TRADE and v is None:
            raise ValueError("stop_loss is required for any trade")
        return v

# Usage with NIM
async def get_trade_decision(client, market_data: str) -> TradeDecision:
    response = await client.chat.completions.create(
        model="nvidia/nemotron-3-super-120b-a12b",
        messages=[...],
        response_format={"type": "json_object"},  # Force JSON
        temperature=0.3  # Low temp for consistent decisions
    )
    
    raw = json.loads(response.choices[0].message.content)
    return TradeDecision(**raw)  # Pydantic validates and raises on invalid
```

---

### Pattern 4: Context Management / Memory

**How Agents Manage Context Windows:**

The 2026 source-code taxonomy identified **seven distinct context compaction strategies** across coding agents. For trading, the relevant patterns are:

**Short-Term Memory (Current Session):**
- Recent market data (last N candles)
- Current open positions
- Recent trade decisions and their reasoning
- Active market conditions (session, volatility regime)

**Long-Term Memory (Persistent):**
- Trade history with outcomes
- Learned patterns (what worked, what didn't)
- Market regime classifications
- Agent performance metrics

**Context Window Strategy for VMPM:**

```python
class TradingContextManager:
    """Manages what goes into the LLM context window."""
    
    def build_context(self, symbol: str, max_tokens: int = 4000) -> str:
        """Build optimal context for LLM, fitting within token budget."""
        context_parts = []
        tokens_used = 0
        
        # Priority 1: Current market state (always include)
        market_data = self._format_market_data(symbol, candles=50)
        context_parts.append(market_data)
        tokens_used += self._count_tokens(market_data)
        
        # Priority 2: Open positions (critical for risk)
        if self.positions.has_open(symbol):
            positions = self._format_positions(symbol)
            context_parts.append(positions)
            tokens_used += self._count_tokens(positions)
        
        # Priority 3: Recent relevant trades (learn from recent history)
        recent_trades = self.memory.get_recent_trades(symbol, limit=5)
        if recent_trades:
            trades_str = self._format_trades(recent_trades)
            if tokens_used + self._count_tokens(trades_str) < max_tokens * 0.8:
                context_parts.append(trades_str)
                tokens_used += self._count_tokens(trades_str)
        
        # Priority 4: Relevant reflections (long-term learning)
        reflections = self.memory.search_reflections(symbol, query="similar market conditions")
        if reflections:
            refl_str = self._format_reflections(reflections[:3])
            if tokens_used + self._count_tokens(refl_str) < max_tokens:
                context_parts.append(refl_str)
        
        return "\n---\n".join(context_parts)
```

**Key Insight:** Context management is not just about fitting within the window — it's about **prioritizing the most decision-relevant information**. For trading, this means: current price action > open positions > recent trades > historical patterns.

---

### Pattern 5: Multi-Agent Coordination

**Three Dominant Patterns Found in 2025-2026 Systems:**

**Pattern A: Hierarchical Supervisor (OpenClaw, Devin)**
```
Supervisor Agent
├── Delegates tasks to specialist agents
├── Collects and synthesizes results
├── Makes final decisions
└── Manages error recovery
    ├── Agent A (Specialist 1)
    ├── Agent B (Specialist 2)
    └── Agent C (Specialist 3)
```

**Pattern B: Peer-to-Peer Network (Strands A2A)**
```
Agent A ←→ Agent B ←→ Agent C
  ↕           ↕           ↕
Agent D ←→ Agent E ←→ Agent F
```
Any agent can call any other agent as a tool. Flexible but harder to control.

**Pattern C: Pipeline / Blackboard (Confluent Event-Driven)**
```
Agent A → [Blackboard/Event Bus] → Agent B → [Blackboard] → Agent C
```
Agents read from and write to a shared state store. Each agent processes the shared state and updates it.

**How This Maps to VMPM's 17-Agent Pipeline:**

VMPM currently uses a **pipeline pattern** (agents run sequentially). The modern approach would be a **hybrid**:

```python
# VMPM Modern Multi-Agent Architecture

# Layer 1: Data Collection Agents (run in parallel)
data_agents = [
    MacroEconomicAgent(),      # Fundamental data
    CurrencyStrengthAgent(),   # Currency index analysis
    SessionIntelligenceAgent(), # Session context
    MarketStructureAgent(),    # Market structure
]

# Layer 2: Analysis Agents (run after data collection, can be parallel)
analysis_agents = [
    InstitutionalFootprintAgent(),  # Smart money analysis
    SupportResistanceAgent(),       # S/R levels
    MomentumAgent(),                # Momentum indicators
    PriceActionAgent(),             # Pattern recognition
]

# Layer 3: Decision Agents (sequential, each builds on previous)
decision_agents = [
    TradeThesisAgent(),        # Form initial thesis
    DevilsAdvocateAgent(),     # Challenge the thesis
    CIOAgent(),                # Final decision
]

# Layer 4: Execution & Management (sequential)
execution_agents = [
    RiskManagerAgent(),        # Position sizing & risk
    ExecutionAgent(),          # Order placement
    TradeManagementAgent(),    # Trade monitoring & management
]

# Layer 5: Learning (post-trade)
learning_agents = [
    PerformanceAnalystAgent(), # Performance analysis
    LearningAgent(),           # Pattern learning
]

# Supervisor: Orchestrates the pipeline
class OrchestratorAgent:
    async def run_pipeline(self, symbol: str):
        # Phase 1: Collect data (parallel)
        data_results = await asyncio.gather(
            *[agent.analyze(symbol) for agent in data_agents]
        )
        
        # Phase 2: Analyze (parallel, using data results)
        context = self._build_context(data_results)
        analysis_results = await asyncio.gather(
            *[agent.analyze(context) for agent in analysis_agents]
        )
        
        # Phase 3: Decide (sequential debate)
        thesis = await decision_agents[0].analyze(analysis_results)
        challenge = await decision_agents[1].analyze(thesis)
        final_decision = await decision_agents[2].analyze(thesis, challenge)
        
        # Phase 4: Execute (if decision is to trade)
        if final_decision.direction != "NO_TRADE":
            risk_params = await execution_agents[0].analyze(final_decision)
            execution = await execution_agents[1].execute(risk_params)
            
        # Phase 5: Learn (always, in background)
        asyncio.create_task(self._learn(symbol, final_decision))
```

---

### Pattern 6: Safety & Guardrails

**How Modern Agents Implement Safety:**

From OpenClaw's architecture and Anthropic's agent research:

**Pre-Execution Validation (Before any trade):**
```python
class TradeGuardian:
    """Pre-execution safety checks — runs BEFORE any order is placed."""
    
    def validate_trade(self, decision: TradeDecision, account: Account) -> GuardrailResult:
        checks = [
            self._check_max_risk_per_trade(decision, account),      # Max 2% risk
            self._check_max_daily_loss(account),                     # Max 5% daily loss
            self._check_max_open_positions(account),                 # Max 3 concurrent
            self._check_spread_sanity(decision, current_spread),     # Spread not too wide
            self._check_news_proximity(decision, economic_calendar), # No trading 5min before news
            self._check_price_sanity(decision, current_price),       # Price within reasonable range
            self._check_lot_size_limits(decision, account),          # Within broker limits
            self._check_correlation_risk(decision, open_positions),  # Not too correlated
        ]
        
        failures = [c for c in checks if not c.passed]
        if failures:
            return GuardrailResult(
                approved=False,
                reason=f"Guardrail failures: {[f.reason for f in failures]}"
            )
        return GuardrailResult(approved=True)
```

**Post-Execution Verification (After order placed):**
```python
class PostExecutionVerifier:
    async def verify(self, order: Order, expected: TradeDecision):
        """Verify the executed order matches the decision."""
        checks = [
            order.fill_price within acceptable_slippage(expected.entry_price),
            order.volume == expected.lot_size,
            order.sl == expected.stop_loss,
            order.tp == expected.take_profit,
        ]
        if not all(checks):
            await self.alert("Execution mismatch detected!")
```

**NeMo Guardrails (NVIDIA):**
NVIDIA provides NeMo Guardrails specifically for constraining LLM outputs:
- **Topical rails**: Ensure the LLM stays on-topic (trading, not poetry)
- **Factuality rails**: Ground responses in actual market data, not hallucination
- **Moderation rails**: Block harmful or off-topic outputs
- **Custom rails**: Define domain-specific rules (e.g., "never suggest trading without a stop loss")

---

### Pattern 7: Error Recovery & Resilience

**How Agents Handle Failures:**

From the source-code taxonomy and production systems:

**1. Retry with Exponential Backoff:**
```python
async def resilient_llm_call(client, messages, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await client.chat.completions.create(messages=messages)
        except (RateLimitError, TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt + random.uniform(0, 1)
            logger.warning(f"LLM call failed, retrying in {wait:.1f}s", error=str(e))
            await asyncio.sleep(wait)
```

**2. Graceful Degradation:**
```python
class ResilientTradingAgent:
    async def analyze(self, context):
        try:
            # Primary: Full LLM analysis
            return await self._llm_analysis(context)
        except LLMUnavailable:
            # Fallback: Deterministic rule-based analysis
            logger.warning("LLM unavailable, falling back to rule-based analysis")
            return await self._rule_based_analysis(context)
        except Exception as e:
            # Last resort: Return neutral signal, don't trade
            logger.error("All analysis methods failed", error=str(e))
            return AgentReport(signal="NEUTRAL", confidence=0.0, reasoning="Analysis failed")
```

**3. MT5 Disconnect Handling:**
```python
class ResilientBroker:
    async def execute_with_retry(self, order, max_retries=3):
        for attempt in range(max_retries):
            try:
                return await self.mt5.place_order(order)
        except MT5ConnectionError:
            logger.warning("MT5 disconnected, attempting reconnect")
            await self._reconnect_mt5()
            continue
        except MT5TradeError as e:
            if "requote" in str(e) and attempt < max_retries - 1:
                # Requote: get fresh price and retry
                order.price = await self.mt5.get_current_price(order.symbol)
                continue
            raise
```

**4. LLM Hallucination Detection:**
```python
class HallucinationDetector:
    def check(self, decision: TradeDecision, market_data: MarketData) -> bool:
        """Verify LLM's reasoning aligns with actual data."""
        # Check if referenced price levels actually exist
        if decision.entry_price:
            actual_price = market_data.current_price
            if abs(decision.entry_price - actual_price) / actual_price > 0.01:
                return True  # Hallucination: price is >1% off from reality
        
        # Check if referenced patterns actually exist in the data
        if "double top" in decision.reasoning:
            if not self._verify_pattern(market_data, "double_top"):
                return True  # Hallucination: pattern doesn't exist
        
        return False
```

---

### Pattern 8: Streaming & Real-time Processing

**How Agents Handle Streaming Data:**

**Token-by-Token LLM Output:**
```python
async def stream_llm_response(client, messages):
    """Process LLM output as it streams — don't wait for full response."""
    stream = await client.chat.completions.create(
        messages=messages,
        stream=True
    )
    async for chunk in stream:
        if chunk.choices[0].delta.tool_calls:
            # Process tool call incrementally
            yield chunk.choices[0].delta.tool_calls
```

**Tick-by-Tick Market Data Processing:**
```python
class RealTimeMarketProcessor:
    """Process market ticks as they arrive — don't wait for candle close."""
    
    def __init__(self):
        self.tick_buffer = []
        self.current_candle = None
    
    async def on_tick(self, tick: Tick):
        """Called for every incoming tick."""
        self.tick_buffer.append(tick)
        
        # Update current forming candle
        self.current_candle = self._update_candle(self.current_candle, tick)
        
        # Check for immediate signals (e.g., price touching S/R level)
        signal = self._check_immediate_signals(tick)
        if signal:
            await self.message_bus.publish("immediate_signal", signal)
        
        # Periodically (every 100ms), batch-process ticks
        if len(self.tick_buffer) >= 100:
            await self._process_tick_batch()
    
    async def _process_tick_batch(self):
        """Process accumulated ticks — update indicators, check conditions."""
        ticks = self.tick_buffer.copy()
        self.tick_buffer.clear()
        
        # Update real-time indicators
        for indicator in self.realtime_indicators:
            indicator.update(ticks)
```

**Key Insight for Trading:** The biggest performance win is **not** streaming LLM output (trading decisions don't need sub-second LLM response). The real win is **streaming market data processing** — detect signals as they form, not after candle close. Use the LLM for high-level reasoning; use deterministic code for real-time signal detection.

---

## 3. NVIDIA NIM Specific Integration

### 3.1 NIM Function Calling / Tool Use

NVIDIA NIM supports **OpenAI-compatible function calling** via the `/v1/chat/completions` endpoint. This is the same interface used by OpenAI, Claude, and other providers.

**Supported Features:**
- **Function calling**: Define tools in `tools` parameter, NIM returns `tool_calls` in response
- **Structured output**: `response_format: {"type": "json_object"}` forces valid JSON output
- **Streaming**: `stream=True` for token-by-token output
- **Tool choice**: `tool_choice: "auto"` (LLM decides), `"required"` (must call a tool), or specific function

**NIM API Call for Trading Agent:**
```python
import httpx

async def nim_chat_completion(messages, tools=None, response_format=None):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NIM_API_KEY}"},
            json={
                "model": "nvidia/nemotron-3-super-120b-a12b",
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.3,
                "max_tokens": 1024,
                "response_format": response_format
            },
            timeout=30.0
        )
        return response.json()
```

### 3.2 Recommended NIM Models for Trading Agents

| Agent Type | Recommended Model | Why |
|---|---|---|
| **Analysis Agents** (macro, structure, S/R) | `nvidia/nemotron-3-super-120b-a12b` | Best reasoning, tool calling, 1M context |
| **Decision Agents** (thesis, devil's advocate, CIO) | `nvidia/nemotron-3-ultra-550b-a55b` | Highest quality reasoning for critical decisions |
| **Fast Agents** (momentum, price action) | `nvidia/nemotron-3-nano-9b-v2` | Low latency for time-sensitive analysis |
| **Learning Agent** | `nvidia/nemotron-3-super-120b-a12b` | Needs strong reasoning for pattern extraction |

**Nemotron-3-Super-120B-A12B** (hybrid Mamba-Transformer MoE):
- 120B total parameters, only 12B active per token (MoE architecture)
- **1M context window** — can hold massive amounts of market data
- Excels at: agentic reasoning, coding, planning, tool calling
- Optimized for NVIDIA GPUs via TensorRT-LLM

### 3.3 NIM Latency Characteristics

For real-time trading applications:
- **Nemotron-3-Nano-9B**: ~200-500ms latency (good for fast agents)
- **Nemotron-3-Super-120B**: ~1-3s latency (acceptable for analysis)
- **Nemotron-3-Ultra-550B**: ~3-8s latency (use only for critical decisions)

**Optimization:** Use the smallest model that produces acceptable quality for each agent type. Not every agent needs the biggest model.

### 3.4 NIM Embedding Models for RAG

NVIDIA provides **NeMo Retriever** models for embedding:
- `nvidia/nv-embedqa-e5-v5` — for question-answering embeddings
- `nvidia/nv-embedqa-mistral7b-v2` — higher quality, slower
- `nvidia/nv-rerankqa-mistral4b-v3` — for reranking retrieved documents

**RAG for Trading (if needed):**
- Embed trade history, market commentary, and news articles
- Retrieve relevant historical patterns when analyzing current conditions
- **Not recommended initially** — the added complexity isn't worth it until the base system is working

### 3.5 NeMo Guardrails for Trading Safety

NeMo Guardrails can enforce trading-specific safety rules:

```yaml
# trading_guardrails.yml
rails:
  input:
    flows:
      - check no_stop_loss_suggestion
      - check no_guaranteed_profit_claims
      - check max_risk_per_trade
  
  output:
    flows:
      - check trade_has_stop_loss
      - check risk_within_limits
      - check price_sanity
```

---

## 4. Recommended Architecture for VMPM (Modern Agentic Style)

### 4.1 The Modern Agent Loop for Trading

Based on all research above, the recommended trading agent loop is:

```
OBSERVE (market data, news, positions, account state)
  → THINK (LLM reasoning about what to do)
    → PLAN (which actions to take, with structured output)
      → VALIDATE (guardrail checks before execution)
        → EXECUTE (broker API calls)
          → OBSERVE (execution results, new market state)
            → REFLECT (did the action work? store lessons learned)
```

This is the **OODA + Reflexion** pattern, specifically adapted for trading.

### 4.2 How to Structure Each VMPM Agent as a Modern Agent

**Every agent should have:**
1. **Goal**: What this agent is trying to achieve (system prompt)
2. **Tools**: What capabilities it has (function definitions)
3. **Memory**: What it remembers (short-term + long-term)
4. **Reasoning Loop**: How it thinks (ReAct loop)

**The Orchestrator becomes a "Supervisor Agent":**
- It doesn't just sequence agents — it **delegates with context**
- Each specialist agent receives: the task, relevant data, and the results of previous agents
- The supervisor **synthesizes** results and makes routing decisions

**Agent Interface (Modernized):**

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class ModernAgent(ABC):
    """Base class for modern VMPM agents."""
    
    name: str
    role: str
    system_prompt: str  # Defines the agent's goal and behavior
    tools: list[Tool]   # What this agent can do
    model: str = "nvidia/nemotron-3-super-120b-a12b"
    
    def __init__(self, llm_client, memory: AgentMemory, config):
        self.llm = llm_client
        self.memory = memory
        self.config = config
    
    async def run(self, context: dict[str, Any]) -> AgentReport:
        """Execute the agent loop."""
        # 1. Build context window
        prompt = self._build_prompt(context)
        
        # 2. Call LLM with tools
        response = await self._call_llm(prompt)
        
        # 3. Process tool calls (if any)
        while response.has_tool_calls:
            tool_results = []
            for tool_call in response.tool_calls:
                result = await self._execute_tool(tool_call)
                tool_results.append(result)
            response = await self._call_llm(prompt + tool_results)
        
        # 4. Parse structured output
        report = self._parse_output(response)
        
        # 5. Store in memory
        await self.memory.store(context, report)
        
        return report
```

### 4.3 NVIDIA NIM as the Agent Brain

**Function Calling Schema for Trading Operations:**

```python
TRADING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": "Retrieve OHLCV candlestick data for a forex pair.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Forex pair, e.g. EURUSD"},
                    "timeframe": {"type": "string", "enum": ["M1","M5","M15","H1","H4","D1"]},
                    "count": {"type": "integer", "default": 100}
                },
                "required": ["symbol", "timeframe"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_indicator",
            "description": "Calculate a technical indicator on price data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "indicator": {"type": "string", "enum": ["RSI","MACD","ATR","EMA","SMA","BB"]},
                    "timeframe": {"type": "string"},
                    "params": {"type": "object", "description": "Indicator parameters, e.g. {'period': 14}"}
                },
                "required": ["symbol", "indicator", "timeframe"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "submit_trade_decision",
            "description": "Submit your final trade decision. Must include direction, entry, stop loss, and reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["BUY", "SELL", "NO_TRADE"]},
                    "symbol": {"type": "string"},
                    "entry_price": {"type": "number"},
                    "stop_loss": {"type": "number"},
                    "take_profit": {"type": "number"},
                    "lot_size": {"type": "number"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasoning": {"type": "string"}
                },
                "required": ["direction", "symbol", "confidence", "reasoning"]
            }
        }
    }
]
```

**Structured Output for Trade Decisions:**
```python
# Use response_format for guaranteed JSON output
response = await client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b",
    messages=[{"role": "system", "content": SYSTEM_PROMPT}, ...],
    tools=TRADING_TOOLS,
    tool_choice={"type": "function", "function": {"name": "submit_trade_decision"}},
    response_format={"type": "json_object"},
    temperature=0.2
)
```

**Caching Strategy (Critical for Performance):**
```python
class DecisionCache:
    """Cache LLM decisions for identical market states."""
    
    def __init__(self, ttl_seconds: int = 60):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get_key(self, market_state: dict) -> str:
        """Create a cache key from the market state."""
        # Hash the relevant market data
        relevant = {
            "symbol": market_state["symbol"],
            "timeframe": market_state["timeframe"],
            "last_5_candles": market_state["candles"][-5:],
            "current_price": market_state["price"],
            "session": market_state["session"],
        }
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]
    
    async def get_or_compute(self, market_state, compute_fn):
        key = self.get_key(market_state)
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["time"] < self.ttl:
                return entry["result"]
        
        result = await compute_fn(market_state)
        self.cache[key] = {"result": result, "time": time.time()}
        return result
```

### 4.4 Implementation Blueprint

**Package Structure:**
```
vmpm/
├── agents/
│   ├── base.py              # ModernAgent base class with agent loop
│   ├── tools.py             # Tool definitions and registry
│   ├── memory.py            # Agent memory (short-term + long-term)
│   ├── orchestrator.py      # Supervisor agent
│   ├── data/                # Layer 1: Data collection agents
│   │   ├── macro.py
│   │   ├── currency.py
│   │   └── session.py
│   ├── analysis/            # Layer 2: Analysis agents
│   │   ├── structure.py
│   │   ├── institutional.py
│   │   ├── sr.py
│   │   ├── momentum.py
│   │   └── price_action.py
│   ├── decision/            # Layer 3: Decision agents
│   │   ├── thesis.py
│   │   ├── devil.py
│   │   └── cio.py
│   ├── execution/           # Layer 4: Execution agents
│   │   ├── risk.py
│   │   ├── execution.py
│   │   └── management.py
│   └── learning/            # Layer 5: Learning agents
│       ├── performance.py
│       └── learning.py
├── broker/
│   ├── base.py              # Broker interface
│   ├── mt5.py               # MT5 via RPyC/Wine
│   └── paper.py             # Paper trading
├── llm/
│   ├── client.py            # NIM client with retry/caching
│   ├── models.py            # Model configuration per agent type
│   └── guardrails.py        # NeMo Guardrails integration
├── data/
│   ├── feed.py              # Market data feed
│   ├── calendar.py          # Economic calendar
│   └── news.py              # News feed
├── core/
│   ├── config.py            # Pydantic configuration
│   ├── message_bus.py       # Async pub/sub
│   ├── state_machine.py     # Pipeline state management
│   └── types.py             # Shared types
└── models/
    ├── knowledge.py          # Knowledge base
    └── schemas.py            # Pydantic schemas for all LLM outputs
```

**Key Interfaces and Protocols:**

```python
# Protocol for all agents
from typing import Protocol, runtime_checkable

@runtime_checkable
class TradingAgent(Protocol):
    name: str
    role: str
    
    async def run(self, context: dict[str, Any]) -> AgentReport: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

# Protocol for broker
@runtime_checkable  
class Broker(Protocol):
    async def place_order(self, order: Order) -> ExecutionReport: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_account(self) -> Account: ...
    async def get_ohlcv(self, symbol: str, timeframe: str, count: int) -> list[Candle]: ...

# Protocol for LLM client
@runtime_checkable
class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse: ...
```

**Configuration Schema:**

```python
from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    model: str = "nvidia/nemotron-3-super-120b-a12b"
    temperature: float = 0.3
    max_tokens: int = 1024
    max_tool_calls: int = 5
    timeout_seconds: float = 30.0
    retry_attempts: int = 3
    cache_ttl_seconds: int = 60

class VMPMConfig(BaseModel):
    broker: BrokerConfig
    nim: NIMConfig
    agents: dict[str, AgentConfig]
    risk: RiskConfig
    trading: TradingConfig
```

**Testing Strategy:**

1. **Unit tests**: Test each agent's `_build_prompt()` and `_parse_output()` independently
2. **Integration tests**: Test agent loop with mock LLM responses
3. **Paper trading tests**: Run full pipeline with paper broker
4. **Backtesting**: Replay historical data through the pipeline
5. **Chaos tests**: Simulate MT5 disconnects, LLM timeouts, news feed outages

---

## 5. Performance Optimization for Trading

### 5.1 Minimizing LLM Latency (The Biggest Bottleneck)

**The Problem:** LLM calls take 200ms-8s. Trading decisions need to be fast.

**Solution 1: Model Tiering**
- Use **small models** (9B) for fast, frequent analysis (momentum, price action)
- Use **large models** (120B+) only for critical decisions (CIO, trade thesis)
- Use **deterministic code** for everything that doesn't need reasoning

**Solution 2: Parallel Execution**
```python
# Run independent analysis agents in parallel
results = await asyncio.gather(
    momentum_agent.run(context),
    price_action_agent.run(context),
    sr_agent.run(context),
    structure_agent.run(context),
)
# Total time = max(individual times), not sum
```

**Solution 3: Pre-computation**
- Calculate indicators **before** the LLM call (deterministic code)
- Build the context with pre-computed data
- The LLM only reasons about the results, not calculates them

**Solution 4: Decision Caching**
- If market state hasn't changed significantly, reuse the last decision
- Cache key: hash of (symbol, last 5 candles, current price, session)
- TTL: 60 seconds (re-evaluate after new candle forms)

### 5.2 When to Use LLM vs Deterministic Code

| Task | Use LLM? | Why |
|---|---|---|
| Calculate RSI | ❌ No | Pure math, deterministic code is faster and exact |
| Identify support/resistance levels | ⚠️ Maybe | Rule-based for simple levels; LLM for complex structure |
| Interpret candlestick patterns | ✅ Yes | Requires contextual understanding |
| Assess market sentiment from news | ✅ Yes | Natural language understanding required |
| Calculate position size | ❌ No | Pure math formula |
| Decide whether to trade | ✅ Yes | Requires weighing multiple factors |
| Place the order | ❌ No | Just API call |
| Reflect on trade outcome | ✅ Yes | Requires reasoning about what went wrong |

**Rule of Thumb:** If the task has a deterministic algorithm, use it. Use LLM only for tasks that require **judgment, interpretation, or synthesis of ambiguous information**.

### 5.3 Parallel Agent Execution Strategy

```python
class ParallelPipeline:
    """Execute agents in parallel where possible."""
    
    async def run(self, symbol: str):
        # Layer 1: All data agents in parallel (no dependencies)
        data = await asyncio.gather(
            self.macro.run(symbol),
            self.currency.run(symbol),
            self.session.run(symbol),
        )
        context = self._merge(data)
        
        # Layer 2: All analysis agents in parallel (depend on data only)
        analysis = await asyncio.gather(
            self.structure.run(context),
            self.institutional.run(context),
            self.sr.run(context),
            self.momentum.run(context),
            self.price_action.run(context),
        )
        context = self._merge(context, analysis)
        
        # Layer 3: Decision agents (sequential — each depends on previous)
        thesis = await self.thesis.run(context)
        devil = await self.devil.run({**context, "thesis": thesis})
        decision = await self.cio.run({**context, "thesis": thesis, "challenge": devil})
        
        return decision
```

### 5.4 Memory Management for Long-Running Processes

```python
class TradingMemoryManager:
    """Manage memory for a trading system that runs 24/5."""
    
    def __init__(self, max_history_days: int = 30):
        self.max_history_days = max_history_days
    
    async def periodic_cleanup(self):
        """Run daily to clean up old data."""
        while True:
            await asyncio.sleep(86400)  # Once per day
            cutoff = datetime.now() - timedelta(days=self.max_history_days)
            
            # Archive old trades
            old_trades = await self.db.get_trades_before(cutoff)
            await self.archive.store(old_trades)
            await self.db.delete_trades_before(cutoff)
            
            # Compress old reflections
            old_reflections = await self.db.get_reflections_before(cutoff)
            compressed = self._compress_reflections(old_reflections)
            await self.db.store_compressed_reflections(compressed)
            
            # Clean up LLM response cache
            self.decision_cache.clear_expired()
```

---

## Summary of Key Recommendations

1. **Adopt the ReAct loop** as the universal agent pattern — Observe → Think → Act → Observe → Reflect
2. **Define tools with Pydantic schemas** — every broker API call, indicator calculation, and data fetch should be a typed tool
3. **Enforce structured output** — use NIM's JSON mode + Pydantic validation for all trade decisions
4. **Implement hierarchical multi-agent coordination** — parallel data/analysis, sequential decision, with a supervisor orchestrator
5. **Use model tiering** — small models for fast analysis, large models for critical decisions
6. **Add pre/post execution guardrails** — validate every trade before and after execution
7. **Implement Reflexion-style learning** — after each trade, reflect on what worked/didn't and store for future reference
8. **Cache decisions** — don't re-query the LLM for identical market states
9. **Use deterministic code where possible** — reserve LLM for tasks requiring judgment
10. **Plan for failures** — retry with backoff, graceful degradation, hallucination detection

---

## References

1. [OpenClaw Architecture Deep Dive — Towards AI, Feb 2026](https://pub.towardsai.net/openclaw-architecture-deep-dive-building-production-ready-ai-agents-from-scratch-e693c1002ae8)
2. [Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures — arXiv, Apr 2026](https://arxiv.org/html/2604.03515v1)
3. [Measuring AI Agent Autonomy in Practice — Anthropic, Feb 2026](https://www.anthropic.com/research/measuring-agent-autonomy)
4. [Agent Feedback Loops: From OODA to Self-Reflection — Tao An, Nov 2025](https://tao-hpu.medium.com/agent-feedback-loops-from-ooda-to-self-reflection-92eb9dd204f6)
5. [Strands Agents SDK — AWS Blog, Jul 2025](https://aws.amazon.com/blogs/machine-learning/strands-agents-sdk-a-technical-deep-dive-into-agent-architectures-and-observability/)
6. [Multi-Agent LLM Systems: Architecture, Communication, and Coordination — Samira Ghodratnama, Jun 2025](https://samiranama.com/posts/LLM-Based-Multi-Agent-Systems-Architectures-and-Collaboration/)
7. [A Taxonomy of Hierarchical Multi-Agent Systems — arXiv, Aug 2025](https://arxiv.org/html/2508.12683)
8. [Four Design Patterns for Event-Driven Multi-Agent Systems — Confluent, Feb 2025](https://www.confluent.io/blog/event-driven-multi-agent-systems/)
9. [Build a RAG Agent with NVIDIA Nemotron — NVIDIA Developer Blog, Sep 2025](https://developer.nvidia.com/blog/build-a-rag-agent-with-nvidia-nemotron/)
10. [NVIDIA NIM Function Calling Documentation](https://docs.nvidia.com/nim/large-language-models/latest/function-calling.html)
11. [VisionClaw: Always-On AI Agents Through Smart Glasses — arXiv, Apr 2026](https://arxiv.org/html/2604.03486v2)
12. [Nemotron-3-Super-120B-A12B Model Card — NVIDIA NIM](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard)
13. [Reflexion: Language Agents with Verbal Reinforcement Learning — Shinn et al., 2023](https://arxiv.org/abs/2303.11366)
14. [ReAct: Synergizing Reasoning and Acting in Language Models — Yao et al., 2023](https://arxiv.org/abs/2210.03629)
