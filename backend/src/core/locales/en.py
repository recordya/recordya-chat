"""English message catalog for backend user-facing strings."""

MESSAGES: dict[str, str] = {
    # Agent service
    "agent.fallback_content": "I don't have an answer to that question.",
    "agent.error.json_body": (
        "There was a problem communicating with the AI model. "
        "Please try again or simplify your question."
    ),
    "agent.error.context_length": (
        "The conversation is too long. Start a new chat to continue."
    ),
    "agent.error.rate_limit": "Too many requests — please try again in a moment.",
    "agent.error.server_error": (
        "The AI model is temporarily unavailable. Please try again shortly."
    ),
    "agent.error.timeout": (
        "The AI model did not respond in time. Please try again."
    ),
    "agent.error.generic": (
        "An unexpected error occurred. Please try again or simplify your question."
    ),
    "agent.error.missing_question": "No question provided.",
    "agent.error.max_iterations": (
        "Iteration limit exceeded. Please try to simplify your question."
    ),
    "agent.status.analyzing": "Analyzing the question...",
    "agent.status.get_schema": "Checking available data...",
    "agent.status.execute_query": "Fetching results...",
    "agent.status.generate_custom_sql": "Preparing the answer...",
    "agent.status.semantic_search": "Searching for similar items...",
    "agent.status.default": "Processing...",
    # SQL plugin SDK
    "sql.error.query_failed": (
        "The query could not be executed. Try a different tool or change the parameters."
    ),
    "sql.error.select_only": "Only SELECT or WITH ... SELECT queries are allowed",
    "sql.error.forbidden_operation": "Disallowed operation detected: {keyword}",
    "sql.error.unknown_tool": "Unknown tool: {tool_name}",
    "sql.error.missing_query": "Missing SQL query",
    "sql.error.security": (
        "The query does not meet security requirements. Use a different tool."
    ),
    "sql.tool.custom.description": (
        "Generate a custom SQL query when no predefined tool fits. "
        "Use for custom analyses and searches."
    ),
    "sql.tool.custom.sql_query": (
        "A SELECT SQL query. SELECT ONLY, no INSERT/UPDATE/DELETE."
    ),
    "sql.tool.custom.reasoning": "A short explanation of the query (optional)",
    # Auth routes
    "auth.error.profile_save_failed": "Failed to save changes",
    "auth.error.create_user_local_disabled": (
        "Adding users is not available in local mode"
    ),
    "auth.error.user_email_exists": "A user with this email address already exists",
    "auth.error.user_created_local_only": (
        "Account saved locally, but the user could not be created in the "
        "authorization system"
    ),
    "auth.error.cannot_deactivate_self": "You cannot deactivate your own account",
    "auth.error.user_not_found": "User does not exist",
    "auth.error.deactivate_failed": "Failed to deactivate the user in Keycloak",
    "auth.error.deactivate_not_in_sso": (
        "The user does not exist in the authorization system — the account was "
        "created outside SSO and cannot be deactivated this way"
    ),
    "auth.error.activate_failed": "Failed to activate the user in Keycloak",
    "auth.error.activate_not_in_sso": (
        "The user does not exist in the authorization system — the account was "
        "created outside SSO and cannot be activated this way"
    ),
    # Chat routes
    "chat.error.rate_limit": "You have reached the limit of {limit} queries per day.",
}
