"""Security utilities - JWT tokens, password hashing, and Keycloak JWKS validation."""

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import httpx
from jose import JWTError, jwt

from .config import settings
from .exceptions import AuthenticationError

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to check against

    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False


def create_access_token(
    user_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token.

    Args:
        user_id: User identifier to encode in token
        role: User role to encode in token
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)

    expire = datetime.now(UTC) + expires_delta

    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "iat": datetime.now(UTC),
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: JWT token string to decode

    Returns:
        Decoded token payload

    Raises:
        AuthenticationError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise AuthenticationError("Invalid token: missing subject")

        return payload

    except JWTError as e:
        raise AuthenticationError(f"Invalid token: {e}") from e


# === Keycloak JWKS validation ===

_jwks_cache: dict = {}
_jwks_cache_expiry: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour


async def _fetch_jwks() -> dict:
    """Fetch JWKS from Keycloak, with caching."""
    global _jwks_cache, _jwks_cache_expiry

    if _jwks_cache and time.monotonic() < _jwks_cache_expiry:
        return _jwks_cache

    url = (
        f"{settings.KEYCLOAK_URL}/realms/"
        f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_expiry = time.monotonic() + _JWKS_CACHE_TTL
        return _jwks_cache


def _find_key(jwks: dict, kid: str) -> dict | None:
    """Find a JWK by kid."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


async def decode_keycloak_token(token: str) -> dict[str, Any]:
    """Validate and decode a Keycloak access token (RS256 via JWKS).

    Validates azp (authorized party) or aud to ensure the token
    was issued for this application's client_id.
    """
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    if not kid:
        raise AuthenticationError("Token missing kid header")

    jwks = await _fetch_jwks()
    key = _find_key(jwks, kid)

    # Key rotation: if kid not found, force refresh once
    if not key:
        global _jwks_cache_expiry
        _jwks_cache_expiry = 0
        jwks = await _fetch_jwks()
        key = _find_key(jwks, kid)

    if not key:
        raise AuthenticationError(f"Unknown signing key: {kid}")

    payload = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )

    # Validate azp or aud contains our client_id
    client_id = settings.KEYCLOAK_CLIENT_ID
    azp = payload.get("azp", "")
    aud = payload.get("aud", "")
    aud_list = aud if isinstance(aud, list) else [aud]

    if azp != client_id and client_id not in aud_list:
        raise AuthenticationError(
            f"Token not issued for client '{client_id}'"
        )

    if not payload.get("sub"):
        raise AuthenticationError("Token missing sub claim")

    return payload
