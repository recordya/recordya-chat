"""Authentication endpoints."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from src.api.dependencies import AuthServiceDep, CurrentUser, DBSession
from src.core.config import settings
from src.core.exceptions import bad_request, forbidden, not_found
from src.core.i18n import translate
from src.core.keycloak_admin import KeycloakAdmin
from src.core.registry import access_guards, user_lifecycle_hooks
from src.core.roles import has_admin_privileges
from src.core.security import hash_password
from src.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


class AuthConfigResponse(BaseModel):
    """Public auth configuration for frontend."""

    auth_mode: str
    locale: str = "en"
    keycloak_url: str | None = None
    keycloak_realm: str | None = None
    keycloak_client_id: str | None = None


@router.get("/config", response_model=AuthConfigResponse)
async def get_auth_config() -> AuthConfigResponse:
    """Return auth mode, locale and Keycloak URLs (public, no auth required)."""
    if settings.AUTH_MODE == "keycloak":
        return AuthConfigResponse(
            auth_mode="keycloak",
            locale=settings.DEFAULT_LOCALE,
            keycloak_url=settings.keycloak_frontend_url,
            keycloak_realm=settings.KEYCLOAK_REALM,
            keycloak_client_id=settings.KEYCLOAK_CLIENT_ID,
        )
    return AuthConfigResponse(auth_mode="local", locale=settings.DEFAULT_LOCALE)


class RegisterRequest(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response after successful login."""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User information response."""
    user_id: str
    email: str
    role: str
    display_name: str | None = None
    enabled: bool = True

    class Config:
        from_attributes = True


class CreateUserRequest(BaseModel):
    """Admin request to create a new user.

    ``plugin_data`` is a namespaced bag passed through to registered
    :class:`UserLifecycleHook` implementations so plugins can attach their own
    fields to a newly created user (e.g. ``{"my_plugin": {"access_days": 30}}``).
    """
    email: EmailStr
    display_name: str | None = None
    plugin_data: dict[str, Any] | None = None


@router.post("/register", response_model=UserResponse)
async def register(
    request: RegisterRequest,
    auth_service: AuthServiceDep,
) -> UserResponse:
    """Register a new user account.

    Args:
        request: Registration data
        auth_service: Auth service

    Returns:
        Created user information
    """
    try:
        user = await auth_service.register(request.email, request.password)
        return UserResponse(
            user_id=str(user.id),
            email=user.email,
            role=user.role,
            display_name=user.display_name,
        )
    except Exception as e:
        raise bad_request(str(e))


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    auth_service: AuthServiceDep,
) -> TokenResponse:
    """Login and get access token.

    Args:
        request: Login credentials
        auth_service: Auth service

    Returns:
        JWT access token
    """
    try:
        user, token = await auth_service.login(request.email, request.password)
        return TokenResponse(access_token=token)
    except Exception as e:
        raise bad_request(str(e))


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
) -> UserResponse:
    """Get current user information.

    Args:
        current_user: Authenticated user from token

    Returns:
        User information
    """
    return UserResponse(
        user_id=str(current_user.id),
        email=current_user.email,
        role=current_user.role,
        display_name=current_user.display_name,
    )


class UpdateProfileRequest(BaseModel):
    """Profile update payload."""
    display_name: str | None = Field(default=None, max_length=255)


@router.patch("/me", response_model=UserResponse)
async def update_current_user(
    request: UpdateProfileRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    """Update current user profile (display name only).

    In keycloak mode the change is propagated to Keycloak (firstName/lastName)
    so it survives the next SSO login (which syncs display_name from KC claims).
    """
    if request.display_name is not None:
        new_name = request.display_name.strip() or None
        current_user.display_name = new_name

        if settings.AUTH_MODE == "keycloak":
            first_name, _, last_name = (new_name or "").partition(" ")
            try:
                async with KeycloakAdmin.from_settings() as kc:
                    await kc.update_user_profile(
                        current_user.email, first_name, last_name,
                    )
            except Exception as exc:
                logger.exception(
                    "Failed to update Keycloak profile for %s: %s",
                    current_user.email, exc,
                )
                raise bad_request(
                    translate("auth.error.profile_save_failed")
                ) from exc

    await db.flush()
    await db.refresh(current_user)
    return UserResponse(
        user_id=str(current_user.id),
        email=current_user.email,
        role=current_user.role,
        display_name=current_user.display_name,
    )


async def _run_lifecycle_hooks(event: str, *args: Any, **kwargs: Any) -> None:
    """Dispatch a user-lifecycle event to all registered hooks (best-effort).

    Failures in individual hooks are logged but never raised, so a plugin
    contributor cannot roll back the core operation that already succeeded.
    """
    for hook_id, hook in user_lifecycle_hooks.get_all_instances().items():
        handler = getattr(hook, event, None)
        if handler is None:
            continue
        try:
            await handler(*args, **kwargs)
        except Exception as exc:
            logger.exception("User lifecycle hook '%s' failed on %s: %s", hook_id, event, exc)


async def _fetch_keycloak_user_map() -> dict[str, dict]:
    """Return {lower_email: {"enabled": bool, "display_name": str | None}} from Keycloak.

    Returns an empty dict on failure so the listing endpoint can degrade gracefully.
    """
    try:
        async with KeycloakAdmin.from_settings() as kc:
            kc_users = await kc.list_users()
    except Exception as exc:
        logger.warning("Could not fetch Keycloak users: %s", exc)
        return {}
    result: dict[str, dict] = {}
    for kc_user in kc_users:
        email = kc_user.get("email")
        if not email:
            continue
        first = (kc_user.get("firstName") or "").strip()
        last = (kc_user.get("lastName") or "").strip()
        display = f"{first} {last}".strip() or None
        result[email.lower()] = {
            "enabled": bool(kc_user.get("enabled", True)),
            "display_name": display,
        }
    return result


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: CurrentUser,
    db: DBSession,
) -> list[UserResponse]:
    """List all users (admin only)."""
    if not has_admin_privileges(current_user.role):
        raise forbidden("Admin role required")

    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()

    kc_map: dict[str, dict] = {}
    if settings.AUTH_MODE == "keycloak":
        kc_map = await _fetch_keycloak_user_map()

    response: list[UserResponse] = []
    for user in users:
        kc_info = kc_map.get(user.email.lower())
        enabled = kc_info["enabled"] if kc_info else True
        display_name = (
            kc_info["display_name"] if kc_info and kc_info["display_name"]
            else user.display_name
        )
        response.append(
            UserResponse(
                user_id=str(user.id),
                email=user.email,
                role=user.role,
                display_name=display_name,
                enabled=enabled,
            )
        )
    return response


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    request: CreateUserRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    """Create a new user (admin only).

    Provisions the account in Keycloak and sends a set-password email
    to the user. Available only in keycloak mode.
    """
    if not has_admin_privileges(current_user.role):
        raise forbidden("Admin role required")
    if settings.AUTH_MODE != "keycloak":
        raise bad_request(translate("auth.error.create_user_local_disabled"))

    email = str(request.email).strip()
    display_name = (request.display_name or "").strip() or None

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise bad_request(translate("auth.error.user_email_exists"))

    user = User(
        email=email,
        hashed_password=hash_password(str(uuid.uuid4())),
        display_name=display_name,
        role="user",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    first_name, _, last_name = (display_name or "").partition(" ")
    try:
        async with KeycloakAdmin.from_settings() as kc:
            await kc.create_user(email, first_name, last_name)
            await kc.send_set_password_email(email)
    except Exception as exc:
        logger.exception("Keycloak provisioning failed for %s: %s", email, exc)
        raise bad_request(
            translate("auth.error.user_created_local_only")
        ) from exc

    await _run_lifecycle_hooks("on_user_created", db, user, request.plugin_data or {})

    return UserResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        enabled=True,
    )


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    """Deactivate a user by disabling them in Keycloak (admin only)."""
    if not has_admin_privileges(current_user.role):
        raise forbidden("Admin role required")
    if user_id == current_user.id:
        raise bad_request(translate("auth.error.cannot_deactivate_self"))

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise not_found(translate("auth.error.user_not_found"))

    if settings.AUTH_MODE == "keycloak":
        try:
            async with KeycloakAdmin.from_settings() as kc:
                found = await kc.set_user_enabled(target.email, False)
        except Exception as exc:
            logger.exception("Failed to disable Keycloak user %s: %s", target.email, exc)
            raise bad_request(translate("auth.error.deactivate_failed")) from exc
        if not found:
            raise bad_request(translate("auth.error.deactivate_not_in_sso"))

    await _run_lifecycle_hooks("on_user_deactivated", db, target)

    return UserResponse(
        user_id=str(target.id),
        email=target.email,
        role=target.role,
        display_name=target.display_name,
        enabled=False,
    )


@router.post("/users/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    """Re-activate a user by enabling them in Keycloak (admin only)."""
    if not has_admin_privileges(current_user.role):
        raise forbidden("Admin role required")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise not_found(translate("auth.error.user_not_found"))

    if settings.AUTH_MODE == "keycloak":
        try:
            async with KeycloakAdmin.from_settings() as kc:
                found = await kc.set_user_enabled(target.email, True)
        except Exception as exc:
            logger.exception("Failed to enable Keycloak user %s: %s", target.email, exc)
            raise bad_request(translate("auth.error.activate_failed")) from exc
        if not found:
            raise bad_request(translate("auth.error.activate_not_in_sso"))

    await _run_lifecycle_hooks("on_user_activated", db, target)

    return UserResponse(
        user_id=str(target.id),
        email=target.email,
        role=target.role,
        display_name=target.display_name,
        enabled=True,
    )


class UsageResponse(BaseModel):
    """Usage statistics response."""
    remaining: int
    limit: int
    is_admin: bool
    is_super_admin: bool = False
    chat_restricted: bool = False


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    current_user: CurrentUser,
    auth_service: AuthServiceDep,
    db: DBSession,
) -> UsageResponse:
    """Get remaining queries for today.

    Args:
        current_user: Authenticated user
        auth_service: Auth service
        db: Database session

    Returns:
        Usage statistics
    """
    user_id = current_user.id
    usage = await auth_service.get_remaining_queries(user_id)

    # Collect extra fields from registered access guards (plugin-provided)
    extra: dict = {}
    for guard in access_guards.get_all_instances().values():
        extra.update(await guard.get_access_info(db, user_id))

    return UsageResponse(**usage, **extra)
