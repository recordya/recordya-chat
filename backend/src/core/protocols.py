"""Protocol definitions for pluggable components.

Plugin hierarchy:
    BasePlugin (ABC)           — metadata + lifecycle + suggestions
    ├── ExecutablePlugin       — full control (run())
    ├── ManagedPlugin          — service-managed tool loop
    │   └── BaseSQLPlugin      — concrete SQL base (in plugin_sdk.sql)
    └── ViewPlugin             — custom UI view (not a chat agent)
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from fastapi import APIRouter
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.core.engine import CoreEngine
    from src.db.models import User


# =============================================================================
# Data Classes for LLM/Tool Communication
# =============================================================================


@dataclass
class LLMRequest:
    """Request for LLM call."""

    messages: list[dict[str, Any]]
    model: str = "gpt-5.2"
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class LLMResponse:
    """Response from LLM call."""

    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    model: str | None = None


@dataclass
class ToolCall:
    """Represents a tool call from LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result of tool execution."""

    call_id: str
    success: bool
    data: Any = None
    error: str | None = None
    sql: str | None = None
    tool_type: Literal["predefined", "custom"] | None = None
    row_count: int | None = None


# =============================================================================
# BasePlugin — shared root for all plugin types
# =============================================================================


class BasePlugin(ABC):
    """Shared base for every plugin type.

    Provides:
    - Metadata attributes (name, display_name, description)
    - Lifecycle hooks (initialize, shutdown, health_check)
    - UI suggestions (get_suggestions)
    """

    name: str
    display_name: str
    description: str

    # Raw manifest.yaml contents; populated by PluginDiscovery after load.
    _manifest: dict[str, Any] | None = None

    def get_manifest(self) -> dict[str, Any]:
        """Return the plugin's manifest contents (empty dict when absent)."""
        return self._manifest or {}

    async def initialize(self, config: dict[str, Any]) -> None:
        """Initialize plugin with configuration."""

    async def shutdown(self) -> None:
        """Clean up resources when application shuts down."""

    async def health_check(self) -> bool:
        """Check if the plugin is healthy and accessible."""
        return True

    def get_suggestions(self) -> list[str]:
        """Get example prompts/suggestions for the UI."""
        return []


# =============================================================================
# ExecutablePlugin — full control over execution
# =============================================================================


class ExecutablePlugin(BasePlugin):
    """Plugin with full execution control.

    A plugin can implement ANY execution strategy:
    - Single agent with tool loop
    - Multi-agent collaboration
    - Rule-based logic
    - Hybrid approaches

    Plugin has FULL CONTROL over:
    - How many LLM calls to make
    - Whether to use tools
    - How to orchestrate multiple agents
    - What events to emit
    """

    @abstractmethod
    async def run(
        self,
        engine: "CoreEngine",
        question: str,
        session_id: str,
        model: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute plugin logic.

        Args:
            engine: CoreEngine providing primitives
            question: User's question
            session_id: Session ID for state management
            model: Optional model override
            **kwargs: Additional arguments (e.g., conversation_history)

        Yields:
            Events: status, tool, result, complete, error
        """
        yield {}  # pragma: no cover

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions this plugin uses."""
        ...

    def get_system_prompt(self) -> str:
        """Optional: Return system prompt for single-agent plugins."""
        return ""


# =============================================================================
# Context injection configuration
# =============================================================================


@dataclass
class ContextConfig:
    """Tells ConversationBuilder how to extract and summarise query results.

    Plugins that want previously-shown results injected into the user's
    message return an instance from ``get_context_config()``.  Plugins
    that return ``None`` (the default) get no context injection.

    Attributes:
        data_widget_types: Widget ``_widget_type`` values whose
            ``_widget_payload.rows`` should be collected.
        primary_key: Row field used for deduplication (e.g. ``"voice_id"``).
        display_field: Row field shown as a human-readable label next to the
            primary key in the context block.
    """

    data_widget_types: frozenset[str]
    primary_key: str
    display_field: str


# =============================================================================
# ManagedPlugin — service-managed tool loop
# =============================================================================


class ManagedPlugin(BasePlugin):
    """Plugin where AgentService manages the agentic tool loop.

    Plugin provides:
    - System prompt for LLM context
    - Tool definitions in OpenAI format
    - Tool execution logic

    AgentService handles:
    - LLM calls
    - Tool call parsing
    - Conversation management
    - Observability
    """

    @abstractmethod
    async def get_system_prompt(self) -> str:
        """Get the complete system prompt for LLM."""
        ...

    @abstractmethod
    def get_tools_definition(self) -> list[dict[str, Any]]:
        """Get OpenAI-compatible tools definition."""
        ...

    @abstractmethod
    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool and return result.

        Tool results may optionally include ``user_notice`` with a short
        deterministic message that AgentService should prepend to the final
        assistant text.
        """
        ...

    def prepare_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        question: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Normalize or enrich tool arguments before execution.

        Managed plugins can override this hook when tool arguments should be
        derived deterministically from the current question, recent
        conversation history, or normalized before ``execute_tool()`` runs.
        """
        return arguments

    def get_context_config(self) -> ContextConfig | None:
        """Return context injection config, or ``None`` to disable.

        Override in subclasses that want ``ConversationBuilder`` to
        automatically inject previously-shown results into the user's
        message.
        """
        return None


# Backward compatibility alias
DataSourcePlugin = ManagedPlugin


# =============================================================================
# Tool surface — shared contract for OpenAI-style tool exposure
# =============================================================================


@runtime_checkable
class ToolSurface(Protocol):
    """Minimal tool surface: OpenAI-compatible definitions plus execution.

    Satisfied structurally by ``ManagedPlugin`` and by adapters such as the
    global tool registry. Used wherever only definitions and execution are
    needed (e.g. registering a plugin's tools as global).
    """

    def get_tools_definition(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool definitions."""
        ...

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool and return a ManagedPlugin-style result."""
        ...


class ToolProvider(ToolSurface, Protocol):
    """Tool surface consumed by the agent loop (adds argument preparation)."""

    def prepare_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        question: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Normalize or enrich tool arguments before execution."""
        ...


def tool_definition_name(definition: dict[str, Any]) -> str:
    """Extract the function name from an OpenAI-compatible tool definition."""
    return str((definition.get("function") or {}).get("name") or "")


def tool_error_result(error: str) -> dict[str, Any]:
    """Build a standard ManagedPlugin-style error result."""
    return {"success": False, "error": error, "result": [], "row_count": 0}


# =============================================================================
# ViewPlugin — custom UI view (not a chat agent)
# =============================================================================


class ViewPlugin(BasePlugin):
    """Plugin that provides a custom UI view instead of a chat agent.

    ViewPlugins appear as icons in the navigation rail (IconRail) and render
    their own full-page UI.  They do NOT appear in the "Agents" sidebar
    section and are NOT registered as data sources.

    Navigation metadata (icon, label, order) is read from ``manifest.yaml``
    under the ``nav`` key — no abstract properties needed here.

    Combine with ``HttpRoutablePlugin`` to expose custom API endpoints::

        class MyView(ViewPlugin, HttpRoutablePlugin):
            ...
    """

    pass  # marker class — concrete plugins implement BasePlugin's abstract methods


# =============================================================================
# Optional HTTP routing contract for plugins
# =============================================================================

PluginRouteAuthMode = Literal["authenticated", "public"]


@runtime_checkable
class HttpRoutablePlugin(Protocol):
    """Optional plugin protocol for exposing HTTP endpoints via core routing."""

    name: str

    def get_api_router(self) -> "APIRouter":
        """Return plugin API router mounted under /api/plugins/{plugin_id}."""
        ...

    def get_api_auth_mode(self) -> PluginRouteAuthMode:
        """Return auth mode for plugin endpoints (default: authenticated)."""
        ...


# =============================================================================
# ChatAccessGuard — plugin hook for access control
# =============================================================================


@runtime_checkable
class ChatAccessGuard(Protocol):
    """Plugin-provided guard that checks whether a user can access the chatbot.

    Plugins register implementations via ``access_guards.register_instance()``.
    Core iterates over all registered guards before processing a chat request
    without knowing any plugin-specific details.

    Scope: UI entry only. Guards check whether the user may open a chat with
    the active plugin. They do not authorize global tool calls. If an exported
    tool needs per-user checks, implement them inside that tool.
    """

    async def check_access(
        self, db: "AsyncSession", user_id: UUID, datasource: str | None = None
    ) -> None:
        """Raise an appropriate HTTP exception if access should be denied.

        ``datasource`` is the name of the agent plugin the user is trying to
        reach (``None`` when it cannot be resolved). Guards that gate access
        per plugin use it to pick the relevant subscription; guards that gate
        all chat uniformly may ignore it.
        """
        ...

    async def get_access_info(self, db: "AsyncSession", user_id: UUID) -> dict[str, Any]:
        """Return extra fields to merge into the /usage response.

        Example return: {"chat_restricted": True}
        Return an empty dict if there is nothing to add.
        """
        ...


# =============================================================================
# UserLifecycleHook — plugin hook for user lifecycle events
# =============================================================================


@runtime_checkable
class UserLifecycleHook(Protocol):
    """Plugin-provided hook reacting to core user lifecycle events.

    Plugins register implementations via ``user_lifecycle_hooks.register_instance()``
    or by exposing a class with matching methods in their package — discovery
    picks them up structurally. Hooks are called best-effort: an exception in a
    hook is logged and does not roll back the core operation.
    """

    async def on_user_created(
        self,
        db: "AsyncSession",
        user: "User",
        plugin_data: dict[str, Any],
    ) -> None:
        """Called after a user has been created in core (DB + Keycloak).

        ``plugin_data`` carries the namespaced payload from the admin
        ``POST /auth/users`` request body — plugins read their own slice
        (e.g. ``plugin_data.get("my_plugin", {})``).
        """
        ...

    async def on_user_activated(self, db: "AsyncSession", user: "User") -> None:
        """Called after a user has been re-enabled in Keycloak."""
        ...

    async def on_user_deactivated(self, db: "AsyncSession", user: "User") -> None:
        """Called after a user has been disabled in Keycloak."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Universal interface for LLM providers."""

    name: str
    supports_tools: bool
    supports_streaming: bool

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a completion from the LLM."""
        ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> "AsyncGenerator[dict[str, Any], None]":
        """Stream a completion from the LLM as a sequence of chunks."""
        ...

    async def health_check(self) -> bool:
        """Check if the LLM provider is available."""
        ...
