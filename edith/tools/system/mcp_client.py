"""Generic MCP (Model Context Protocol) client — lets the user wire in any
stdio-based MCP server from the web dashboard's Integrations tab, with no
code change or redeploy needed to add one (see edith/mcp/api.py). A server
added there takes effect on the next process restart: every enabled server's
tools are discovered once, at registry-build time (register_all, called from
edith/bootstrap.py's build_registry), and merged into the normal
ToolRegistry alongside built-in tools — same "optional integration, skipped
on failure rather than blocking startup" pattern as Qdrant/Temporal/Firebase
elsewhere in this codebase.

Every call (both the one-time list_tools and each later call_tool) opens its
own stdio_client connection and spawns a fresh subprocess, rather than
holding one connection open per server for the process lifetime — the whole
tool-dispatch contract in this codebase (ToolRegistry.dispatch ->
run_completion_with_tools -> Agent.handle_turn) is synchronous, called via
asyncio.to_thread with no event loop already running on that thread, so
asyncio.run() per call is both safe and the simplest way to bridge into the
MCP SDK's async-only client API. The extra subprocess-startup latency per
call is the accepted trade-off for not having to manage long-lived async
connections inside a sync codebase.
"""

import asyncio
import json
import logging
import re
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from edith.memory import mcp_store
from edith.tools.registry import ToolRegistry

logger = logging.getLogger("edith.tools.mcp_client")

# Per-call timeout — an MCP server that hangs (bad command, network stall)
# must not hang the whole agent turn indefinitely.
CALL_TIMEOUT_SECONDS = 60
LIST_TOOLS_TIMEOUT_SECONDS = 20


def _sanitize_for_tool_name(text: str) -> str:
    """OpenAI-style function names must match ^[a-zA-Z0-9_-]+$."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


def _server_params(server: dict[str, Any]) -> StdioServerParameters:
    return StdioServerParameters(
        command=server["command"],
        args=json.loads(server["args_json"] or "[]"),
        env=json.loads(server["env_json"]) if server.get("env_json") else None,
    )


async def _list_tools_async(params: StdioServerParameters) -> list:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), LIST_TOOLS_TIMEOUT_SECONDS)
            result = await asyncio.wait_for(session.list_tools(), LIST_TOOLS_TIMEOUT_SECONDS)
            return result.tools


async def _call_tool_async(params: StdioServerParameters, tool_name: str, args: dict) -> str:
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), LIST_TOOLS_TIMEOUT_SECONDS)
            result = await asyncio.wait_for(session.call_tool(tool_name, args), CALL_TIMEOUT_SECONDS)
            parts = [block.text for block in result.content if getattr(block, "text", None)]
            text = "\n".join(parts) if parts else "(no text content returned)"
            return f"ERROR: {text}" if result.is_error else text


def register_all(registry: ToolRegistry, conn) -> None:
    for server in mcp_store.list_servers(conn, enabled_only=True):
        params = _server_params(server)
        try:
            tools = asyncio.run(_list_tools_async(params))
        except Exception:
            logger.exception("Failed to list tools from MCP server %r — skipping", server["name"])
            continue

        for tool in tools:
            _register_one(registry, server, params, tool)


def _register_one(registry: ToolRegistry, server: dict[str, Any], params: StdioServerParameters, tool: Any) -> None:
    # Namespaced so identically-named tools from two different servers can't collide.
    qualified_name = f"mcp_{_sanitize_for_tool_name(server['name'])}_{_sanitize_for_tool_name(tool.name)}"

    def dispatch(**kwargs: Any) -> str:
        try:
            return asyncio.run(_call_tool_async(params, tool.name, kwargs))
        except Exception as e:  # noqa: BLE001 — surface as a tool error, don't crash the loop
            logger.exception("MCP tool call failed: server=%r tool=%r", server["name"], tool.name)
            return f"ERROR: MCP tool '{tool.name}' on server '{server['name']}' failed: {e}"

    registry.register(
        {
            "type": "function",
            "function": {
                "name": qualified_name,
                "description": f"[{server['name']}] {tool.description or tool.name}",
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            },
        },
        dispatch,
    )
