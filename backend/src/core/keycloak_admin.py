"""Keycloak Admin API client for user provisioning.

Provides helpers for creating users in Keycloak and sending
welcome / set-password emails.  Designed to be used from migration
scripts, management commands and plugins that need to provision users.

Usage::

    async with KeycloakAdmin.from_settings() as kc:
        created = await kc.create_user("jan@example.com", "Jan", "Kowalski")
        if created:
            await kc.send_set_password_email("jan@example.com")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from src.core.config import settings

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds
_TOKEN_REFRESH_EVERY = 20  # refresh token every N operations

logger = logging.getLogger(__name__)


@dataclass
class KeycloakAdmin:
    """Thin async wrapper around Keycloak Admin REST API."""

    base_url: str
    realm: str
    admin_username: str
    admin_password: str
    app_client_id: str
    redirect_uri: str = "http://localhost:8080"
    _client: httpx.AsyncClient = field(default=None, repr=False)  # type: ignore[assignment]
    _token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Strip trailing slash to avoid double-slash in URL construction
        self.base_url = self.base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        admin_username: str | None = None,
        admin_password: str | None = None,
        redirect_uri: str | None = None,
    ) -> "KeycloakAdmin":
        """Build instance from application ``settings``.

        Admin credentials default to ``settings.KEYCLOAK_ADMIN``
        and ``settings.KEYCLOAK_ADMIN_PASSWORD`` (read from env / .env).

        ``redirect_uri`` defaults to the first origin in ``CORS_ORIGINS``
        (i.e. the frontend URL).
        """
        if not redirect_uri:
            redirect_uri = settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:8080"
        return cls(
            base_url=settings.KEYCLOAK_URL,
            realm=settings.KEYCLOAK_REALM,
            admin_username=admin_username or settings.KEYCLOAK_ADMIN,
            admin_password=admin_password or settings.KEYCLOAK_ADMIN_PASSWORD,
            app_client_id=settings.KEYCLOAK_CLIENT_ID,
            redirect_uri=redirect_uri,
        )

    async def __aenter__(self) -> "KeycloakAdmin":
        self._client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_token()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        """Obtain (or refresh) an admin access token from the master realm."""
        resp = await self._client.post(
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data={
                "client_id": "admin-cli",
                "username": self.admin_username,
                "password": self.admin_password,
                "grant_type": "password",
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # User operations
    # ------------------------------------------------------------------

    async def user_exists(self, email: str) -> bool:
        """Check whether a user with *email* already exists in the realm."""
        resp = await self._client.get(
            f"{self.base_url}/admin/realms/{self.realm}/users",
            headers=self._headers(),
            params={"email": email, "exact": "true"},
        )
        resp.raise_for_status()
        return len(resp.json()) > 0

    async def create_user(
        self,
        email: str,
        first_name: str = "",
        last_name: str = "",
    ) -> bool:
        """Create a Keycloak user. Returns ``True`` if created, ``False`` if exists."""
        if await self.user_exists(email):
            return False

        resp = await self._client.post(
            f"{self.base_url}/admin/realms/{self.realm}/users",
            headers=self._headers(),
            json={
                "username": email,
                "email": email,
                "enabled": True,
                "emailVerified": True,
                "firstName": first_name,
                "lastName": last_name,
            },
        )
        if resp.status_code == 409:
            return False
        resp.raise_for_status()
        return True

    async def list_users(self, max_users: int = 1000) -> list[dict]:
        """Fetch users from the realm (up to *max_users*).

        Returns the raw Keycloak user representation (includes ``email`` and
        ``enabled`` keys, among others).
        """
        resp = await self._client.get(
            f"{self.base_url}/admin/realms/{self.realm}/users",
            headers=self._headers(),
            params={"max": max_users},
        )
        resp.raise_for_status()
        return resp.json()

    async def set_user_enabled(self, email: str, enabled: bool) -> bool:
        """Enable or disable a Keycloak user by email.

        Returns ``True`` on success, ``False`` if user not found.
        """
        return await self._patch_user(email, {"enabled": enabled})

    async def update_user_profile(
        self,
        email: str,
        first_name: str = "",
        last_name: str = "",
    ) -> bool:
        """Update first/last name on a Keycloak user by email.

        Returns ``True`` on success, ``False`` if user not found.
        """
        return await self._patch_user(
            email,
            {"firstName": first_name, "lastName": last_name},
        )

    async def _patch_user(self, email: str, payload: dict) -> bool:
        """Look up user by email and PUT *payload* fields onto the record."""
        resp = await self._client.get(
            f"{self.base_url}/admin/realms/{self.realm}/users",
            headers=self._headers(),
            params={"email": email, "exact": "true"},
        )
        resp.raise_for_status()
        users = resp.json()
        if not users:
            return False

        kc_user_id = users[0]["id"]
        resp = await self._client.put(
            f"{self.base_url}/admin/realms/{self.realm}/users/{kc_user_id}",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        return True

    async def send_set_password_email(
        self,
        email: str,
        lifespan: int = 86_400,
    ) -> bool:
        """Send an ``UPDATE_PASSWORD`` action email.

        Returns ``True`` on success, ``False`` if user not found.
        """
        resp = await self._client.get(
            f"{self.base_url}/admin/realms/{self.realm}/users",
            headers=self._headers(),
            params={"email": email, "exact": "true"},
        )
        resp.raise_for_status()
        users = resp.json()
        if not users:
            return False

        kc_user_id = users[0]["id"]
        resp = await self._client.put(
            f"{self.base_url}/admin/realms/{self.realm}/users/{kc_user_id}/execute-actions-email",
            headers=self._headers(),
            params={
                "client_id": self.app_client_id,
                "redirect_uri": self.redirect_uri,
                "lifespan": lifespan,
            },
            json=["UPDATE_PASSWORD"],
        )
        resp.raise_for_status()
        return True

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    async def _with_retry(self, coro_factory, *, label: str = "operation"):
        """Execute *coro_factory()* with retry + exponential backoff.

        *coro_factory* is a zero-arg callable that returns an awaitable
        (needed because a failed coroutine cannot be re-awaited).
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await coro_factory()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                if attempt == _MAX_RETRIES:
                    raise
                wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                    label, attempt, _MAX_RETRIES, exc, wait,
                )
                await asyncio.sleep(wait)
                # Token may have expired — refresh before retry
                await self._refresh_token()
        return None  # unreachable, but keeps type checkers happy

    # ------------------------------------------------------------------
    # Batch helpers (for migration scripts)
    # ------------------------------------------------------------------

    async def provision_users(
        self,
        users: list[dict],
        *,
        send_emails: bool = True,
        email_delay: float = 0.5,
    ) -> list[str]:
        """Create Keycloak accounts and optionally send welcome emails.

        Each entry in *users* must have ``"email"`` and optionally
        ``"first_name"`` and ``"last_name"``.

        Args:
            send_emails: Send a "set password" email to newly created users.
            email_delay: Seconds to wait between emails (avoids SMTP throttle).

        Returns list of emails for which accounts were **newly created**.
        """
        created_emails: list[str] = []

        for idx, user in enumerate(users):
            email = user["email"]

            # Refresh token periodically to avoid expiration
            if idx > 0 and idx % _TOKEN_REFRESH_EVERY == 0:
                await self._refresh_token()

            try:
                created = await self._with_retry(
                    lambda e=email, u=user: self.create_user(
                        e, u.get("first_name", ""), u.get("last_name", ""),
                    ),
                    label=f"create_user({email})",
                )
                if created:
                    created_emails.append(email)
                    logger.info("Keycloak user created: %s", email)
                else:
                    logger.info("Keycloak user already exists: %s", email)
            except Exception:
                logger.exception("Failed to create Keycloak user: %s", email)

        if send_emails and created_emails:
            await self._refresh_token()
            logger.info("Sending welcome emails to %d user(s)…", len(created_emails))
            for idx, email in enumerate(created_emails):
                # Refresh token periodically during email sending
                if idx > 0 and idx % _TOKEN_REFRESH_EVERY == 0:
                    await self._refresh_token()

                try:
                    await self._with_retry(
                        lambda e=email: self.send_set_password_email(e),
                        label=f"send_email({email})",
                    )
                    logger.info("Welcome email sent: %s", email)
                except Exception:
                    logger.exception("Failed to send welcome email: %s", email)

                # Delay between emails to avoid SMTP throttling
                if email_delay > 0 and idx < len(created_emails) - 1:
                    await asyncio.sleep(email_delay)

        return created_emails
