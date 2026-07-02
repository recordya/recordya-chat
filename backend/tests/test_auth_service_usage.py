"""Tests for AuthService rate-limit bypass — admin and super_admin are unlimited.

Covers the role gate in `check_and_increment_usage` and `get_remaining_queries`,
which routes through `has_admin_privileges` so both `admin` and `super_admin`
bypass the daily limit while regular users are counted.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.auth import AuthService

USER_ID = uuid.uuid4()


def _service_with_role(role: str) -> AuthService:
    """AuthService whose user lookup yields a user with *role*.

    The admin/super_admin branches return before touching the usage table,
    so the bare AsyncMock db is never exercised for those cases.
    """
    service = AuthService(AsyncMock())
    service.get_user_by_id = AsyncMock(return_value=SimpleNamespace(id=USER_ID, role=role))
    return service


def _service_for_user_path(role: str, usage=None) -> AuthService:
    """AuthService wired so the non-admin usage-table lookup returns *usage*."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = usage
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    service = AuthService(db)
    service.get_user_by_id = AsyncMock(return_value=SimpleNamespace(id=USER_ID, role=role))
    return service


# ---------------------------------------------------------------------------
# check_and_increment_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_and_increment_usage_admin_bypasses_limit() -> None:
    service = _service_with_role("admin")
    result = await service.check_and_increment_usage(USER_ID)
    assert result == {"allowed": True, "count": 0, "limit": -1, "is_admin": True}


@pytest.mark.asyncio
async def test_check_and_increment_usage_super_admin_bypasses_limit() -> None:
    service = _service_with_role("super_admin")
    result = await service.check_and_increment_usage(USER_ID)
    assert result == {"allowed": True, "count": 0, "limit": -1, "is_admin": True}


@pytest.mark.asyncio
async def test_check_and_increment_usage_regular_user_is_counted() -> None:
    service = _service_for_user_path("user", usage=None)
    result = await service.check_and_increment_usage(USER_ID)
    assert result["is_admin"] is False
    assert result["limit"] == AuthService.DAILY_QUERY_LIMIT
    assert result["count"] == 1
    service.db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_remaining_queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_remaining_queries_admin_unlimited() -> None:
    service = _service_with_role("admin")
    result = await service.get_remaining_queries(USER_ID)
    assert result == {
        "remaining": -1,
        "limit": -1,
        "is_admin": True,
        "is_super_admin": False,
    }


@pytest.mark.asyncio
async def test_get_remaining_queries_super_admin_unlimited() -> None:
    service = _service_with_role("super_admin")
    result = await service.get_remaining_queries(USER_ID)
    assert result == {
        "remaining": -1,
        "limit": -1,
        "is_admin": True,
        "is_super_admin": True,
    }


@pytest.mark.asyncio
async def test_get_remaining_queries_regular_user_limited() -> None:
    service = _service_for_user_path("user", usage=None)
    result = await service.get_remaining_queries(USER_ID)
    assert result["is_admin"] is False
    assert result["is_super_admin"] is False
    assert result["limit"] == AuthService.DAILY_QUERY_LIMIT
    assert result["remaining"] == AuthService.DAILY_QUERY_LIMIT
