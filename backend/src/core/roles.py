"""Role constants and privilege helpers.

Single source of truth for user role semantics. ``super_admin`` is a superset
of ``admin`` for all privileged operations; only ``super_admin`` may see the
diagnostic/reasoning layer (reasoning panel, ``reasoning_steps`` and the full
tool payloads in the SSE stream).
"""

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"


def has_admin_privileges(role: str | None) -> bool:
    """Return True for roles with admin powers (``admin`` and ``super_admin``)."""
    return role in (ROLE_ADMIN, ROLE_SUPER_ADMIN)


def is_super_admin(role: str | None) -> bool:
    """Return True only for ``super_admin`` (diagnostic/reasoning access)."""
    return role == ROLE_SUPER_ADMIN
