"""FastMCP integration helpers for plugin-provided local tools."""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import Any, Protocol

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.core.protocols import ManagedPlugin, tool_error_result

logger = logging.getLogger(__name__)

__all__ = [
    "FastMCP",
    "McpToolProvider",
    "FastMcpToolAdapter",
    "FastMCPManagedPlugin",
    "create_fastmcp_tool_adapter",
]


class McpToolProvider(Protocol):
    """Protocol for plugins that register local FastMCP tools."""

    def populate_mcp(self, mcp: FastMCP) -> None:
        """Register plugin-local tools on the provided FastMCP instance."""
        ...


class FastMcpToolAdapter:
    """Adapter from plugin-local FastMCP tools to ManagedPlugin tool calls."""

    def __init__(self, provider: McpToolProvider, name: str) -> None:
        self._provider = provider
        self._mcp = FastMCP(name, on_duplicate="error")
        self._tool_names: set[str] = set()
        self._openai_tools: list[dict[str, Any]] = []
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @property
    def tool_names(self) -> set[str]:
        """Registered local tool names."""
        return set(self._tool_names)

    async def initialize(self) -> None:
        """Populate and cache local tool definitions. Idempotent."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return

            self._provider.populate_mcp(self._mcp)
            tools = await self._mcp.list_tools()

            openai_tools: list[dict[str, Any]] = []
            tool_names: set[str] = set()
            for tool in tools:
                name = str(tool.name)
                tool_names.add(name)
                definition: dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description or "",
                        "parameters": tool.parameters or {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                }
                meta = getattr(tool, "meta", None) or {}
                hint = meta.get("status_hint") if isinstance(meta, dict) else None
                if isinstance(hint, str) and hint:
                    definition["status_hint"] = hint
                openai_tools.append(definition)

            self._tool_names = tool_names
            self._openai_tools = openai_tools
            self._initialized = True

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return cached OpenAI-compatible tool definitions."""
        return list(self._openai_tools)

    def has_tool(self, tool_name: str) -> bool:
        """Return whether this adapter owns *tool_name*."""
        return tool_name in self._tool_names

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a local tool and normalize errors to ManagedPlugin results."""
        await self.initialize()
        if tool_name not in self._tool_names:
            return tool_error_result(f"Unknown local MCP tool: {tool_name}")

        try:
            result = await self._mcp.call_tool(tool_name, arguments)
        except ToolError as exc:
            return tool_error_result(str(exc))
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Local MCP tool '%s' failed", tool_name)
            return tool_error_result(f"Local MCP tool error: {exc}")

        if getattr(result, "is_error", False):
            return tool_error_result(
                _content_text(result) or "Local MCP tool returned an error"
            )

        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            return structured

        return tool_error_result("Local MCP tool did not return structured object content")


class FastMCPManagedPlugin(ManagedPlugin):
    """ManagedPlugin base whose local tools come solely from FastMCP.

    ``populate_mcp()`` is the single source of truth for tool definitions
    and execution: subclasses register typed tool methods there and the
    base class implements ``get_tools_definition()`` / ``execute_tool()``
    through :class:`FastMcpToolAdapter`.

    Subclasses implement ``get_system_prompt()`` and ``populate_mcp()``.
    Hybrid plugins that merge local FastMCP tools with another tool source
    (e.g. a remote MCP server) should keep using
    :func:`create_fastmcp_tool_adapter` directly instead.
    """

    def __init__(self, mcp_name: str | None = None) -> None:
        self._fastmcp_name = mcp_name
        self._fastmcp_tool_adapter: FastMcpToolAdapter | None = None

    @abstractmethod
    def populate_mcp(self, mcp: FastMCP) -> None:
        """Register plugin-local tools on the provided FastMCP instance."""
        ...

    async def initialize(self, config: dict[str, Any]) -> None:
        """Initialize local FastMCP tool definitions.

        Subclasses overriding this must call ``await super().initialize(config)``
        (or ``initialize_mcp_tools()``) so definitions are ready before
        discovery validates manifest-declared global tools.
        """
        await self.initialize_mcp_tools()

    async def initialize_mcp_tools(self) -> None:
        """Populate and cache local tool definitions. Idempotent."""
        await self._get_mcp_tool_adapter().initialize()

    def get_tools_definition(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible definitions of the local FastMCP tools."""
        return self._get_mcp_tool_adapter().get_openai_tools()

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a local FastMCP tool and return a ManagedPlugin result."""
        return await self._get_mcp_tool_adapter().call_tool(tool_name, arguments)

    def _get_mcp_tool_adapter(self) -> FastMcpToolAdapter:
        # Lazy creation: uses the final self.name set by discovery/manifest
        # and tolerates subclasses whose __init__ skips super().__init__().
        adapter = getattr(self, "_fastmcp_tool_adapter", None)
        if adapter is None:
            name = (
                getattr(self, "_fastmcp_name", None)
                or getattr(self, "name", None)
                or type(self).__name__
            )
            adapter = FastMcpToolAdapter(self, name)
            self._fastmcp_tool_adapter = adapter
        return adapter


def create_fastmcp_tool_adapter(provider: McpToolProvider, name: str) -> FastMcpToolAdapter:
    """Create a local FastMCP tool adapter for *provider*."""
    return FastMcpToolAdapter(provider, name)


def _content_text(result: object) -> str:
    content = getattr(result, "content", None) or []
    parts = [str(text) for item in content if (text := getattr(item, "text", None))]
    return "\n".join(parts)
