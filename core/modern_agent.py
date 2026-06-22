"""Modern agent base class for VMPM — the agentic architecture.

Every agent now has:
- A reasoning loop (LLM-powered or deterministic)
- Typed tools it can call
- Short-term memory (current context) + long-term memory (reflections)
- Structured output (Pydantic schemas)
- Error recovery with graceful degradation

Agents are split into two categories:
1. DeterministicAgent — pure Python, no LLM, fast (<10ms)
2. LLMAgent — uses NIM for reasoning, structured output, slower (200ms-5s)
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from vmpm.core.nim_client import NIMClient, ModelTier
from vmpm.models.schemas import schema_prompt

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class AgentType(str, Enum):
    DETERMINISTIC = "deterministic"  # Pure Python, no LLM
    LLM = "llm"                      # Uses NIM for reasoning


class AgentState(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING = "waiting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class AgentReport:
    """Standardized output from any agent."""
    agent_name: str
    timestamp: float = field(default_factory=time.time)
    signal: str = "NEUTRAL"          # BULLISH, BEARISH, NEUTRAL, BUY, SELL, etc.
    confidence: float = 0.0          # 0.0 - 1.0
    data: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    report_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    agent_type: AgentType = AgentType.DETERMINISTIC
    llm_latency_ms: float = 0.0      # Time spent in LLM calls (0 for deterministic)
    cache_hit: bool = False


class AgentTool:
    """A tool that an agent can call during its reasoning loop."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: Any,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func

    def to_openai_tool(self) -> dict:
        """Convert to OpenAI tool format for NIM function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def execute(self, **kwargs) -> Any:
        if asyncio.iscoroutinefunction(self.func):
            return await self.func(**kwargs)
        return self.func(**kwargs)


class AgentMemory:
    """Agent memory: short-term (current context) + long-term (reflections)."""

    def __init__(self, max_reflections: int = 100):
        self._short_term: dict[str, Any] = {}  # Current context
        self._reflections: list[dict[str, Any]] = []  # Past lessons
        self._max_reflections = max_reflections

    def set_context(self, key: str, value: Any) -> None:
        self._short_term[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._short_term.get(key, default)

    def store_reflection(self, reflection: dict[str, Any]) -> None:
        """Store a lesson learned from a trade."""
        reflection["stored_at"] = time.time()
        self._reflections.append(reflection)
        if len(self._reflections) > self._max_reflections:
            self._reflections = self._reflections[-self._max_reflections:]

    def get_relevant_reflections(self, symbol: str, limit: int = 3) -> list[dict]:
        """Get recent reflections for a symbol."""
        relevant = [r for r in self._reflections if r.get("symbol") == symbol]
        return relevant[-limit:]

    def clear_short_term(self) -> None:
        self._short_term.clear()

    @property
    def reflection_count(self) -> int:
        return len(self._reflections)


# ── Base Agent (Abstract) ────────────────────────────────────────────

class BaseAgent(ABC):
    """Abstract base for all VMPM agents."""

    name: str = "base-agent"
    role: str = "Base Agent"
    agent_type: AgentType = AgentType.DETERMINISTIC
    priority: int = 0

    def __init__(
        self,
        config: Any = None,
        message_bus: Any = None,
        nim_client: NIMClient | None = None,
    ):
        self.config = config
        self.message_bus = message_bus
        self.nim = nim_client
        self.state = AgentState.IDLE
        self.memory = AgentMemory()
        self._logger = logger.bind(agent=self.name)

    @abstractmethod
    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Core analysis logic. Must be implemented by subclasses."""
        ...

    async def process(self, context: dict[str, Any]) -> AgentReport:
        """Wrapper around analyze() with state management and error handling."""
        self.state = AgentState.PROCESSING
        start = time.monotonic()
        try:
            report = await self.analyze(context)
            elapsed_ms = (time.monotonic() - start) * 1000
            self._logger.info(
                "analysis_complete",
                signal=report.signal,
                confidence=report.confidence,
                elapsed_ms=round(elapsed_ms, 1),
                agent_type=self.agent_type.value,
            )
            self.state = AgentState.IDLE
            return report
        except Exception as exc:
            self.state = AgentState.ERROR
            elapsed_ms = (time.monotonic() - start) * 1000
            self._logger.error(
                "analysis_failed",
                error=str(exc),
                elapsed_ms=round(elapsed_ms, 1),
            )
            return AgentReport(
                agent_name=self.name,
                signal="ERROR",
                confidence=0.0,
                reasoning=f"Error: {exc}",
                agent_type=self.agent_type,
            )

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        if self.message_bus:
            await self.message_bus.publish(topic, data, sender=self.name)


# ── Deterministic Agent ──────────────────────────────────────────────

class DeterministicAgent(BaseAgent):
    """Agent that uses pure Python logic — no LLM calls.

    For tasks with deterministic algorithms:
    - Technical indicator calculations
    - Position sizing (math formulas)
    - Risk limit checks
    - S/R level detection (rule-based)
    - Candlestick pattern recognition (TA-Lib)

    Latency: <10ms
    """

    agent_type = AgentType.DETERMINISTIC

    @abstractmethod
    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """Pure Python analysis — no LLM."""
        ...


# ── LLM Agent ────────────────────────────────────────────────────────

class LLMAgent(BaseAgent):
    """Agent that uses NVIDIA NIM for reasoning.

    For tasks requiring judgment, interpretation, or synthesis:
    - Trade thesis building
    - Devil's advocate challenging
    - CIO final decision
    - Complex market narrative analysis
    - Post-trade reflection

    Latency: 200ms-5s depending on model tier
    """

    agent_type = AgentType.LLM

    # Subclasses should set these
    model_tier: ModelTier = ModelTier.STANDARD
    system_prompt: str = ""
    response_model: type[BaseModel] | None = None
    tools: list[AgentTool] = field(default_factory=list)
    temperature: float = 0.3

    async def analyze(self, context: dict[str, Any]) -> AgentReport:
        """LLM-powered analysis with structured output."""
        if not self.nim:
            raise RuntimeError(f"LLMAgent '{self.name}' requires NIMClient")

        # Build the prompt from context
        user_message = self._build_user_message(context)
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": user_message},
        ]

        # Call NIM with structured output
        start = time.monotonic()
        tools = [t.to_openai_tool() for t in self.tools] if self.tools else None

        result = await self.nim.chat_completion(
            messages=messages,
            response_model=self.response_model,
            tier=self.model_tier,
            agent_name=self.name,
            context=context,
            tools=tools,
            tool_choice="auto" if tools else None,
            temperature=self.temperature,
        )
        llm_latency_ms = (time.monotonic() - start) * 1000

        # Handle tool calls (if LLM wants to call tools)
        if isinstance(result, dict) and result.get("type") == "tool_calls":
            result = await self._handle_tool_calls(result, messages, context)

        # Convert to AgentReport
        return self._to_report(result, llm_latency_ms)

    def _build_system_prompt(self) -> str:
        """Build the system prompt. Override for custom behavior."""
        prompt = self.system_prompt
        if self.response_model and not self.tools:
            prompt += "\n\n" + schema_prompt(self.response_model)
        return prompt

    def _build_user_message(self, context: dict[str, Any]) -> str:
        """Build the user message from context. Override for custom formatting."""
        parts = []
        for key, value in context.items():
            if isinstance(value, (str, int, float, bool)):
                parts.append(f"{key}: {value}")
            elif isinstance(value, dict):
                parts.append(f"{key}: {value}")
            elif isinstance(value, list) and len(value) < 20:
                parts.append(f"{key}: {value}")
        return "\n".join(parts)

    async def _handle_tool_calls(
        self,
        tool_result: dict,
        messages: list[dict],
        context: dict[str, Any],
    ) -> Any:
        """Execute tool calls requested by the LLM and continue the conversation."""
        tool_map = {t.name: t for t in self.tools}
        tool_messages = list(messages)

        for tc in tool_result.get("tool_calls", []):
            func_name = tc.get("function", {}).get("name", "")
            func_args = tc.get("function", {}).get("arguments", "{}")

            if func_name in tool_map:
                try:
                    args = __import__("json").loads(func_args) if isinstance(func_args, str) else func_args
                    result = await tool_map[func_name].execute(**args)
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": str(result),
                    })
                except Exception as e:
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": f"Error: {e}",
                    })

        # Re-call LLM with tool results
        return await self.nim.chat_completion(
            messages=tool_messages,
            response_model=self.response_model,
            tier=self.model_tier,
            agent_name=self.name,
            context=context,
            temperature=self.temperature,
        )

    def _to_report(self, result: Any, llm_latency_ms: float) -> AgentReport:
        """Convert LLM result to AgentReport. Override for custom mapping."""
        if isinstance(result, BaseModel):
            return AgentReport(
                agent_name=self.name,
                signal=getattr(result, "direction", "NEUTRAL"),
                confidence=getattr(result, "confidence", 0.5),
                data=result.model_dump(),
                reasoning=getattr(result, "reasoning", "") or getattr(result, "narrative", ""),
                agent_type=self.agent_type,
                llm_latency_ms=llm_latency_ms,
            )
        return AgentReport(
            agent_name=self.name,
            signal="NEUTRAL",
            confidence=0.0,
            data=result if isinstance(result, dict) else {"raw": str(result)},
            reasoning=str(result),
            agent_type=self.agent_type,
            llm_latency_ms=llm_latency_ms,
        )
