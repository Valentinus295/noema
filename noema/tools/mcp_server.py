"""
MCP Server Scaffold — Model Context Protocol server for Noema tools.

Exposes Noema's tool registry as an MCP server so external consumers
(Claude Desktop, other AI agents, monitoring dashboards) can discover
and execute Noema tools through the MCP protocol.

This is a scaffold — the full MCP server requires the `mcp` Python package.
Install with: uv sync (mcp>=1.0 added to pyproject.toml)

Architecture:
    1. Tool discovery (list_tools) — returns all registered tools with schemas
    2. Tool execution (call_tool) — executes a tool by name with arguments
    3. Noema agent integration — tools are the same objects used by Noema agents

Pattern:
    MCP client → MCP server → ToolRegistry → Tool.execute() → Result
"""

from __future__ import annotations

import json
import logging
from typing import Any

from noema.tools import ToolRegistry

logger = logging.getLogger(__name__)


# ── Tool Registry Initialization ───────────────────────────────────────

def create_noema_tool_registry() -> ToolRegistry:
    """Create and populate the tool registry with all Noema tools.

    This function is the single source of truth for tool registration.
    Add new tools here as they're created.
    """
    # Lazy imports to avoid circular dependencies
    from noema.tools.economic_calendar import economic_calendar_tool, central_bank_tool
    from noema.tools.market_data import market_data_tool, verified_snapshot_tool
    from noema.tools.broker_status import broker_status_tool, account_state_tool
    from noema.tools.correlation import correlation_tool, correlation_matrix_tool

    registry = ToolRegistry()

    # Register all tools
    registry.register(economic_calendar_tool)
    registry.register(central_bank_tool)
    registry.register(market_data_tool)
    registry.register(verified_snapshot_tool)
    registry.register(broker_status_tool)
    registry.register(account_state_tool)
    registry.register(correlation_tool)
    registry.register(correlation_matrix_tool)

    logger.info(
        f"Noema MCP: registered {registry.tool_count} tools "
        f"across {len(registry._agent_tools)} agent mappings"
    )
    return registry


# ── MCP Server Definition ──────────────────────────────────────────────

# This server can be run as an MCP server when the mcp package is available.
# For now it serves as a scaffold that documents the MCP interface and
# provides the tool registry initialization logic.

# MCP server name and version
SERVER_NAME = "noema-tools"
SERVER_VERSION = "0.1.0"


# ── Tool Listing (MCP: tools/list) ─────────────────────────────────────

def list_all_tools(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    """List all available tools with their schemas (MCP-compatible format).

    Returns a list of tool definitions in MCP format:
    {
        "name": "get_economic_calendar",
        "description": "Fetch upcoming economic events...",
        "inputSchema": {
            "type": "object",
            "properties": {...},
            "required": [...]
        }
    }
    """
    if registry is None:
        registry = create_noema_tool_registry()

    tools = []
    for tool in registry.get_all().values():
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "inputSchema": {
                "type": "object",
                "properties": tool.parameters,
                "required": list(tool.parameters.keys()),
            },
        })
    return tools


# ── Tool Execution (MCP: tools/call) ──────────────────────────────────

async def call_tool(
    name: str,
    arguments: dict[str, Any],
    registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Execute a tool by name with the given arguments.

    Returns MCP-compatible result:
    {
        "content": [{"type": "text", "text": "..."}],
        "isError": false
    }
    """
    if registry is None:
        registry = create_noema_tool_registry()

    tool = registry.get(name)
    if tool is None:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            "isError": True,
        }

    try:
        result = await tool.execute(**arguments)
        return {
            "content": [{"type": "text", "text": result}],
            "isError": False,
        }
    except Exception as e:
        logger.error(f"Tool execution failed: {name} — {e}")
        return {
            "content": [{"type": "text", "text": f"Error executing {name}: {e}"}],
            "isError": True,
        }


# ── MCP Server Entry Point (when mcp package is available) ──────────────

def create_mcp_server(registry: ToolRegistry | None = None):
    """Create an MCP server instance exposing Noema tools.

    Usage (when mcp>=1.0 is installed):
        from mcp.server import Server
        from noema.tools.mcp_server import create_mcp_server

        server = create_mcp_server()
        server.run()

    Args:
        registry: Optional pre-built ToolRegistry. Creates default if None.

    Returns:
        MCP Server instance (when mcp is available) or None
    """
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError:
        logger.error(
            "MCP package not installed. Install with: pip install mcp>=1.0"
        )
        return None

    if registry is None:
        registry = create_noema_tool_registry()

    server = Server(SERVER_NAME, version=SERVER_VERSION)

    @server.list_tools()
    async def handle_list_tools() -> list[dict[str, Any]]:
        """MCP handler: list all available Noema tools."""
        return list_all_tools(registry)

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """MCP handler: execute a Noema tool."""
        return await call_tool(name, arguments, registry)

    return server


# ── CLI Entry Point ────────────────────────────────────────────────────

def main():
    """Run the Noema MCP tool server."""
    import asyncio

    server = create_mcp_server()
    if server is None:
        logger.error("Cannot start MCP server: mcp package not available")
        return 1

    logger.info(f"Starting Noema MCP server v{SERVER_VERSION}")
    try:
        asyncio.run(server.run_stdio_async())
    except KeyboardInterrupt:
        logger.info("MCP server stopped")
    return 0


if __name__ == "__main__":
    exit(main())
