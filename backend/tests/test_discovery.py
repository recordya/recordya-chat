"""Tests for plugin discovery."""

import logging
import types
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from src.core.discovery import PluginDiscovery
from src.core.protocols import BasePlugin, ChatAccessGuard, ViewPlugin
from src.core.registry import PluginRegistry


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
