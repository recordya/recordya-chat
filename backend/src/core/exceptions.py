"""Custom exceptions for the application."""

from fastapi import HTTPException, status


class AppException(Exception):
    """Base application exception."""

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(AppException):
    """Authentication failed."""

    pass


class AuthorizationError(AppException):
    """User not authorized for this action."""

    pass


class DatabaseError(AppException):
    """Database operation failed."""

    pass


class ConnectorError(AppException):
    """SQL Connector error."""

    pass


class LLMError(AppException):
    """LLM Provider error."""

    pass


class ValidationError(AppException):
    """Validation error."""

    pass


class RateLimitError(AppException):
    """Rate limit exceeded."""

    pass


# HTTP Exception helpers
def unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    """Create 401 Unauthorized exception."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(detail: str = "Not enough permissions") -> HTTPException:
    """Create 403 Forbidden exception."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def not_found(detail: str = "Resource not found") -> HTTPException:
    """Create 404 Not Found exception."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
    )


def bad_request(detail: str = "Bad request") -> HTTPException:
    """Create 400 Bad Request exception."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
    )


def rate_limited(detail: str = "Rate limit exceeded") -> HTTPException:
    """Create 429 Too Many Requests exception."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
    )
