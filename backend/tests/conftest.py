"""Global test configuration for backend tests."""

import os

import pytest

os.environ.setdefault(
    "APP_DATABASE_URL",
    "postgresql+asyncpg://user:password@localhost:5432/app_db",
)


@pytest.fixture(autouse=True)
def _disable_langfuse(monkeypatch):
    """Prevent unit tests from sending traces to Langfuse."""
    monkeypatch.setattr("src.services.agent.get_langfuse", lambda: None)

