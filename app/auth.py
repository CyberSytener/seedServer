"""Compatibility re-exports for legacy imports.

Canonical auth implementation lives in `app.core.auth`.
"""

from app.core.auth import (  # noqa: F401
    AuthContext,
    authenticate,
    issue_api_key,
    issue_key_for_user,
    require_admin_key,
    require_auth_context,
    verify_user_context,
    _hash_key,
)

__all__ = [
    "AuthContext",
    "authenticate",
    "issue_api_key",
    "issue_key_for_user",
    "require_admin_key",
    "require_auth_context",
    "verify_user_context",
    "_hash_key",
]
