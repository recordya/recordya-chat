"""Global tool registry — process-wide tools exported by plugins.

Core owns the registry and routing; plugins own the tool implementations.
A plugin exports tools by listing their names under ``provides_global_tools``
in its ``manifest.yaml``. Exported tools are regular entries of the plugin's
``get_tools_definition()`` and execute through the plugin's own
``execute_tool()`` — there is no separate implementation channel.

Registration happens during plugin discovery (see
:meth:`src.core.discovery.PluginDiscovery._register_global_tools`) and
consumption goes through ``CompositeToolProvider`` in the agent loop.

Authorization model: ``ChatAccessGuard`` controls UI entry to the active chat
plugin only. Global tool calls are not re-authorized against the owner plugin;
exported tools must enforce any per-user restrictions themselves.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .exceptions import AppException
from .protocols import ToolSurface, tool_definition_name, tool_error_result

logger = logging.getLogger(__name__)


class GlobalToolError(AppException):
    """Raised on global tool registration or validation failures."""


class GlobalToolRegistry:
    """Registry of tools exported by plugins for cross-plugin use.

    Tool-name collisions between plugins fail fast at registration time.
    Registration is all-or-nothing per plugin: on any missing or colliding
    tool name, none of the plugin's tools are registered.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, ToolSurface] = {}
        self._owners: dict[str, str] = {}
        self._definitions: dict[str, dict[str, Any]] = {}

    def register_plugin(
        self, plugin_name: str, plugin: ToolSurface, tool_names: Sequence[str]
    ) -> list[str]:
        """Register the plugin's *tool_names* as global tools.

        Definitions are taken from the plugin's regular
        ``get_tools_definition()``; execution routes to its ``execute_tool()``.
        Returns the registered tool names.
        """
        exported = list(dict.fromkeys(tool_names))
        if not exported:
            return []
        if not isinstance(plugin, ToolSurface):
            raise GlobalToolError(
                f"Plugin '{plugin_name}' declares provides_global_tools but does "
                "not expose get_tools_definition()/execute_tool()"
            )

        definitions_by_name: dict[str, dict[str, Any]] = {}
        for definition in plugin.get_tools_definition():
            name = tool_definition_name(definition)
            if name:
                definitions_by_name[name] = definition

        # Validate everything first (all-or-nothing)
        for tool_name in exported:
            if tool_name not in definitions_by_name:
                raise GlobalToolError(
                    f"Plugin '{plugin_name}' declares global tool '{tool_name}' "
                    "absent from its get_tools_definition()"
                )
            owner = self._owners.get(tool_name)
            if owner is not None:
                raise GlobalToolError(
                    f"Global tool '{tool_name}' from plugin '{plugin_name}' "
                    f"collides with tool already provided by plugin '{owner}'"
                )

        for tool_name in exported:
            self._plugins[tool_name] = plugin
            self._owners[tool_name] = plugin_name
            self._definitions[tool_name] = definitions_by_name[tool_name]

        return exported

    def unregister_plugin(self, plugin_name: str) -> None:
        """Remove all tools owned by *plugin_name*."""
        for tool_name in [t for t, p in self._owners.items() if p == plugin_name]:
            del self._plugins[tool_name]
            del self._owners[tool_name]
            del self._definitions[tool_name]

    def has_tool(self, tool_name: str) -> bool:
        """Check whether a global tool is registered."""
        return tool_name in self._plugins

    def get_owner(self, tool_name: str) -> str | None:
        """Return the plugin name that provides *tool_name*, if any."""
        return self._owners.get(tool_name)

    def list_tools(self) -> list[str]:
        """List all registered global tool names."""
        return list(self._plugins.keys())

    def get_tools_definition(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible definitions of all registered global tools."""
        return [dict(definition) for definition in self._definitions.values()]

    async def execute(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Route a tool call to the owning plugin's regular execute_tool()."""
        plugin = self._plugins.get(tool_name)
        if plugin is None:
            return tool_error_result(f"Unknown global tool: {tool_name}")
        return await plugin.execute_tool(tool_name, arguments)

    def clear(self) -> None:
        """Remove all registrations."""
        self._plugins.clear()
        self._owners.clear()
        self._definitions.clear()


# Global registry instance
_registry: GlobalToolRegistry | None = None


def get_global_tool_registry() -> GlobalToolRegistry:
    """Get the process-wide global tool registry."""
    global _registry
    if _registry is None:
        _registry = GlobalToolRegistry()
    return _registry
