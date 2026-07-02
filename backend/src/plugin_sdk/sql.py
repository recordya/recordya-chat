"""Base class for SQL data source plugins.

This module provides BaseSQLPlugin - a base class for plugins that interact
with PostgreSQL databases. It handles connection pooling, SQL validation,
and tool execution.

Usage:
    from src.plugin_sdk import BaseSQLPlugin

    class MyPlugin(BaseSQLPlugin):
        name = "my_plugin"
        PROMPT_TEMPLATE = "..."
        allowed_tables = frozenset({"table1", "table2"})

        def get_predefined_tools(self) -> list[dict[str, Any]]:
            return [{"name": "tool1", "description": "...", "sql": "SELECT ..."}]

        async def _get_template_vars(self) -> dict[str, Any]:
            return {"key": "value"}
"""

# Standard library
import hashlib
import logging
import re
from abc import abstractmethod
from typing import Any, Literal

# Third party
import asyncpg

# Local
from src.core.constants import (
    DANGEROUS_KEYWORDS,
    TOOL_GENERATE_CUSTOM_SQL,
    TOOL_TYPE_CUSTOM,
    TOOL_TYPE_PREDEFINED,
)
from src.core.i18n import translate
from src.core.protocols import ManagedPlugin, ToolResult

logger = logging.getLogger(__name__)


class BaseSQLPlugin(ManagedPlugin):
    """Base implementation for SQL-based ManagedPlugin.

    Provides:
    - PostgreSQL connection management via asyncpg
    - SQL validation (read-only SELECT/WITH queries, dangerous keywords, allowed tables)
    - Tool definition building from predefined tools
    - Tool execution routing (predefined + custom SQL)
    - Template-based system prompt generation
    - Automatic metadata loading from manifest.yaml

    Subclasses must:
    - Provide manifest.yaml with metadata (id, name, description, version)
    - Define PROMPT_TEMPLATE with placeholders
    - Define allowed_tables set
    - Implement get_predefined_tools()
    - Implement _get_template_vars() for dynamic placeholder values

    Metadata (name, display_name, etc.) is loaded from manifest.yaml by discovery.
    Class attributes serve as fallbacks if manifest is not present.
    """

    # Metadata - override in subclasses
    name: str = "base"
    display_name: str = "Base Plugin"
    description: str = "Base data source plugin"
    version: str = "0.0.0"

    # Prompt template - override in subclasses
    # Use placeholders like {schema}, {categories}, {allowed_tables}, {examples}
    PROMPT_TEMPLATE: str = ""

    # Optional: Langfuse Prompt Management name.
    # When set, get_system_prompt() fetches the prompt from Langfuse (label="production")
    # and falls back to PROMPT_TEMPLATE if unavailable.
    LANGFUSE_PROMPT_NAME: str | None = None

    # Allowed tables whitelist - override in subclasses
    allowed_tables: set[str] = set()

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._config: dict[str, Any] = {}
        self._manifest: dict[str, Any] | None = None  # Set by discovery from manifest.yaml
        self._prompt_label: str = "production"  # Langfuse prompt label override

    # =========================================================================
    # Lifecycle (overrides BasePlugin defaults)
    # =========================================================================

    async def initialize(self, config: dict[str, Any]) -> None:
        """Initialize plugin with configuration.
        
        Expected config keys:
        - connection_string: PostgreSQL connection URL
        - pool_size: Max pool size (default: 10)
        """
        self._config = config
        connection_string = config.get("connection_string")
        
        if not connection_string:
            raise ValueError(f"Plugin '{self.name}': connection_string is required")

        pool_size = config.get("pool_size", 10)
        
        self._pool = await asyncpg.create_pool(
            connection_string,
            min_size=2,
            max_size=pool_size,
            statement_cache_size=0,
        )

    async def shutdown(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def health_check(self) -> bool:
        """Check database connectivity."""
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    # =========================================================================
    # Core interface (implements ManagedPlugin abstract methods)
    # =========================================================================

    def get_prompt_hash(self) -> str:
        """Return a short SHA-256 hash of the raw PROMPT_TEMPLATE.

        Useful for tracking prompt versions in observability (e.g. Langfuse)
        and detecting regressions after prompt changes.
        """
        return hashlib.sha256(self.PROMPT_TEMPLATE.encode()).hexdigest()[:12]

    async def get_system_prompt(self) -> str:
        """Build complete system prompt.

        When LANGFUSE_PROMPT_NAME is set, fetches the prompt from Langfuse
        Prompt Management (label="production") and renders {{variables}} via
        ``prompt.compile(**vars)``.  Falls back to local PROMPT_TEMPLATE on
        any failure (Langfuse unavailable, prompt missing, etc.).

        Subclasses implement _get_template_vars() to provide values
        for placeholders like {schema}, {categories}, etc.
        """
        template_vars = await self._get_template_vars()

        if self.LANGFUSE_PROMPT_NAME:
            try:
                from src.core.langfuse import get_langfuse

                langfuse = get_langfuse()
                if langfuse:
                    prompt_client = langfuse.get_prompt(
                        self.LANGFUSE_PROMPT_NAME, label=self._prompt_label,
                    )
                    if not prompt_client.is_fallback:
                        compiled = prompt_client.compile(**template_vars)
                        logger.info(
                            "Prompt '%s' v%s fetched from Langfuse",
                            self.LANGFUSE_PROMPT_NAME,
                            prompt_client.version,
                        )
                        return compiled
            except Exception:
                logger.warning(
                    "Langfuse prompt '%s' unavailable, using local template",
                    self.LANGFUSE_PROMPT_NAME,
                    exc_info=True,
                )

        return self.PROMPT_TEMPLATE.format(**template_vars)

    def get_tools_definition(self) -> list[dict[str, Any]]:
        """Build OpenAI-compatible tools from predefined tools."""
        tools = []

        for tool in self.get_predefined_tools():
            tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("parameters") or {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            })

        # Add custom SQL generation tool
        tools.append(self._build_custom_sql_tool_definition())

        return tools

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool and return result (dict format for legacy compat).

        Routes to predefined tool or custom SQL execution.
        """
        try:
            if tool_name == TOOL_GENERATE_CUSTOM_SQL:
                return await self._execute_custom_sql(arguments)
            return await self._execute_predefined_tool(tool_name, arguments or {})
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return self._error_result(translate("sql.error.query_failed"))

    # =========================================================================
    # SQL execution (internal)
    # =========================================================================

    async def execute_query(self, query: str) -> list[dict[str, Any]]:
        """Execute SQL query and return results."""
        if not self._pool:
            raise RuntimeError(f"Plugin '{self.name}' not initialized")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query.strip().rstrip(";"))
            return [dict(row) for row in rows]

    async def execute_readonly_query(self, query: str) -> list[dict[str, Any]]:
        """Execute validated read-only query."""
        is_valid, error = self.validate_sql(query)
        if not is_valid:
            raise ValueError(error or "Invalid SQL query")
        return await self.execute_query(query)

    # =========================================================================
    # SQL validation (internal)
    # =========================================================================

    def validate_sql(self, sql: str) -> tuple[bool, str | None]:
        """Validate SQL query for safety.

        Checks:
        1. Must be a read-only SELECT query (plain SELECT or WITH ... SELECT)
        2. No dangerous keywords (INSERT, UPDATE, DELETE, etc.)
        3. Only uses allowed tables
        """
        sql_clean = sql.strip()
        sql_upper = sql_clean.upper()

        cte_info = self._analyze_with_clause(sql_clean)
        if not self._is_readonly_select(sql_upper, cte_info):
            return False, translate("sql.error.select_only")

        # Check for dangerous keywords
        for keyword in DANGEROUS_KEYWORDS:
            if re.search(rf'\b{keyword}\b', sql_upper):
                return False, translate("sql.error.forbidden_operation", keyword=keyword)

        # Check allowed tables
        if self.allowed_tables:
            table_pattern = r'\b(?:from|join)\s+([a-z_][a-z0-9_]*)'
            found_tables = {
                match.group(1)
                for match in re.finditer(table_pattern, sql_clean.lower())
                if not self._is_cte_reference(match.group(1), match.start(), cte_info)
            }

            disallowed = found_tables - {t.lower() for t in self.allowed_tables}
            if disallowed:
                return False, f"Niedozwolone tabele: {', '.join(disallowed)}"

        return True, None

    @classmethod
    def _is_readonly_select(
        cls, sql_upper: str, cte_info: dict[str, Any] | None,
    ) -> bool:
        if sql_upper.startswith("SELECT"):
            return True
        if not sql_upper.startswith("WITH") or cte_info is None:
            return False
        return sql_upper[cte_info["main_start"]:].lstrip().startswith("SELECT")

    @classmethod
    def _is_cte_reference(
        cls, table_name: str, match_start: int, cte_info: dict[str, Any] | None,
    ) -> bool:
        if cte_info is None:
            return False
        cte_name = table_name.lower()
        if cte_name not in cte_info["names"]:
            return False
        own_body_range = cte_info["body_ranges"].get(cte_name)
        if own_body_range and own_body_range[0] <= match_start <= own_body_range[1]:
            return False
        return True

    @classmethod
    def _analyze_with_clause(cls, sql: str) -> dict[str, Any] | None:
        if not re.match(r"^\s*WITH\b", sql, flags=re.IGNORECASE):
            return None

        position = re.match(r"^\s*WITH\b", sql, flags=re.IGNORECASE).end()
        position = cls._skip_whitespace(sql, position)
        if re.match(r"RECURSIVE\b", sql[position:], flags=re.IGNORECASE):
            position += len("RECURSIVE")

        names: set[str] = set()
        body_ranges: dict[str, tuple[int, int]] = {}

        while position < len(sql):
            position = cls._skip_whitespace(sql, position)
            name_match = re.match(r'"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_]*)', sql[position:])
            if not name_match:
                return None
            cte_name = (name_match.group(1) or name_match.group(2)).lower()
            names.add(cte_name)
            position += name_match.end()
            position = cls._skip_whitespace(sql, position)

            if position < len(sql) and sql[position] == "(":
                position = cls._find_matching_paren(sql, position) + 1
                if position <= 0:
                    return None
                position = cls._skip_whitespace(sql, position)

            if not re.match(r"AS\b", sql[position:], flags=re.IGNORECASE):
                return None
            position += len("AS")
            position = cls._skip_whitespace(sql, position)
            if position >= len(sql) or sql[position] != "(":
                return None

            body_start = position
            body_end = cls._find_matching_paren(sql, body_start)
            if body_end < 0:
                return None
            body_ranges[cte_name] = (body_start, body_end)
            position = cls._skip_whitespace(sql, body_end + 1)

            if position < len(sql) and sql[position] == ",":
                position += 1
                continue
            return {"names": names, "body_ranges": body_ranges, "main_start": position}

        return None

    @staticmethod
    def _skip_whitespace(sql: str, position: int) -> int:
        while position < len(sql) and sql[position].isspace():
            position += 1
        return position

    @staticmethod
    def _find_matching_paren(sql: str, start: int) -> int:
        depth = 0
        quote: str | None = None
        index = start
        while index < len(sql):
            char = sql[index]
            if quote:
                if char == quote:
                    if quote == "'" and index + 1 < len(sql) and sql[index + 1] == "'":
                        index += 2
                        continue
                    quote = None
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return -1

    # =========================================================================
    # Tool execution helpers (internal)
    # =========================================================================

    def _build_custom_sql_tool_definition(self) -> dict[str, Any]:
        """Build definition for generate_custom_sql tool."""
        return {
            "type": "function",
            "function": {
                "name": TOOL_GENERATE_CUSTOM_SQL,
                "description": translate("sql.tool.custom.description"),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql_query": {
                            "type": "string",
                            "description": translate("sql.tool.custom.sql_query"),
                        },
                        "reasoning": {
                            "type": "string",
                            "description": translate("sql.tool.custom.reasoning"),
                        },
                    },
                    "required": ["sql_query"],
                },
            },
        }

    def get_tool(self, tool_name: str) -> dict[str, Any] | None:
        """Return the full predefined-tool dict by name (or ``None``)."""
        for tool in self.get_predefined_tools():
            if tool["name"] == tool_name:
                return tool
        return None

    def get_tool_sql(self, tool_name: str) -> str | None:
        """Get SQL for a predefined tool by name."""
        tool = self.get_tool(tool_name)
        return tool.get("sql") if tool else None

    def _prepare_predefined_sql(
        self, tool: dict[str, Any], arguments: dict[str, Any]
    ) -> str:
        """Render the SQL for a predefined tool with the given arguments.

        Default implementation returns ``tool['sql']`` unchanged. Override in
        subclasses that declare ``parameters`` on predefined tools and need
        to substitute placeholders or append clauses (e.g. ``LIMIT``).

        Raise ``ValueError`` to surface a user-facing validation error.
        """
        return tool["sql"]

    async def _execute_predefined_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute a predefined tool by name."""
        tool = self.get_tool(tool_name)
        if not tool or not tool.get("sql"):
            return self._error_result(translate("sql.error.unknown_tool", tool_name=tool_name))
        try:
            tool_sql = self._prepare_predefined_sql(tool, arguments or {})
        except ValueError as e:
            logger.warning("Predefined tool %r argument error: %s", tool_name, e)
            return self._error_result(str(e))
        results = await self.execute_readonly_query(tool_sql)
        return self._success_result(results, tool_sql, TOOL_TYPE_PREDEFINED)

    async def _execute_custom_sql(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute custom SQL query from arguments."""
        sql_query = arguments.get("sql_query", "")
        if not sql_query:
            return self._error_result(translate("sql.error.missing_query"))

        # Clean SQL (remove markdown code blocks)
        sql_query = re.sub(
            r"^```(?:sql)?\n?|```$", "", sql_query.strip(), flags=re.MULTILINE
        ).strip()

        # Validate
        is_valid, error = self.validate_sql(sql_query)
        if not is_valid:
            logger.warning(f"SQL validation failed: {error}")
            return self._error_result(translate("sql.error.security"))

        # Execute
        results = await self.execute_readonly_query(sql_query)
        return self._success_result(results, sql_query, TOOL_TYPE_CUSTOM)

    def _success_result(
        self, results: list[dict[str, Any]], sql: str, tool_type: Literal["predefined", "custom"]
    ) -> dict[str, Any]:
        """Factory for successful tool execution result (dict format for legacy compat)."""
        return {
            "success": True,
            "result": results,
            "row_count": len(results),
            "sql": sql,
            "tool_type": tool_type,
            "error": None,
        }

    def _error_result(self, error: str) -> dict[str, Any]:
        """Factory for failed tool execution result (dict format for legacy compat)."""
        return {
            "success": False,
            "result": None,
            "error": error,
        }

    # =========================================================================
    # Abstract methods - must be implemented by subclasses
    # =========================================================================

    @abstractmethod
    def get_predefined_tools(self) -> list[dict[str, Any]]:
        """Get list of predefined SQL tools.

        Each tool is a dict with:
        - name: Tool identifier
        - description: When to use this tool
        - sql: The SQL query to execute
        """
        ...

    @abstractmethod
    async def _get_template_vars(self) -> dict[str, Any]:
        """Get variables for PROMPT_TEMPLATE placeholders.

        Override to provide values like:
        - schema: Database schema description
        - categories: Dynamic categories from DB
        - allowed_tables: List of queryable tables
        - examples: Example queries
        """
        ...

    def get_suggestions(self) -> list[str]:
        """Get example prompts/suggestions for UI.

        Reads from manifest.yaml welcome.suggestions by default.
        Override in subclasses only if custom logic is needed.
        """
        if self._manifest and "welcome" in self._manifest:
            suggestions = self._manifest["welcome"].get("suggestions", [])
            return [s["text"] if isinstance(s, dict) else str(s) for s in suggestions]
        return []


# Backwards compatibility alias
BaseDataSourcePlugin = BaseSQLPlugin

