"""Plugin SDK - stable utilities for plugin developers.

This module provides stable helpers that won't change between
minor versions. Use these instead of importing from src.core directly.

Available exports:
- BasePlugin: Shared ABC for all plugin types
- ExecutablePlugin: ABC for full-control plugins (run())
- ManagedPlugin: ABC for service-managed plugins (tool loop)
- ViewPlugin: ABC for custom UI view plugins (not chat agents)
- BaseSQLPlugin: Concrete base for SQL-based ManagedPlugin (PostgreSQL)
- FastMCPManagedPlugin: ManagedPlugin base for local FastMCP tools (populate_mcp)
- CoreEngine: LLM and tool execution primitives
- LLMRequest, LLMResponse, ToolCall, ToolResult: Type definitions
- create_tool_definition: Helper function
"""

from typing import Any

from src.core.engine import CoreEngine
from src.core.protocols import (
    BasePlugin,
    ContextConfig,
    ExecutablePlugin,
    LLMRequest,
    LLMResponse,
    ManagedPlugin,
    ToolCall,
    ToolResult,
    ViewPlugin,
)
from src.core.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    has_admin_privileges,
    is_super_admin,
)
from src.plugin_sdk.manifest import PluginManifest
from src.plugin_sdk.mcp import (
    FastMCP,
    FastMCPManagedPlugin,
    FastMcpToolAdapter,
    McpToolProvider,
    create_fastmcp_tool_adapter,
)
from src.plugin_sdk.sql import BaseSQLPlugin

__all__ = [
    # Base classes
    "BasePlugin",
    "ExecutablePlugin",
    "ManagedPlugin",
    "ViewPlugin",
    "BaseSQLPlugin",
    "CoreEngine",
    # Types
    "ContextConfig",
    "LLMRequest",
    "LLMResponse",
    "ToolCall",
    "ToolResult",
    # Manifest
    "PluginManifest",
    # MCP
    "FastMCP",
    "McpToolProvider",
    "FastMcpToolAdapter",
    "FastMCPManagedPlugin",
    "create_fastmcp_tool_adapter",
    # Roles
    "ROLE_USER",
    "ROLE_ADMIN",
    "ROLE_SUPER_ADMIN",
    "has_admin_privileges",
    "is_super_admin",
    # Helpers
    "create_tool_definition",
]


def create_tool_definition(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    status_hint: str | None = None,
) -> dict[str, Any]:
    """Create OpenAI-compatible tool definition.

    Args:
        name: Tool name
        description: Tool description for LLM
        parameters: JSON Schema for parameters (defaults to empty object)
        status_hint: Optional UI status hint

    Returns:
        OpenAI-compatible tool definition dict
    """
    tool: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters or {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
    if status_hint:
        tool["status_hint"] = status_hint
    return tool



