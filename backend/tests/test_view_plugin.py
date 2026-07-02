"""Tests for ViewPlugin infrastructure.

Covers:
- ViewPlugin protocol (inheritance, isinstance checks)
- Discovery routing (ViewPlugin → view_plugins, not datasources)
- GET /api/views endpoint
- view_plugins registry behavior
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.core.protocols import BasePlugin, ExecutablePlugin, ManagedPlugin, ViewPlugin
from src.core.registry import PluginRegistry

# =============================================================================
# Test Fixtures: concrete plugin stubs
# =============================================================================


class StubViewPlugin(ViewPlugin):
    """Minimal concrete ViewPlugin for testing."""

    name = "stub_view"
    display_name = "Stub View"
    description = "A test view plugin"


class StubViewPluginWithRouter(ViewPlugin):
    """ViewPlugin with HTTP routes for testing."""

    name = "routable_view"
    display_name = "Routable View"
    description = "View with API"

    def get_api_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/items")
        async def list_items() -> dict:
            return {"items": [{"id": 1}]}

        return router

    def get_api_auth_mode(self) -> str:
        return "public"


class StubManagedPlugin(ManagedPlugin):
    """Minimal ManagedPlugin stub for routing comparison tests."""

    name = "stub_agent"
    display_name = "Stub Agent"
    description = "A test agent plugin"

    def get_system_prompt(self) -> str:
        return "test"

    def get_tools_definition(self) -> list:
        return []

    async def execute_tool(self, tool_name: str, arguments: dict) -> dict:
        return {}


# =============================================================================
# ViewPlugin Protocol Tests
# =============================================================================


class TestViewPluginProtocol:
    """Test ViewPlugin class hierarchy and isinstance behavior."""

    def test_is_subclass_of_base_plugin(self) -> None:
        assert issubclass(ViewPlugin, BasePlugin)

    def test_is_not_subclass_of_managed_plugin(self) -> None:
        assert not issubclass(ViewPlugin, ManagedPlugin)

    def test_is_not_subclass_of_executable_plugin(self) -> None:
        assert not issubclass(ViewPlugin, ExecutablePlugin)

    def test_isinstance_check_on_concrete_view(self) -> None:
        plugin = StubViewPlugin()
        assert isinstance(plugin, ViewPlugin)
        assert isinstance(plugin, BasePlugin)
        assert not isinstance(plugin, ManagedPlugin)
        assert not isinstance(plugin, ExecutablePlugin)

    def test_isinstance_managed_is_not_view(self) -> None:
        plugin = StubManagedPlugin()
        assert not isinstance(plugin, ViewPlugin)
        assert isinstance(plugin, ManagedPlugin)
        assert isinstance(plugin, BasePlugin)


# =============================================================================
# Discovery Routing Tests
# =============================================================================


class TestDiscoveryRouting:
    """Test that main.py routing logic sends ViewPlugin to view_plugins."""

    def test_view_plugin_goes_to_view_registry(self) -> None:
        """Simulate the routing logic from main.py lifespan."""
        view_reg: PluginRegistry[ViewPlugin] = PluginRegistry()
        agent_reg: PluginRegistry[BasePlugin] = PluginRegistry()

        loaded = {
            "stub_view": StubViewPlugin(),
            "stub_agent": StubManagedPlugin(),
        }

        for name, plugin in loaded.items():
            if isinstance(plugin, ViewPlugin):
                view_reg.register_instance(name, plugin)
            else:
                agent_reg.register_instance(name, plugin)

        assert view_reg.has_instance("stub_view")
        assert not view_reg.has_instance("stub_agent")
        assert agent_reg.has_instance("stub_agent")
        assert not agent_reg.has_instance("stub_view")

    def test_view_plugin_not_in_datasources(self) -> None:
        """ViewPlugin must never be registered in datasources."""
        agent_reg: PluginRegistry[BasePlugin] = PluginRegistry()
        view = StubViewPlugin()

        if isinstance(view, ViewPlugin):
            pass  # should go to view_plugins
        else:
            agent_reg.register_instance(view.name, view)

        assert not agent_reg.has_instance("stub_view")


# =============================================================================
# GET /api/views Endpoint Tests
# =============================================================================


def _create_view_app(plugins: dict[str, ViewPlugin]) -> FastAPI:
    """Create a FastAPI app with the views router and mocked registry."""
    from src.api.routes.views import router

    app = FastAPI()
    app.include_router(router, prefix="/api/views")
    return app


class TestViewsEndpoint:
    """Test GET /api/views endpoint."""

    def test_list_views_returns_empty_when_no_plugins(self) -> None:
        app = _create_view_app({})
        with patch("src.api.routes.views.view_plugins") as mock_reg:
            mock_reg.get_all_instances.return_value = {}
            # Bypass auth dependency
            from src.api.dependencies import get_current_user

            app.dependency_overrides[get_current_user] = lambda: {"id": "test"}
            client = TestClient(app)
            response = client.get("/api/views")
            assert response.status_code == 200
            assert response.json() == {"views": []}

    def test_list_views_returns_view_plugin_metadata(self) -> None:
        plugin = StubViewPlugin()
        plugin._manifest = {
            "nav": {"icon": "clipboard-list", "label": "Test View", "order": 5},
        }

        app = _create_view_app({"stub_view": plugin})
        with patch("src.api.routes.views.view_plugins") as mock_reg:
            mock_reg.get_all_instances.return_value = {"stub_view": plugin}
            from src.api.dependencies import get_current_user

            app.dependency_overrides[get_current_user] = lambda: {"id": "test"}
            client = TestClient(app)
            response = client.get("/api/views")
            assert response.status_code == 200
            data = response.json()
            assert len(data["views"]) == 1
            view = data["views"][0]
            assert view["id"] == "stub_view"
            assert view["name"] == "Stub View"
            assert view["icon"] == "clipboard-list"
            assert view["label"] == "Test View"
            assert view["order"] == 5

    def test_list_views_uses_defaults_when_no_manifest(self) -> None:
        """When _manifest is missing, endpoint should use sensible defaults."""
        plugin = StubViewPlugin()
        # No _manifest attribute set

        app = _create_view_app({"stub_view": plugin})
        with patch("src.api.routes.views.view_plugins") as mock_reg:
            mock_reg.get_all_instances.return_value = {"stub_view": plugin}
            from src.api.dependencies import get_current_user

            app.dependency_overrides[get_current_user] = lambda: {"id": "test"}
            client = TestClient(app)
            response = client.get("/api/views")
            assert response.status_code == 200
            view = response.json()["views"][0]
            assert view["icon"] == "layout-grid"  # default
            assert view["order"] == 10  # default
            assert view["label"] == "Stub View"  # falls back to display_name


# =============================================================================
# ViewPlugin Registry Tests
# =============================================================================


class TestViewPluginRegistry:
    """Test view_plugins registry operations."""

    def test_register_and_retrieve(self) -> None:
        reg: PluginRegistry[ViewPlugin] = PluginRegistry()
        plugin = StubViewPlugin()
        reg.register_instance("stub_view", plugin)

        assert reg.has_instance("stub_view")
        assert reg.get_instance("stub_view") is plugin

    def test_get_all_instances(self) -> None:
        reg: PluginRegistry[ViewPlugin] = PluginRegistry()
        p1 = StubViewPlugin()
        p2 = StubViewPluginWithRouter()
        reg.register_instance("v1", p1)
        reg.register_instance("v2", p2)

        all_instances = reg.get_all_instances()
        assert len(all_instances) == 2
        assert all_instances["v1"] is p1
        assert all_instances["v2"] is p2

    def test_unregister(self) -> None:
        reg: PluginRegistry[ViewPlugin] = PluginRegistry()
        reg.register_instance("stub_view", StubViewPlugin())
        assert reg.has_instance("stub_view")

        reg.unregister_instance("stub_view")
        assert not reg.has_instance("stub_view")

    def test_clear(self) -> None:
        reg: PluginRegistry[ViewPlugin] = PluginRegistry()
        reg.register_instance("v1", StubViewPlugin())
        reg.register_instance("v2", StubViewPluginWithRouter())
        assert len(reg.list_instances()) == 2

        reg.clear()
        assert len(reg.list_instances()) == 0
