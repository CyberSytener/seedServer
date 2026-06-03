from __future__ import annotations
import logging

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import HTTPException, Request

from app.core.auth import AuthContext as LegacyAuthContext
from app.core.auth import authenticate, verify_user_context
from app.settings import get_settings

logger = logging.getLogger(__name__)


ROLE_SCOPES: Dict[str, Set[str]] = {
    "user": {
        "runs:read",
        "runs:write",
        "modules:read",
        "flows:read",
        "catalog:read",
        # Phase 7 — agent session scopes (read-only posture for user role)
        "agent:sessions",
        "agent:tools:read",
        "agent:context:read",
    },
    "developer": {
        "runs:read",
        "runs:write",
        "modules:read",
        "modules:write",
        "flows:*",
        "catalog:read",
        "blueprints:write",
        "artifacts:read",
        "providers:read",
        "providers:use:real",
        # Phase 7 — agent session scopes (developer can execute tools + change persona)
        "agent:sessions",
        "agent:tools:read",
        "agent:tools:execute",
        "agent:context:read",
        "agent:persona:write",
    },
    "operator": {
        "runs:read",
        "runs:write",
        "modules:read",
        "flows:*",
        "catalog:read",
        "blueprints:write",
        "dlq:*",
        "artifacts:read",
        "providers:read",
        # Phase 7 — agent session scopes (operator same as developer)
        "agent:sessions",
        "agent:tools:read",
        "agent:tools:execute",
        "agent:context:read",
        "agent:persona:write",
    },
    "admin": {"*"},
}


@dataclass(frozen=True)
class UnifiedAuthContext:
    user_id: str
    role: str
    scopes: Set[str] = field(default_factory=set)
    is_admin: bool = False
    auth_type: str = "unknown"
    claims: Dict[str, Any] = field(default_factory=dict)

    def has_scope(self, required_scope: str) -> bool:
        if not required_scope:
            return True
        if "*" in self.scopes:
            return True
        for owned_scope in self.scopes:
            if owned_scope == required_scope:
                return True
            if owned_scope.endswith(":*") and required_scope.startswith(owned_scope[:-1]):
                return True
        return False


def _parse_scopes(raw: Any) -> Set[str]:
    if isinstance(raw, str):
        parts = [item.strip() for item in raw.replace(" ", ",").split(",")]
        return {item for item in parts if item}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _merge_role_scopes(role: str, claims_scopes: Set[str]) -> Set[str]:
    baseline = set(ROLE_SCOPES.get(role, ROLE_SCOPES["user"]))
    if claims_scopes:
        return baseline.union(claims_scopes)
    return baseline


def _extract_bearer_token(request: Request) -> str:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if not auth_header:
        return ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return auth_header


def _build_test_context(token: str) -> UnifiedAuthContext:
    settings = get_settings()
    # Format: test_<user_id>|<role>|<scope1,scope2>
    payload = token[5:]
    user_id = "sim-user"
    role = str(settings.test_auth_default_role or "developer").strip().lower() or "developer"
    token_scopes: Set[str] = set()
    if payload:
        parts = payload.split("|")
        if len(parts) >= 1 and str(parts[0]).strip():
            user_id = str(parts[0]).strip()
        if len(parts) >= 2 and str(parts[1]).strip():
            role = str(parts[1]).strip().lower()
        if len(parts) >= 3:
            token_scopes = _parse_scopes(parts[2])

    default_scopes = _parse_scopes(settings.test_auth_default_scopes)
    scopes = _merge_role_scopes(role, default_scopes.union(token_scopes))
    return UnifiedAuthContext(
        user_id=user_id,
        role=role,
        scopes=scopes,
        is_admin=role == "admin" or "*" in scopes,
        auth_type="test_token",
        claims={"test_mode": True},
    )


def _test_auth_enabled() -> bool:
    settings = get_settings()
    return bool(settings.test_auth_mode and settings.environment in {"development", "test"})


def _build_from_legacy(
    request: Request,
    db: Any,
    legacy: LegacyAuthContext,
) -> UnifiedAuthContext:
    role = "admin" if legacy.is_admin else "user"
    claims: Dict[str, Any] = {}
    auth_type = "api_key"

    bearer = _extract_bearer_token(request)
    jwt_claims = verify_user_context(f"Bearer {bearer}") if bearer else None
    if isinstance(jwt_claims, dict) and jwt_claims:
        auth_type = "jwt"
        claims = dict(jwt_claims)
        role = str(jwt_claims.get("role") or role).strip().lower() or role
        claim_scopes = _parse_scopes(jwt_claims.get("scopes") or jwt_claims.get("scope"))
        scopes = _merge_role_scopes(role, claim_scopes)
        if legacy.is_admin:
            scopes.add("*")
            role = "admin"
        return UnifiedAuthContext(
            user_id=legacy.user_id,
            role=role,
            scopes=scopes,
            is_admin=legacy.is_admin or role == "admin" or "*" in scopes,
            auth_type=auth_type,
            claims=claims,
        )

    claim_scopes: Set[str] = set()
    try:
        if hasattr(db, "fetchone"):
            row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (legacy.user_id,))
            raw_meta = row["meta_json"] if isinstance(row, dict) and "meta_json" in row else None
            if isinstance(raw_meta, str) and raw_meta.strip():
                parsed_meta = json.loads(raw_meta)
                if isinstance(parsed_meta, dict):
                    meta_role = str(parsed_meta.get("role") or "").strip().lower()
                    if meta_role:
                        role = meta_role
                    elif _test_auth_enabled() and bool(parsed_meta.get("dev_user")):
                        # Backward-compatible upgrade path for existing seeded dev users.
                        role = "developer"
                    claim_scopes = _parse_scopes(parsed_meta.get("scopes"))
                    claims = parsed_meta
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    scopes = _merge_role_scopes(role, claim_scopes)
    return UnifiedAuthContext(
        user_id=legacy.user_id,
        role=role,
        scopes=scopes,
        is_admin=legacy.is_admin or role == "admin" or "*" in scopes,
        auth_type=auth_type,
        claims=claims,
    )


def resolve_auth_context(
    request: Request,
    db: Any,
    *,
    required: bool = True,
) -> Optional[UnifiedAuthContext]:
    existing = getattr(request.state, "auth", None)
    if isinstance(existing, UnifiedAuthContext):
        return existing

    settings = get_settings()
    token = _extract_bearer_token(request)
    if _test_auth_enabled() and token.startswith("test_"):
        ctx = _build_test_context(token)
        request.state.auth = ctx
        return ctx

    try:
        legacy = authenticate(request, db)
    except HTTPException:
        if required:
            raise
        return None
    except Exception:
        if required:
            raise HTTPException(status_code=401, detail="authentication_failed")
        return None

    ctx = _build_from_legacy(request, db, legacy)
    request.state.auth = ctx
    return ctx


def require_scope(
    request: Request,
    db: Any,
    scope: str,
) -> UnifiedAuthContext:
    ctx = resolve_auth_context(request, db, required=True)
    if ctx is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    if ctx.has_scope(scope):
        return ctx
    raise HTTPException(
        status_code=403,
        detail={
            "error": "missing_scope",
            "required_scope": scope,
            "role": ctx.role,
            "user_id": ctx.user_id,
        },
    )


def require_any_scope(
    request: Request,
    db: Any,
    scopes: Iterable[str],
) -> UnifiedAuthContext:
    normalized = [str(scope).strip() for scope in scopes if str(scope).strip()]
    ctx = resolve_auth_context(request, db, required=True)
    if ctx is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    if any(ctx.has_scope(scope) for scope in normalized):
        return ctx
    raise HTTPException(
        status_code=403,
        detail={
            "error": "missing_any_scope",
            "required_scopes": normalized,
            "role": ctx.role,
            "user_id": ctx.user_id,
        },
    )


def ensure_audit_events_table(db: Any) -> None:
    """Create the audit_events table if it doesn't exist (idempotent)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 1,
            path TEXT,
            method TEXT,
            user_id TEXT,
            role TEXT,
            auth_type TEXT,
            details_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_user "
        "ON audit_events(user_id, timestamp DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_action "
        "ON audit_events(action, timestamp DESC)"
    )


def _store_audit_event_db(db: Any, payload: Dict[str, Any]) -> bool:
    """Insert one audit event row.  Returns True on success."""
    try:
        db.execute(
            """
            INSERT INTO audit_events
                (timestamp, action, allowed, path, method, user_id, role, auth_type, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["timestamp"],
                payload["action"],
                int(payload["allowed"]),
                payload.get("path"),
                payload.get("method"),
                payload.get("user_id"),
                payload.get("role"),
                payload.get("auth_type"),
                json.dumps(payload.get("details") or {}, ensure_ascii=False),
            ),
        )
        return True
    except Exception:
        logger.debug("audit DB write failed, falling back to JSONL", exc_info=True)
        return False


def _store_audit_event_jsonl(payload: Dict[str, Any]) -> None:
    """Legacy JSONL file fallback."""
    root = Path(".seed_artifacts") / "audit"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "auth_events.jsonl"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def query_audit_events(
    db: Any,
    *,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Query audit events from the DB table."""
    clauses: List[str] = []
    params: List[Any] = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM audit_events{where} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = db.fetchall(sql, tuple(params))
    results: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        raw = d.pop("details_json", "{}")
        d["details"] = json.loads(raw) if raw else {}
        results.append(d)
    return results


def audit_auth_event(
    *,
    action: str,
    request: Request,
    context: Optional[UnifiedAuthContext],
    allowed: bool,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist an audit event to DB (preferred) with JSONL fallback."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "allowed": bool(allowed),
        "path": str(request.url.path),
        "method": request.method,
        "user_id": context.user_id if context else None,
        "role": context.role if context else None,
        "auth_type": context.auth_type if context else None,
        "details": details or {},
    }
    # Try DB first, fallback to JSONL
    db = getattr(getattr(request.app, "state", None), "seed", None)
    db = getattr(db, "db", None) if db is not None else None
    if db is not None and _store_audit_event_db(db, payload):
        return
    _store_audit_event_jsonl(payload)
