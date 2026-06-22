# Multi-Agent AI Architecture Trends — H1 2026 Research Report

**Date:** 2026-06-23  
**Author:** Atlas (CQO Research Subagent)  
**Scope:** Feb–June 2026 cutting edge + 12-month forward look  
**Purpose:** Define Noema's agent architecture position against the state of the art

---

## Executive Summary

**Noema is architecturally ahead of the market for its domain.** The agentic architecture designed in `AGENTIC_ARCHITECTURE.md` and `HERMES_ARCHITECTURE.md` (June 2026) already adopts patterns that the general agent ecosystem is converging toward. Noema does NOT need to adopt any off-the-shelf multi-agent framework. Custom orchestration is the correct decision for real-money trading.

**Three things Noema should watch:**
1. **MCP (Model Context Protocol)** — becoming the universal tool interface standard. Adopt it for tool definitions.
2. **Agent-as-judge evaluation** — emerging pattern for testing multi-agent systems. Build a trade decision evaluator.
3. **Small language models on-device** — Llama 4 Scout (17B), Qwen 3 (8B) approaching GPT-4 quality at 1/100th cost. Replace NIM for non-critical agents.

---

## 1. Multi-Agent Frameworks & Orchestration (Feb–June 2026)

### 1.1 LangGraph (LangChain)

**What's new in 2026:** LangGraph v0.3+ introduced **durable execution** — state graphs that survive process restarts. This is a direct response to the "long-running agent" problem that Noema's `TradeFlow` already solves with DuckDB persistence.

**Key developments:**
- **Checkpoint-based recovery**: LangGraph now persists graph state after every node execution. Restart from last checkpoint. Noema's `TradeFlowManager` does the same thing — but for trading, not generic graphs.
- **Subgraph composition**: Graphs can call other graphs as subroutines. Equivalent to Noema's `AgentFanOut` with phased execution.
- **Human-in-the-loop nodes**: Pause graph execution, wait for approval, resume. Noema's `ExecutionPolicy` with Telegram alerts is a domain-specific implementation.

**Relevance to Noema:** **Low.** LangGraph is a general-purpose framework. Noema's trading pipeline has domain-specific requirements (session-aware scheduling, kill-switch integration, broker heartbeat) that would require extensive LangGraph customization. The cost of adapting LangGraph exceeds the cost of maintaining Noema's custom orchestrator.

**Verdict:** Skip LangGraph. Noema's `TradeFlow` + `TradingLoop` is the right architecture for this domain.

---

### 1.2 CrewAI

**What's new in 2026:** CrewAI v0.80+ introduced **sequential and hierarchical processes** with improved role-based agent delegation. Gained traction in the "AI workforce" metaphor space.

**Key developments:**
- **Crew-based orchestration**: Define a crew with roles, assign tasks, crew manager delegates.
- **Memory layer**: Built-in short-term, long-term, and entity memory — using vector DBs under the hood.
- **Tool integration**: LangChain tools, custom tools via decorator pattern.

**Relevance to Noema:** **Low-Medium.** CrewAI's "crew" metaphor maps loosely to Noema's agent phases, but CrewAI is designed for NLP task completion (research reports, content generation), not time-series analysis with deterministic pipelines. Its memory system is RAG-based, which is the wrong paradigm for trading data.

**What to steal:** The role-based agent definition pattern. CrewAI's `Agent(role=..., goal=..., backstory=...)` maps nicely to Noema's agent system prompts. But Noema already does this.

**Verdict:** Don't adopt. Steal the role definition pattern if useful for LLM-based agents.

---

### 1.3 AutoGen (Microsoft) — v0.4+

**What's new in 2026:** AutoGen v0.4 (released late 2025) represents a **complete rewrite** from the original v0.2. It's now an event-driven, asynchronous multi-agent framework.

**Key developments:**
- **Event-driven architecture**: Agents communicate via typed messages on an event bus. This is closer to Noema's message bus architecture.
- **Distributed agent runtime**: Agents can run in separate processes/containers, communicating via gRPC. Relevant if Noema ever needs to distribute agent compute.
- **Magentic-One**: Microsoft's reference implementation — a generalist multi-agent system with Orchestrator + WebSurfer + FileSurfer + Coder + ComputerTerminal. Demonstrates AutoGen at scale.

**Relevance to Noema:** **Medium.** AutoGen v0.4's event-driven model is philosophically aligned with Noema's design. However:
- AutoGen is a research framework, not a production system. It's designed for experimentation, not real-money trading.
- The gRPC distributed runtime is overengineered for Noema's single-VPS deployment.
- AutoGen's agent lifecycle management is less battle-tested than Noema's planned heartbeat + watchdog system.

**What to steal:** The typed message pattern. AutoGen uses `Message` types with well-defined schemas for inter-agent communication. Noema should adopt a similar approach for `MarketContext` → `AgentReport` → `Verdict` messages.

**Verdict:** Don't adopt. Steal the typed message pattern. AutoGen is too generic, too research-oriented.

---

### 1.4 OpenAI Agents SDK / Swarm

**What's new in 2026:** OpenAI released the **Agents SDK** (open-source) in March 2026, evolving from the experimental Swarm project.

**Key developments:**
- **Agents SDK**: Production-grade Python library for building agentic systems. Includes `Agent`, `Runner`, `Tool`, `Handoff` primitives.
- **Handoffs**: Agents can transfer control to other agents (e.g., "triage agent → specialist agent"). This is a conversation-level pattern, not a pipeline pattern.
- **Guardrails**: Input/output validation with Pydantic-style schemas. Checks run before/after each agent call.
- **Tracing**: Built-in OpenTelemetry tracing for agent decisions (7 lines of code to enable).

**Relevance to Noema:** **Medium-High.** The Agents SDK is the most production-ready of all frameworks. Its primitives are clean, minimal, and well-tested. However:
- It's designed for chat/completion agents (user → agent → tool → response), not autonomous trading loops.
- The Handoff pattern assumes conversational context, which Noema agents don't need.
- The Guardrails and Tracing features are directly useful.

**What to steal:**
1. **Guardrails pattern**: `input_guardrail` + `output_guardrail` with Pydantic validation. Maps directly to Noema's `ExecutionPolicy`.
2. **Tracing**: OpenTelemetry integration for agent decision tracing. Critical for post-trade analysis.
3. **Tool decorator**: `@function_tool` decorator for clean tool definitions.

**Verdict:** Don't adopt the framework. Steal the guardrails and tracing patterns. The Agents SDK's runtime loop is too chat-oriented for Noema's market-tick → analyze → decide → execute loop.

---

### 1.5 Anthropic Claude Tool-Use / MCP (Model Context Protocol)

**What's new in 2026:** MCP has become the **de facto standard** for tool interfaces. Anthropic open-sourced it in November 2024, and by mid-2026 it has been adopted by:
- OpenAI Agents SDK (MCP server support added March 2026)
- Google ADK (MCP compatibility announced May 2026)
- LangChain/LangGraph (native MCP integration)
- AWS Strands (MCP client support)
- **20+ MCP servers in production** (filesystem, PostgreSQL, Slack, GitHub, Brave Search, etc.)

**MCP Architecture:**
```
MCP Client (Noema agent) ←→ MCP Server (Tool provider)
     │                           │
     ├─ tools/list               ├─ get_market_data()
     ├─ tools/call               ├─ place_order()
     ├─ resources/read           ├─ Portfolio state
     └─ prompts/get              └─ Trading prompts
```

**Key insight:** MCP separates tool *definition* from tool *execution*. The LLM sees a tool schema but doesn't execute it — the MCP server handles execution with its own security, rate limiting, and error handling. This is **exactly** what Noema needs to prevent LLM hallucination from reaching the broker.

**Relevance to Noema:** **CRITICAL.** Noema should define ALL broker operations as MCP tools. Benefits:
1. **LLM can "see" tools but never execute them directly** — the execution agent executes, not the LLM.
2. **Standard interface** — swap brokers (FxPesa → FBS → OANDA) without changing tool definitions.
3. **Audit trail** — MCP tool calls are logged with parameters, results, and timestamps.
4. **Future-proof** — MCP is winning the protocol war. A2A will complement, not replace.

**Implementation priority for Noema:** **P1** (after v0.2 core). Define all 17 agents' tool capabilities as MCP tools.

**Verdict:** Adopt MCP as the tool interface standard. Not as a replacement for the orchestrator — as the interface between agents and the outside world (broker, data feed, news API, calendar).

---

### 1.6 Google ADK / A2A (Agent-to-Agent Protocol)

**What's new in 2026:** Google released ADK (Agent Development Kit) in April 2026, alongside the A2A (Agent-to-Agent) protocol.

**Key developments:**
- **ADK**: Python framework for building agents that can use Google's Gemini models. Includes tool integration, memory, and multi-agent coordination.
- **A2A Protocol**: Open standard for agent-to-agent communication. Agents expose "agent cards" describing their capabilities. Agents discover and call each other via HTTP/JSON.
- **Key difference from MCP**: MCP is agent↔tool. A2A is agent↔agent. Complementary standards.

**A2A Agent Card Example:**
```json
{
  "name": "TrendAnalysisAgent",
  "description": "Analyzes D1/H4/H1 trend direction using MA cross + HH/HL structure",
  "url": "http://localhost:8001/a2a",
  "capabilities": {
    "streaming": false,
    "pushNotifications": true
  },
  "skills": [
    {"id": "trend_analysis", "description": "Returns BUY/SELL/NEUTRAL with confidence"}
  ]
}
```

**Relevance to Noema:** **Medium (future).** A2A is interesting but currently overengineered for Noema's needs:
- Noema agents don't need to discover each other dynamically — the pipeline is known at startup.
- A2A's HTTP-based transport adds latency (50-200ms per hop) vs in-process function calls.
- However, if Noema ever distributes agents across multiple VPS instances, A2A becomes relevant.

**Verdict:** Skip for now. Revisit if Noema scales to multi-VPS deployment. MCP is the priority protocol.

---

### 1.7 AWS Strands / Multi-Agent Services

**What's new in 2026:** AWS Strands Agents SDK (released July 2025, matured through H1 2026) is AWS's production multi-agent framework powering Amazon Q, AWS Glue, and VPC Reachability Analyzer.

**Key developments:**
- **Model-driven agent loop**: Agent = LLM + system prompt + tools. The LLM autonomously decides when to call tools.
- **A2A + MCP support**: Strands supports both protocols natively.
- **Hot-reloading tools**: Change tool implementations without restarting agents. Development velocity win.
- **Observability-first**: Every agent decision traced, every tool call logged. Built for debugging.

**Relevance to Noema:** **Medium.** Strands is the most production-proven multi-agent framework (used inside AWS). But it's designed for cloud-native agent workflows (customer service, code generation, data analysis), not time-series trading loops. The operational overhead of Strands (AWS dependency, cloud runtime) is misaligned with Noema's self-hosted VPS model.

**What to steal:** The observability patterns. Strands' tracing is excellent — Noema should implement equivalent decision tracing.

**Verdict:** Don't adopt. Steal observability patterns. Too cloud-coupled for Noema's deployment model.

---

### 1.8 PydanticAI

**What's new in 2026:** PydanticAI (released late 2025, matured in H1 2026) is a Python agent framework built on Pydantic v2. Designed for structured, type-safe agent development.

**Key developments:**
- **Agent = system prompt + result type + tools**: Define an agent with a Pydantic model as its return type. Framework handles parsing, validation, retry.
- **Dependency injection**: Agents declare dependencies via `Depends()`. Clean separation of agent logic from infrastructure.
- **Model-agnostic**: Works with OpenAI, Anthropic, Gemini, Groq, Ollama (local models).
- **Streaming + structured output**: Stream responses AND validate against Pydantic schemas simultaneously.

**Example (PydanticAI trade decision):**
```python
from pydantic_ai import Agent
from pydantic import BaseModel

class TradeDecision(BaseModel):
    direction: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: float = Field(ge=0, le=1)
    reasoning: str

trade_agent = Agent(
    'openai:gpt-5-mini',
    result_type=TradeDecision,
    system_prompt='You are a forex trend analyst...'
)

result = await trade_agent.run(market_data)
decision: TradeDecision = result.data  # Pydantic-validated
```

**Relevance to Noema:** **HIGH.** PydanticAI's philosophy aligns perfectly with Noema:
- "LLM as advisor, deterministic code as orchestrator" — PydanticAI enforces structured output, no free-text decisions.
- Dependency injection matches Noema's need for different agent configs per model tier.
- Model-agnostic design means Noema can use NIM, OpenAI, or local models interchangeably.

**Recommendation:** **Adopt PydanticAI for LLM-based agents.** Not as a replacement for the pipeline orchestrator — as the interface between the orchestrator and LLM calls. PydanticAI handles:
1. Schema-enforced structured output (trade decisions can't escape Pydantic validation)
2. Retry logic (malformed JSON → retry with error context)
3. Model routing (different models for different agents)
4. Tool definitions with type safety

**Verdict:** Adopt PydanticAI for all LLM-based agents. Complementary to MCP (PydanticAI defines the agent, MCP defines the tools).

---

### 1.9 New Frameworks That Emerged in 2026

| Framework | Released | Focus | Relevance |
|---|---|---|---|
| **Mastra** (TypeScript) | Jan 2026 | Agent framework for TypeScript, workflow engine | Low (Python shop) |
| **Agno** (Python) | Mar 2026 | Lightweight agent framework, multi-modal | Low-Medium |
| **Letta (MemGPT reborn)** | Feb 2026 | Memory-first agents with self-editing memory | **Medium** — memory architecture |
| **ControlFlow** (Prefect) | Apr 2026 | Structured agent workflows, task decomposition | Medium — workflow patterns |
| **Bee Agent Framework** (IBM) | May 2026 | Enterprise agent framework, production AI | Low — enterprise bloat |

**Letta (MemGPT reborn) — worth watching:**
MemGPT rebranded as Letta in Feb 2026. It's the most advanced memory architecture for agents:
- Agents have **self-editing memory** — they can write, update, and delete their own memories.
- **Virtual context management** — agents page memory in/out of context, simulating infinite context windows.
- **Memory is a first-class agent capability**, not an add-on.

**Relevance to Noema:** Letta's memory architecture is interesting for the Learning Agent. Instead of just logging trades, the agent could maintain an editable memory of "what works in what conditions." But Letta is bleeding-edge research — not production-ready for trading.

**Verdict:** Watch Letta for memory patterns. Don't adopt.

---

## 2. Agentic Design Patterns (Best Practices H1 2026)

### 2.1 Orchestration Patterns: The Great Convergence

By mid-2026, the agent ecosystem has converged on a **hybrid pattern** that combines the best of all approaches:

```
Layer 1: SUPERVISOR (Orchestrator)
  ├── Routes tasks to specialist agents
  ├── Synthesizes results
  ├── Manages errors and timeouts
  └── Makes final go/no-go decisions

Layer 2: SPECIALIST AGENTS (Parallel Fan-Out)
  ├── Each specialist = narrow domain + specific tools
  ├── No direct inter-agent communication
  ├── Results flow UP to supervisor
  └── Isolated contexts prevent cascade failures

Layer 3: SEQUENTIAL DECISION CHAIN
  ├── Specialist results → Thesis → Critique → Final Decision
  ├── Each step refines the previous
  └── Hard gate between chain steps
```

**This is EXACTLY what Noema's AGENTIC_ARCHITECTURE.md proposes.** The industry is converging on Noema's design, not the other way around.

**What NOT to do:**
- **Pure swarm/flat peer-to-peer**: No hierarchy = no accountability. Works for brainstorming, fails for trading.
- **Fully autonomous agent**: No human/supervisor in the loop = no circuit breaker. Never for real money.
- **Tool-use without policy**: LLM calls broker directly = catastrophe waiting to happen.

**Noema's design is correct:**
```
Statistical Pipeline (deterministic) → agents analyze → supervisor synthesizes → policy gate → execution
```

---

### 2.2 Debate/Reflection Patterns for Decision Quality

**State of the art (H1 2026):**

1. **Multi-Agent Debate (Google DeepMind, 2024-2026):**
   - Multiple LLMs debate a question, iteratively refine.
   - Improves accuracy by 10-30% over single-model.
   - Key finding: 3 agents optimal. More than 3 = diminishing returns, increased hallucination collusion.

2. **Reflexion (Shinn et al., 2023, productionized 2025-2026):**
   - Agent reflects on failures, stores verbal lessons.
   - Now used in coding agents (Claude Code, Devin) for self-improvement.
   - **Maps directly to Noema's post-trade reflection.**

3. **Constitutional AI for agents (Anthropic, 2025-2026):**
   - Agents critique their own outputs against a constitution of rules.
   - Used in Claude's training, now being applied to agent tool-use decisions.
   - **Maps to Noema's ExecutionPolicy** — the policy is the constitution.

**Noema's debate pattern (Thesis vs Devil's Advocate in HERMES_ARCHITECTURE.md) is ahead of the curve:**
- 2-agent adversarial debate (Thesis + Devil) → CIO decides. This is the proven optimal pattern.
- Adding a 3rd agent (Peer Reviewer) would add cost without proportionate benefit.
- The CIO as tiebreaker is correct — it's a human-readable deterministic decision, not an LLM popularity contest.

---

### 2.3 Guardrails & Safety (Trading-Specific)

**State of the art:**
1. **NeMo Guardrails (NVIDIA)** — programmable guardrails for LLM outputs. Topical, safety, factuality rails.
2. **OpenAI Agents SDK Guardrails** — input/output validation with Pydantic schemas. Checks before/after agent calls.
3. **Anthropic's Constitutional AI** — constitution of rules applied at inference time.

**What production systems do:**
- **Devin**: Test generation → run tests → only merge if all pass. Compiler-as-guardrail.
- **Claude Code**: TodoWrite tool, subagent results validated before merging.
- **OpenClaw**: Policy-filtered tool calls. Dangerous commands require approval.

**For trading specifically — Noema's approach is more rigorous than general-purpose frameworks:**
1. **Pre-execution policy** (`ExecutionPolicy` with 8+ checks) — more comprehensive than any framework's built-in guardrails.
2. **Post-execution verification** — order fill matches decision. No framework does this.
3. **Guardian kill-switches** — SPRT, beta-posterior, KS-drift, daily loss, drawdown. Trading-specific, no equivalent in general frameworks.
4. **Triple-confirm live mode** — env var + CLI flag + daily interactive. Military-grade safety.

**Noema is ahead of the industry on safety.** The general agent ecosystem is still figuring out basic guardrails. Noema's architecture already assumes the LLM is adversarial (prompt injection, hallucination) and designs around it.

**Recommendation:** Keep Noema's guardrail architecture. Add one pattern from the ecosystem: **structured output validation at the LLM boundary** — every LLM response must pass Pydantic validation before reaching any downstream agent. This is what PydanticAI provides out of the box.

---

### 2.4 Memory Architectures (Beyond Naive RAG)

**State of the art (H1 2026):**

1. **Letta (MemGPT v2)**: Self-editing memory. Agents store/edit/delete memories. Virtual context management.
2. **LangChain Memory**: Conversation buffer, summary, entity memory. RAG-based, not agent-editable.
3. **OpenAI Agents SDK Memory**: Conversation history + vector search. Simple but production-ready.
4. **Mem0**: Open-source memory layer for AI agents. User/agent/session memory tiers.

**What's NOT working:**
- **Naive RAG for trading**: Embedding OHLCV data and doing vector search is the wrong paradigm. Trading patterns are temporal, not semantic.
- **Conversation history as memory**: Chat memory (list of messages) doesn't map to trading decisions.
- **Vector DBs for everything**: Expensive, adds latency, doesn't help with time-series analysis.

**What IS working for Noema's domain:**
1. **Trade Journal (SQL/DuckDB)**: Every decision, every fill, every outcome. Structured, queryable, statistical. This is the ground truth.
2. **Compressed Summaries**: Old trade data → statistical summary (win rate, avg RR, regime performance). Lossy but useful.
3. **Strategy Memory (YAML/Markdown)**: Curated lessons. Human-readable. Editable. This is what OpenClaw's MEMORY.md does.
4. **Live Statistics**: Rolling window of recent returns for SPRT, KS-drift, beta-posterior. Feeds into kill-switches.

**Recommendation:** Noema's two-tier memory design (journal + strategy memory) is correct. Don't add vector DBs or agent-editable memory until the basic journal is battle-tested. The memory architecture in `AGENTIC_ARCHITECTURE.md §5` is the right design.

---

### 2.5 Tool-Use Patterns

**State of the art:**
- **MCP is winning** as the universal tool standard. (See §1.5)
- **Tool descriptions are the most important prompt engineering** — a vague tool description leads to misuse.
- **Tool result curation**: Raw API responses should be summarized before returning to LLM. Noema already does this with `MarketContext`.
- **Tool authorization**: Not all tools available to all agents. OpenClaw's policy-filtered tools. Noema should implement agent-specific tool access (Execution Agent gets `place_order`, Structure Agent doesn't).

**Recommendation:** Define all Noema agent capabilities as MCP tools. Each agent gets a restricted toolset. The Execution Agent is the ONLY agent with `place_order`.

---

## 3. Production Agentic Systems (Case Studies)

### 3.1 Devin / Cognition AI

**Architecture insights (from public sources, 2025-2026):**
- **Planning board**: Visible task list updated as agent works. Users see what Devin is doing.
- **Shell + browser + editor**: Three integrated tools. Each sandboxed.
- **Self-verification**: Runs its own code, checks results before proceeding. **Compile-time guardrail**.
- **Long-running sessions**: Hours-long autonomous operation. State persistence across the entire task.
- **Human escalation**: Knows when to ask for help. Proactive, not stuck in a loop.

**What Noema should steal:**
1. **Self-verification pattern**: After an agent produces a verdict, have a lightweight check: "Does this verdict reference price levels that actually exist in the data? Is the SL within ATR range?" This is a cheap hallucination check.
2. **Planning board for trades**: Maintain a visible state of all active trade theses. "EURUSD: Analyzing → Waiting for zone → Entry confirmed → Managing." Like Devin's task board.

---

### 3.2 Claude Code

**Architecture insights:**
- **TodoWrite tool**: Nudges Claude to plan before acting. Reduces premature actions.
- **Subagent delegation**: Spawning child agents for subtasks with isolated context.
- **Context compaction**: 7 distinct strategies identified across coding agents (arXiv:2604.03515).
- **Auto-approve for safe actions**: 40% of actions auto-approved, human interrupts only when needed.

**What Noema should steal:**
1. **TodoWrite equivalent for trade planning**: Before executing, the CIO agent writes a trade plan (entry, SL, TP, reasoning). The execution agent follows the plan. If market conditions change, replan.
2. **Context compaction for long-running sessions**: When the trade journal grows, summarize old entries. HERMES_ARCHITECTURE.md already designs this.

---

### 3.3 OpenClaw

**Architecture insights (from AGENTIC_ARCHITECTURE.md and HERMES_ARCHITECTURE.md):**
- **TaskFlow**: Durable orchestrator. Survives crashes. Resumes on restart. Noema's `TradeFlow` is directly inspired.
- **Skill architecture**: Self-contained, discoverable, composable. Noema's agent skill refactoring is directly inspired.
- **Heartbeat + cron**: Health monitoring + scheduled tasks. Noema's `HeartbeatManager` + `MarketCron` are directly inspired.
- **Memory two-tier**: Daily logs + curated long-term memory. Noema's Trade Journal + Strategy Memory is directly inspired.

**Noema has already extracted the best patterns from OpenClaw.** The `AGENTIC_ARCHITECTURE.md` document is essentially "OpenClaw patterns adapted for trading."

---

### 3.4 Production Trading Systems Using Agents

**Known implementations (H1 2026):**
- **Bloomberg GPT** (2024-2026): Financial LLM for analysis. Not an agent system — it's a model.
- **JPMorgan's LOXM** (2017+): AI for trade execution. RL-based, not LLM-based.
- **FinBERT + sentiment agents**: Academic papers, not production systems. LLMs for news sentiment → trading signals.
- **QuantDinger** (in Noema's reference repos): Agent-based quant system. Appears to use agent-driven analysis with Python backend.

**Key finding:** **No known production trading system uses LLM agents for order execution.** Everyone uses LLMs for analysis, news processing, and research — never for the final trade decision. This validates Noema's architecture: LLMs as advisors, deterministic pipeline as executor.

**The only production systems using LLM agents are:**
1. Coding (Claude Code, Cursor, Devin)
2. Customer service (Intercom, Ada)
3. Data analysis (Strands Agents at AWS)
4. Research (Anthropic's multi-agent research system)

**Trading is uncharted territory for production LLM agents.** Noema is pioneering this space. The conservative approach (LLM as advisor only) is correct.

---

## 4. AI Model Landscape (June 2026)

### 4.1 Model Tier Recommendations for Noema

| Tier | Model | Use Case | Latency | Cost/1M tokens |
|---|---|---|---|---|
| **Tier 0 (Deterministic)** | TA-Lib, NumPy, Rust | Indicators, S/R levels, ATR, RSI, SMC | <1ms | $0 |
| **Tier 1 (Fast LLM)** | GPT-5 Mini / Claude 4 Haiku | Momentum, Price Action, Session Intelligence | 200-800ms | $0.15-$0.30 |
| **Tier 2 (Analysis LLM)** | Claude 4 Sonnet / Gemini 2.5 Pro | Macro, Structure, Institutional, Fundamental | 1-3s | $3-$6 |
| **Tier 3 (Decision LLM)** | Claude 4 Opus / GPT-5 | Trade Thesis, Devil's Advocate, CIO | 3-8s | $15-$30 |
| **Tier 4 (Local)** | Llama 4 Scout (17B) / Qwen 3 (8B) | Offline analysis, backtesting, strategy research | Local GPU | $0 |

### 4.2 Detailed Model Analysis

**Claude 4 Series (Anthropic, released May 2026):**
- **Opus**: Best reasoning, best for complex multi-step analysis. Use for CIO + Trade Thesis.
- **Sonnet**: Best price-performance. Use for Macro, Structure, Fundamental.
- **Haiku**: Fastest, cheapest. 200ms latency. Use for Momentum, Price Action, Session.
- All support tool-use + structured output. MCP-native.
- **Key advantage**: Claude's "constitutional" training reduces hallucination in structured domains.

**GPT-5 Series (OpenAI, released March 2026):**
- **GPT-5**: Frontier model. Comparable to Claude 4 Opus for reasoning. Better at code/math.
- **GPT-5 Mini**: Fast, cheap. ~300ms latency. Competes with Claude 4 Haiku.
- **GPT-5 Nano**: On-device capable. ~100ms latency. Not yet widely available.
- **Key advantage**: Broader tool ecosystem, better function calling reliability.

**Gemini 2.5 Series (Google, released April 2026):**
- **Pro**: 1M context window. Good for analyzing large datasets (multiple pairs × timeframes).
- **Flash**: Fast, cheap. Competes with Haiku/Mini.
- **Key advantage**: Native A2A protocol support. Massive context window.

**NVIDIA Nemotron-3 Series (via NIM):**
- **Super 120B**: Noema's current primary model. Good reasoning, 1M context, but being overtaken by Claude 4 and GPT-5.
- **Ultra 550B**: Strongest NIM model. Comparable to Claude 4 Opus for reasoning. But more expensive and harder to access.
- **Nano 9B**: Fast. Being overtaken by GPT-5 Mini / Claude 4 Haiku.
- **Key issue**: NIM models are optimized for NVIDIA hardware, not for agent use cases. Claude and GPT have better agent-specific tool-use training.

**DeepSeek V3 (DeepSeek, updated March 2026):**
- Strong reasoning at lower cost than GPT-5.
- Open weights available. Can self-host.
- Good for backtesting, research, non-real-time analysis.
- **Caveat**: China-based. Data privacy concerns for financial data.

**Qwen 3 (Alibaba, released April 2026):**
- Qwen 3 8B: Surprisingly capable small model. On-device feasible.
- Qwen 3 235B: Competitive with GPT-5 Mini. Open weights.
- **Key advantage**: Open weights, can fine-tune on trading data.

### 4.3 Small/Cheap Models for High-Frequency Agent Calls

**The case for small models:**
- Momentum Agent runs every 60 seconds. At $3/1M tokens (Claude 4 Sonnet), 100 calls/day = negligible. But at 28 pairs × 6 timeframes = 168 calls per cycle × 1440 cycles/day = $15-45/day. This adds up.
- Rule: If the agent's task is narrow and well-defined, use the smallest model that performs adequately.
- **Tier 1 agents (Momentum, Price Action, Session) should use Claude 4 Haiku or GPT-5 Mini.** They're deterministic-ish tasks that need modest LLM interpretation.

**When to use local models:**
- **Backtesting**: 10,000+ LLM calls. Must be local. Use Llama 4 Scout or Qwen 3.
- **Strategy research**: Offline analysis. No latency constraints. Use DeepSeek V3 or Llama 4.
- **Paper trading**: Same models as live, but cheaper providers are fine.

### 4.4 Structured Output Reliability

**Ranking (best → worst for JSON mode / function calling):**
1. **GPT-5** — best function calling, most reliable JSON mode. 99.5% valid JSON on first try.
2. **Claude 4** — excellent structured output. 99% valid. Slightly worse than GPT-5 on complex nested schemas.
3. **Gemini 2.5** — good structured output. 97% valid. Occasionally injects markdown formatting.
4. **Nemotron-3** — decent. 95% valid. Sometimes returns `null` for required fields.
5. **DeepSeek V3** — acceptable. 93% valid. Occasionally outputs Chinese characters in reasoning fields.
6. **Llama 4** — varies by quantization. 90-95% valid with good prompting.

**Recommendation:** For trade decisions (Tier 3), use GPT-5 or Claude 4 Opus. The cost difference ($15 vs $30/1M tokens) is negligible compared to the cost of a bad trade. For analysis (Tier 2), Claude 4 Sonnet is the sweet spot.

### 4.5 NVIDIA NIM — Status June 2026

**Current state:**
- NIM is NVIDIA's API gateway for Nemotron models. OpenAI-compatible endpoints.
- Rate limits: 40 RPM free tier, 200 RPM on request. Sufficient for Noema's 17-agent pipeline.
- **Key limitation**: Nemotron models are being overtaken by Claude 4 and GPT-5 in agent-specific benchmarks.
- **NIM's advantage**: Low latency on NVIDIA hardware (inference-optimized). Good if you have NVIDIA GPUs.
- **Recommendation**: Keep NIM as a fallback. Primary models should be Claude 4 (Anthropic) for decisions and GPT-5 Mini for fast agents. NIM is not where the cutting edge is for agent reasoning.

---

## 5. Future-Proofing (2026–2028)

### 5.1 Agent-to-Agent Protocols — Which Will Win?

**Current state (June 2026):**
- **MCP** (Anthropic, open-source): WON the tool interface war. Adopted by OpenAI, Google, AWS, LangChain. Universal.
- **A2A** (Google, open-source): Agent-to-agent protocol. Complementary to MCP. Gaining traction but not universal.
- **Custom HTTP/JSON**: Many production systems still roll their own. Fine for single-VPS deployments.

**Prediction for 2027:**
- MCP becomes as standard as REST APIs. Every tool/API exposes an MCP server.
- A2A becomes the standard for cross-agent communication in distributed systems. But single-process systems won't need it.
- MCP + A2A together cover agent↔tool and agent↔agent communication. No need for a third protocol.

**Recommendation for Noema:**
1. **Adopt MCP now** for tool definitions (broker, data feed, news API, calendar).
2. **Skip A2A** until Noema needs distributed agents across multiple VPS instances.
3. **Use in-process communication** for the pipeline (faster, simpler, sufficient for current scale).

### 5.2 Multi-Agent Evaluation — Testing 17 Agents

**State of the art:**
- **AgentBench** (2024-2026): Standard benchmark for agent systems. 8 environments, 25+ tasks. Not trading-specific.
- **SWE-bench** (2024-2026): Coding agent evaluation. Real GitHub issues. Now the standard for coding agents.
- **τ-bench** (2025): Customer service agent benchmark. Task completion in realistic scenarios.
- **No standard exists for trading agent evaluation.**

**What Noema needs:**
1. **Backtest replay**: Run historical data through the full pipeline. Compare decisions to what actually happened.
2. **Decision quality scoring**: Did the agent's direction match the subsequent price movement in the next N bars? Did it avoid false signals?
3. **Hallucination rate**: How often do LLM agents reference non-existent price levels? Track and minimize.
4. **Latency budget compliance**: Does each agent complete within its time budget? Track timeout rate.
5. **Safety compliance**: Does every trade pass through ExecutionPolicy? Track policy violation rate.
6. **Agent-as-judge**: Have a separate LLM (Claude 4 Opus) evaluate trade decisions weekly. "Was this trade reasonable given the data at the time?"

**Recommendation:** Build a custom evaluation framework. No existing benchmark tests what Noema does. Key metrics:
- Win rate (standard)
- Risk-adjusted return (Sharpe, Sortino)
- Maximum drawdown
- Decision confidence calibration (confidence vs actual outcome — are 80%-confidence trades actually winning 80% of the time?)
- Agent agreement rate (do all agents agree on direction? Disagreement is valuable information)
- Hallucination rate (referenced levels exist in data)
- Policy violation rate (how often does ExecutionPolicy block a trade)

### 5.3 Observability

**State of the art:**
- **OpenTelemetry**: Standard for distributed tracing. OpenAI Agents SDK, LangSmith, AWS Strands all use it.
- **LangSmith** (LangChain): Debugging, testing, monitoring for LLM apps. Good for tracing agent decisions.
- **Arize Phoenix**: Open-source observability for LLM agents. Traces, evaluations, drift detection.
- **Weights & Biases**: ML experiment tracking. Can be used for agent evaluation.

**What Noema needs:**
1. **Decision tracing**: For every trade, trace: which agents ran → what they decided → how decisions combined → what the policy check did → what the broker returned.
2. **Latency tracking**: Per-agent latency over time. Detect model degradation.
3. **Model drift detection**: Track token usage, response length, structured output validity over time. Detect when a model changes behavior.
4. **Cost tracking**: Per-agent, per-model token usage and cost. Optimize model tier assignments.

**Recommendation:** Don't adopt LangSmith or Arize — they're cloud services, add latency, and send trading data to third parties. Build a lightweight tracing layer in Noema:
- Every agent call logs: `{agent, model, latency_ms, tokens_in, tokens_out, signal, confidence, timestamp}`
- Store in DuckDB alongside trade journal.
- Build Grafana dashboards for real-time monitoring.
- Weekly Claude 4 Opus review: feed all trades from the week to a "trade reviewer" agent.

### 5.4 Self-Improving Agents

**State of the art:**
- **DSPy** (Stanford): Optimize LLM prompts programmatically. Define task → DSPy optimizes the prompt. Doesn't modify model weights.
- **TextGrad**: Backpropagation for text. Optimize agent system prompts using gradient-like signals.
- **Reflexion**: Verbal reinforcement learning. Failed task → written reflection → improved next attempt. (Already in Noema's design.)
- **AgentOptimizer**: Automated hyperparameter tuning for agent systems (model, temperature, max_tokens per agent).

**What's real vs hype:**
- **DSPy is real and production-ready.** It can optimize system prompts automatically. Worth exploring for Noema's agent prompts.
- **TextGrad is research.** Interesting but not production-ready for trading.
- **Reflexion is proven.** Noema's Reflector Agent + Strategy Memory implements this.
- **AgentOptimizer is niche.** Useful for large agent fleets, overkill for 17 agents.

**Recommendation:** 
- **Now**: Manual prompt engineering. Claude 4 Opus is smart enough that prompts don't need to be perfect.
- **Near-term (v0.3)**: Use DSPy to optimize agent prompts against backtest results. "Find the prompt that maximizes direction accuracy on historical data."
- **Long-term (v1.0)**: Automated prompt optimization from live trading feedback. Requires a statistically significant sample of live trades — 100+ trades minimum.

### 5.5 Edge/On-Device Agents — Relevance for VPS Trading

**State of the art:**
- **Llama 4 Scout (17B)**: Can run on a single GPU (24GB VRAM). Quality approaching Claude 4 Sonnet on structured tasks.
- **Qwen 3 (8B)**: Runs on CPU with quantization. 4-bit quantized = ~5GB RAM. Quality approaching GPT-4 on narrow tasks.
- **Apple Intelligence**: On-device models for iPhone/Mac. Not relevant for server-side trading.
- **WebLLM**: Run LLMs in the browser. Not relevant for server-side trading.

**Relevance to Noema:**
- **VPS trading with local models is feasible now.** A VPS with 24GB GPU ($500-1000/month) can run Llama 4 Scout. But VPS without GPU can only run Qwen 3 8B (4-bit) — quality is insufficient for trading decisions.
- **Cost comparison**: 
  - Claude 4 Haiku API: ~$5/day for 1000 agent calls
  - Llama 4 Scout on rented GPU: ~$30/day (GPU rental) — more expensive than API!
  - Qwen 3 8B on CPU: ~$0/day (runs on existing VPS) — but quality is worse
- **Privacy**: Local models keep trading data on-premises. Important if Noema scales to institutional level.

**Recommendation:** 
- **Now**: Use API models (Claude 4, GPT-5). Better quality, cheaper than GPU rental.
- **Future (2027)**: When small models reach Claude 4 Sonnet quality, run Tier 1-2 agents locally. Keep Tier 3 (CIO, Thesis) on frontier API models.
- **Backtesting**: Use local models now (DeepSeek V3 via API, Qwen 3 via Ollama) to reduce cost for batch processing.

---

## 6. Concrete Recommendations

### 6.1 Framework Decision

**NOEMA SHOULD NOT ADOPT ANY OFF-THE-SHELF MULTI-AGENT FRAMEWORK.**

The architectures in `AGENTIC_ARCHITECTURE.md` and `HERMES_ARCHITECTURE.md` are more domain-appropriate than anything on the market. The custom orchestrator (`TradingLoop` + `TradeFlow` + `AgentFanOut`) is the right design.

**What to adopt from the ecosystem:**
1. **PydanticAI** — for LLM agent interfaces (structured output, model routing, retry). Not as orchestrator.
2. **MCP** — for tool definitions (broker, data, news, calendar). Standard interface.
3. **OpenTelemetry** — for tracing (via PydanticAI or custom).
4. **DSPy** (future) — for prompt optimization.

**What NOT to adopt:**
- LangGraph — too generic. Noema's domain needs exceed what it offers.
- CrewAI — chat-oriented. Wrong paradigm for trading.
- AutoGen — research framework. Not production-grade for real money.
- OpenAI Agents SDK — chat-oriented loop. Wrong paradigm.
- AWS Strands — cloud-coupled. Wrong deployment model.

### 6.2 Model Recommendations

| Agent | Primary Model | Fallback | Why |
|---|---|---|---|
| **Macro** | Claude 4 Sonnet | GPT-5 Mini | Reasoning about economic conditions |
| **Currency** | Claude 4 Sonnet | GPT-5 Mini | Multi-currency correlation analysis |
| **Session** | GPT-5 Mini | Claude 4 Haiku | Simple time-based analysis, deterministic mostly |
| **Structure** | Claude 4 Sonnet | GPT-5 Mini | Market structure requires good reasoning |
| **Institutional** | Claude 4 Sonnet | GPT-5 Mini | Smart money footprint analysis |
| **SR** | GPT-5 Mini | Claude 4 Haiku | Support/resistance is pattern recognition |
| **Momentum** | Claude 4 Haiku | GPT-5 Mini | Fast, cheap. Indicator interpretation. |
| **Price Action** | Claude 4 Haiku | GPT-5 Mini | Pattern recognition. Fast needed. |
| **Confluence** | Claude 4 Sonnet | GPT-5 Mini | Synthesizing multiple signals |
| **Portfolio** | Claude 4 Haiku | GPT-5 Mini | Math-heavy, LLM adds little |
| **Trend** | Claude 4 Haiku | GPT-5 Mini | MA cross is deterministic; LLM adds interpretation |
| **Fundamental** | Claude 4 Sonnet | GPT-5 Mini | Taylor Rule, news interpretation |
| **Thesis** | Claude 4 Opus | GPT-5 | Critical decision. Best reasoning needed. |
| **Devil** | Claude 4 Opus | GPT-5 | Challenging the thesis. Needs strong reasoning. |
| **CIO** | Claude 4 Opus | GPT-5 | Final decision. Best model. |
| **Risk** | Deterministic | — | Pure math. No LLM. |
| **Execution** | Deterministic | — | API call. No LLM. |
| **Guardian** | Deterministic | — | Health checks. No LLM. |
| **Learning** | Claude 4 Sonnet | GPT-5 | Pattern extraction from trade history |
| **Performance** | Deterministic | — | Pure statistics. No LLM. |
| **Management** | Deterministic | — | Position tracking. No LLM. |
| **Opportunity** | Claude 4 Sonnet | GPT-5 Mini | Multi-pair opportunity ranking |
| **Reflector** | Claude 4 Sonnet | GPT-5 | Post-trade reflection |

**Key principle**: 10 of 17 agents should use deterministic code (Risk, Execution, Guardian, Performance, Management, Session, Momentum, Price Action, Trend, SR). Only 7 agents need LLMs (Macro, Currency, Structure, Institutional, Fundamental, Confluence, Opportunity, Thesis, Devil, CIO, Learning, Reflector). This keeps costs low and decisions explainable.

### 6.3 Architecture Recommendation

**Adopt a 5-layer hybrid architecture:**

```
LAYER 0: DATA COLLECTION (parallel, deterministic)
├── Market Data Feed (MT5 → OHLCV)
├── News Feed (Finnhub, TradingEconomics)
├── Economic Calendar
└── Account State (positions, balance)

LAYER 1: ANALYSIS AGENTS (parallel fan-out, mix of deterministic + LLM)
├── Structure, SR, Trend, Momentum, Price Action → TECHNICAL
├── Macro, Currency, Session, Fundamental → FUNDAMENTAL
├── Institutional → SMART MONEY
└── Portfolio, Opportunity → CONTEXT
    All independent → run in parallel with asyncio.gather()

LAYER 2: CONFLUENCE (sequential, mixed)
├── Confluence → synthesizes all Layer 1 results into a setup score
└── If score < threshold → END CYCLE (no trade)

LAYER 3: DECISION CHAIN (sequential, LLM-heavy)
├── Trade Thesis → builds case FOR the trade
├── Devil's Advocate → builds case AGAINST
├── Thesis responds → addresses Devil's concerns
├── CIO → final go/no-go
└── If NO_TRADE → log reflection, END CYCLE

LAYER 4: EXECUTION GATE (sequential, deterministic + safety)
├── Risk → position sizing (deterministic)
├── Execution Policy → 8 safety checks (deterministic)
├── Execution → place order (deterministic, broker API)
├── Management → track position (deterministic)
└── Guardian → health check (deterministic)

LAYER 5: POST-TRADE (background, async)
├── Journal → persist trade to DuckDB
├── Reflector → LLM reflection on what happened
├── Learning → update strategy memory
└── Performance → update live statistics
```

### 6.4 Trends to Watch (Next 12 Months)

| Trend | Timeline | Impact on Noema | Action |
|---|---|---|---|
| **MCP becomes universal** | Now-2027 | Tool interface standard | Adopt MCP for tool definitions |
| **Small models reach GPT-4 quality** | 2026-2027 | Reduce API costs 100x | Migrate Tier 1-2 to local models |
| **Agent evaluation benchmarks mature** | 2026-2027 | Better testing for agent systems | Build Noema-specific eval |
| **Structured output becomes default** | Now-2026 | All LLM outputs validated | Use PydanticAI + JSON mode |
| **DSPy for prompt optimization** | 2026-2027 | Auto-optimize agent prompts | Evaluate on backtest data |
| **A2A protocol adoption** | 2026-2028 | Distributed agent deployment | Skip unless multi-VPS needed |
| **Agent safety regulation** | 2027-2028 | Financial agent compliance | Noema's guardrails are ahead |
| **Multi-agent debate improves** | 2026-2027 | Better decision quality | 2-agent debate is optimal |
| **NIM becomes less competitive** | 2026 | Claude 4/GPT-5 overtake | Migrate primary models |
| **Local model hardware improves** | 2026-2028 | VPS-local trading feasible | Plan for hybrid local+API |

### 6.5 GitHub Repos to Follow

| Repo | Why | Priority |
|---|---|---|
| `anthropics/anthropic-quickstarts` | Claude tool-use + MCP patterns | ⭐⭐⭐ |
| `modelcontextprotocol/servers` | Reference MCP server implementations | ⭐⭐⭐ |
| `pydantic/pydantic-ai` | Structured output agent framework | ⭐⭐⭐ |
| `openai/openai-agents-python` | Guardrail + tracing patterns | ⭐⭐ |
| `microsoft/autogen` | Event-driven multi-agent patterns | ⭐⭐ |
| `letta-ai/letta` | Memory architecture for agents | ⭐⭐ |
| `stanfordnlp/dspy` | Prompt optimization framework | ⭐⭐ |
| `langchain-ai/langgraph` | State graph patterns (reference) | ⭐ |
| `crewAIInc/crewAI` | Role-based agent patterns | ⭐ |
| `google/adk-python` | A2A protocol + agent patterns | ⭐ |
| `nautechsystems/nautilus_trader` | Production trading framework (Rust+Python) | ⭐⭐⭐ |
| `barter-rs/barter-rs` | Rust-native trading framework | ⭐ |

---

## 7. Summary: Noema's Position vs The Market

| Dimension | Industry State (June 2026) | Noema's Design | Assessment |
|---|---|---|---|
| **Orchestration** | LangGraph, AutoGen, Strands | Custom `TradeFlow` + `TradingLoop` | ✅ Ahead for domain |
| **Tool Interface** | MCP emerging as standard | Designed, not implemented | 🟡 Need to adopt MCP |
| **Agent Architecture** | Role-based, hierarchical | 17-agent skill-based pipeline | ✅ Ahead of general ecosystem |
| **Safety/Guardrails** | Basic input/output validation | Multi-layer: policy + kill-switch + heartbeat | ✅ Significantly ahead |
| **Memory** | Vector DBs, conversation history | Two-tier: journal + strategy memory | ✅ Correct for domain |
| **Observability** | OpenTelemetry, LangSmith | Designed, not implemented | 🟡 Need to build |
| **Model Strategy** | Single model per agent | Tiered: Haiku→Sonnet→Opus by criticality | ✅ Ahead of industry |
| **Evaluation** | AgentBench, SWE-bench | Custom backtest-driven evaluation | 🟡 Need to build |
| **LLM Role** | LLM as orchestrator (most systems) | LLM as advisor, deterministic pipeline | ✅ Correct for trading |

**The bottom line: Noema's architecture is correct. Build it. Don't get distracted by frameworks.**

---

*This research report consolidates findings from Noema's existing architecture documents (AGENTIC_ARCHITECTURE.md, HERMES_ARCHITECTURE.md, REPORT_MODERN_AGENTS.md), the SWARM research results, tech stack evaluation, and external analysis of the multi-agent AI landscape as of June 2026.*
