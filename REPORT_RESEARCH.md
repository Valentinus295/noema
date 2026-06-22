# Noema Agentic Systems Research Report

**Date:** 2026-06-17  
**Scope:** Architecture, frameworks, LLM integration, and infrastructure for a multi-agent forex trading system  
**Repository:** `noema` (v0.1.0, ~6,700 lines Python)

---

## Table of Contents

1. [Current AI Agentic Frameworks (2025–2026)](#1-current-ai-agentic-frameworks-20252026)
2. [NVIDIA NIM / API Endpoint Integration](#2-nvidia-nim--api-endpoint-integration)
3. [Multi-Agent Communication Patterns](#3-multi-agent-communication-patterns)
4. [LLM Integration Best Practices for Trading](#4-llm-integration-best-practices-for-trading)
5. [Observability & Monitoring](#5-observability--monitoring)
6. [Testing AI Agent Systems](#6-testing-ai-agent-systems)
7. [Deployment & Infrastructure](#7-deployment--infrastructure)
8. [Recommended Architecture](#8-recommended-architecture)

---

## 1. Current AI Agentic Frameworks (2025–2026)

### 1.1 The Landscape at a Glance

The agentic framework ecosystem has exploded since 2024. The major contenders as of mid-2026:

| Framework | Philosophy | Multi-Agent | Structured Output | Best For |
|-----------|-----------|-------------|-------------------|----------|
| **LangChain/LangGraph** | Graph-based DAG orchestration | ✅ Sub-graphs | ✅ via Pydantic | Complex multi-step workflows |
| **CrewAI** | Role-based collaboration | ✅ Crew/Task/Agent | ✅ | Team-of-agents workflows |
| **AutoGen (Microsoft)** | Conversational multi-agent | ✅ Group chat | ✅ | Research, debate-style |
| **OpenAI Agents SDK** | OpenAI-native agent runtime | ✅ Handoffs | ✅ Native | OpenAI-ecosystem projects |
| **Google ADK** | Declarative agent definition | ✅ Built-in | ✅ | Gemini-ecosystem projects |
| **PydanticAI** | Type-safe, minimal | ✅ via deps | ✅ Native Pydantic | Production Python agents |
| **Agno (PhiData)** | Lightweight, modular | ✅ Teams/Coordinator | ✅ | Fast prototyping, multimodal |
| **Smolagents (HF)** | Code-centric, minimal | ❌ Limited | ✅ | Simple code-execution agents |
| **Mastra** | TypeScript-first | ✅ | ✅ | JS/TS agent platforms |

*Sources: [Langfuse Agent Comparison (Mar 2025)](https://langfuse.com/blog/2025-03-19-ai-agent-comparison), [ZenML LangGraph Alternatives (Jun 2025)](https://www.zenml.io/blog/langgraph-alternatives)*

### 1.2 Deep Evaluation for Noema

#### LangChain / LangGraph — ⚠️ Overkill, High Risk

**What it is:** LangGraph extends LangChain into a graph-based agent orchestration system where each step is a node in a directed acyclic graph. LangChain itself is the most popular LLM framework (60K+ GitHub stars).

**Pros:**
- Massive ecosystem, extensive integrations
- Graph visualization and debugging tools
- LangSmith integration for observability
- Pydantic-based structured output

**Cons (critical for Noema):**
- **API instability:** LangChain's APIs change week-to-week. Tutorials break within months. Multiple production teams report constant breakage ([ZenML, 2025](https://www.zenml.io/blog/langgraph-alternatives)). For a trading system managing real money, this is unacceptable.
- **Over-abstracted:** 5+ layers of indirection between your code and the LLM call. Debugging a bad trade signal through LangGraph's state objects, sub-graphs, and decorators is nightmarish.
- **Heavy dependency tree:** LangChain pulls in hundreds of transitive dependencies. Noema's current lean stack (`structlog`, `pydantic`, `polars`, `duckdb`) would be polluted.
- **Performance overhead:** Single-threaded by default; true concurrency requires LangGraph Server (managed cloud or self-hosted).
- **Already rejected by Noema:** The `pyproject.toml` puts `langgraph>=0.4` in the `v2` optional dependency group with the note: *"Quality + security delta reviews rejected these as v0.x core deps."* This was the right call.

**Verdict: Do NOT adopt.** The overhead-to-value ratio is terrible for a trading system. Noema needs determinism and speed, not framework abstractions.

#### CrewAI — ❌ Not Recommended

**What it is:** Role-based multi-agent framework where you define "Crews" of agents with roles, goals, and backstories, then let them collaborate.

**Pros:**
- Intuitive role-based design
- Built-in task delegation
- Good for brainstorming/research workflows

**Cons:**
- **Designed for LLM-first workflows:** Noema's agents are 90% deterministic (TA-Lib, polars, duckdb). Only the fundamental analysis agent needs LLM. CrewAI assumes every agent is an LLM agent.
- **Opinionated orchestration:** CrewAI decides how agents talk to each other. Noema needs explicit control over the 12-phase pipeline.
- **No backpressure or latency guarantees:** Not designed for time-critical systems.
- **Adds dependency weight** for minimal benefit.

**Verdict: Wrong paradigm.** CrewAI is for "team of LLM agents collaborating." Noema is "team of deterministic analysts with optional LLM narration."

#### AutoGen (Microsoft) — ❌ Not Recommended

**What it is:** Multi-agent conversation framework where agents communicate through structured conversations, including "group chat" patterns.

**Pros:**
- Strong research backing (Microsoft Research)
- Good for debate-style reasoning (Devil's Advocate fits!)
- Supports tool use and code execution

**Cons:**
- **Conversation-based overhead:** Every interaction is a "chat message." For Noema's `AgentReport` with structured `signal`, `confidence`, `data` fields, this is unnecessary wrapping.
- **Latency:** Multi-turn conversations add latency. Trading decisions need sub-second.
- **Complexity:** Group chat manager, speaker selection, conversation summarization — all overhead Noema doesn't need.

**Verdict: Wrong abstraction level.** Interesting for research, not for production trading.

#### OpenAI Agents SDK — ⚠️ Consider for LLM-Only Agents

**What it is:** OpenAI's official agent framework with native support for handoffs, tools, and structured output.

**Pros:**
- Clean API, well-documented
- Native structured output via Pydantic
- Good for function calling / tool use

**Cons:**
- OpenAI-centric (Noema wants NVIDIA NIM)
- Still evolving rapidly

**Verdict: Could work for the LLM narration layer only**, but adds an OpenAI dependency you'd need to abstract away. Prefer using the OpenAI-compatible client directly.

#### PydanticAI — ✅ RECOMMENDED (Lightweight LLM Layer)

**What it is:** A minimal, type-safe agent framework built by the Pydantic team. Agents are Python functions with Pydantic-validated inputs/outputs. ([pydantic.dev](https://pydantic.dev/))

**Pros:**
- **Native Pydantic integration:** Noema already uses Pydantic 2.6+ everywhere. PydanticAI fits like a glove.
- **Type-safe structured output:** Define your output schema as a Pydantic model, get validated results. No prompt gymnastics.
- **Model-agnostic:** Works with OpenAI, Anthropic, Google, and any OpenAI-compatible endpoint (NVIDIA NIM).
- **Lightweight:** Minimal dependencies, no graph abstractions, no state machines. Just Python functions with type validation.
- **Dependency injection:** Built-in system for injecting runtime context (broker connections, config, etc.)
- **Tool use:** Agents can call Python functions as tools, validated by Pydantic.
- **Production-ready:** PydanticAI + Logfire (Pydantic's observability tool) gives tracing out of the box.

**Cons:**
- Newer than LangChain, smaller community
- No built-in multi-agent orchestration (you provide your own)
- No graph/workflow abstraction

**Verdict: Best fit for Noema.** Use PydanticAI as the LLM interaction layer for the FundamentalBiasAgent and Devil's Advocate LLM mode. Keep the rest of the system as-is (deterministic agents). PydanticAI adds ~2 dependencies and provides exactly what's needed: type-safe LLM calls with structured output.

#### Agno (formerly PhiData) — ⚠️ Viable Alternative

**What it is:** Lightweight framework for building modular, autonomous AI agents. Supports multi-agent teams with Coordinator, Route, and Collaboration modes. ([github.com/agno-agi/agno](https://github.com/agno-agi/agno))

**Pros:**
- Very lightweight, fast setup
- Multi-agent team modes (Coordinator, Route, Collaboration)
- Streaming support via Model Context Protocol (MCP)
- NVIDIA integration (featured in NVIDIA NeMo Agent Toolkit)

**Cons:**
- Less mature than PydanticAI for type safety
- Team orchestration is still opinionated
- Adds abstractions Noema doesn't need

**Verdict: Good framework, but PydanticAI is better for Noema's needs** because Noema already has its own orchestration and just needs a clean LLM interface.

#### LlamaIndex — ❌ Not Needed Now

**What it is:** Framework for connecting LLMs to external data (RAG).

**Verdict:** Noema's `KnowledgeBase` is a JSON file of trade outcomes, not a vector database. If RAG is needed later (e.g., for economic research documents), LlamaIndex could be added, but it's not needed for the current scope.

#### BAML (Boundary ML) — ✅ Worth Considering for Structured Output

**What it is:** A domain-specific language for defining typed LLM functions. You define types and functions in `.baml` files, and it generates type-safe Python clients. ([github.com/BoundaryML/baml](https://github.com/BoundaryML/baml))

**Why it matters for Noema:** The agentic trading system article ([Pau Labarta Bajo, May 2025](https://paulabartabajo.substack.com/p/lets-build-an-agentic-trading-platform)) specifically recommends BAML over LangChain for financial sentiment extraction because it makes "fast prompt experimentation easier" and provides guaranteed structured output.

**Verdict: Strong alternative to PydanticAI for the structured output use case.** Choose one: BAML if you want a dedicated prompt engineering workflow, PydanticAI if you want to stay in pure Python.

### 1.3 Framework Recommendation Summary

| Component | Recommendation | Rationale |
|-----------|---------------|-----------|
| Orchestration | **Keep hand-rolled asyncio** | Noema's sequential pipeline + MessageBus is appropriate for 7-17 agents |
| LLM calls | **PydanticAI** | Type-safe, lightweight, Pydantic-native, model-agnostic |
| Structured output | **Pydantic models** (via PydanticAI) | Already in the stack, zero migration |
| Multi-agent coordination | **Keep MessageBus** | Add backpressure + optional persistence (see §3) |
| Prompt engineering | **BAML** (optional) | If prompt iteration velocity becomes critical |

---

## 2. NVIDIA NIM / API Endpoint Integration

### 2.1 What is NVIDIA NIM?

**NVIDIA NIM** (NVIDIA Inference Microservices) is NVIDIA's platform for deploying and serving AI models. It provides:

- **API Catalog** ([build.nvidia.com](https://build.nvidia.com)): Hosted inference endpoints for popular open-source models (Llama 3.x, Mixtral, Nemotron, etc.)
- **Self-hosted NIM containers:** Deploy optimized model serving on your own GPU infrastructure
- **OpenAI-compatible API:** All NIM endpoints accept OpenAI SDK calls

*Source: [NVIDIA NIM Product Page](https://www.nvidia.com/en-us/ai-data-science/products/nim-microservices/)*

### 2.2 Available Models (2025–2026)

From NVIDIA's API Catalog, the most relevant models for financial analysis:

| Model | Size | Best For | Latency | Cost |
|-------|------|----------|---------|------|
| **Nemotron 3 Super 120B** | 120B (12B active MoE) | Complex reasoning, analysis | Medium | $$$ |
| **Nemotron 3 Nano 30B** | 30B (3B active MoE) | Fast inference, simple tasks | Low | $ |
| **Llama 3.3 70B** | 70B | General purpose, good reasoning | Medium | $$ |
| **Llama 3.1 8B** | 8B | Fast classification, simple extraction | Very Low | $ |
| **Mixtral 8x22B** | MoE | Multi-lingual, complex reasoning | Medium | $$ |
| **Mistral Large** | Large | Instruction following | Medium | $$ |

*Source: [build.nvidia.com model catalog](https://build.nvidia.com)*

### 2.3 Integration: OpenAI-Compatible Client

NVIDIA NIM endpoints are **OpenAI-compatible**. This means Noema's existing `openai>=1.40` dependency works directly:

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="nvapi-xxxx",  # from build.nvidia.com
)

response = await client.chat.completions.create(
    model="nvidia/llama-3.3-70b-instruct",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.1,  # Low temp for financial analysis
    max_tokens=1024,
)
```

### 2.4 Best Practices for Trading Systems

#### Rate Limiting & Retries

```python
import asyncio
from openai import AsyncOpenAI, RateLimitError, APITimeoutError

class NIMClient:
    """Resilient NVIDIA NIM client with rate limiting and fallback."""
    
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=os.environ["NVIDIA_API_KEY"],
            timeout=30.0,
            max_retries=3,  # Built-in retry with exponential backoff
        )
        self._semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
    
    async def complete(self, messages, model="nvidia/llama-3.3-70b-instruct", **kwargs):
        async with self._semaphore:
            try:
                return await self.client.chat.completions.create(
                    model=model, messages=messages, **kwargs
                )
            except RateLimitError:
                await asyncio.sleep(2)  # Back off
                return await self.client.chat.completions.create(
                    model=model, messages=messages, **kwargs
                )
```

#### Model Selection Strategy (Model Routing)

Use cheaper/faster models for simple tasks, expensive models for complex reasoning:

| Task | Model | Rationale |
|------|-------|-----------|
| Sentiment classification | Llama 3.1 8B | Simple enum output, <100ms |
| News summarization | Nemotron 3 Nano 30B | Good quality, fast |
| Fundamental analysis narration | Llama 3.3 70B or Nemotron Super 120B | Complex reasoning needed |
| Devil's Advocate critique | Nemotron Super 120B | Needs strong adversarial reasoning |

#### Latency Optimization

For trading systems, latency is critical:

1. **Streaming:** Use `stream=True` for narration agents to start displaying results immediately
2. **Batch non-critical calls:** Learning agent analysis can be batched after market close
3. **Cache aggressively:** Same news → same bias (see §4.6)
4. **Use smaller models:** 8B models respond in <200ms on NIM; 70B models in 1-3s
5. **Pre-warm:** Keep a warm connection pool; don't create clients per-request

#### Fallback Strategy

```
Primary: NVIDIA NIM (build.nvidia.com)
  ↓ (on failure)
Secondary: Self-hosted NIM on local GPU (if available)
  ↓ (on failure)
Tertiary: Skip LLM narration, use deterministic output only
  ↓ (on failure)
Degraded: Log warning, continue pipeline without fundamental narration
```

**Critical design principle:** LLM narration is **advisory only**. The deterministic pipeline must never depend on LLM availability. The `ConfluenceConfig.llm_review_enabled: bool = False` flag already implements this pattern.

### 2.5 LiteLLM Proxy as Router/Aggregator

**LiteLLM** is a Python library/proxy that provides a unified interface to 100+ LLM providers. For Noema:

**When to use LiteLLM:**
- If you need to route across multiple providers (NVIDIA NIM + OpenAI + Anthropic)
- If you want a single API key management layer
- If you need usage tracking across models

**When NOT to use LiteLLM:**
- Noema only needs NVIDIA NIM → direct OpenAI client is simpler
- Adds a proxy layer (latency + complexity)
- Another dependency to maintain

**Verdict:** Skip LiteLLM for now. Use the OpenAI client directly with NVIDIA NIM. Add LiteLLM later if multi-provider routing becomes necessary.

### 2.6 Cost Estimation

NVIDIA API Catalog pricing (approximate, 2025–2026):

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| Llama 3.1 8B | $0.20 | $0.20 |
| Llama 3.3 70B | $0.80 | $0.80 |
| Nemotron Super 120B | $1.20 | $1.20 |

**Estimated daily usage for Noema:**
- 5 pairs × 4 analyses/day × ~2K tokens each = ~40K tokens/day
- At Llama 3.3 70B rates: ~$0.03/day → ~$1/month
- With Devil's Advocate LLM mode: ~2x → ~$2/month

**NVIDIA free tier:** build.nvidia.com offers 1,000 free API calls/day — more than enough for Noema's current scale.

---

## 3. Multi-Agent Communication Patterns

### 3.1 Pattern Comparison

| Pattern | Latency | Durability | Complexity | Noema Fit |
|---------|---------|-----------|------------|----------|
| **In-process Pub/Sub** (current) | ~0ms | ❌ None | Low | ✅ Good |
| **Redis Pub/Sub** | ~1ms | ❌ None | Medium | ⚠️ Overkill |
| **Redis Streams** | ~1ms | ✅ Persistent | Medium | ✅ Good for audit |
| **NATS** | <1ms | ✅ JetStream | Medium | ✅ Best option |
| **ZeroMQ** | <0.1ms | ❌ None | High | ⚠️ Low-level |
| **Actor Model (Ray)** | ~1ms | ❌ None | High | ❌ Overkill |
| **Event Sourcing** | Variable | ✅ Full history | High | ⚠️ Future consideration |
| **Blackboard** | Variable | ✅ Shared state | Medium | ✅ Good for collaborative reasoning |

### 3.2 Current Architecture Assessment

Noema's current `MessageBus` is an in-process async pub/sub with `asyncio.Queue`. This is **appropriate for the current scale** (7-17 agents, single process). The issues identified in `REPORT_ARCHITECTURE.md` are:

1. **No backpressure** — unbounded queue
2. **No persistence** — fire-and-forget
3. **Not actually used** — `main.py` calls agents sequentially via `await agent.process(context)`

### 3.3 Recommended Pattern: Hybrid Pub/Sub + Shared Context

For a trading system with 7-17 agents, the optimal pattern is:

```
┌─────────────────────────────────────────────────────┐
│                  Shared Context (Blackboard)          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐  │
│  │ market  │ │ signals │ │ reports │ │ decisions │  │
│  │  data   │ │         │ │         │ │          │  │
│  └─────────┘ └─────────┘ └─────────┘ └──────────┘  │
└─────────────────────────────────────────────────────┘
         ↑ write              ↑ read    ↑ write
    ┌─────────┐         ┌─────────┐  ┌─────────┐
    │  Feed   │  ──pub──│  Bus    │──│ Executor│
    │  Agent  │         │ (async) │  │  Agent  │
    └─────────┘         └─────────┘  └─────────┘
```

**Key design:**
1. **Shared Context (Blackboard):** A typed `PipelineContext` dataclass that agents read from and write to. This is the "blackboard" pattern — agents contribute their analysis to a shared state.
2. **MessageBus for events:** Use pub/sub for lifecycle events (trade_executed, session_start, error) and notifications.
3. **Sequential pipeline for analysis:** Keep `main.py`'s sequential agent invocation for the 12-phase pipeline. This ensures deterministic ordering.

### 3.4 Should You Add NATS/Redis?

**No, not yet.** Here's why:

- **Single process:** Noema runs as a single Python process. NATS/Redis add network hops.
- **No horizontal scaling need:** 17 agents in one process is fine.
- **Audit trail:** Instead of Redis Streams, use DuckDB (already in the stack) for event persistence.

**When to add NATS:**
- If you split agents into separate processes/containers
- If you need to scale horizontally (multiple instances analyzing different pairs)
- If you need cross-machine communication (e.g., signal from analysis server to execution server)

### 3.5 Recommended MessageBus Improvements

```python
# Add to core/message_bus.py

class MessageBus:
    def __init__(self, max_queue_size: int = 1000) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=max_queue_size)
        self._history: list[Message] = []  # Optional: keep last N messages
        self._max_history = 10_000
    
    async def publish(self, message: Message) -> None:
        # Backpressure: if queue is full, drop oldest or block
        if self._queue.full():
            logger.warning("message_bus_backpressure", topic=message.topic)
            try:
                self._queue.get_nowait()  # Drop oldest
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(message)
        
        # Persist to history for audit
        self._history.append(message)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
```

---

## 4. LLM Integration Best Practices for Trading

### 4.1 Structured Output (Pydantic Schemas)

**Always use Pydantic models for LLM output.** Never parse free-form text for trading signals.

```python
from pydantic import BaseModel, Field
from enum import Enum

class Bias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class FundamentalNarration(BaseModel):
    """Structured output from the FundamentalBiasAgent LLM narration."""
    bias: Bias
    confidence: float = Field(ge=0.0, le=1.0)
    key_factors: list[str] = Field(max_length=5)
    risk_events: list[str] = Field(max_length=3)
    reasoning: str = Field(max_length=500)
    source_quality: float = Field(ge=0.0, le=1.0, description="Quality of input data")

class DevilsAdvocateCritique(BaseModel):
    """Structured output from the Devil's Advocate LLM mode."""
    verdict: Bias  # BULLISH = trade looks good, BEARISH = reject
    confidence: float = Field(ge=0.0, le=1.0)
    failure_modes: list[str] = Field(max_length=5)
    counter_arguments: list[str] = Field(max_length=3)
    recommendation: str  # "PROCEED" | "REJECT" | "REDUCE_SIZE"
```

**Why this matters:**
- Noema's `AgentReport.signal` must be "BULLISH", "BEARISH", or "NEUTRAL" — no room for hallucinated strings
- Pydantic validation catches malformed LLM output before it reaches the trading pipeline
- Structured output enables deterministic downstream processing

### 4.2 Function Calling / Tool Use

**Should Noema agents have tools?** Yes, but selectively:

| Agent | Tools | Rationale |
|-------|-------|-----------|
| FundamentalBiasAgent | `get_economic_calendar()`, `get_news_sentiment()` | LLM needs real data to reason about |
| DevilsAdvocateAgent | `get_historical_win_rate()`, `get_correlation_matrix()` | Needs data to build counter-arguments |
| LearningAgent | `query_trade_history()`, `calculate_pattern_stats()` | Analytical tools for pattern recognition |
| All other agents | None | Deterministic, no LLM needed |

**Implementation with PydanticAI:**

```python
from pydantic_ai import Agent, RunContext

fundamental_agent = Agent(
    'nvidia/llama-3.3-70b-instruct',  # Via NVIDIA NIM
    result_type=FundamentalNarration,
    system_prompt="You are a macroeconomic analyst for forex trading...",
)

@fundamental_agent.tool
async def get_economic_calendar(ctx: RunContext[Depends], currency: str) -> list[dict]:
    """Get upcoming economic events for a currency."""
    return await ctx.deps.calendar.get_events(currency)
```

### 4.3 RAG for Economic Knowledge Base

**Current state:** Noema's `KnowledgeBase` (`models/knowledge.py`) is a JSON file tracking trade outcomes. It's not a knowledge base in the RAG sense — it's a statistics accumulator.

**When RAG becomes valuable:**
- If you want to feed economic research papers, central bank statements, or analyst reports to the LLM
- If you want the Devil's Advocate to cite historical precedents

**Recommendation: Defer RAG.** The current deterministic pipeline + NVIDIA NIM for narration is sufficient. Add RAG later if:
1. You accumulate a corpus of >100 relevant documents
2. The LLM needs domain-specific knowledge it doesn't have from training
3. You want to cite specific sources in trade rationale

**If you add RAG later:**
- Use **ChromaDB** or **Qdrant** (lightweight, local) for vector storage
- Use **sentence-transformers** for embeddings (local, no API cost)
- Keep it separate from the trading pipeline — RAG is a preprocessing step

### 4.4 Prompt Engineering for Financial Analysis

**Principles:**

1. **Role-based prompts:** "You are a senior macro analyst at a hedge fund" > "Analyze this data"
2. **Structured instructions:** Always specify output format, max length, and constraints
3. **Context injection:** Feed real market data, not summaries
4. **Adversarial prompting:** For Devil's Advocate — "Your job is to find reasons this trade will FAIL"
5. **Temperature control:** 0.0-0.2 for analysis, 0.3-0.5 for creative reasoning

**Example prompt for FundamentalBiasAgent:**

```
You are a macroeconomic analyst specializing in G10 forex.

Given the following economic data for {currency_pair}:
- Latest NFP: {nfp_actual} (forecast: {nfp_forecast}, prior: {nfp_prior})
- Latest CPI: {cpi_actual} (forecast: {cpi_forecast})
- Central bank stance: {cb_stance}
- Yield differential: {yield_diff}%

Provide your analysis as structured output:
1. Directional bias (bullish/bearish/neutral for the base currency)
2. Confidence level (0-1)
3. Key factors (max 5)
4. Upcoming risk events (max 3)

Be concise. This feeds into an automated trading system.
```

### 4.5 LLM Caching Strategy

**Critical insight:** "Same news → same bias, don't re-compute."

```python
import hashlib
import json
from datetime import datetime, timedelta

class LLMCache:
    """Cache LLM responses to avoid re-computing identical analyses."""
    
    def __init__(self, ttl_hours: int = 4):
        self._cache: dict[str, tuple[datetime, Any]] = {}
        self._ttl = timedelta(hours=ttl_hours)
    
    def _key(self, model: str, messages: list[dict]) -> str:
        content = json.dumps({"model": model, "messages": messages}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    async def get_or_compute(self, model, messages, compute_fn):
        key = self._key(model, messages)
        if key in self._cache:
            ts, result = self._cache[key]
            if datetime.now() - ts < self._ttl:
                return result  # Cache hit
        
        result = await compute_fn()
        self._cache[key] = (datetime.now(), result)
        return result
```

**Cache invalidation rules:**
- **News analysis:** Cache for 4 hours (news doesn't change, but market reaction evolves)
- **Devil's Advocate:** Do NOT cache (each trade is unique)
- **Learning agent:** Do NOT cache (historical analysis changes with new data)

### 4.6 Guardrails

1. **Output validation:** Pydantic models catch malformed output (see §4.1)
2. **Confidence clamping:** Never trust LLM confidence > 0.9 for financial analysis — cap at 0.85
3. **Hallucination detection:** If LLM mentions specific numbers not in the input data, reject
4. **Fallback to deterministic:** If LLM output fails validation, fall back to the deterministic bias score (already implemented in `_compute_bias_score()`)
5. **Human-in-the-loop:** For high-stakes decisions (large position sizes), flag for human review

### 4.7 Model Routing

Implement a simple router that selects models based on task complexity:

```python
class ModelRouter:
    """Route LLM calls to appropriate models based on task complexity."""
    
    MODELS = {
        "simple": "nvidia/llama-3.1-8b-instruct",      # <200ms, cheap
        "medium": "nvidia/nemotron-3-nano-30b-a3b",     # ~500ms, balanced
        "complex": "nvidia/llama-3.3-70b-instruct",     # ~2s, high quality
    }
    
    def select_model(self, task_type: str) -> str:
        mapping = {
            "sentiment_classification": "simple",
            "news_summary": "medium",
            "fundamental_analysis": "complex",
            "devils_advocate": "complex",
            "learning_insight": "medium",
        }
        return self.MODELS[mapping.get(task_type, "medium")]
```

---

## 5. Observability & Monitoring

### 5.1 LLM Observability Tools Comparison

| Tool | Open Source | Best For | Cost |
|------|------------|----------|------|
| **Langfuse** | ✅ MIT | Multi-step agent debugging | Free self-hosted |
| **LangSmith** | ❌ | LangChain users | $39/seat/mo |
| **Arize Phoenix** | ✅ | OpenTelemetry integration | Free |
| **Helicone** | ✅ | Fastest setup, caching | Free tier |
| **Portkey** | ✅ | Multi-provider routing | Free tier |
| **W&B Weave** | ✅ | MLOps experiment tracking | Free tier |
| **Pydantic Logfire** | ❌ | PydanticAI tracing | Free tier |

*Source: [Firecrawl Best LLM Observability Tools 2026](https://www.firecrawl.dev/blog/best-llm-observability-tools)*

### 5.2 Recommended Stack for Noema

**Layer 1: System Metrics → Prometheus + Grafana**
- Already have `prometheus-client>=0.21` in dependencies
- Track: agent latency, message bus throughput, trade execution time, error rates
- Grafana dashboards for real-time monitoring

**Layer 2: Structured Logging → structlog (already in stack)**
- Noema already uses structlog — excellent
- Add correlation IDs to trace a single trade decision across all 17 agents
- Log to JSON for machine parsing, console for human readability

**Layer 3: LLM Tracing → Langfuse (self-hosted)**
- Open source (MIT), self-hostable
- Trace every LLM call: prompt, response, latency, token count, cost
- Debug why the LLM gave a particular bias assessment
- Works with any OpenAI-compatible client (NVIDIA NIM)

**Layer 4: Trade Audit Trail → DuckDB**
- Already in the stack
- Store every trade decision, agent reports, market conditions
- Queryable for post-mortem analysis

### 5.3 Structured Logging Best Practices

```python
import structlog

logger = structlog.get_logger(__name__)

# Every log entry should include:
logger.info(
    "agent_analysis_complete",
    agent="fundamental-bias",
    pair="EURUSD",
    signal="BULLISH",
    confidence=0.72,
    latency_ms=145,
    llm_model="nvidia/llama-3.3-70b-instruct",
    llm_tokens_in=512,
    llm_tokens_out=128,
    pipeline_phase="fundamental",
    trade_id="abc123",  # Correlation ID
)
```

---

## 6. Testing AI Agent Systems

### 6.1 Testing Strategy for Noema

| Layer | Approach | Tools |
|-------|----------|-------|
| **Unit tests** | Test deterministic logic in isolation | pytest, hypothesis |
| **LLM tests** | Mock LLM responses for CI, real LLM for integration | pytest + VCR/cassettes |
| **Integration tests** | Full pipeline with paper broker | pytest-asyncio + PaperBroker |
| **Property-based tests** | Financial calculations always produce valid ranges | hypothesis |
| **Chaos tests** | Broker disconnection, API failures | pytest + fault injection |
| **Backtests** | Historical data replay | Custom + polars |
| **Statistical validation** | SPRT, bootstrap (already in stack) | scipy, numpy |

### 6.2 Testing LLM-Dependent Agents

**Strategy: Three-tier testing**

```python
# Tier 1: Unit test with mocked LLM (fast, deterministic, CI-safe)
@pytest.fixture
def mock_llm_response():
    return FundamentalNarration(
        bias=Bias.BULLISH,
        confidence=0.72,
        key_factors=["NFP beat", "hawkish Fed"],
        risk_events=["CPI release tomorrow"],
        reasoning="Strong labor market supports USD",
        source_quality=0.8,
    )

async def test_fundamental_agent_with_mock(mock_llm_response):
    agent = FundamentalBiasAgent(llm_client=MockLLM(mock_llm_response))
    report = await agent.analyze(sample_context)
    assert report.signal == "BULLISH"
    assert 0.5 <= report.confidence <= 0.85

# Tier 2: Integration test with real LLM (slower, non-deterministic, nightly)
@pytest.mark.integration
async def test_fundamental_agent_real_llm():
    agent = FundamentalBiasAgent()  # Uses real NVIDIA NIM
    report = await agent.analyze(sample_context)
    assert report.signal in ("BULLISH", "BEARISH", "NEUTRAL")
    assert isinstance(report.confidence, float)

# Tier 3: Backtest with historical data (offline, comprehensive)
def test_backtest_2024():
    results = run_backtest(year=2024, pairs=["EURUSD", "GBPUSD"])
    assert results.sharpe_ratio > 0.5
    assert results.max_drawdown < 0.10
```

### 6.3 Property-Based Testing for Financial Calculations

```python
from hypothesis import given, strategies as st

@given(
    actual=st.floats(min_value=-10, max_value=10),
    forecast=st.floats(min_value=-10, max_value=10),
    prior=st.floats(min_value=-10, max_value=10),
)
def test_sentiment_always_returns_valid_direction(actual, forecast, prior):
    result = _determine_sentiment(actual, forecast, prior)
    assert result in (Direction.BULLISH, Direction.BEARISH, Direction.NEUTRAL)

@given(
    risk_pct=st.floats(min_value=0.01, max_value=5.0),
    balance=st.floats(min_value=100, max_value=1_000_000),
    sl_pips=st.floats(min_value=1, max_value=500),
)
def test_lot_size_calculation_bounds(risk_pct, balance, sl_pips):
    lot_size = calculate_lot_size(risk_pct, balance, sl_pips)
    assert 0.01 <= lot_size <= 100.0  # Sanity bounds
```

### 6.4 Chaos Engineering for Broker Connections

```python
@pytest.fixture
def flaky_broker():
    """Broker that randomly disconnects."""
    class FlakyBroker(PaperBroker):
        async def execute_order(self, order):
            if random.random() < 0.1:  # 10% failure rate
                raise ConnectionError("MT5 disconnected")
            return await super().execute_order(order)
    return FlakyBroker()

async def test_execution_agent_handles_broker_failure(flaky_broker):
    agent = ExecutionAgent(broker=flaky_broker)
    # Should retry or gracefully degrade, not crash
    for _ in range(100):
        report = await agent.analyze(sample_order_context)
        assert report.signal in ("EXECUTED", "FAILED", "RETRYING")
```

### 6.5 Statistical Validation

Noema already has SPRT (Sequential Probability Ratio Test) and bootstrap in the stack. These are **the right choices**:

- **SPRT:** Ideal for online testing — determines as early as possible whether a strategy is profitable or not, without needing a fixed sample size
- **Bootstrap:** Non-parametric confidence intervals for Sharpe ratio, win rate, etc.

**Additional recommendation:** Add **walk-forward optimization** to prevent overfitting:
- Train on 12 months, test on 3 months, roll forward
- This is standard in quantitative trading

---

## 7. Deployment & Infrastructure

### 7.1 Docker Containerization

**Recommended Dockerfile structure:**

```dockerfile
# Multi-stage build
FROM python:3.11-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libta-lib0-dev && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

FROM deps AS runtime
COPY . .
CMD ["python", "-m", "noema.main"]
```

**Wine + MT5 in Docker:**
- Use a **separate container** for Wine + MT5
- Expose MT5 via RPyC (already the pattern in `broker/mt5.py`)
- This isolates the fragile Wine dependency from the main trading logic

### 7.2 Process Management

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **systemd** | Simple, built-in, auto-restart | Single machine | ✅ Current scale |
| **supervisor** | Easy config, web UI | Single machine | ✅ Alternative |
| **Kubernetes** | Scaling, self-healing, rolling updates | Complexity, cost | ⚠️ Future |
| **Docker Compose** | Multi-container, easy | No auto-scaling | ✅ Good middle ground |

**Recommendation:** **Docker Compose** for development and single-server production. Migrate to Kubernetes only if you need multi-server deployment.

```yaml
# docker-compose.yml
services:
  noema:
    build: .
    restart: always
    environment:
      - NVIDIA_API_KEY=${NVIDIA_API_KEY}
      - MT5_LOGIN=${MT5_LOGIN}
    depends_on:
      - mt5bridge
      - prometheus
    volumes:
      - ./data:/app/data
      - ./config:/app/config

  mt5bridge:
    build: ./docker/mt5-wine
    restart: always
    ports:
      - "18861:18861"  # RPyC port

  prometheus:
    image: prom/prometheus
    volumes:
      - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
```

### 7.3 Wine + MT5 Alternatives

| Option | Pros | Cons | Cost |
|--------|------|------|------|
| **Wine + MT5 (current)** | No extra cost, runs on Linux | Fragile, Wine quirks, RPyC overhead | $0 |
| **Windows VPS** | Native MT5, reliable | Extra server, network hop | $10-30/mo |
| **MT5 Web API** | No Wine needed | Limited features, not all brokers | Broker-dependent |
| **cTrader/cAlgo** | Better API, .NET native | Different broker ecosystem | Migration cost |
| **Interactive Brokers** | Professional API, Python native | Different market (not pure forex) | $0 API |

**Recommendation:** Keep Wine + MT5 for now (it works). Document the Wine setup carefully. If Wine becomes too unstable, consider a **Windows VPS** ($10-30/mo on Hetzner/Contabo) running MT5 natively, connected via RPyC over VPN.

### 7.4 CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: Noema CI
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff mypy && ruff check . && mypy .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync --extra dev
      - run: uv run pytest tests/ -x --ignore=tests/integration

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install detect-secrets pip-audit
      - run: detect-secrets scan && pip-audit
```

### 7.5 Feature Flags

Noema already has `ConfluenceConfig.llm_review_enabled: bool = False`. Extend this pattern:

```python
class FeatureFlags(BaseModel):
    """Feature flags for gradual rollout."""
    llm_narration: bool = False          # LLM fundamental analysis
    llm_devils_advocate: bool = False    # LLM trade critique
    llm_learning_insights: bool = False  # LLM pattern analysis
    advanced_risk: bool = False          # PCA/correlation risk
    paper_trading: bool = True           # Paper vs live execution
    
    # Rollout percentage (0-100)
    llm_narration_pct: int = 0           # % of trades using LLM narration
```

---

## 8. Recommended Architecture

### 8.1 Architecture Pattern: Deterministic Pipeline + Advisory LLM Layer

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Noema Trading System                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Orchestrator (main.py)                      │  │
│  │  Sequential 12-phase pipeline with shared PipelineContext      │  │
│  └───────────────────────────────────────────────────────────────┘  │
│           │                                                         │
│  ┌────────▼──────────────────────────────────────────────────────┐  │
│  │              Phase 1-8: Deterministic Analysis                 │  │
│  │  Macro → Trend → Structure → S/R → OrderBlocks → RSI → Candle│  │
│  │  (TA-Lib, polars, duckdb — NO LLM)                           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│           │                                                         │
│  ┌────────▼──────────────────────────────────────────────────────┐  │
│  │           Phase 9: Confluence + Optional LLM Review           │  │
│  │  ┌─────────────────┐  ┌────────────────────────────────────┐  │  │
│  │  │ Deterministic   │  │ LLM Advisory (PydanticAI + NIM)   │  │  │
│  │  │ Confluence Score│→ │ FundamentalNarration (if enabled)  │  │  │
│  │  │ (weights, TA)   │  │ Devil'sAdvocateCritique (if enabled│  │  │
│  │  └─────────────────┘  └────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│           │                                                         │
│  ┌────────▼──────────────────────────────────────────────────────┐  │
│  │           Phase 10-12: Risk → Execution → Learning            │  │
│  │  RiskManager → ExecutionAgent → PerformanceAgent → Learning   │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Infrastructure Layer                        │  │
│  │  MessageBus (events) │ KnowledgeBase │ DuckDB (audit)        │  │
│  │  Prometheus (metrics)│ structlog (logs)│ Langfuse (LLM trace)│  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    External Services                           │  │
│  │  MT5 (Wine/RPyC) │ NVIDIA NIM API │ finnhub (news)          │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 Recommended Tech Stack

| Component | Current | Recommended | Change? |
|-----------|---------|-------------|---------|
| **Language** | Python 3.11+ | Python 3.11+ | No change |
| **Async** | asyncio + uvloop | asyncio + uvloop | No change |
| **Message Bus** | In-process asyncio | In-process asyncio (improved) | Minor improvements |
| **Data** | polars + duckdb | polars + duckdb | No change |
| **Config** | pydantic + pydantic-settings | pydantic + pydantic-settings | No change |
| **Logging** | structlog | structlog | No change |
| **Metrics** | prometheus-client | prometheus-client + Grafana | Add Grafana |
| **Broker** | MT5 via RPyC/Wine | MT5 via RPyC/Wine | No change |
| **Technical Analysis** | TA-Lib | TA-Lib | No change |
| **LLM Client** | openai (planned) | openai + PydanticAI | Add PydanticAI |
| **LLM Provider** | TBD | NVIDIA NIM (build.nvidia.com) | New |
| **LLM Observability** | None | Langfuse (self-hosted) | New |
| **Testing** | pytest + hypothesis | pytest + hypothesis | No change |
| **Deployment** | Bare metal | Docker Compose | New |
| **Process mgmt** | Manual | Docker restart + systemd | New |
| **CI/CD** | None | GitHub Actions | New |
| **Orchestration framework** | None (hand-rolled) | None (hand-rolled) | **Keep** |

### 8.3 Migration Path

**Phase 0: Foundation (Week 1-2)**
1. Resolve the 17-agent vs 7-agent architecture discrepancy
2. Add backpressure to MessageBus
3. Add correlation IDs to all log entries
4. Write unit tests for existing deterministic agents

**Phase 1: LLM Integration (Week 3-4)**
1. Add `pydantic-ai` dependency
2. Create `NIMClient` wrapper with retry, caching, and model routing
3. Implement `FundamentalNarration` Pydantic model
4. Add LLM narration to `FundamentalBiasAgent` behind feature flag
5. Add Langfuse for LLM tracing

**Phase 2: Enhanced Agents (Week 5-6)**
1. Add LLM mode to `DevilsAdvocateAgent`
2. Implement `LLMCache` for deduplication
3. Add property-based tests for financial calculations
4. Add chaos tests for broker disconnection

**Phase 3: Infrastructure (Week 7-8)**
1. Dockerize the application (main + mt5bridge + monitoring)
2. Set up Grafana dashboards
3. Add CI/CD pipeline (GitHub Actions)
4. Implement feature flags for gradual rollout

**Phase 4: Production Hardening (Week 9-10)**
1. Paper trading with full pipeline for 2+ weeks
2. Statistical validation of LLM-enhanced vs pure-deterministic performance
3. Latency profiling and optimization
4. Documentation and runbooks

### 8.4 Priority-Ordered Implementation Plan

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| **P0** | Resolve 17 vs 7 agent architecture | 1 week | Eliminates confusion, unblocks everything |
| **P0** | Write tests for existing agents | 1 week | Prevents regressions during LLM integration |
| **P1** | Add PydanticAI + NIMClient | 3 days | Enables LLM integration |
| **P1** | LLM narration for FundamentalBiasAgent | 3 days | Core feature request |
| **P2** | LLM Devil's Advocate mode | 2 days | High-value enhancement |
| **P2** | LLM caching | 1 day | Cost optimization |
| **P2** | Langfuse integration | 1 day | Observability |
| **P3** | Docker Compose deployment | 2 days | Operational reliability |
| **P3** | CI/CD pipeline | 1 day | Development velocity |
| **P3** | Grafana dashboards | 1 day | Monitoring |
| **P4** | Backtest framework | 1 week | Strategy validation |
| **P4** | Walk-forward optimization | 3 days | Overfitting prevention |

### 8.5 Cost Estimates

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| **NVIDIA NIM API** | $0-5 | Free tier (1000 calls/day) covers Noema's volume |
| **Hetzner VPS** (if needed) | $10-30 | For Windows VPS if Wine becomes unstable |
| **Langfuse** (self-hosted) | $0 | Runs on same server |
| **Grafana + Prometheus** | $0 | Runs on same server |
| **Total** | **$0-35/mo** | Mostly free at current scale |

---

## Appendix A: Key Sources

1. [Langfuse — Comparing Open-Source AI Agent Frameworks (Mar 2025)](https://langfuse.com/blog/2025-03-19-ai-agent-comparison)
2. [ZenML — 8 LangGraph Alternatives (Jun 2025)](https://www.zenml.io/blog/langgraph-alternatives)
3. [HPE — The Power of the AGNO Framework (Jul 2025)](https://developer.hpe.com/blog/part-4-the-rise-of-agentic-ai-and-the-power-of-the-agno-framework/)
4. [Firecrawl — Best LLM Observability Tools 2026](https://www.firecrawl.dev/blog/best-llm-observability-tools)
5. [Pau Labarta Bajo — Agentic Trading System (May 2025)](https://paulabartabajo.substack.com/p/lets-build-an-agentic-trading-platform)
6. [NVIDIA NIM Product Page](https://www.nvidia.com/en-us/ai-data-science/products/nim-microservices/)
7. [NVIDIA API Catalog (build.nvidia.com)](https://build.nvidia.com)
8. [PydanticAI Documentation](https://pydantic.dev/)
9. [Agno GitHub](https://github.com/agno-agi/agno)
10. [BAML GitHub](https://github.com/BoundaryML/baml)

## Appendix B: Decision Matrix

### Should I use an agent framework?

```
Is >50% of your agent logic LLM-driven?
├── Yes → Use an agent framework (CrewAI, AutoGen, Agno)
└── No → Is your orchestration complex (cycles, branching, human-in-loop)?
    ├── Yes → Use LangGraph or hand-rolled state machine
    └── No → Keep hand-rolled orchestration
        └── Do you need type-safe LLM calls?
            ├── Yes → Use PydanticAI (Noema's path)
            └── No → Use raw OpenAI client
```

### Should I use LiteLLM?

```
Do you need to route across >2 LLM providers?
├── Yes → Use LiteLLM
└── No → Use provider's SDK directly (OpenAI client for NVIDIA NIM)
```

### Should I use NATS/Redis?

```
Are your agents in separate processes/machines?
├── Yes → Use NATS (lightweight) or Redis Streams (if already in stack)
└── No → Keep in-process asyncio MessageBus
```

---

*Report generated 2026-06-17 by Noema Research Agent*
