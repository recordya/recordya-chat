"""Tests for the admin-managed model configuration.

Covers:
- GET /api/config/models returns the catalog and the active selection
- PATCH /api/config/models persists the selection (admin only)
- PATCH rejects non-admins (403) and unknown models (400)
- app_settings helpers (get/set/get_selected_model)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_current_user
from src.api.routes.config import router as config_router
from src.core.config import settings
from src.db.app_database import get_db
from src.db.models import SystemSetting
from src.services.app_settings import (
    AVAILABLE_MODELS,
    get_selected_model,
    get_setting,
    is_known_model,
    set_setting,
)


class _FakeUser:
    def __init__(self, role: str = "user") -> None:
        self.id = uuid.uuid4()
        self.email = "user@test"
        self.role = role


def _make_settings_db() -> AsyncMock:
    """A DB mock that stores ``system_settings`` rows keyed by their key.

    Only the ``llm_model`` key is queried by the code under test, so the
    select stub can return the single stored row for any statement.
    """
    db = AsyncMock()
    store: dict[str, SystemSetting] = {}

    def _add(obj: SystemSetting) -> None:
        store[obj.key] = obj

    async def _execute(_stmt: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=store.get("llm_model"))
        return result

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.store = store
    return db


def _build_app(db: AsyncMock, role: str = "user") -> FastAPI:
    app = FastAPI()
    app.include_router(config_router, prefix="/api/config")
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(role)
    app.dependency_overrides[get_db] = lambda: db
    return app


def test_get_model_config_returns_catalog_and_default() -> None:
    db = _make_settings_db()
    client = TestClient(_build_app(db, role="admin"))

    response = client.get("/api/config/models")

    assert response.status_code == 200
    body = response.json()
    assert body["selected"] == settings.DEFAULT_LLM_MODEL
    assert len(body["available"]) == len(AVAILABLE_MODELS)
    assert {m["id"] for m in body["available"]} == {m.id for m in AVAILABLE_MODELS}


def test_update_model_config_admin_persists_selection() -> None:
    db = _make_settings_db()
    client = TestClient(_build_app(db, role="admin"))

    response = client.patch("/api/config/models", json={"model": "gpt-5"})

    assert response.status_code == 200
    assert response.json()["selected"] == "gpt-5"
    assert db.store["llm_model"].value == "gpt-5"

    # A subsequent read reflects the persisted value.
    assert client.get("/api/config/models").json()["selected"] == "gpt-5"


def test_update_model_config_non_admin_forbidden() -> None:
    db = _make_settings_db()
    client = TestClient(_build_app(db, role="user"))

    response = client.patch("/api/config/models", json={"model": "gpt-5"})

    assert response.status_code == 403
    assert "llm_model" not in db.store


def test_update_model_config_rejects_unknown_model() -> None:
    db = _make_settings_db()
    client = TestClient(_build_app(db, role="admin"))

    response = client.patch("/api/config/models", json={"model": "does-not-exist"})

    assert response.status_code == 400
    assert "llm_model" not in db.store


def test_is_known_model() -> None:
    assert is_known_model(AVAILABLE_MODELS[0].id)
    assert not is_known_model("nope")


@pytest.mark.asyncio
async def test_app_settings_set_then_get() -> None:
    db = _make_settings_db()

    assert await get_selected_model(db) == settings.DEFAULT_LLM_MODEL

    await set_setting(db, "llm_model", "gpt-4o")

    assert await get_setting(db, "llm_model") == "gpt-4o"
    assert await get_selected_model(db) == "gpt-4o"


@pytest.mark.asyncio
async def test_app_settings_update_existing_value() -> None:
    db = _make_settings_db()

    await set_setting(db, "llm_model", "gpt-5")
    await set_setting(db, "llm_model", "gpt-5-mini")

    assert await get_selected_model(db) == "gpt-5-mini"
    db.add.assert_called_once()
