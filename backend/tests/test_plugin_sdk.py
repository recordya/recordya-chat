"""Tests for Plugin SDK helpers."""

from src.plugin_sdk import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    BasePlugin,
    BaseSQLPlugin,
    ExecutablePlugin,
    LLMRequest,
    LLMResponse,
    ManagedPlugin,
    PluginManifest,
    ToolCall,
    ToolResult,
    ViewPlugin,
    create_tool_definition,
    has_admin_privileges,
    is_super_admin,
)

# ================= Helper Function Tests =================


def test_create_tool_definition_minimal():
    """Test creating tool definition with minimal params."""
    tool = create_tool_definition(
        name="test_tool",
        description="A test tool",
    )

    assert tool["type"] == "function"
    assert tool["function"]["name"] == "test_tool"
    assert tool["function"]["description"] == "A test tool"
    assert tool["function"]["parameters"]["type"] == "object"
    assert tool["function"]["parameters"]["properties"] == {}


def test_create_tool_definition_with_parameters():
    """Test creating tool definition with parameters."""
    params = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results"},
        },
        "required": ["query"],
    }

    tool = create_tool_definition(
        name="search",
        description="Search for items",
        parameters=params,
    )

    assert tool["function"]["parameters"] == params


def test_create_tool_definition_with_status_hint():
    """Test creating tool definition with status hint."""
    tool = create_tool_definition(
        name="fetch_data",
        description="Fetch data from source",
        status_hint="Loading data...",
    )

    assert tool["status_hint"] == "Loading data..."



# ================= Type Export Tests =================



def test_base_plugin_exported():
    """Test that BasePlugin is exported."""
    assert BasePlugin is not None
    assert hasattr(BasePlugin, "initialize")
    assert hasattr(BasePlugin, "shutdown")
    assert hasattr(BasePlugin, "health_check")
    assert hasattr(BasePlugin, "get_suggestions")


def test_managed_plugin_exported():
    """Test that ManagedPlugin is exported."""
    assert ManagedPlugin is not None
    assert hasattr(ManagedPlugin, "get_system_prompt")
    assert hasattr(ManagedPlugin, "get_tools_definition")
    assert hasattr(ManagedPlugin, "execute_tool")
    assert issubclass(ManagedPlugin, BasePlugin)


def test_executable_plugin_exported():
    """Test that ExecutablePlugin is exported."""
    assert ExecutablePlugin is not None
    assert hasattr(ExecutablePlugin, "run")
    assert hasattr(ExecutablePlugin, "get_tools")
    assert issubclass(ExecutablePlugin, BasePlugin)


def test_view_plugin_exported():
    """Test that ViewPlugin is exported."""
    assert ViewPlugin is not None
    assert issubclass(ViewPlugin, BasePlugin)
    # ViewPlugin is NOT a ManagedPlugin or ExecutablePlugin
    assert not issubclass(ViewPlugin, ManagedPlugin)
    assert not issubclass(ViewPlugin, ExecutablePlugin)


def test_llm_request_exported():
    """Test that LLMRequest is exported and usable."""
    request = LLMRequest(
        messages=[{"role": "user", "content": "Hello"}],
        model="gpt-4o",
    )

    assert request.messages == [{"role": "user", "content": "Hello"}]
    assert request.model == "gpt-4o"
    assert request.tools is None


def test_llm_response_exported():
    """Test that LLMResponse is exported and usable."""
    response = LLMResponse(
        content="Hello back!",
        tool_calls=None,
    )

    assert response.content == "Hello back!"
    assert response.tool_calls is None


def test_tool_call_exported():
    """Test that ToolCall is exported and usable."""
    call = ToolCall(
        id="call_123",
        name="test_tool",
        arguments={"key": "value"},
    )

    assert call.id == "call_123"
    assert call.name == "test_tool"
    assert call.arguments == {"key": "value"}


def test_tool_result_exported():
    """Test that ToolResult is exported and usable."""
    result = ToolResult(
        call_id="call_123",
        success=True,
        data={"result": "ok"},
    )

    assert result.call_id == "call_123"
    assert result.success is True
    assert result.data == {"result": "ok"}


# ================= BaseSQLPlugin Tests =================


def test_base_sql_plugin_exported():
    """Test that BaseSQLPlugin is exported."""
    assert BaseSQLPlugin is not None
    assert hasattr(BaseSQLPlugin, "initialize")
    assert hasattr(BaseSQLPlugin, "execute_tool")
    assert hasattr(BaseSQLPlugin, "validate_sql")
    assert issubclass(BaseSQLPlugin, ManagedPlugin)


def test_base_sql_plugin_validate_sql():
    """Test SQL validation in BaseSQLPlugin."""
    # Create a minimal concrete implementation for testing
    class TestSQLPlugin(BaseSQLPlugin):
        allowed_tables = frozenset({"users", "orders"})

        def get_predefined_tools(self):
            return []

        async def _get_template_vars(self):
            return {}

    plugin = TestSQLPlugin()

    # Valid SELECT
    is_valid, error = plugin.validate_sql("SELECT * FROM users")
    assert is_valid is True
    assert error is None

    # Invalid - INSERT (error message is in Polish)
    is_valid, error = plugin.validate_sql("INSERT INTO users VALUES (1)")
    assert is_valid is False
    assert error is not None  # "Dozwolone są tylko zapytania SELECT"

    # Invalid - disallowed table
    is_valid, error = plugin.validate_sql("SELECT * FROM secrets")
    assert is_valid is False
    assert "secrets" in error


# ================= PluginManifest Tests =================


def test_plugin_manifest_exported():
    """Test that PluginManifest is exported."""
    assert PluginManifest is not None


def test_plugin_manifest_minimal():
    """Test creating manifest with minimal fields."""
    manifest = PluginManifest(
        id="test_plugin",
        name="Test Plugin",
    )

    assert manifest.id == "test_plugin"
    assert manifest.name == "Test Plugin"


def test_plugin_manifest_full():
    """Test creating manifest with all fields."""
    manifest = PluginManifest(
        id="test_plugin",
        name="Test Plugin",
        description="A test plugin for unit tests",
        agent={"icon": "headphones", "color": "#8B5CF6"},
        welcome={
            "title": "Test Expert",
            "description": "I can help with testing",
            "suggestions": [
                {"text": "Show top 10 items", "icon": "trending-up"},
            ],
        },
        capabilities=["database", "llm"],
    )

    assert manifest.id == "test_plugin"
    assert manifest.agent.icon == "headphones"
    assert manifest.agent.color == "#8B5CF6"
    assert manifest.welcome.title == "Test Expert"
    assert len(manifest.welcome.suggestions) == 1
    assert manifest.welcome.suggestions[0].text == "Show top 10 items"
    assert manifest.capabilities == ["database", "llm"]


def test_plugin_manifest_allows_extra_fields():
    """Test that manifest allows extra fields."""
    manifest = PluginManifest(
        id="test",
        name="Test",
        custom_field="custom_value",
    )

    assert manifest.id == "test"
    # Extra fields are allowed but stored in model_extra
    assert manifest.model_extra.get("custom_field") == "custom_value"


# ================= NavConfig / ViewPlugin Manifest Tests =================


def test_plugin_manifest_nav_config():
    """Test creating manifest with nav config for ViewPlugin."""
    manifest = PluginManifest(
        id="orders",
        name="Orders",
        description="Order management view",
        nav={"icon": "clipboard-list", "label": "Zamówienia", "order": 10},
    )

    assert manifest.nav is not None
    assert manifest.nav.icon == "clipboard-list"
    assert manifest.nav.label == "Zamówienia"
    assert manifest.nav.order == 10


def test_plugin_manifest_nav_config_defaults():
    """Test NavConfig defaults when only label is provided."""
    manifest = PluginManifest(
        id="my_view",
        name="My View",
        nav={"label": "My View"},
    )

    assert manifest.nav is not None
    assert manifest.nav.icon == "layout-grid"  # default icon
    assert manifest.nav.label == "My View"
    assert manifest.nav.order == 10  # default order


def test_plugin_manifest_nav_is_none_by_default():
    """Test that nav is None when not provided (agent plugins)."""
    manifest = PluginManifest(
        id="agent_plugin",
        name="Agent Plugin",
    )

    assert manifest.nav is None


def test_plugin_manifest_enabled_default_true():
    """Test that enabled defaults to True."""
    manifest = PluginManifest(id="test", name="Test")
    assert manifest.enabled is True


def test_plugin_manifest_enabled_false():
    """Test that enabled can be set to False."""
    manifest = PluginManifest(id="test", name="Test", enabled=False)
    assert manifest.enabled is False


# ================= Role Helper Tests =================


def test_role_constants_values():
    """Role constants expose the expected string values."""
    assert ROLE_USER == "user"
    assert ROLE_ADMIN == "admin"
    assert ROLE_SUPER_ADMIN == "super_admin"


def test_has_admin_privileges_for_admin_and_super_admin():
    """admin and super_admin both have admin powers."""
    assert has_admin_privileges(ROLE_ADMIN) is True
    assert has_admin_privileges(ROLE_SUPER_ADMIN) is True


def test_has_admin_privileges_false_for_user_and_none():
    """Regular users and missing roles have no admin powers."""
    assert has_admin_privileges(ROLE_USER) is False
    assert has_admin_privileges(None) is False


def test_is_super_admin_is_exclusive():
    """Only super_admin is a super admin."""
    assert is_super_admin(ROLE_SUPER_ADMIN) is True
    assert is_super_admin(ROLE_ADMIN) is False
    assert is_super_admin(ROLE_USER) is False
    assert is_super_admin(None) is False


