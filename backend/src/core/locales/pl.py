"""Polish message catalog for backend user-facing strings."""

MESSAGES: dict[str, str] = {
    # Agent service
    "agent.fallback_content": "Nie mam odpowiedzi na to pytanie.",
    "agent.error.json_body": (
        "Wystąpił problem z komunikacją z modelem AI. "
        "Spróbuj ponownie lub uprość pytanie."
    ),
    "agent.error.context_length": (
        "Konwersacja jest zbyt długa. Rozpocznij nowy czat, aby kontynuować."
    ),
    "agent.error.rate_limit": "Zbyt wiele zapytań — spróbuj ponownie za chwilę.",
    "agent.error.server_error": (
        "Model AI jest chwilowo niedostępny. Spróbuj ponownie za chwilę."
    ),
    "agent.error.timeout": (
        "Model AI nie odpowiedział w wyznaczonym czasie. Spróbuj ponownie."
    ),
    "agent.error.generic": (
        "Wystąpił nieoczekiwany błąd. Spróbuj ponownie lub uprość pytanie."
    ),
    "agent.error.missing_question": "Brak pytania.",
    "agent.error.max_iterations": (
        "Przekroczono limit iteracji. Spróbuj uprościć pytanie."
    ),
    "agent.status.analyzing": "Analizuję pytanie...",
    "agent.status.get_schema": "Sprawdzam dostępne dane...",
    "agent.status.execute_query": "Pobieram wyniki...",
    "agent.status.generate_custom_sql": "Przygotowuję odpowiedź...",
    "agent.status.semantic_search": "Szukam podobnych...",
    "agent.status.default": "Przetwarzam...",
    # SQL plugin SDK
    "sql.error.query_failed": (
        "Nie udało się wykonać zapytania. "
        "Spróbuj użyć innego narzędzia lub zmienić parametry."
    ),
    "sql.error.select_only": "Dozwolone są tylko zapytania SELECT lub WITH ... SELECT",
    "sql.error.forbidden_operation": "Wykryto niedozwoloną operację: {keyword}",
    "sql.error.unknown_tool": "Nieznane narzędzie: {tool_name}",
    "sql.error.missing_query": "Brak zapytania SQL",
    "sql.error.security": (
        "Zapytanie nie spełnia wymagań bezpieczeństwa. Użyj innego narzędzia."
    ),
    "sql.tool.custom.description": (
        "Wygeneruj własne zapytanie SQL gdy żadne predefiniowane narzędzie nie "
        "pasuje. Użyj dla niestandardowych analiz i wyszukiwań."
    ),
    "sql.tool.custom.sql_query": (
        "Zapytanie SQL SELECT. TYLKO SELECT, bez INSERT/UPDATE/DELETE."
    ),
    "sql.tool.custom.reasoning": "Krótkie wyjaśnienie zapytania (opcjonalne)",
    # Auth routes
    "auth.error.profile_save_failed": "Nie udało się zapisać zmiany",
    "auth.error.create_user_local_disabled": (
        "Dodawanie użytkowników jest niedostępne w trybie local"
    ),
    "auth.error.user_email_exists": "Użytkownik o tym adresie e-mail już istnieje",
    "auth.error.user_created_local_only": (
        "Konto zapisane lokalnie, ale nie udało się utworzyć użytkownika w "
        "systemie autoryzacji"
    ),
    "auth.error.cannot_deactivate_self": "Nie możesz dezaktywować własnego konta",
    "auth.error.user_not_found": "Użytkownik nie istnieje",
    "auth.error.deactivate_failed": "Nie udało się dezaktywować użytkownika w Keycloaku",
    "auth.error.deactivate_not_in_sso": (
        "Użytkownik nie istnieje w systemie autoryzacji — konto powstało poza "
        "SSO i nie można go dezaktywować tym mechanizmem"
    ),
    "auth.error.activate_failed": "Nie udało się aktywować użytkownika w Keycloaku",
    "auth.error.activate_not_in_sso": (
        "Użytkownik nie istnieje w systemie autoryzacji — konto powstało poza "
        "SSO i nie można go aktywować tym mechanizmem"
    ),
    # Chat routes
    "chat.error.rate_limit": "Osiągnięto limit {limit} zapytań na dzień.",
}
