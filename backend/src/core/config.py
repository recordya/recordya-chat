"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application Database (users, chats, usage)
    APP_DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/app_db"

    # Authentication
    AUTH_MODE: Literal["keycloak", "local"] = "keycloak"

    # JWT Configuration (used in local mode)
    SECRET_KEY: str = "your-super-secret-key-minimum-32-characters-long"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    ALGORITHM: str = "HS256"

    # Keycloak (used when AUTH_MODE=keycloak)
    KEYCLOAK_URL: str = "http://localhost:8180"
    KEYCLOAK_FRONTEND_URL: str = ""
    KEYCLOAK_REALM: str = "recordya"
    KEYCLOAK_CLIENT_ID: str = "recordya-chat"
    KEYCLOAK_ADMIN: str = "admin"
    KEYCLOAK_ADMIN_PASSWORD: str = "admin"

    @property
    def keycloak_frontend_url(self) -> str:
        """Public Keycloak URL (browser-facing). Falls back to KEYCLOAK_URL."""
        return self.KEYCLOAK_FRONTEND_URL or self.KEYCLOAK_URL

    # LLM Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    DEFAULT_LLM_MODEL: str = "gpt-5.2"

    # Agentic loop safety limit (max tool-loop iterations per request)
    MAX_ITERATIONS: int = 10

    # Conversation history replay (tool-call memory across turns)
    CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET: int = 8000
    CONVERSATION_DEGRADED_MAX_ROWS: int = 20
    CONVERSATION_MAX_TURNS: int = 10

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    ENV: str = "local"

    # Localization
    # Single, static source of truth for the displayed language across the
    # frontend, backend messages, and Keycloak. Resolved once; no runtime
    # switching, no browser detection. Falls back to "en" for unknown values.
    DEFAULT_LOCALE: str = "en"

    @field_validator("DEFAULT_LOCALE", mode="before")
    @classmethod
    def normalize_default_locale(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in {"en", "pl"} else "en"

    # Plugins
    PLUGINS_DIR: str = "plugins"

    # === Observability (transparent to plugins) ===
    OBSERVABILITY_PROVIDER: Literal["langfuse", "phoenix", "none"] = "none"

    # Langfuse (LLM observability)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENABLED: bool = False  # Enable when keys are configured

    # Phoenix (alternative observability)
    PHOENIX_ENDPOINT: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
