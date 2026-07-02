"""Authentication service - user registration, login, and session management."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AuthenticationError
from src.core.roles import has_admin_privileges, is_super_admin
from src.core.security import create_access_token, hash_password, verify_password
from src.db.models import DailyUsage, User


class AuthService:
    """Service for handling user authentication and authorization."""

    DAILY_QUERY_LIMIT = 200

    def __init__(self, db: AsyncSession):
        """Initialize auth service.

        Args:
            db: Database session
        """
        self.db = db

    async def register(self, email: str, password: str) -> User:
        """Register a new user.

        Args:
            email: User email address
            password: Plain text password

        Returns:
            Created user object

        Raises:
            AuthenticationError: If email is already registered
        """
        # Check if email already exists
        existing = await self.db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise AuthenticationError("Email already registered")

        # Create new user
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="user",
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        return user

    async def login(self, email: str, password: str) -> tuple[User, str]:
        """Authenticate user and create access token.

        Args:
            email: User email address
            password: Plain text password

        Returns:
            Tuple of (user, access_token)

        Raises:
            AuthenticationError: If credentials are invalid
        """
        # Find user by email
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            raise AuthenticationError("Invalid email or password")

        # Verify password
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password")

        # Create access token
        token = create_access_token(str(user.id), user.role)

        return user, token

    async def get_user_by_id(self, user_id: str | uuid.UUID) -> User | None:
        """Get user by ID.

        Args:
            user_id: User UUID

        Returns:
            User object or None if not found
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create_from_sso(
        self, email: str, role: str, display_name: str | None = None,
    ) -> User:
        """JIT-provision or update a user from SSO claims.

        Creates a new user if not found, seeding display_name from Keycloak.
        For existing users, syncs role from Keycloak; display_name is owned
        by the app (editable via PATCH /auth/me) and is not overwritten on
        subsequent logins.
        """
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                email=email,
                hashed_password="",
                role=role,
                display_name=display_name,
            )
            self.db.add(user)
            await self.db.flush()
            await self.db.refresh(user)
            return user

        if user.role != role:
            user.role = role
            await self.db.flush()

        return user

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email.

        Args:
            email: User email address

        Returns:
            User object or None if not found
        """
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def check_and_increment_usage(self, user_id: uuid.UUID) -> dict:
        """Check and increment daily usage for rate limiting.

        Args:
            user_id: User UUID

        Returns:
            Dictionary with usage info:
            {
                "allowed": bool,
                "count": int,
                "limit": int,
                "is_admin": bool
            }

        Raises:
            RateLimitError: If user has exceeded daily limit
        """
        # Get user to check role
        user = await self.get_user_by_id(user_id)
        if not user:
            raise AuthenticationError("User not found")

        # Admins (and super_admins) have no limit
        if has_admin_privileges(user.role):
            return {
                "allowed": True,
                "count": 0,
                "limit": -1,
                "is_admin": True,
            }

        today = date.today()

        # Get or create daily usage record
        result = await self.db.execute(
            select(DailyUsage).where(
                DailyUsage.user_id == user_id,
                DailyUsage.usage_date == today,
            )
        )
        usage = result.scalar_one_or_none()

        if usage is None:
            # Create new record
            usage = DailyUsage(
                user_id=user_id,
                usage_date=today,
                query_count=1,
            )
            self.db.add(usage)
        else:
            # Increment existing record
            usage.query_count += 1

        await self.db.flush()

        # Check if limit exceeded
        if usage.query_count > self.DAILY_QUERY_LIMIT:
            return {
                "allowed": False,
                "count": usage.query_count,
                "limit": self.DAILY_QUERY_LIMIT,
                "is_admin": False,
            }

        return {
            "allowed": True,
            "count": usage.query_count,
            "limit": self.DAILY_QUERY_LIMIT,
            "is_admin": False,
        }

    async def get_remaining_queries(self, user_id: uuid.UUID) -> dict:
        """Get remaining queries for today.

        Args:
            user_id: User UUID

        Returns:
            Dictionary with remaining queries info
        """
        # Get user to check role
        user = await self.get_user_by_id(user_id)
        if not user:
            raise AuthenticationError("User not found")

        # Admins (and super_admins) have no limit
        if has_admin_privileges(user.role):
            return {
                "remaining": -1,
                "limit": -1,
                "is_admin": True,
                "is_super_admin": is_super_admin(user.role),
            }

        today = date.today()

        # Get today's usage
        result = await self.db.execute(
            select(DailyUsage).where(
                DailyUsage.user_id == user_id,
                DailyUsage.usage_date == today,
            )
        )
        usage = result.scalar_one_or_none()

        current_count = usage.query_count if usage else 0

        return {
            "remaining": max(0, self.DAILY_QUERY_LIMIT - current_count),
            "limit": self.DAILY_QUERY_LIMIT,
            "is_admin": False,
            "is_super_admin": False,
        }
