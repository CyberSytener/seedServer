from __future__ import annotations
import logging

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from app.core.interfaces.database import DatabaseProtocol
from app.core.metrics import AUTH_FAILURES
from app.settings import get_settings


# ---------------------------------------------------------------------------
# Auth failure rate limiter (in-process, per-IP sliding window)
# Backed by Redis when available, with in-memory fallback.
# ---------------------------------------------------------------------------

class AuthFailureRateLimiter:
    """Block auth attempts after too many failures for a given IP.

    Thread-safe.  Uses an in-memory sliding-window counter as fallback when
    Redis is not available.  Call ``attach_redis`` after startup to enable
    distributed rate limiting across instances.
    """

    def __init__(self, max_failures: int = 10, window_seconds: int = 60) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._redis: Optional[object] = None

    def attach_redis(self, redis_client: object) -> None:
        """Attach an async Redis client for distributed rate limiting."""
        self._redis = redis_client

    # --- In-memory fallback ---

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window
        ts_list = self._buckets[key]
        while ts_list and ts_list[0] < cutoff:
            ts_list.pop(0)
        if not ts_list:
            del self._buckets[key]

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(ip, now)
            self._buckets[ip].append(now)

    def is_blocked(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(ip, now)
            return len(self._buckets.get(ip, [])) >= self.max_failures

    def reset(self, ip: str) -> None:
        with self._lock:
            self._buckets.pop(ip, None)

    # --- Redis-backed (async) ---

    async def record_failure_async(self, ip: str) -> None:
        """Record a failure in Redis (if attached), else fall back to memory."""
        if self._redis is not None:
            try:
                key = f"auth:failure:{ip}"
                await self._redis.incr(key)  # type: ignore[union-attr]
                await self._redis.expire(key, self.window)  # type: ignore[union-attr]
                return
            except Exception:
                logging.debug("Redis auth-failure record failed, falling back to memory", exc_info=True)
        self.record_failure(ip)

    async def is_blocked_async(self, ip: str) -> bool:
        """Check Redis first, fall back to memory."""
        if self._redis is not None:
            try:
                key = f"auth:failure:{ip}"
                count = int(await self._redis.get(key) or 0)  # type: ignore[union-attr]
                return count >= self.max_failures
            except Exception:
                logging.debug("Redis auth-failure check failed, falling back to memory", exc_info=True)
        return self.is_blocked(ip)


# Module-level singleton — importable for tests & decoration
_auth_failure_limiter = AuthFailureRateLimiter()


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    is_admin: bool


def _test_auth_enabled() -> bool:
    settings = get_settings()
    return bool(settings.test_auth_mode and settings.environment in {"development", "test"})


def _hash_key(key: str) -> str:
    settings = get_settings()
    pepper = settings.api_key_pepper or ""
    raw = (pepper + "|" + key).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def issue_api_key() -> str:
    # prefix for easier detection / logging / future revocation formats
    return "seed_" + secrets.token_urlsafe(32)


def _extract_api_key(request: Request) -> Optional[str]:
    # Prefer Authorization header: supports both Bearer <key> and raw <key>
    auth = (request.headers.get("Authorization") or "").strip()
    if auth:
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            if token.lower() in {"", "null", "undefined", "none"}:
                return None
            return token
        if auth.lower() in {"", "null", "undefined", "none"}:
            return None
        return auth
    # Backward compatible header
    x = request.headers.get("X-API-Key")
    if x:
        return x.strip()
    return None


def _parse_scopes_csv(raw: str) -> set[str]:
    parts = [item.strip() for item in str(raw or "").replace(" ", ",").split(",")]
    return {item for item in parts if item}


def _parse_test_token(token: str) -> tuple[str, str, set[str]]:
    """
    Parse deterministic test token.

    Format:
      test_<user_id>|<role>|<scope1,scope2,...>
    """
    settings = get_settings()
    payload = token[5:]
    user_id = "sim-user"
    role = str(settings.test_auth_default_role or "developer").strip().lower() or "developer"
    scopes: set[str] = set()

    if payload:
        parts = payload.split("|")
        if len(parts) >= 1 and str(parts[0]).strip():
            user_id = str(parts[0]).strip()
        if len(parts) >= 2 and str(parts[1]).strip():
            role = str(parts[1]).strip().lower()
        if len(parts) >= 3:
            scopes = _parse_scopes_csv(parts[2])

    if not user_id:
        user_id = "sim-user"
    return user_id, role, scopes


def _ensure_test_user_exists(
    db: DatabaseProtocol,
    *,
    user_id: str,
    role: str,
    scopes: set[str],
    is_admin: bool,
) -> None:
    if not hasattr(db, "fetchone") or not hasattr(db, "execute"):
        return
    existing = db.fetchone("SELECT id FROM users WHERE id = ?", (user_id,))
    if existing:
        return

    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "test_auth_mode": True,
        "role": role,
        "scopes": sorted(scopes),
    }
    db.execute(
        """
        INSERT INTO users(id, created_at, is_admin, is_banned, meta_json)
        VALUES(?, ?, ?, 0, ?)
        """,
        (user_id, now, 1 if is_admin else 0, json.dumps(meta, ensure_ascii=False)),
    )


def authenticate(request: Request, db: DatabaseProtocol) -> AuthContext:
    import logging
    settings = get_settings()
    header_names = []
    try:
        header_names = sorted(str(name).lower() for name in request.headers.keys())
    except Exception:
        header_names = []
    logging.debug(
        "[AUTH DEBUG] admin_key_set=%s header_names=%s",
        bool(settings.admin_key),
        header_names,
    )
    client_ip = request.client.host if request.client else "unknown"

    # --- Auth failure rate-limit check (per-IP) ---
    if _auth_failure_limiter.is_blocked(client_ip):
        AUTH_FAILURES.labels(reason="rate_limited").inc()
        logging.warning(
            "Authentication rate-limited",
            extra={"client_ip": client_ip, "reason": "too_many_failures"},
        )
        raise HTTPException(status_code=429, detail="too many auth failures – try again later")

    # Admin override uses resolved settings only.
    admin_key = request.headers.get("X-Admin-Key")
    expected_admin = settings.admin_key
    if admin_key and expected_admin and hmac.compare_digest(admin_key, expected_admin):
        logging.info(
            "Admin authentication successful",
            extra={"client_ip": client_ip, "auth_method": "admin_key"}
        )
        return AuthContext(user_id="admin", is_admin=True)

    api_key = _extract_api_key(request)
    if api_key and _test_auth_enabled() and api_key.startswith("test_"):
        logging.warning(
            "Test auth token accepted — only valid in development/test",
            extra={"client_ip": client_ip},
        )
        user_id, role, scopes = _parse_test_token(api_key)
        is_admin = role == "admin" or "*" in scopes
        try:
            _ensure_test_user_exists(
                db,
                user_id=user_id,
                role=role,
                scopes=scopes,
                is_admin=is_admin,
            )
        except Exception:
            # Best effort only; test tokens may be used with non-persistent DB stubs.
            pass
        return AuthContext(user_id=user_id, is_admin=is_admin)

    if not api_key:
        # Legacy mode (NOT recommended) - identify user directly
        if settings.enable_legacy_x_user_id:
            if settings.is_production or settings.public_mode:
                logging.error("Legacy X-User-ID auth must not be enabled in production")
                raise HTTPException(status_code=403, detail="legacy auth disabled")
            logging.warning(
                "Legacy X-User-ID auth is active — disable for production",
                extra={"client_ip": client_ip},
            )
            legacy_user = request.headers.get("X-User-ID")
            if legacy_user:
                user_id = legacy_user.strip()
                
                # Validate user_id format (alphanumeric, underscore, hyphen, 1-100 chars)
                import re
                if not re.match(r'^[a-zA-Z0-9_-]{1,100}$', user_id):
                    AUTH_FAILURES.labels(reason="invalid_user_id_format").inc()
                    _auth_failure_limiter.record_failure(client_ip)
                    logging.warning(
                        "Authentication failed: invalid user_id format in legacy mode",
                        extra={
                            "client_ip": client_ip,
                            "path": str(request.url.path),
                            "reason": "invalid_user_id_format"
                        }
                    )
                    raise HTTPException(status_code=400, detail="invalid user_id format")
                
                # User MUST already exist — no auto-creation from untrusted headers
                existing = db.fetchone("SELECT id, is_banned FROM users WHERE id = ?", (user_id,))
                if not existing:
                    AUTH_FAILURES.labels(reason="legacy_user_not_found").inc()
                    _auth_failure_limiter.record_failure(client_ip)
                    raise HTTPException(status_code=401, detail="unknown user")
                try:
                    if int(existing["is_banned"] or 0) == 1:
                        raise HTTPException(status_code=403, detail="banned")
                except (TypeError, ValueError, KeyError):
                    pass
                return AuthContext(user_id=user_id, is_admin=False)
        
        # Log failed authentication attempt
        AUTH_FAILURES.labels(reason="missing_api_key").inc()
        _auth_failure_limiter.record_failure(client_ip)
        logging.warning(
            "Authentication failed: missing API key",
            extra={
                "client_ip": client_ip,
                "path": str(request.url.path),
                "reason": "missing_api_key"
            }
        )
        raise HTTPException(status_code=401, detail="missing api key")

    key_hash = _hash_key(api_key)
    row = db.fetchone(
        "SELECT id,is_admin,is_banned FROM users WHERE api_key_hash = ?",
        (key_hash,),
    )
    if not row:
        # JWT fallback compatibility: allow Authorization: Bearer <jwt>
        try:
            from app.core.security.jwt import JWTHandler

            payload = JWTHandler().validate_token(api_key)
            jwt_user_id = str((payload or {}).get("user_id") or "").strip()
            if jwt_user_id:
                jwt_row = db.fetchone(
                    "SELECT id,is_admin,is_banned FROM users WHERE id = ?",
                    (jwt_user_id,),
                )
                if jwt_row:
                    try:
                        is_banned = int(jwt_row["is_banned"] or 0)
                    except (TypeError, ValueError, KeyError):
                        is_banned = 0
                    if is_banned == 1:
                        AUTH_FAILURES.labels(reason="banned").inc()
                        _auth_failure_limiter.record_failure(client_ip)
                        raise HTTPException(status_code=403, detail="banned")
                    logging.info(
                        "Authentication successful via JWT",
                        extra={
                            "user_id": jwt_row["id"],
                            "is_admin": bool(jwt_row["is_admin"]),
                            "auth_method": "jwt",
                        },
                    )
                    return AuthContext(user_id=jwt_row["id"], is_admin=bool(jwt_row["is_admin"]))
        except HTTPException:
            raise
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        # Log invalid API key attempt (mask key for security)
        AUTH_FAILURES.labels(reason="invalid_api_key").inc()
        _auth_failure_limiter.record_failure(client_ip)
        logging.warning(
            "Authentication failed: invalid API key",
            extra={
                "client_ip": client_ip,
                "path": str(request.url.path),
                "key_last4": api_key[-4:] if len(api_key) >= 4 else "***",
                "reason": "invalid_api_key"
            }
        )
        raise HTTPException(status_code=401, detail="invalid api key")
    
    # Safely check banned status (handle NULL)
    try:
        is_banned = int(row["is_banned"] or 0)
    except (TypeError, ValueError, KeyError):
        is_banned = 0
    
    if is_banned == 1:
        # Log banned user attempt
        AUTH_FAILURES.labels(reason="banned").inc()
        _auth_failure_limiter.record_failure(client_ip)
        logging.warning(
            "Authentication failed: banned user",
            extra={
                "client_ip": client_ip,
                "user_id": row["id"],
                "path": str(request.url.path),
                "reason": "banned",
                "auth_method": "api_key"
            }
        )
        raise HTTPException(status_code=403, detail="banned")

    # Log successful authentication
    logging.info(
        "Authentication successful",
        extra={
            "user_id": row["id"],
            "is_admin": bool(row["is_admin"]),
            "auth_method": "api_key"
        }
    )

    return AuthContext(user_id=row["id"], is_admin=bool(row["is_admin"]))


def require_admin_key(request: Request) -> AuthContext:
    """
    Strict admin authentication.

    Admin operations must use X-Admin-Key and do not accept Bearer/API-key auth.
    """
    settings = get_settings()
    expected_admin = str(settings.admin_key or "").strip()
    if not expected_admin:
        AUTH_FAILURES.labels(reason="admin_disabled").inc()
        raise HTTPException(status_code=403, detail="admin provisioning disabled")

    provided = str(request.headers.get("X-Admin-Key") or "").strip()
    if not provided or not hmac.compare_digest(provided, expected_admin):
        AUTH_FAILURES.labels(reason="invalid_admin_key").inc()
        raise HTTPException(status_code=401, detail="admin key required")

    return AuthContext(user_id="admin", is_admin=True)


def issue_key_for_user(db: DatabaseProtocol, user_id: str) -> str:
    """Issue a new API key for an existing user."""
    import logging
    
    # Check if user exists
    existing = db.fetchone("SELECT id FROM users WHERE id = ?", (user_id,))
    if not existing:
        logging.error(f"Cannot issue key: user {user_id} does not exist")
        raise ValueError(f"User {user_id} not found")
    
    key = issue_api_key()
    key_hash = _hash_key(key)
    last4 = key[-4:]
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE users SET api_key_hash=?, api_key_last4=?, api_key_created_at=? WHERE id=?",
        (key_hash, last4, now, user_id),
    )
    
    logging.info(
        "API key issued",
        extra={
            "user_id": user_id,
            "key_last4": last4
        }
    )
    
    return key


def require_auth_context(request: Request, db: DatabaseProtocol) -> AuthContext:
    """
    Require authentication and return auth context.
    Raises HTTPException if authentication fails.
    """
    return authenticate(request, db)


def verify_user_context(authorization: Optional[str]) -> Optional[dict]:
    """
    Validate an Authorization header (Bearer <JWT> or raw token) and
    return a user context dict with at least `user_id` when valid.

    Returns:
        dict with claims (includes 'user_id') or `None` if invalid / missing.
    """
    if not authorization:
        return None

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    try:
        # Reuse the core JWT handler (shared by API and WebSocket)
        from app.core.security.jwt import JWTHandler
    except Exception:
        # PyJWT not installed or handler unavailable — cannot validate token
        return None

    try:
        handler = JWTHandler()
    except Exception:
        return None
    payload = handler.validate_token(token)
    if not payload or "user_id" not in payload:
        return None

    # Return a shallow dict with the user_id and original claims for callers
    return {"user_id": payload["user_id"], **payload}
