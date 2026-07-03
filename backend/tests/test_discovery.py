"""Tests for plugin discovery."""

import logging
import sys
import types
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from src.core.discovery import PluginDiscovery, PluginLoadError
from src.core.global_tools import (
    GlobalToolError,
    GlobalToolRegistry,
    get_global_tool_registry,
)
from src.core.protocols import BasePlugin, ChatAccessGuard, ViewPlugin
from src.core.registry import PluginRegistry
from src.plugin_sdk import FastMCP, FastMCPManagedPlugin


class MockPlugin(BasePlugin):
    """Mock plugin for testing."""

    name = "mock_plugin"
    display_name = "Mock Plugin"
    description = "Test plugin"
    version = "1.0.0"

    async def initialize(self, config):
        self._config = config


class MockViewPlugin(ViewPlugin):
    """Mock view plugin for testing."""

    name = "mock_view"
    display_name = "Mock View"
    description = "Test view plugin"
    version = "1.0.0"

    async def initialize(self, config):
        self._config = config


class UnhealthyPlugin(BasePlugin):
    """Plugin that fails health check."""

    name = "unhealthy"
    display_name = "Unhealthy"
    description = "Test"
    version = "1.0.0"

    async def health_check(self):
        return False


@pytest.fixture
def discovery():
    """Create discovery instance."""
    return PluginDiscovery()


@pytest.mark.asyncio
async def test_load_plugin_success(discovery):
    """Test successful plugin loading."""
    config = {"connection_string": "test://"}

    await discovery._load_plugin(MockPlugin, {"mock_plugin": config})

    assert discovery.get_plugin("mock_plugin") is not None
    assert len(discovery.list_plugins()) == 1


@pytest.mark.asyncio
async def test_load_plugin_failed_health_check(discovery, caplog):
    """Test plugin that fails health check is skipped."""
    await discovery._load_plugin(UnhealthyPlugin, {})

    assert discovery.get_plugin("unhealthy") is None
    assert "failed health check" in caplog.text.lower()


@pytest.mark.asyncio
async def test_load_plugin_duplicate(discovery):
    """Test duplicate plugin is skipped."""
    await discovery._load_plugin(MockPlugin, {})
    await discovery._load_plugin(MockPlugin, {})  # Duplicate

    assert len(discovery.list_plugins()) == 1


@pytest.mark.asyncio
async def test_shutdown_all(discovery):
    """Test shutdown cleans up all plugins."""
    await discovery._load_plugin(MockPlugin, {})
    assert len(discovery.list_plugins()) == 1

    await discovery.shutdown_all()

    assert len(discovery.list_plugins()) == 0


def test_list_plugins_empty(discovery):
    """Test listing empty plugins."""
    assert discovery.list_plugins() == []


def test_get_plugin_not_found(discovery):
    """Test getting non-existent plugin."""
    assert discovery.get_plugin("nonexistent") is None


@pytest.mark.asyncio
async def test_get_all_plugins(discovery):
    """Test getting all plugins."""
    await discovery._load_plugin(MockPlugin, {})

    plugins = discovery.get_all_plugins()
    assert len(plugins) == 1
    assert "mock_plugin" in plugins


@pytest.mark.asyncio
async def test_config_priority():
    """Test configuration priority."""
    discovery = PluginDiscovery()

    # Explicit config should be used
    explicit_config = {"connection_string": "explicit://"}
    await discovery._load_plugin(MockPlugin, {"mock_plugin": explicit_config})

    plugin = discovery.get_plugin("mock_plugin")
    assert plugin._config == explicit_config


# ================= enabled flag tests =================


@pytest.mark.asyncio
async def test_disabled_plugin_is_skipped(discovery, caplog):
    """Test that a plugin with enabled=False in manifest is not loaded."""
    disabled_manifest = {"id": "mock_plugin", "name": "Mock", "enabled": False}

    with caplog.at_level(logging.INFO):
        with patch.object(discovery, "_load_manifest", return_value=disabled_manifest):
            await discovery._load_plugin(MockPlugin, {})

    assert discovery.get_plugin("mock_plugin") is None
    assert "disabled in manifest" in caplog.text.lower()


@pytest.mark.asyncio
async def test_enabled_plugin_is_loaded(discovery):
    """Test that a plugin with enabled=True in manifest loads normally."""
    enabled_manifest = {"id": "mock_plugin", "name": "Mock", "enabled": True}

    with patch.object(discovery, "_load_manifest", return_value=enabled_manifest):
        await discovery._load_plugin(MockPlugin, {})

    assert discovery.get_plugin("mock_plugin") is not None


@pytest.mark.asyncio
async def test_plugin_without_enabled_key_is_loaded(discovery):
    """Test that a plugin without 'enabled' in manifest loads (default=True)."""
    manifest_no_enabled = {"id": "mock_plugin", "name": "Mock"}

    with patch.object(discovery, "_load_manifest", return_value=manifest_no_enabled):
        await discovery._load_plugin(MockPlugin, {})

    assert discovery.get_plugin("mock_plugin") is not None


@pytest.mark.asyncio
async def test_disabled_view_plugin_is_skipped(discovery, caplog):
    """Test that a ViewPlugin with enabled=False is also skipped."""
    disabled_manifest = {"id": "mock_view", "name": "Mock View", "enabled": False}

    with caplog.at_level(logging.INFO):
        with patch.object(discovery, "_load_manifest", return_value=disabled_manifest):
            await discovery._load_plugin(MockViewPlugin, {})

    assert discovery.get_plugin("mock_view") is None
    assert "disabled in manifest" in caplog.text.lower()



# ================= access guard discovery tests =================


class StubAccessGuard:
    """Minimal ChatAccessGuard implementation for testing."""

    async def check_access(
        self, db: Any, user_id: UUID, datasource: str | None = None
    ) -> None:
        pass

    async def get_access_info(self, db: Any, user_id: UUID) -> dict[str, Any]:
        return {"test_guard": True}


class NotAGuard:
    """Class that only has check_access but not get_access_info."""

    async def check_access(
        self, db: Any, user_id: UUID, datasource: str | None = None
    ) -> None:
        pass


def test_register_access_guards_detects_guard():
    """Test that _register_access_guards finds and registers a valid guard."""
    module = types.ModuleType("fake_module")
    module.StubAccessGuard = StubAccessGuard

    registry = PluginRegistry()
    with patch("src.core.registry.access_guards", registry):
        PluginDiscovery._register_access_guards(module, "test_pkg")

    assert registry.has_instance("test_pkg:StubAccessGuard")
    instance = registry.get_all_instances()["test_pkg:StubAccessGuard"]
    assert hasattr(instance, "check_access")
    assert hasattr(instance, "get_access_info")


def test_register_access_guards_ignores_incomplete_class():
    """Test that a class missing get_access_info is NOT registered."""
    module = types.ModuleType("fake_module")
    module.NotAGuard = NotAGuard

    registry = PluginRegistry()
    with patch("src.core.registry.access_guards", registry):
        PluginDiscovery._register_access_guards(module, "test_pkg")

    assert not registry.has_instance("test_pkg:NotAGuard")


def test_register_access_guards_skips_protocol_class():
    """Test that the ChatAccessGuard protocol itself is not registered."""
    module = types.ModuleType("fake_module")
    module.ChatAccessGuard = ChatAccessGuard

    registry = PluginRegistry()
    with patch("src.core.registry.access_guards", registry):
        PluginDiscovery._register_access_guards(module, "test_pkg")

    assert len(registry.get_all_instances()) == 0


def test_register_access_guards_idempotent():
    """Test that calling _register_access_guards twice does not duplicate."""
    module = types.ModuleType("fake_module")
    module.StubAccessGuard = StubAccessGuard

    registry = PluginRegistry()
    with patch("src.core.registry.access_guards", registry):
        PluginDiscovery._register_access_guards(module, "test_pkg")
        PluginDiscovery._register_access_guards(module, "test_pkg")

    assert len(registry.get_all_instances()) == 1



# ================= access guard flow tests =================


class DenyingGuard:
    """Guard that always denies access."""

    async def check_access(
        self, db: Any, user_id: UUID, datasource: str | None = None
    ) -> None:
        from src.core.exceptions import forbidden
        raise forbidden("Access denied by test guard")

    async def get_access_info(self, db: Any, user_id: UUID) -> dict[str, Any]:
        return {"access_denied": True}


class AllowingGuard:
    """Guard that always allows access."""

    async def check_access(
        self, db: Any, user_id: UUID, datasource: str | None = None
    ) -> None:
        pass

    async def get_access_info(self, db: Any, user_id: UUID) -> dict[str, Any]:
        return {"extra_field": "value"}


@pytest.mark.asyncio
async def test_guard_check_access_raises_on_deny():
    """Test that a denying guard raises HTTPException."""
    from fastapi import HTTPException

    guard = DenyingGuard()
    with pytest.raises(HTTPException) as exc_info:
        await guard.check_access(None, UUID("00000000-0000-0000-0000-000000000001"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_guard_check_access_passes_on_allow():
    """Test that an allowing guard does not raise."""
    guard = AllowingGuard()
    await guard.check_access(None, UUID("00000000-0000-0000-0000-000000000001"))


@pytest.mark.asyncio
async def test_guard_get_access_info_returns_extra_fields():
    """Test that get_access_info returns mergeable dict."""
    guard = AllowingGuard()
    info = await guard.get_access_info(None, UUID("00000000-0000-0000-0000-000000000001"))
    assert info == {"extra_field": "value"}


@pytest.mark.asyncio
async def test_multiple_guards_first_deny_stops_access():
    """Test that if any guard denies, access is blocked (simulates core loop)."""
    from fastapi import HTTPException

    guards = [AllowingGuard(), DenyingGuard(), AllowingGuard()]
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    with pytest.raises(HTTPException) as exc_info:
        for guard in guards:
            await guard.check_access(None, test_user_id)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_multiple_guards_merge_access_info():
    """Test that get_access_info from multiple guards is merged."""
    guard1 = AllowingGuard()
    guard2 = DenyingGuard()

    test_user_id = UUID("00000000-0000-0000-0000-000000000001")
    extra: dict = {}
    for guard in [guard1, guard2]:
        extra.update(await guard.get_access_info(None, test_user_id))

    assert extra == {"extra_field": "value", "access_denied": True}


# ================= global tool tests =================


def _global_tool_def(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


class GlobalToolPlugin(BasePlugin):
    """Plugin exporting one of its regular tools via provides_global_tools."""

    name = "global_tool_plugin"
    display_name = "Global Tool Plugin"
    description = "Test"
    version = "1.0.0"

    async def initialize(self, config):
        pass

    def get_tools_definition(self) -> list[dict[str, Any]]:
        return [_global_tool_def("shared_tool")]

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return {"success": True, "result": [], "row_count": 0}


class CollidingGlobalToolPlugin(GlobalToolPlugin):
    """Second plugin exporting a tool with the same name."""

    name = "colliding_plugin"


class FastMCPGlobalToolPlugin(FastMCPManagedPlugin):
    """FastMCP-managed plugin exporting a local tool via provides_global_tools."""

    name = "fastmcp_global_plugin"
    display_name = "FastMCP Global Plugin"
    description = "Test"
    version = "1.0.0"

    async def get_system_prompt(self) -> str:
        return "prompt"

    def populate_mcp(self, mcp: FastMCP) -> None:
        mcp.add_tool(self.shared_tool)

    async def shared_tool(self, value: str) -> dict[str, Any]:
        """Shared tool."""
        return {"success": True, "result": [{"value": value}], "row_count": 1}


def _providing_manifest(plugin_id: str) -> dict[str, Any]:
    return {
        "id": plugin_id,
        "name": plugin_id,
        "provides_global_tools": ["shared_tool"],
    }


@pytest.fixture
def global_registry():
    """Isolate the process-wide global tool registry per test."""
    registry = get_global_tool_registry()
    registry.clear()
    yield registry
    registry.clear()


@pytest.mark.asyncio
async def test_load_plugin_registers_global_tools(discovery, global_registry):
    """Manifest-declared tools are registered during plugin load."""
    manifest = _providing_manifest("global_tool_plugin")
    with patch.object(discovery, "_load_manifest", return_value=manifest):
        await discovery._load_plugin(GlobalToolPlugin, {})

    assert global_registry.has_tool("shared_tool")
    assert global_registry.get_owner("shared_tool") == "global_tool_plugin"


@pytest.mark.asyncio
async def test_load_fastmcp_managed_plugin_registers_global_tools(
    discovery, global_registry
):
    """FastMCP-managed plugin definitions are ready when global tools register."""
    manifest = _providing_manifest("fastmcp_global_plugin")
    with patch.object(discovery, "_load_manifest", return_value=manifest):
        await discovery._load_plugin(FastMCPGlobalToolPlugin, {})

    assert global_registry.has_tool("shared_tool")
    assert global_registry.get_owner("shared_tool") == "fastmcp_global_plugin"


@pytest.mark.asyncio
async def test_load_plugin_without_declaration_registers_nothing(
    discovery, global_registry
):
    """No provides_global_tools in manifest means no global registration."""
    await discovery._load_plugin(GlobalToolPlugin, {})

    assert not global_registry.has_tool("shared_tool")


@pytest.mark.asyncio
async def test_global_tool_collision_aborts_startup(discovery, global_registry):
    """A tool-name collision propagates and aborts startup; first registration wins."""
    with patch.object(
        discovery,
        "_load_manifest",
        return_value=_providing_manifest("global_tool_plugin"),
    ):
        await discovery._load_plugin(GlobalToolPlugin, {})
    with patch.object(
        discovery,
        "_load_manifest",
        return_value=_providing_manifest("colliding_plugin"),
    ):
        with pytest.raises(GlobalToolError, match="collides"):
            await discovery._load_plugin(CollidingGlobalToolPlugin, {})

    assert discovery.get_plugin("colliding_plugin") is None
    assert global_registry.get_owner("shared_tool") == "global_tool_plugin"


@pytest.mark.asyncio
async def test_declared_tool_missing_from_definitions_aborts_startup(
    discovery, global_registry
):
    """A manifest declaring a tool absent from get_tools_definition aborts startup."""
    manifest = {
        "id": "global_tool_plugin",
        "name": "Global Tool Plugin",
        "provides_global_tools": ["nonexistent_tool"],
    }
    with patch.object(discovery, "_load_manifest", return_value=manifest):
        with pytest.raises(GlobalToolError, match="nonexistent_tool"):
            await discovery._load_plugin(GlobalToolPlugin, {})

    assert discovery.get_plugin("global_tool_plugin") is None
    assert not global_registry.has_tool("nonexistent_tool")


def _plugin_class_with_manifest(tmp_path, base_class, manifest_yaml: str) -> type:
    """Create a plugin class whose module dir contains the given manifest.yaml."""
    module_name = f"fake_manifest_module_{base_class.__name__}"
    module = types.ModuleType(module_name)
    module.__file__ = str(tmp_path / "__init__.py")
    sys.modules[module_name] = module
    (tmp_path / "manifest.yaml").write_text(manifest_yaml)
    return type(f"Fake{base_class.__name__}", (base_class,), {"__module__": module_name})


@pytest.mark.asyncio
async def test_non_list_provides_manifest_aborts_startup(
    discovery, global_registry, tmp_path
):
    """A manifest with a string provides_global_tools fails Pydantic validation."""
    plugin_class = _plugin_class_with_manifest(
        tmp_path,
        GlobalToolPlugin,
        'id: "global_tool_plugin"\n'
        'name: "Global Tool Plugin"\n'
        'provides_global_tools: "shared_tool"\n',
    )
    try:
        with pytest.raises(PluginLoadError, match="Invalid manifest"):
            await discovery._load_plugin(plugin_class, {})
    finally:
        del sys.modules[plugin_class.__module__]

    assert discovery.get_plugin("global_tool_plugin") is None
    assert not global_registry.has_tool("shared_tool")


@pytest.mark.asyncio
async def test_validate_required_global_tools_missing_raises(
    discovery, global_registry
):
    """Startup validation fails fast when a required global tool is absent."""
    manifest = {
        "id": "mock_plugin",
        "name": "Mock",
        "requires_global_tools": ["absent_tool"],
    }
    with patch.object(discovery, "_load_manifest", return_value=manifest):
        await discovery._load_plugin(MockPlugin, {})

    with pytest.raises(PluginLoadError, match="absent_tool"):
        discovery._validate_required_global_tools()


@pytest.mark.asyncio
async def test_non_list_requires_manifest_aborts_startup(
    discovery, global_registry, tmp_path
):
    """A manifest with a string requires_global_tools fails Pydantic validation."""
    plugin_class = _plugin_class_with_manifest(
        tmp_path,
        MockPlugin,
        'id: "mock_plugin"\n'
        'name: "Mock"\n'
        'requires_global_tools: "shared_tool"\n',
    )
    try:
        with pytest.raises(PluginLoadError, match="Invalid manifest"):
            await discovery._load_plugin(plugin_class, {})
    finally:
        del sys.modules[plugin_class.__module__]

    assert discovery.get_plugin("mock_plugin") is None


@pytest.mark.asyncio
async def test_validate_required_global_tools_present_passes(
    discovery, global_registry
):
    """Validation passes when required global tools are provided."""
    with patch.object(
        discovery,
        "_load_manifest",
        return_value=_providing_manifest("global_tool_plugin"),
    ):
        await discovery._load_plugin(GlobalToolPlugin, {})
    manifest = {
        "id": "mock_plugin",
        "name": "Mock",
        "requires_global_tools": ["shared_tool"],
    }
    with patch.object(discovery, "_load_manifest", return_value=manifest):
        await discovery._load_plugin(MockPlugin, {})

    discovery._validate_required_global_tools()


@pytest.mark.asyncio
async def test_shutdown_all_unregisters_global_tools(discovery, global_registry):
    """Shutdown removes exported tools from the global registry."""
    manifest = _providing_manifest("global_tool_plugin")
    with patch.object(discovery, "_load_manifest", return_value=manifest):
        await discovery._load_plugin(GlobalToolPlugin, {})
    assert global_registry.has_tool("shared_tool")

    await discovery.shutdown_all()

    assert not global_registry.has_tool("shared_tool")


@pytest.mark.asyncio
async def test_failed_discovery_cleans_up_plugins_and_global_registry(
    discovery, global_registry
):
    """A required-global-tools validation failure leaves no partial state."""

    async def load_provider_then_broken_consumer(configs):
        with patch.object(
            discovery,
            "_load_manifest",
            return_value=_providing_manifest("global_tool_plugin"),
        ):
            await discovery._load_plugin(GlobalToolPlugin, configs)

        manifest = {
            "id": "mock_plugin",
            "name": "Mock",
            "requires_global_tools": ["absent_tool"],
        }
        with patch.object(discovery, "_load_manifest", return_value=manifest):
            await discovery._load_plugin(MockPlugin, configs)

    with patch.object(
        discovery,
        "_discover_entry_points",
        side_effect=load_provider_then_broken_consumer,
    ):
        with pytest.raises(PluginLoadError, match="absent_tool"):
            await discovery.discover_and_load()

    assert discovery.list_plugins() == []
    assert global_registry.list_tools() == []


def test_registry_collision_raises():
    """Registering the same tool name from two plugins fails."""
    registry = GlobalToolRegistry()
    plugin = GlobalToolPlugin()
    registry.register_plugin("first", plugin, ["shared_tool"])

    with pytest.raises(GlobalToolError, match="collides"):
        registry.register_plugin("second", plugin, ["shared_tool"])


def test_registry_registration_is_all_or_nothing():
    """On any collision, none of the plugin's tools are registered."""

    class TwoToolPlugin:
        def get_tools_definition(self) -> list[dict[str, Any]]:
            return [_global_tool_def("brand_new_tool"), _global_tool_def("shared_tool")]

        async def execute_tool(self, tool_name, arguments):
            return {"success": True, "result": [], "row_count": 0}

    registry = GlobalToolRegistry()
    registry.register_plugin("first", GlobalToolPlugin(), ["shared_tool"])

    with pytest.raises(GlobalToolError):
        registry.register_plugin(
            "second", TwoToolPlugin(), ["brand_new_tool", "shared_tool"]
        )

    assert not registry.has_tool("brand_new_tool")
    assert registry.get_owner("shared_tool") == "first"


def test_registry_missing_declared_tool_raises():
    """Declaring a tool absent from get_tools_definition fails registration."""
    registry = GlobalToolRegistry()

    with pytest.raises(GlobalToolError, match="absent"):
        registry.register_plugin("first", GlobalToolPlugin(), ["nonexistent_tool"])

    assert not registry.has_tool("nonexistent_tool")


def test_registry_plugin_without_tool_surface_raises():
    """A plugin without get_tools_definition/execute_tool cannot export tools."""
    registry = GlobalToolRegistry()

    with pytest.raises(GlobalToolError, match="does not expose"):
        registry.register_plugin("first", object(), ["shared_tool"])


@pytest.mark.asyncio
async def test_registry_execute_unknown_tool_returns_error_result():
    """Executing an unregistered tool returns a standard error payload."""
    registry = GlobalToolRegistry()

    result = await registry.execute("nope", {})

    assert result["success"] is False
    assert "nope" in result["error"]
