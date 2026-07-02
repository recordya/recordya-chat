"""FastAPI dependencies for dependency injection."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import not_found, unauthorized
from src.core.protocols import BasePlugin
from src.core.registry import datasources
from src.core.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER
from src.core.security import decode_access_token, decode_keycloak_token
from src.db.app_database import get_db
from src.db.models import Chat, User
from src.llm.client import LlmFacade, get_llm_facade
from src.services.auth import AuthService

# Type aliases for cleaner dependency injection
DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_auth_service(db: DBSession) -> AuthService:
    """Get AuthService instance."""
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@dataclass(frozen=True)
class TokenClaims:
    """Normalized token claims from either Keycloak or local JWT."""

    sub: str
    email: str
    role: str
    display_name: str | None = None


async def get_token_claims(
    authorization: Annotated[str | None, Header()] = None,
) -> TokenClaims:
    """Extract and validate token claims (supports both auth modes)."""
    if not authorization:
        raise unauthorized("Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise unauthorized("Invalid authorization header format")

    token = parts[1]

    if settings.AUTH_MODE == "keycloak":
        payload = await decode_keycloak_token(token)
        realm_roles = payload.get("realm_roles", [])
        if ROLE_SUPER_ADMIN in realm_roles:
            role = ROLE_SUPER_ADMIN
        elif ROLE_ADMIN in realm_roles:
            role = ROLE_ADMIN
        else:
            role = ROLE_USER
        display_name = (
            payload.get("name") or payload.get("preferred_username")
        )
        return TokenClaims(
            sub=payload["sub"],
            email=payload["email"],
            role=role,
            display_name=display_name,
        )

    # Local mode — role flows through from the JWT (super_admin included)
    payload = decode_access_token(token)
    return TokenClaims(
        sub=payload["sub"],
        email=payload.get("email", ""),
        role=payload.get("role", ROLE_USER),
    )


Claims = Annotated[TokenClaims, Depends(get_token_claims)]


async def get_current_user(
    claims: Claims,
    auth_service: AuthServiceDep,
) -> User:
    """Get current authenticated user. JIT-provisions Keycloak users on first access."""
    if settings.AUTH_MODE == "keycloak":
        user = await auth_service.get_or_create_from_sso(
            email=claims.email,
            role=claims.role,
            display_name=claims.display_name,
        )
    else:
        user = await auth_service.get_user_by_id(uuid.UUID(claims.sub))

    if not user:
        raise unauthorized("User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_llm_provider() -> LlmFacade:
    """Get the shared LLM facade."""
    return get_llm_facade()


LLMProviderDep = Annotated[LlmFacade, Depends(get_llm_provider)]


# Plugin-based dependencies

def get_datasource_plugin(
    datasource: str | None = None,
) -> BasePlugin:
    """Get a data source plugin by name or first available.

    Args:
        datasource: Plugin name (optional, defaults to first available)

    Returns:
        BasePlugin instance
    """
    # If specific datasource requested, use it
    if datasource and datasources.has_instance(datasource):
        return datasources.get_instance(datasource)

    # Fall back to first available
    available = datasources.list_instances()
    if available:
        return datasources.get_instance(available[0])

    raise not_found("No data sources configured")


DataSourceDep = Annotated[BasePlugin, Depends(get_datasource_plugin)]


def get_datasource_by_path(
    datasource: Annotated[str, Path(description="Data source name")],
) -> BasePlugin:
    """Get data source plugin from path parameter."""
    return get_datasource_plugin(datasource)


DataSourceByPath = Annotated[BasePlugin, Depends(get_datasource_by_path)]


# Chat ownership dependency

async def get_user_chat(
    chat_id: Annotated[str, Path(description="Chat ID")],
    current_user: "CurrentUser",
    db: DBSession,
) -> Chat:
    """Get chat ensuring it belongs to current user.

    Args:
        chat_id: Chat UUID from path
        current_user: Authenticated user
        db: Database session

    Returns:
        Chat object

    Raises:
        HTTPException: 404 if chat not found or doesn't belong to user
    """
    result = await db.execute(
        select(Chat).where(
            Chat.id == uuid.UUID(chat_id),
            Chat.user_id == current_user.id,
        )
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise not_found("Chat not found")
    return chat


UserChat = Annotated[Chat, Depends(get_user_chat)]
