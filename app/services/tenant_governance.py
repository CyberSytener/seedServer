from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.infrastructure.db.sqlite import DB

ROLE_VALUES = {"owner", "admin", "operator", "viewer", "billing"}
WINDOW_VALUES = {"minute", "hour", "day", "month"}
METRIC_VALUES = {"quantity", "cost_usd", "credits"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _project_scope(project_id: Optional[str]) -> str:
    return str(project_id or "").strip()


def _window_start(window: str) -> datetime:
    normalized = str(window or "").strip().lower()
    now = _now()
    if normalized == "minute":
        return now - timedelta(minutes=1)
    if normalized == "hour":
        return now - timedelta(hours=1)
    if normalized == "day":
        return now - timedelta(days=1)
    if normalized == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError("Unsupported quota window")


def ensure_tenant_governance_tables(db: DB) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_orgs (
            tenant_id TEXT PRIMARY KEY,
            display_name TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_projects (
            project_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            display_name TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(tenant_id) REFERENCES tenant_orgs(tenant_id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            granted_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(tenant_id, project_id, user_id, role),
            FOREIGN KEY(tenant_id) REFERENCES tenant_orgs(tenant_id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_quotas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL,
            metric TEXT NOT NULL DEFAULT 'quantity',
            window TEXT NOT NULL,
            limit_value REAL NOT NULL,
            hard_limit INTEGER NOT NULL DEFAULT 1,
            updated_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(tenant_id, project_id, operation, metric, window),
            FOREIGN KEY(tenant_id) REFERENCES tenant_orgs(tenant_id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            credits REAL NOT NULL DEFAULT 0,
            actor_id TEXT,
            status TEXT NOT NULL DEFAULT 'ok',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(tenant_id) REFERENCES tenant_orgs(tenant_id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            actor_id TEXT,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(tenant_id) REFERENCES tenant_orgs(tenant_id) ON DELETE CASCADE
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_tenant_projects_tenant ON tenant_projects(tenant_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tenant_memberships_tenant ON tenant_memberships(tenant_id, project_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tenant_quotas_tenant ON tenant_quotas(tenant_id, project_id, operation)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tenant_usage_tenant ON tenant_usage_events(tenant_id, project_id, operation, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tenant_audit_tenant ON tenant_audit_log(tenant_id, project_id, created_at)")


class TenantGovernanceService:
    def __init__(self, db: DB) -> None:
        self._db = db
        ensure_tenant_governance_tables(self._db)
        # In-memory idempotency key set with TTL tracking
        self._idempotency_keys: Dict[str, float] = {}
        self._idempotency_ttl_seconds: float = 3600.0  # 1 hour

    def upsert_tenant(
        self,
        *,
        tenant_id: str,
        display_name: Optional[str],
        metadata: Optional[Dict[str, Any]],
        actor_id: str,
    ) -> Dict[str, Any]:
        tenant_id = str(tenant_id or "").strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        now_iso = _now_iso()
        self._db.execute(
            """
            INSERT INTO tenant_orgs(tenant_id, display_name, meta_json, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id) DO UPDATE
            SET display_name=excluded.display_name,
                meta_json=excluded.meta_json,
                updated_at=excluded.updated_at
            """,
            (
                tenant_id,
                str(display_name or "").strip() or None,
                json.dumps(metadata or {}, ensure_ascii=False),
                now_iso,
                now_iso,
            ),
        )
        self._audit(
            tenant_id=tenant_id,
            project_id="",
            actor_id=actor_id,
            action="tenant.upsert",
            target_type="tenant",
            target_id=tenant_id,
            payload={"display_name": display_name, "metadata": metadata or {}},
        )
        return self._tenant_row(tenant_id)

    def upsert_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        display_name: Optional[str],
        metadata: Optional[Dict[str, Any]],
        actor_id: str,
    ) -> Dict[str, Any]:
        tenant_id = str(tenant_id or "").strip()
        project_id = str(project_id or "").strip()
        if not tenant_id or not project_id:
            raise ValueError("tenant_id and project_id are required")
        if self._db.fetchone("SELECT tenant_id FROM tenant_orgs WHERE tenant_id = ?", (tenant_id,)) is None:
            raise ValueError("tenant_not_found")
        now_iso = _now_iso()
        self._db.execute(
            """
            INSERT INTO tenant_projects(project_id, tenant_id, display_name, meta_json, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE
            SET display_name=excluded.display_name,
                meta_json=excluded.meta_json,
                updated_at=excluded.updated_at
            """,
            (
                project_id,
                tenant_id,
                str(display_name or "").strip() or None,
                json.dumps(metadata or {}, ensure_ascii=False),
                now_iso,
                now_iso,
            ),
        )
        self._audit(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            action="project.upsert",
            target_type="project",
            target_id=project_id,
            payload={"display_name": display_name, "metadata": metadata or {}},
        )
        return self._project_row(project_id)

    def grant_role(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str,
        actor_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant_id = str(tenant_id or "").strip()
        user_id = str(user_id or "").strip()
        role_value = str(role or "").strip().lower()
        scope = _project_scope(project_id)
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and user_id are required")
        if role_value not in ROLE_VALUES:
            raise ValueError("unsupported_role")
        if self._db.fetchone("SELECT tenant_id FROM tenant_orgs WHERE tenant_id = ?", (tenant_id,)) is None:
            raise ValueError("tenant_not_found")
        if scope:
            row = self._db.fetchone(
                "SELECT project_id FROM tenant_projects WHERE project_id = ? AND tenant_id = ?",
                (scope, tenant_id),
            )
            if row is None:
                raise ValueError("project_not_found")
        self._db.execute(
            """
            INSERT OR IGNORE INTO tenant_memberships(tenant_id, project_id, user_id, role, granted_by, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, scope, user_id, role_value, actor_id, _now_iso()),
        )
        self._audit(
            tenant_id=tenant_id,
            project_id=scope,
            actor_id=actor_id,
            action="role.grant",
            target_type="membership",
            target_id=user_id,
            payload={"role": role_value},
        )
        return {
            "tenant_id": tenant_id,
            "project_id": scope or None,
            "user_id": user_id,
            "role": role_value,
        }

    def set_quota(
        self,
        *,
        tenant_id: str,
        operation: str,
        window: str,
        limit_value: float,
        metric: str,
        actor_id: str,
        project_id: Optional[str] = None,
        hard_limit: bool = True,
    ) -> Dict[str, Any]:
        tenant_id = str(tenant_id or "").strip()
        operation_value = str(operation or "").strip().lower()
        window_value = str(window or "").strip().lower()
        metric_value = str(metric or "").strip().lower()
        scope = _project_scope(project_id)
        if not tenant_id or not operation_value:
            raise ValueError("tenant_id and operation are required")
        if window_value not in WINDOW_VALUES:
            raise ValueError("unsupported_window")
        if metric_value not in METRIC_VALUES:
            raise ValueError("unsupported_metric")
        if float(limit_value) <= 0:
            raise ValueError("limit_value must be > 0")
        if self._db.fetchone("SELECT tenant_id FROM tenant_orgs WHERE tenant_id = ?", (tenant_id,)) is None:
            raise ValueError("tenant_not_found")
        if scope:
            row = self._db.fetchone(
                "SELECT project_id FROM tenant_projects WHERE project_id = ? AND tenant_id = ?",
                (scope, tenant_id),
            )
            if row is None:
                raise ValueError("project_not_found")
        now_iso = _now_iso()
        self._db.execute(
            """
            INSERT INTO tenant_quotas(tenant_id, project_id, operation, metric, window, limit_value, hard_limit, updated_by, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, project_id, operation, metric, window) DO UPDATE
            SET limit_value=excluded.limit_value,
                hard_limit=excluded.hard_limit,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at
            """,
            (
                tenant_id,
                scope,
                operation_value,
                metric_value,
                window_value,
                float(limit_value),
                1 if hard_limit else 0,
                actor_id,
                now_iso,
                now_iso,
            ),
        )
        self._audit(
            tenant_id=tenant_id,
            project_id=scope,
            actor_id=actor_id,
            action="quota.set",
            target_type="quota",
            target_id=f"{operation_value}:{metric_value}:{window_value}",
            payload={
                "limit_value": float(limit_value),
                "hard_limit": bool(hard_limit),
            },
        )
        return {
            "tenant_id": tenant_id,
            "project_id": scope or None,
            "operation": operation_value,
            "metric": metric_value,
            "window": window_value,
            "limit_value": float(limit_value),
            "hard_limit": bool(hard_limit),
        }

    def check_quota(
        self,
        *,
        tenant_id: str,
        operation: str,
        project_id: Optional[str] = None,
        quantity: float = 1.0,
        cost_usd: float = 0.0,
        credits: float = 0.0,
    ) -> Dict[str, Any]:
        tenant_id = str(tenant_id or "").strip()
        operation_value = str(operation or "").strip().lower()
        scope = _project_scope(project_id)
        if not tenant_id or not operation_value:
            raise ValueError("tenant_id and operation are required")
        quotas = self._db.fetchall(
            """
            SELECT tenant_id, project_id, operation, metric, window, limit_value, hard_limit
            FROM tenant_quotas
            WHERE tenant_id = ? AND operation = ?
            """,
            (tenant_id, operation_value),
        )
        checks: List[Dict[str, Any]] = []
        violations: List[Dict[str, Any]] = []

        for row in quotas:
            quota_scope = str(row["project_id"] or "")
            if quota_scope and quota_scope != scope:
                continue
            since = _window_start(str(row["window"])).isoformat()
            metric_value = str(row["metric"] or "quantity")
            usage_before = self._sum_usage(
                tenant_id=tenant_id,
                operation=operation_value,
                metric=metric_value,
                since_iso=since,
                project_scope=quota_scope,
            )
            increment = self._metric_delta(
                metric=metric_value,
                quantity=quantity,
                cost_usd=cost_usd,
                credits=credits,
            )
            projected = usage_before + increment
            limit_value = float(row["limit_value"] or 0.0)
            remaining = max(0.0, limit_value - projected)
            hard_limit = bool(row["hard_limit"])
            passed = projected <= limit_value
            check = {
                "scope": "tenant" if not quota_scope else "project",
                "project_id": quota_scope or None,
                "metric": metric_value,
                "window": str(row["window"]),
                "limit_value": limit_value,
                "used_before": round(usage_before, 6),
                "increment": round(increment, 6),
                "projected": round(projected, 6),
                "remaining": round(remaining, 6),
                "hard_limit": hard_limit,
                "passed": passed,
            }
            checks.append(check)
            if not passed and hard_limit:
                violations.append(check)

        return {
            "tenant_id": tenant_id,
            "project_id": scope or None,
            "operation": operation_value,
            "allowed": len(violations) == 0,
            "checks": checks,
            "violations": violations,
        }

    def _prune_expired_idempotency_keys(self) -> None:
        """Remove expired idempotency keys (older than TTL)."""
        now = _now().timestamp()
        expired = [
            k for k, ts in self._idempotency_keys.items()
            if now - ts > self._idempotency_ttl_seconds
        ]
        for k in expired:
            del self._idempotency_keys[k]

    def record_usage(
        self,
        *,
        tenant_id: str,
        operation: str,
        actor_id: str,
        project_id: Optional[str] = None,
        quantity: float = 1.0,
        cost_usd: float = 0.0,
        credits: float = 0.0,
        enforce_quotas: bool = True,
        status: str = "ok",
        error: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Idempotency dedup: if same key already processed, skip
        if idempotency_key:
            self._prune_expired_idempotency_keys()
            if idempotency_key in self._idempotency_keys:
                return {
                    "tenant_id": str(tenant_id or "").strip(),
                    "operation": str(operation or "").strip().lower(),
                    "deduplicated": True,
                    "idempotency_key": idempotency_key,
                }

        tenant_id = str(tenant_id or "").strip()
        operation_value = str(operation or "").strip().lower()
        scope = _project_scope(project_id)
        if not tenant_id or not operation_value:
            raise ValueError("tenant_id and operation are required")

        quota = self.check_quota(
            tenant_id=tenant_id,
            operation=operation_value,
            project_id=scope or None,
            quantity=quantity,
            cost_usd=cost_usd,
            credits=credits,
        )

        event_status = str(status or "ok")
        event_error = str(error or "").strip() or None
        allowed = bool(quota["allowed"])
        if enforce_quotas and not allowed:
            event_status = "blocked"
            if not event_error:
                first = quota["violations"][0] if quota["violations"] else {}
                event_error = f"quota_exceeded:{first.get('metric')}:{first.get('window')}"

        self._db.execute(
            """
            INSERT INTO tenant_usage_events(
                tenant_id, project_id, operation, quantity, cost_usd, credits, actor_id, status, error, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                scope,
                operation_value,
                float(quantity),
                float(cost_usd),
                float(credits),
                actor_id,
                event_status,
                event_error,
                _now_iso(),
            ),
        )
        self._audit(
            tenant_id=tenant_id,
            project_id=scope,
            actor_id=actor_id,
            action="usage.record",
            target_type="usage_event",
            target_id=operation_value,
            payload={
                "quantity": float(quantity),
                "cost_usd": float(cost_usd),
                "credits": float(credits),
                "status": event_status,
                "error": event_error,
                "enforce_quotas": bool(enforce_quotas),
            },
        )
        # Record idempotency key after successful insert
        if idempotency_key:
            self._idempotency_keys[idempotency_key] = _now().timestamp()

        return {
            "tenant_id": tenant_id,
            "project_id": scope or None,
            "operation": operation_value,
            "allowed": allowed,
            "recorded_status": event_status,
            "error": event_error,
            "quota": quota,
        }

    def export_usage(
        self,
        *,
        tenant_id: str,
        hours: int = 24,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant_id = str(tenant_id or "").strip()
        scope = _project_scope(project_id)
        if not tenant_id:
            raise ValueError("tenant_id is required")
        cutoff_iso = (_now() - timedelta(hours=max(1, int(hours)))).isoformat()
        if scope:
            rows = self._db.fetchall(
                """
                SELECT operation, quantity, cost_usd, credits, status, error, actor_id, created_at
                FROM tenant_usage_events
                WHERE tenant_id = ? AND project_id = ? AND created_at >= ?
                ORDER BY created_at DESC
                """,
                (tenant_id, scope, cutoff_iso),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT operation, quantity, cost_usd, credits, status, error, actor_id, created_at, project_id
                FROM tenant_usage_events
                WHERE tenant_id = ? AND created_at >= ?
                ORDER BY created_at DESC
                """,
                (tenant_id, cutoff_iso),
            )

        totals: Dict[str, Dict[str, float]] = {}
        blocked = 0
        events: List[Dict[str, Any]] = []
        for row in rows:
            op = str(row["operation"])
            summary = totals.setdefault(
                op,
                {"quantity": 0.0, "cost_usd": 0.0, "credits": 0.0, "events": 0.0},
            )
            summary["quantity"] += float(row["quantity"] or 0.0)
            summary["cost_usd"] += float(row["cost_usd"] or 0.0)
            summary["credits"] += float(row["credits"] or 0.0)
            summary["events"] += 1.0
            if str(row["status"] or "").lower() == "blocked":
                blocked += 1
            events.append(
                {
                    "operation": op,
                    "quantity": float(row["quantity"] or 0.0),
                    "cost_usd": float(row["cost_usd"] or 0.0),
                    "credits": float(row["credits"] or 0.0),
                    "status": str(row["status"] or "ok"),
                    "error": row["error"],
                    "actor_id": row["actor_id"],
                    "project_id": (row["project_id"] if "project_id" in row.keys() else scope) or None,
                    "created_at": row["created_at"],
                }
            )

        quotas = self.list_quotas(tenant_id=tenant_id, project_id=scope or None)
        return {
            "tenant_id": tenant_id,
            "project_id": scope or None,
            "window_hours": max(1, int(hours)),
            "events_count": len(events),
            "blocked_count": blocked,
            "totals_by_operation": totals,
            "quotas": quotas,
            "events": events,
        }

    def get_audit(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tenant_id = str(tenant_id or "").strip()
        scope = _project_scope(project_id)
        query = (
            """
            SELECT actor_id, action, target_type, target_id, payload_json, created_at, project_id
            FROM tenant_audit_log
            WHERE tenant_id = ? {project_clause}
            ORDER BY id DESC
            LIMIT ?
            """
        )
        if scope:
            rows = self._db.fetchall(query.format(project_clause="AND project_id = ?"), (tenant_id, scope, int(limit)))
        else:
            rows = self._db.fetchall(query.format(project_clause=""), (tenant_id, int(limit)))
        out: List[Dict[str, Any]] = []
        for row in rows:
            payload_raw = row["payload_json"] or "{}"
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
            out.append(
                {
                    "actor_id": row["actor_id"],
                    "action": row["action"],
                    "target_type": row["target_type"],
                    "target_id": row["target_id"],
                    "project_id": row["project_id"] or None,
                    "payload": payload,
                    "created_at": row["created_at"],
                }
            )
        return out

    def list_projects(self, *, tenant_id: str) -> List[Dict[str, Any]]:
        rows = self._db.fetchall(
            """
            SELECT project_id, tenant_id, display_name, status, meta_json, created_at, updated_at
            FROM tenant_projects
            WHERE tenant_id = ?
            ORDER BY project_id
            """,
            (tenant_id,),
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "project_id": row["project_id"],
                    "tenant_id": row["tenant_id"],
                    "display_name": row["display_name"],
                    "status": row["status"],
                    "metadata": json.loads(row["meta_json"] or "{}"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return out

    def list_memberships(self, *, tenant_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        scope = _project_scope(project_id)
        if scope:
            rows = self._db.fetchall(
                """
                SELECT tenant_id, project_id, user_id, role, granted_by, created_at
                FROM tenant_memberships
                WHERE tenant_id = ? AND project_id = ?
                ORDER BY user_id, role
                """,
                (tenant_id, scope),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT tenant_id, project_id, user_id, role, granted_by, created_at
                FROM tenant_memberships
                WHERE tenant_id = ?
                ORDER BY project_id, user_id, role
                """,
                (tenant_id,),
            )
        return [
            {
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"] or None,
                "user_id": row["user_id"],
                "role": row["role"],
                "granted_by": row["granted_by"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_quotas(self, *, tenant_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        scope = _project_scope(project_id)
        if scope:
            rows = self._db.fetchall(
                """
                SELECT tenant_id, project_id, operation, metric, window, limit_value, hard_limit, updated_by, updated_at
                FROM tenant_quotas
                WHERE tenant_id = ? AND (project_id = '' OR project_id = ?)
                ORDER BY operation, metric, window, project_id
                """,
                (tenant_id, scope),
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT tenant_id, project_id, operation, metric, window, limit_value, hard_limit, updated_by, updated_at
                FROM tenant_quotas
                WHERE tenant_id = ?
                ORDER BY operation, metric, window, project_id
                """,
                (tenant_id,),
            )
        return [
            {
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"] or None,
                "operation": row["operation"],
                "metric": row["metric"],
                "window": row["window"],
                "limit_value": float(row["limit_value"] or 0.0),
                "hard_limit": bool(row["hard_limit"]),
                "updated_by": row["updated_by"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def governance_snapshot(self, *, tenant_id: str) -> Dict[str, Any]:
        return {
            "tenant": self._tenant_row(tenant_id),
            "projects": self.list_projects(tenant_id=tenant_id),
            "memberships": self.list_memberships(tenant_id=tenant_id),
            "quotas": self.list_quotas(tenant_id=tenant_id),
        }

    def _tenant_row(self, tenant_id: str) -> Dict[str, Any]:
        row = self._db.fetchone(
            """
            SELECT tenant_id, display_name, status, meta_json, created_at, updated_at
            FROM tenant_orgs
            WHERE tenant_id = ?
            """,
            (tenant_id,),
        )
        if row is None:
            raise ValueError("tenant_not_found")
        return {
            "tenant_id": row["tenant_id"],
            "display_name": row["display_name"],
            "status": row["status"],
            "metadata": json.loads(row["meta_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _project_row(self, project_id: str) -> Dict[str, Any]:
        row = self._db.fetchone(
            """
            SELECT project_id, tenant_id, display_name, status, meta_json, created_at, updated_at
            FROM tenant_projects
            WHERE project_id = ?
            """,
            (project_id,),
        )
        if row is None:
            raise ValueError("project_not_found")
        return {
            "project_id": row["project_id"],
            "tenant_id": row["tenant_id"],
            "display_name": row["display_name"],
            "status": row["status"],
            "metadata": json.loads(row["meta_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _sum_usage(
        self,
        *,
        tenant_id: str,
        operation: str,
        metric: str,
        since_iso: str,
        project_scope: str,
    ) -> float:
        metric_column = {"quantity": "quantity", "cost_usd": "cost_usd", "credits": "credits"}[metric]
        if project_scope:
            row = self._db.fetchone(
                f"""
                SELECT COALESCE(SUM({metric_column}), 0) AS total
                FROM tenant_usage_events
                WHERE tenant_id = ? AND project_id = ? AND operation = ? AND created_at >= ?
                """,
                (tenant_id, project_scope, operation, since_iso),
            )
        else:
            row = self._db.fetchone(
                f"""
                SELECT COALESCE(SUM({metric_column}), 0) AS total
                FROM tenant_usage_events
                WHERE tenant_id = ? AND operation = ? AND created_at >= ?
                """,
                (tenant_id, operation, since_iso),
            )
        return float(row["total"] or 0.0) if row else 0.0

    @staticmethod
    def _metric_delta(*, metric: str, quantity: float, cost_usd: float, credits: float) -> float:
        if metric == "quantity":
            return float(quantity)
        if metric == "cost_usd":
            return float(cost_usd)
        return float(credits)

    def _audit(
        self,
        *,
        tenant_id: str,
        project_id: str,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        self._db.execute(
            """
            INSERT INTO tenant_audit_log(
                tenant_id, project_id, actor_id, action, target_type, target_id, payload_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                project_id,
                actor_id,
                action,
                target_type,
                target_id,
                json.dumps(payload or {}, ensure_ascii=False),
                _now_iso(),
            ),
        )

