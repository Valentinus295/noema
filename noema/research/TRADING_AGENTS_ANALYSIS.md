# TradingAgents Architecture Analysis — Patterns for Noema Adoption

**Date**: 2026-06-23
**Source**: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (88k⭐)
**Analyst**: Atlas (CQO, VMPM)

---

## 1. Executive Summary

TradingAgents is the reference implementation for multi-agent LLM trading. Its architecture uses a **LangGraph StateGraph** to orchestrate 11 agents through a fixed pipeline: 4 analyst agents (market, sentiment, news, fundamentals) → Bull/Bear researcher debate → Research Manager → Trader → Aggressive/Conservative/Neutral risk debate → Portfolio Manager (final decision). The key innovations are: (a) a two-tier debate system (investment thesis + risk management), (b) deferred reflection via append-only memory log, and (c) tool-augmented analysts that call real APIs.

### Recommendation

Adopt 3 patterns immediately:
1. **Multi-perspective risk debate** — replace Devil's Advocate single-pass with aggressive/conservative/neutral triangle
2. **Deferred reflection memory** — append-only log with next-run resolution
3. **Tool-augmented agents** — give agents real tools (economic calendar, correlation checks, broker status)

Avoid 2 patterns:
1. **Sequential analyst execution** — keep Noema's parallel Layer 2
2. **LangChain dependency** — keep Noema's lean architecture

---

## 2. Architecture Comparison

### TradingAgents Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 1: DATA COLLECTION                  │
│                                                              │
│  ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌────────────┐ │
│  │ Market  │   │Sentiment │   │  News   │   │Fundamentals│ │
│  │Analyst  │──▶│ Analyst  │──▶│ Analyst │──▶│  Analyst   │ │
│  │         │   │          │   │         │   │            │ │
│  │ Tools:  │   │ Tools:   │   │ Tools:  │   │ Tools:     │ │
│  │ OHLCV   │   │ Reddit   │   │ News API│   │ Balance    │ │
│  │ T.A.    │   │ StockTws │   │ Macro   │   │ Sheet      │ │
│  │ Snapsh. │   │          │   │ Polymrkt│   │ CashFlow ▲ │ │
│  └────┬────┘   └────┬─────┘   └────┬────┘   └─────┬──────┘ │
│       │              │              │               │        │
│       └──────────────┴──────────────┴───────────────┘        │
│                          ▼                                    │
├─────────────────────────────────────────────────────────────┤
│              LAYER 2: DUAL DEBATE SYSTEM                      │
│                                                              │
│  INVESTMENT DEBATE (configurable rounds)                     │
│  ┌──────────┐    ┌──────────┐                                │
│  │   Bull   │◀──▶│   Bear   │  ← debate history in state    │
│  │Researcher│    │Researcher│                                │
│  └────┬─────┘    └────┬─────┘                                │
│       └───────┬───────┘                                       │
│               ▼                                               │
│       ┌──────────────┐                                       │
│       │  Research    │ → Structured: BUY/OVERWEIGHT/HOLD/    │
│       │  Manager     │   UNDERWEIGHT/SELL                     │
│       └──────┬───────┘                                       │
│              ▼                                                │
│       ┌──────────┐                                           │
│       │  Trader  │ → Structured: BUY/HOLD/SELL + levels     │
│       └──────┬───┘                                           │
│              ▼                                                │
├─────────────────────────────────────────────────────────────┤
│               LAYER 3: RISK DEBATE                            │
│                                                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │Aggressive │◀▶│Conservative│◀▶│  Neutral  │  ← 3-way     │
│  │  Debator  │  │  Debator  │  │  Debator  │    debate     │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        └──────────────┬──────────────┘                       │
│                       ▼                                       │
│              ┌───────────────┐                               │
│              │   Portfolio   │ → FINAL: BUY/OVERWEIGHT/     │
│              │   Manager     │   HOLD/UNDERWEIGHT/SELL       │
│              └───────────────┘                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  MEMORY LOG      │
                    │  Append-only     │
                    │  Deferred Refl.  │
                    └──────────────────┘
```

### Noema Pipeline (Current)

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: DATA (parallel, deterministic, <10ms)             │
│  ┌─────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐  │
│  │Data │ │Sessn│ │Broker│ │Corr. │ │Funda │ │Currcy  │  │
│  │Fetch│ │Agent│ │Status│ │Agent │ │Agent │ │Agent   │  │
│  └──┬──┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └───┬────┘  │
│     └───────┴────────┴────────┴────────┴────────┘         │
│                          ▼                                   │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: ANALYSIS (parallel, mix det+LLM, 200ms-5s)       │
│  ┌───────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│  │Trend  │ │Structure│ │   S/R  │ │Momentum│ │Price   │   │
│  │Agent  │ │ Agent   │ │ Agent  │ │ Agent  │ │Action  │   │
│  └───┬───┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘   │
│  ┌───┴───┐ ┌───┴────┐ ┌───┴────┐ ┌───┴────┐               │
│  │Institu│ │Conflnce│ │Opportu │ │Perform │               │
│  │Agent  │ │ Agent  │ │  nity  │ │  Agent │               │
│  └───┬───┘ └───┬────┘ └───┬────┘ └───┬────┘               │
│      └─────────┴──────────┴──────────┘                     │
│                          ▼                                   │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: DECISION (sequential LLM debate, 3-15s)          │
│                                                              │
│  ┌─────────────┐    ┌────────────┐    ┌───────────┐        │
│  │   Trade     │───▶│   Devil's  │───▶│    CIO    │        │
│  │   Thesis    │    │  Advocate  │    │  (Final)  │        │
│  └─────────────┘    └────────────┘    └───────────┘        │
│                                                              │
│  Single-pass: build case → challenge → decide               │
├─────────────────────────────────────────────────────────────┤
│  LAYER 4: EXECUTION (sequential, deterministic)             │
│  ┌──────────┐    ┌──────────────┐                           │
│  │  Risk    │───▶│  Execution   │                           │
│  │  Agent   │    │  Agent       │                           │
│  └──────────┘    └──────────────┘                           │
├─────────────────────────────────────────────────────────────┤
│  LAYER 5: LEARNING (background, async)                      │
│  ┌──────────┐                                               │
│  │Reflector │  ← Post-trade reflection, no cross-run memory │
│  └──────────┘                                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Differences

| Dimension | TradingAgents | Noema | Winner |
|-----------|--------------|-------|--------|
| **Agent count** | 11 (focused) | 17 (comprehensive) | Noema (more coverage) |
| **Analyst execution** | Sequential (4 analysts) | Parallel (12 analysis agents) | **Noema** (2-3x faster) |
| **Debate depth** | 2-tier, multi-round | Single-pass chain | **TradingAgents** |
| **Risk management** | 3-perspective debate | Single risk check | **TradingAgents** |
| **Memory** | Cross-run append-only log | In-session only | **TradingAgents** |
| **Tool integration** | LangChain @tool, per-analyst | None currently | **TradingAgents** |
| **Orchestration** | LangGraph StateGraph | Custom asyncio orchestrator | Noema (leaner) |
| **Structured output** | Pydantic + graceful fallback | Pydantic response models | TradingAgents (fallback) |
| **Asset focus** | Stocks + crypto | Forex | Noema (domain fit) |
| **Production readiness** | Good (checkpoint, vendor abs) | Good (metrics, caching) | Tie |

---

## 3. Prompt Engineering Analysis

### TradingAgents' Prompt Patterns

#### Pattern 1: Instrument Identity Anchoring
```python
context = (
    "The instrument to analyze is `AAPL`. "
    "Resolved identity: Company: Apple Inc.; Business classification: Technology / "
    "Consumer Electronics; Exchange: NMS. Do not substitute a different company "
    "or ticker unless a tool result explicitly disproves this resolved identity."
)
```
**Why it works**: Prevents LLM hallucination where the model pattern-matches a chart shape to a wrong company narrative. Each agent's prompt includes this identity block.

**Noema can adapt**: Use `ResolvedPairIdentity` for forex — include base/quote country, carry differential, session characteristics.

#### Pattern 2: Rating Scale Guidance in Prompt
```
Rating Scale (use exactly one):
- Buy: Strong conviction in the bull thesis; recommend taking or growing the position
- Overweight: Constructive view; recommend gradually increasing exposure
- Hold: Balanced view; recommend maintaining the current position
- Underweight: Cautious view; recommend trimming exposure
- Sell: Strong conviction in the bear thesis; recommend exiting or avoiding the position

Commit to a clear stance whenever the debate's strongest arguments warrant one;
reserve Hold for situations where the evidence on both sides is genuinely balanced.
```
**Why it works**: The LLM gets not just a schema but behavioral guidance. "Commit to a clear stance" pushes against the model's natural tendency to hedge.

**Noema can adapt**: Add behavioral guidance to CIO's system prompt beyond the current schema instruction.

#### Pattern 3: Convergent Tool Validation
```python
# Before writing the final report, call get_verified_market_snapshot
# Treat it as the source of truth for exact OHLCV, price-level, or indicator-value claims.
# If another tool's output conflicts, flag the discrepancy.
```
**Why it works**: Creates a deterministic ground truth that prevents the LLM from confabulating exact numbers. The market analyst MUST call the snapshot tool before finalizing.

**Noema can adapt**: Add `get_verified_broker_snapshot` tool that returns MT5 data as ground truth.

#### Pattern 4: Debate-Style Personality Instructions
```
Output conversationally as if you are speaking without any special formatting.

Engage actively by addressing any specific concerns raised, refuting the weaknesses
in their logic, and asserting the benefits of risk-taking to outpace market norms.
Maintain a focus on debating and persuading, not just presenting data.
```
**Why it works**: Instead of producing bullet lists, agents engage in conversational debate. This is more effective at surfacing contradictions than parallel independent analysis.

**Noema can adapt**: Apply to the debate synthesis function.

---

## 4. Noema Patterns to Adopt (3-5)

### Pattern 1: Multi-Perspective Risk Debate ★★★
**Source**: TradingAgents' Aggressive/Conservative/Neutral risk debate
**What**: Replace Devil's Advocate single-pass with 3-person risk debate
**Implementation**: Create `RiskDebateAggressiveAgent`, `RiskDebateConservativeAgent`, `RiskDebateNeutralAgent` that debate the trader's plan. Add `RiskDirectorAgent` that synthesizes their debate into the CIO decision input.

### Pattern 2: Deferred Reflection Memory ★★★
**Source**: TradingAgents' `TradingMemoryLog`
**What**: Append-only markdown log storing decisions at run time, resolving with outcomes on next run. Inject past context into PM/CIO prompts.
**Implementation**: Create `noema/memory/trade_memory.py` with `TradeMemoryLog` class. Store as pending entries during pipeline, resolve on next same-symbol run.

### Pattern 3: Tool-Augmented Agents ★★
**Source**: TradingAgents' per-analyst tool sets
**What**: Give analysis and decision agents access to real tools — economic calendar, correlation checks, news sentiment, broker status.
**Implementation**: Build `noema/tools/` with ToolRegistry. Update `LLMAgent` to support tool calling. Register tools per agent.

### Pattern 4: Market Data Validator ★★
**Source**: TradingAgents' `get_verified_market_snapshot`
**What**: A deterministic truth source that agents must call before making exact price/indicator claims.
**Implementation**: `noema/tools/market_data.py` with `get_verified_broker_snapshot(symbol, curr_date)` returning MT5-verified OHLCV data.

### Pattern 5: Structured Output with Graceful Fallback ★
**Source**: TradingAgents' `invoke_structured_or_freetext`
**What**: Try structured output, fall back to free-text if parsing fails — never block the pipeline.
**Implementation**: Already partially supported in `_parse_response`. Add `invoke_structured_or_freetext` pattern.

---

## 5. What Noema Should AVOID (From TradingAgents)

### 1. Sequential Analyst Execution ✗
TradingAgents runs 4 analysts sequentially (market → sentiment → news → fundamentals), each with tool-call loops. This is slow. Noema's Layer 2 parallel execution is superior. Keep the parallel approach.

### 2. LangChain/LangGraph Dependency ✗
TradingAgents is built on LangGraph's StateGraph. This adds framework overhead, version lock-in, and abstraction complexity. Noema's custom asyncio orchestrator is leaner and more maintainable.

### 3. Single LLM Provider Universe ✗
Though TradingAgents supports multiple providers, its architecture assumes LangChain's provider abstraction. Noema's NIM client is optimized for NVIDIA's API with better caching and rate limiting.

### 4. Overloaded System Prompts ✗
TradingAgents' market analyst system prompt includes a full catalog of 13 indicators with usage/tips. This burns tokens redundantly — the tool descriptions already contain this information. Noema should keep prompts focused on role/behavior, not data catalogs.

### 5. Monolithic Symbol State ✗
All agents share a single `AgentState` TypedDict. This creates coupling (every agent must know every state key). Noema's approach of passing context dicts per agent is better — each agent only sees what it needs.

---

## 6. Implementation Plan

### Phase A: Tool Infrastructure + Risk Context (This PR)
1. Create `noema/tools/` with ToolRegistry + MCP server scaffold
2. Implement `RiskContext` dataclass + injection into all LLM agents
3. Implement `debate_synthesis()` for CIO decision layer
4. Update `pyproject.toml` with MCP dependency

### Phase B: Memory + Risk Debate (Next PR)
1. Implement `TradeMemoryLog` with append-only markdown storage
2. Implement multi-perspective risk debate agents
3. Implement market data validator tool
4. Implement deferred reflection in orchestrator

### Phase C: Depth + Polish
1. Implement ResolvedPairIdentity for forex instruments
2. Add behavioral prompt guidance to CIO
3. Implement structured output with graceful fallback
4. Add correlation and economic calendar tools

---

## 7. Key Learnings

1. **Debate quality > analysis breadth**: TradingAgents' 11 agents with debate produce better decisions than 17 independent agents could. The key is the adversarial back-and-forth, not just the number of perspectives.

2. **Memory matters**: TradingAgents' deferred reflection (store decision now, learn from outcome later) creates a feedback loop that Noema currently lacks. Cross-run memory is the single most important missing feature.

3. **Tools prevent hallucination**: Giving analysts real tools (and requiring them to call a "verified snapshot" before finalizing) dramatically reduces LLM confabulation. The `get_verified_market_snapshot` pattern is brilliant.

4. **Risk should be debated, not checked**: A single risk gate is fragile. Three perspectives (aggressive, conservative, neutral) debating creates a more robust risk assessment.

5. **Structured output needs fallback**: Production systems can't afford pipeline failures when structured parsing fails. TradingAgents' try-structured-fall-back-to-freetext pattern is essential.
