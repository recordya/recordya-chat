"""Tests for SQL validation in plugins."""

import pytest
from src.datasources.base import BaseSQLPlugin


class TestPlugin(BaseSQLPlugin):
    """Test plugin implementation."""
    
    name = "test"
    display_name = "Test Plugin"
    description = "Test"
    version = "1.0.0"
    
    PROMPT_TEMPLATE = "Test prompt template"
    allowed_tables = frozenset({"users", "orders", "products"})
    
    def get_predefined_tools(self):
        return []
    
    async def _get_template_vars(self):
        return {}


@pytest.fixture
def plugin():
    """Create test plugin."""
    return TestPlugin()


class TestSQLValidation:
    """Tests for SQL validation."""
    
    def test_valid_select(self, plugin):
        """Test valid SELECT query passes."""
        valid, error = plugin.validate_sql("SELECT * FROM users")
        assert valid is True
        assert error is None
    
    def test_select_with_joins(self, plugin):
        """Test SELECT with JOINs passes."""
        sql = """
            SELECT u.name, o.total
            FROM users u
            JOIN orders o ON u.id = o.user_id
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is True

    def test_with_select_cte_passes(self, plugin):
        """Test read-only WITH ... SELECT queries pass."""
        sql = """
            WITH daily AS (
                SELECT u.id, COUNT(o.id) AS order_count
                FROM users u
                JOIN orders o ON u.id = o.user_id
                GROUP BY u.id
            )
            SELECT * FROM daily
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is True
        assert error is None

    def test_with_multiple_ctes_passes(self, plugin):
        """Test CTEs may reference earlier CTE names."""
        sql = """
            WITH daily AS (
                SELECT user_id, COUNT(*) AS order_count
                FROM orders
                GROUP BY user_id
            ), ranked AS (
                SELECT user_id, order_count
                FROM daily
            )
            SELECT * FROM ranked
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is True

    def test_with_disallowed_table_in_cte_is_rejected(self, plugin):
        """Test disallowed physical tables inside CTE bodies are rejected."""
        sql = """
            WITH leaked AS (
                SELECT * FROM secrets
            )
            SELECT * FROM leaked
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is False
        assert "secrets" in error.lower()

    def test_with_mutating_cte_is_rejected(self, plugin):
        """Test data-modifying CTEs remain blocked."""
        sql = """
            WITH changed AS (
                UPDATE users SET name = 'test' RETURNING id
            )
            SELECT * FROM changed
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is False
        assert "UPDATE" in error
    
    def test_reject_insert(self, plugin):
        """Test INSERT is rejected."""
        valid, error = plugin.validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert valid is False
        # Rejected because it doesn't start with SELECT
        assert "SELECT" in error or "INSERT" in error
    
    def test_reject_update(self, plugin):
        """Test UPDATE is rejected."""
        valid, error = plugin.validate_sql("UPDATE users SET name = 'test'")
        assert valid is False
        assert "UPDATE" in error or "SELECT" in error
    
    def test_reject_delete(self, plugin):
        """Test DELETE is rejected."""
        valid, error = plugin.validate_sql("DELETE FROM users WHERE id = 1")
        assert valid is False
    
    def test_reject_drop(self, plugin):
        """Test DROP is rejected."""
        valid, error = plugin.validate_sql("DROP TABLE users")
        assert valid is False
    
    def test_reject_truncate(self, plugin):
        """Test TRUNCATE is rejected."""
        valid, error = plugin.validate_sql("TRUNCATE users")
        assert valid is False
    
    def test_reject_alter(self, plugin):
        """Test ALTER is rejected."""
        valid, error = plugin.validate_sql("ALTER TABLE users ADD COLUMN age INT")
        assert valid is False
    
    def test_reject_create(self, plugin):
        """Test CREATE is rejected."""
        valid, error = plugin.validate_sql("CREATE TABLE test (id INT)")
        assert valid is False
    
    def test_reject_grant(self, plugin):
        """Test GRANT is rejected."""
        valid, error = plugin.validate_sql("GRANT SELECT ON users TO test")
        assert valid is False
    
    def test_disallowed_table(self, plugin):
        """Test query with disallowed table is rejected."""
        valid, error = plugin.validate_sql("SELECT * FROM secrets")
        assert valid is False
        assert "secrets" in error.lower()
    
    def test_multiple_allowed_tables(self, plugin):
        """Test query with multiple allowed tables passes."""
        sql = """
            SELECT * FROM users u
            JOIN orders o ON u.id = o.user_id
            JOIN products p ON o.product_id = p.id
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is True
    
    def test_mixed_allowed_disallowed(self, plugin):
        """Test query with mix of allowed and disallowed tables fails."""
        sql = """
            SELECT * FROM users u
            JOIN secrets s ON u.id = s.user_id
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is False
    
    def test_subquery_validation(self, plugin):
        """Test subquery table validation."""
        sql = """
            SELECT * FROM users
            WHERE id IN (SELECT user_id FROM orders)
        """
        valid, error = plugin.validate_sql(sql)
        assert valid is True
    
    def test_case_insensitive_keyword_detection(self, plugin):
        """Test dangerous keywords are detected case-insensitively."""
        valid, error = plugin.validate_sql("delete from users")
        assert valid is False
        
        valid, error = plugin.validate_sql("DELETE FROM users")
        assert valid is False
    
    def test_keyword_in_string_not_flagged(self, plugin):
        """Test keywords in strings are not flagged incorrectly."""
        # This is a limitation - we do simple word boundary check
        sql = "SELECT * FROM users WHERE name = 'delete_me'"
        valid, error = plugin.validate_sql(sql)
        # Should pass because DELETE is inside a word
        assert valid is True
    
    def test_empty_query(self, plugin):
        """Test empty query is rejected."""
        valid, error = plugin.validate_sql("")
        assert valid is False
    
    def test_whitespace_query(self, plugin):
        """Test whitespace-only query is rejected."""
        valid, error = plugin.validate_sql("   ")
        assert valid is False


class TestToolsDefinition:
    """Tests for OpenAI tools definition."""
    
    def test_tools_definition_format(self, plugin):
        """Test tools definition follows OpenAI format."""
        tools = plugin.get_tools_definition()
        
        # Should have at least generate_custom_sql
        assert len(tools) >= 1
        
        # Check format
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
    
    def test_custom_sql_tool_included(self, plugin):
        """Test generate_custom_sql tool is included."""
        tools = plugin.get_tools_definition()
        tool_names = [t["function"]["name"] for t in tools]
        assert "generate_custom_sql" in tool_names


class TestToolSQL:
    """Tests for get_tool_sql."""
    
    def test_get_nonexistent_tool(self, plugin):
        """Test getting SQL for nonexistent tool returns None."""
        sql = plugin.get_tool_sql("nonexistent_tool")
        assert sql is None


class TestPluginWithTools:
    """Tests for plugin with predefined tools."""
    
    def test_tool_sql_retrieval(self):
        """Test retrieving SQL for predefined tools."""
        class PluginWithTools(TestPlugin):
            def get_predefined_tools(self):
                return [
                    {
                        "name": "top_users",
                        "description": "Get top users",
                        "sql": "SELECT * FROM users ORDER BY score DESC LIMIT 10"
                    }
                ]
        
        plugin = PluginWithTools()
        sql = plugin.get_tool_sql("top_users")
        assert sql is not None
        assert "SELECT" in sql
        assert "users" in sql
    
    def test_tools_in_definition(self):
        """Test predefined tools appear in tools definition."""
        class PluginWithTools(TestPlugin):
            def get_predefined_tools(self):
                return [
                    {"name": "tool1", "description": "Tool 1", "sql": "SELECT 1"},
                    {"name": "tool2", "description": "Tool 2", "sql": "SELECT 2"},
                ]

        plugin = PluginWithTools()
        tools = plugin.get_tools_definition()
        tool_names = [t["function"]["name"] for t in tools]

        assert "tool1" in tool_names
        assert "tool2" in tool_names
        assert "generate_custom_sql" in tool_names

    def test_get_tool_returns_full_dict(self):
        """``get_tool`` returns the full dict for a predefined tool."""
        class PluginWithTools(TestPlugin):
            def get_predefined_tools(self):
                return [
                    {"name": "alpha", "description": "A", "sql": "SELECT 1"},
                ]

        plugin = PluginWithTools()
        assert plugin.get_tool("alpha")["sql"] == "SELECT 1"
        assert plugin.get_tool("missing") is None

    def test_default_prepare_predefined_sql_is_noop(self):
        """Default ``_prepare_predefined_sql`` returns ``tool['sql']`` unchanged."""
        class PluginWithTools(TestPlugin):
            def get_predefined_tools(self):
                return [{"name": "x", "description": "x", "sql": "SELECT 1"}]

        plugin = PluginWithTools()
        tool = plugin.get_tool("x")
        assert plugin._prepare_predefined_sql(tool, {}) == "SELECT 1"
        assert plugin._prepare_predefined_sql(tool, {"limit": 5}) == "SELECT 1"

    def test_parameters_propagated_to_tool_definition(self):
        """If a predefined tool declares ``parameters``, they must be exposed."""
        class PluginWithTools(TestPlugin):
            def get_predefined_tools(self):
                return [{
                    "name": "with_params",
                    "description": "Has parameters",
                    "sql": "SELECT 1",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                        "required": [],
                    },
                }]

        plugin = PluginWithTools()
        tools = plugin.get_tools_definition()
        target = next(t for t in tools if t["function"]["name"] == "with_params")
        assert target["function"]["parameters"]["properties"] == {
            "limit": {"type": "integer"},
        }
