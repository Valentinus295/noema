"""
Tool Registry — unified tool management for Noema agents.

Pattern inspired by TradingAgents' per-agent tool sets:
- Each tool is a @tool-decorated function with typed parameters.
- Tools are registered globally and assigned to agents as needed.
- Supports both sync and async tool execution.
- Tools can be exported via MCP (Model Context Protocol) for external consumers.

Usage:
    registry = ToolRegistry()
    registry.register(get_economic_calendar)
    tools = registry.get_tools_for_agent("macro-economic")
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ── Tool Protocol ──────────────────────────────────────────────────────

@runtime_checkable
class ToolFunction(Protocol):
    """Expected shape of a tool function: a callable with __name__."""
    __name__: str
    def __call__(self, **kwargs) -> Any: ...


@dataclass
class ToolDef:
    """Definition of a registered tool."""
    name: str
    description: str
    func: ToolFunction
    parameters: dict[str, Any]  # JSON Schema for parameters
    tags: list[str] = field(default_factory=list)
    category: str = "general"
    requires_broker: bool = False
    requires_llm: bool = False

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.parameters.keys()),
                },
            },
        }

    def to_schema(self) -> dict[str, Any]:
        """Alias for to_openai_tool()."""
        return self.to_openai_tool()

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool with provided arguments. Returns string result."""
        try:
            if asyncio.iscoroutinefunction(self.func):
                result = await self.func(**kwargs)
            else:
                result = self.func(**kwargs)
            return json.dumps(result, default=str) if not isinstance(result, str) else result
        except Exception as e:
            logger.error(f"Tool execution failed: {self.name} — {e}")
            return json.dumps({"error": str(e), "tool": self.name})


# ── Agent-to-Tool Mapping ──────────────────────────────────────────────

# Default tool assignments per agent (inspired by TradingAgents:
# Market → OHLCV+T.A., News → news+macro, Fundamentals → balance sheet, etc.)
DEFAULT_AGENT_TOOLS: dict[str, list[str]] = {
    "macro-economic": ["get_economic_calendar", "get_currency_correlation"],
    "fundamental-bias": ["get_economic_calendar", "get_news_sentiment"],
    "trend": ["get_market_data"],
    "structure": ["get_market_data"],
    "momentum": ["get_market_data"],
    "price-action": ["get_market_data"],
    "sr-levels": ["get_market_data"],
    "broker": ["get_broker_status", "get_account_state"],
    "risk": ["get_broker_status", "get_account_state", "get_currency_correlation"],
    "cio": ["get_broker_status", "get_economic_calendar"],
    "execution": ["get_broker_status", "get_account_state"],
    "thesis": [],  # Pure reasoning — no tools needed
    "devils-advocate": [],  # Pure reasoning — no tools needed
}


# ── ToolRegistry ────────────────────────────────────────────────────────

class ToolRegistry:
    """Central registry for all Noema tools.

    Features:
    - Register/unregister tools by name
    - Query tools by agent name or category
    - Export tool schemas for MCP server
    - Execute tools with argument validation
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}
        self._agent_tools: dict[str, list[str]] = defaultdict(list)
        # Initialize with default mappings
        for agent, tool_names in DEFAULT_AGENT_TOOLS.items():
            self._agent_tools[agent] = list(tool_names)

    # ── Registration ───────────────────────────────────────────────

    def register(self, tool: ToolDef) -> None:
        """Register a tool definition."""
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered — overwriting")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name} (category={tool.category})")

    def unregister(self, name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(name, None)
        # Remove from agent assignments
        for agent_tools in self._agent_tools.values():
            if name in agent_tools:
                agent_tools.remove(name)

    def assign_to_agent(self, agent_name: str, tool_names: list[str]) -> None:
        """Assign specific tools to an agent."""
        valid = [n for n in tool_names if n in self._tools]
        invalid = set(tool_names) - set(valid)
        if invalid:
            logger.warning(
                f"Unknown tools for agent '{agent_name}': {invalid}"
            )
        self._agent_tools[agent_name] = valid

    # ── Query ──────────────────────────────────────────────────────

    def get(self, name: str) -> ToolDef | None:
        """Get a single tool by name."""
        return self._tools.get(name)

    def get_all(self) -> dict[str, ToolDef]:
        """Get all registered tools."""
        return dict(self._tools)

    def get_by_category(self, category: str) -> list[ToolDef]:
        """Get all tools in a category."""
        return [t for t in self._tools.values() if t.category == category]

    def get_by_tag(self, tag: str) -> list[ToolDef]:
        """Get all tools with a specific tag."""
        return [t for t in self._tools.values() if tag in t.tags]

    def get_for_agent(self, agent_name: str) -> list[ToolDef]:
        """Get tools assigned to a specific agent."""
        tool_names = self._agent_tools.get(agent_name, [])
        return [self._tools[n] for n in tool_names if n in self._tools]

    def get_schemas_for_agent(self, agent_name: str) -> list[dict[str, Any]]:
        """Get OpenAI-format tool schemas for an agent."""
        return [t.to_openai_tool() for t in self.get_for_agent(agent_name)]

    # ── Metadata ───────────────────────────────────────────────────

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def agent_count(self) -> int:
        return len(self._agent_tools)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return sorted(self._tools.keys())

    def summary(self) -> dict[str, Any]:
        """Return a summary of the registry for monitoring."""
        by_category: dict[str, int] = defaultdict(int)
        for t in self._tools.values():
            by_category[t.category] += 1

        return {
            "total_tools": self.tool_count,
            "tools_by_category": dict(by_category),
            "agents_with_tools": len(self._agent_tools),
            "tool_names": self.list_tools(),
        }
