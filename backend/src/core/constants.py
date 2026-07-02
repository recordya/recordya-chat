"""Core constants shared across the application."""

# Dangerous SQL keywords that should not be in read-only queries
DANGEROUS_KEYWORDS = frozenset({
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "EXECUTE",
})

# Tool names
TOOL_GENERATE_CUSTOM_SQL = "generate_custom_sql"

# Tool types
TOOL_TYPE_PREDEFINED = "predefined"
TOOL_TYPE_CUSTOM = "custom"
