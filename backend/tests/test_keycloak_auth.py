"""Tests for Keycloak SSO authentication — token decoding, claims mapping, JIT provisioning."""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import AuthenticationError

# ---------------------------------------------------------------------------
# decode_keycloak_token
# ---------------------------------------------------------------------------

FAKE_JWKS = {
    "keys": [
        {
            "kid": "test-key-1",
            "kty": "RSA",
            "use": "sig",
            "n": "fake-n",
            "e": "AQAB",
        }
    ]
}

VALID_PAYLOAD = {
    "sub": "kc-uuid-1234",
    "email": "jan@firma.pl",
    "azp": "recordya-chat",
    "aud": "account",
    "name": "Jan Kowalski",
    "preferred_username": "jan@firma.pl",
    "realm_roles": ["user", "admin"],
}


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    """Reset JWKS cache between tests."""
    from src.core import security
    security._jwks_cache.clear()
    security._jwks_cache_expiry = 0
    yield
    security._jwks_cache.clear()
    security._jwks_cache_expiry = 0


class TestDecodeKeycloakToken:
    """Tests for decode_keycloak_token in security.py."""

    @pytest.mark.asyncio
    async def test_rejects_token_without_kid_header(self):
        from src.core.security import decode_keycloak_token

        with patch("src.core.security.jwt") as mock_jwt:
            mock_jwt.get_unverified_header.return_value = {}
            with pytest.raises(AuthenticationError, match="kid"):
                await decode_keycloak_token("some.fake.token")

    @pytest.mark.asyncio
    async def test_rejects_wrong_azp(self):
        """Token issued for a different client should be rejected."""
        from src.core.security import decode_keycloak_token

        payload = {**VALID_PAYLOAD, "azp": "other-client", "aud": "account"}

        with (
            patch("src.core.security.jwt") as mock_jwt,
            patch("src.core.security._fetch_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": "test-key-1"}
            mock_jwt.decode.return_value = payload
            with pytest.raises(AuthenticationError, match="not issued for client"):
                await decode_keycloak_token("some.fake.token")

    @pytest.mark.asyncio
    async def test_accepts_matching_azp(self):
        """Token with correct azp should be accepted even if aud != client_id."""
        from src.core.security import decode_keycloak_token

        with (
            patch("src.core.security.jwt") as mock_jwt,
            patch("src.core.security._fetch_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": "test-key-1"}
            mock_jwt.decode.return_value = VALID_PAYLOAD
            result = await decode_keycloak_token("some.fake.token")
            assert result["email"] == "jan@firma.pl"
            assert result["sub"] == "kc-uuid-1234"

    @pytest.mark.asyncio
    async def test_accepts_matching_aud_list(self):
        """Token with client_id in aud list should be accepted."""
        from src.core.security import decode_keycloak_token

        payload = {**VALID_PAYLOAD, "azp": "other", "aud": ["account", "recordya-chat"]}

        with (
            patch("src.core.security.jwt") as mock_jwt,
            patch("src.core.security._fetch_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": "test-key-1"}
            mock_jwt.decode.return_value = payload
            result = await decode_keycloak_token("some.fake.token")
            assert result["sub"] == "kc-uuid-1234"

    @pytest.mark.asyncio
    async def test_rejects_missing_sub(self):
        """Token without sub claim should be rejected."""
        from src.core.security import decode_keycloak_token

        payload = {**VALID_PAYLOAD, "sub": ""}

        with (
            patch("src.core.security.jwt") as mock_jwt,
            patch("src.core.security._fetch_jwks", new_callable=AsyncMock, return_value=FAKE_JWKS),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": "test-key-1"}
            mock_jwt.decode.return_value = payload
            with pytest.raises(AuthenticationError, match="sub"):
                await decode_keycloak_token("some.fake.token")



    @pytest.mark.asyncio
    async def test_key_rotation_triggers_jwks_refresh(self):
        """When kid is not in cache, JWKS should be re-fetched."""
        from src.core.security import decode_keycloak_token

        rotated_jwks = {
            "keys": [{"kid": "new-key", "kty": "RSA", "use": "sig", "n": "n2", "e": "AQAB"}]
        }
        call_count = 0

        async def mock_fetch():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"keys": []}  # First call: old cache, no matching key
            return rotated_jwks  # Second call: refreshed with new key

        payload = {**VALID_PAYLOAD}

        with (
            patch("src.core.security.jwt") as mock_jwt,
            patch("src.core.security._fetch_jwks", side_effect=mock_fetch),
        ):
            mock_jwt.get_unverified_header.return_value = {"kid": "new-key"}
            mock_jwt.decode.return_value = payload
            result = await decode_keycloak_token("rotated.token")
            assert result["email"] == "jan@firma.pl"
            assert call_count == 2


class TestJwksCache:
    """Tests for JWKS caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_is_used_within_ttl(self):
        """Cached JWKS should be returned without HTTP call if TTL not expired."""
        from src.core import security

        security._jwks_cache = FAKE_JWKS
        security._jwks_cache_expiry = time.monotonic() + 999

        with patch("src.core.security.httpx.AsyncClient") as mock_client:
            result = await security._fetch_jwks()
            assert result == FAKE_JWKS
            mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_cache_triggers_refresh(self):
        """Expired cache should trigger a new HTTP request."""
        from src.core import security

        security._jwks_cache = {"keys": []}
        security._jwks_cache_expiry = time.monotonic() - 1  # expired

        mock_response = MagicMock()
        mock_response.json.return_value = FAKE_JWKS
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("src.core.security.httpx.AsyncClient", return_value=mock_client_instance):
            result = await security._fetch_jwks()
            assert result == FAKE_JWKS
            mock_client_instance.get.assert_called_once()


# ---------------------------------------------------------------------------
# get_token_claims
# ---------------------------------------------------------------------------

class TestGetTokenClaims:
    """Tests for get_token_claims in dependencies.py."""

    @pytest.mark.asyncio
    async def test_keycloak_mode_maps_admin_role(self):
        from src.api.dependencies import get_token_claims

        payload = {**VALID_PAYLOAD, "realm_roles": ["user", "admin"]}

        with (
            patch("src.api.dependencies.settings") as mock_settings,
            patch(
                "src.api.dependencies.decode_keycloak_token",
                new_callable=AsyncMock, return_value=payload,
            ),
        ):
            mock_settings.AUTH_MODE = "keycloak"
            claims = await get_token_claims(authorization="Bearer fake.token")
            assert claims.role == "admin"
            assert claims.email == "jan@firma.pl"
            assert claims.display_name == "Jan Kowalski"

    @pytest.mark.asyncio
    async def test_keycloak_mode_maps_super_admin_role(self):
        from src.api.dependencies import get_token_claims

        payload = {**VALID_PAYLOAD, "realm_roles": ["user", "super_admin"]}

        with (
            patch("src.api.dependencies.settings") as mock_settings,
            patch(
                "src.api.dependencies.decode_keycloak_token",
                new_callable=AsyncMock, return_value=payload,
            ),
        ):
            mock_settings.AUTH_MODE = "keycloak"
            claims = await get_token_claims(authorization="Bearer fake.token")
            assert claims.role == "super_admin"

    @pytest.mark.asyncio
    async def test_keycloak_mode_super_admin_takes_precedence_over_admin(self):
        from src.api.dependencies import get_token_claims

        payload = {**VALID_PAYLOAD, "realm_roles": ["user", "admin", "super_admin"]}

        with (
            patch("src.api.dependencies.settings") as mock_settings,
            patch(
                "src.api.dependencies.decode_keycloak_token",
                new_callable=AsyncMock, return_value=payload,
            ),
        ):
            mock_settings.AUTH_MODE = "keycloak"
            claims = await get_token_claims(authorization="Bearer fake.token")
            assert claims.role == "super_admin"

    @pytest.mark.asyncio
    async def test_keycloak_mode_maps_user_role_without_admin(self):
        from src.api.dependencies import get_token_claims

        payload = {**VALID_PAYLOAD, "realm_roles": ["user"]}

        with (
            patch("src.api.dependencies.settings") as mock_settings,
            patch(
                "src.api.dependencies.decode_keycloak_token",
                new_callable=AsyncMock, return_value=payload,
            ),
        ):
            mock_settings.AUTH_MODE = "keycloak"
            claims = await get_token_claims(authorization="Bearer fake.token")
            assert claims.role == "user"

    @pytest.mark.asyncio
    async def test_keycloak_falls_back_to_preferred_username(self):
        from src.api.dependencies import get_token_claims

        payload = {**VALID_PAYLOAD, "name": None, "preferred_username": "jan"}

        with (
            patch("src.api.dependencies.settings") as mock_settings,
            patch(
                "src.api.dependencies.decode_keycloak_token",
                new_callable=AsyncMock, return_value=payload,
            ),
        ):
            mock_settings.AUTH_MODE = "keycloak"
            claims = await get_token_claims(authorization="Bearer fake.token")
            assert claims.display_name == "jan"

    @pytest.mark.asyncio
    async def test_local_mode_returns_local_claims(self):
        from src.api.dependencies import get_token_claims

        local_payload = {"sub": str(uuid.uuid4()), "email": "local@test.com", "role": "admin"}

        with (
            patch("src.api.dependencies.settings") as mock_settings,
            patch("src.api.dependencies.decode_access_token", return_value=local_payload),
        ):
            mock_settings.AUTH_MODE = "local"
            claims = await get_token_claims(authorization="Bearer local.jwt")
            assert claims.email == "local@test.com"
            assert claims.role == "admin"
            assert claims.display_name is None

    @pytest.mark.asyncio
    async def test_missing_authorization_raises_401(self):
        from fastapi import HTTPException

        from src.api.dependencies import get_token_claims

        with pytest.raises(HTTPException) as exc_info:
            await get_token_claims(authorization=None)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_or_create_from_sso (JIT provisioning)
# ---------------------------------------------------------------------------

class TestJitProvisioning:
    """Tests for AuthService.get_or_create_from_sso."""

    def _make_mock_db(self, existing_user=None):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        return mock_db

    @pytest.mark.asyncio
    async def test_creates_new_user_when_not_found(self):
        from src.services.auth import AuthService

        mock_db = self._make_mock_db(existing_user=None)
        service = AuthService(mock_db)

        await service.get_or_create_from_sso(
            email="new@firma.pl", role="user", display_name="New User"
        )

        mock_db.add.assert_called_once()
        added_user = mock_db.add.call_args[0][0]
        assert added_user.email == "new@firma.pl"
        assert added_user.role == "user"
        assert added_user.display_name == "New User"
        assert added_user.hashed_password == ""

    @pytest.mark.asyncio
    async def test_syncs_role_on_existing_user(self):
        from src.db.models import User
        from src.services.auth import AuthService

        existing = User(email="jan@firma.pl", role="user", display_name="Jan", hashed_password="x")
        mock_db = self._make_mock_db(existing_user=existing)
        service = AuthService(mock_db)

        user = await service.get_or_create_from_sso(
            email="jan@firma.pl", role="admin", display_name="Jan"
        )

        assert user.role == "admin"
        mock_db.flush.assert_called_once()
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_overwrite_display_name_on_existing_user(self):
        from src.db.models import User
        from src.services.auth import AuthService

        existing = User(email="jan@firma.pl", role="admin", display_name="Old", hashed_password="")
        mock_db = self._make_mock_db(existing_user=existing)
        service = AuthService(mock_db)

        user = await service.get_or_create_from_sso(
            email="jan@firma.pl", role="admin", display_name="Jan Kowalski"
        )

        assert user.display_name == "Old"
        mock_db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_flush_when_nothing_changed(self):
        from src.db.models import User
        from src.services.auth import AuthService

        existing = User(email="jan@firma.pl", role="admin", display_name="Jan", hashed_password="")
        mock_db = self._make_mock_db(existing_user=existing)
        service = AuthService(mock_db)

        user = await service.get_or_create_from_sso(
            email="jan@firma.pl", role="admin", display_name="Jan"
        )

        assert user is existing
        mock_db.flush.assert_not_called()
