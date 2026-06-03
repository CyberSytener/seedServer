from __future__ import annotations

import asyncio
import enum
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.infrastructure.db.postgres import AsyncPGDatabase


class BlueprintStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SANDBOXED = "SANDBOXED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BlueprintRecord:
    __slots__ = ("name", "owner_id", "status", "data", "created_at", "updated_at")

    def __init__(
        self,
        name: str,
        data: Dict[str, Any],
        *,
        owner_id: str = "system",
        status: BlueprintStatus = BlueprintStatus.DRAFT,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        self.name = name
        self.owner_id = owner_id
        self.status = status
        self.data = data
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class RunRecord:
    __slots__ = (
        "run_id",
        "blueprint_name",
        "owner_id",
        "status",
        "execution_mode",
        "request_payload",
        "result",
        "execution_trace",
        "performance",
        "ai_summary",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        run_id: str,
        blueprint_name: str,
        *,
        owner_id: str = "system",
        status: str = "unknown",
        execution_mode: str = "LIVE",
        request_payload: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        execution_trace: Optional[List[Dict[str, Any]]] = None,
        performance: Optional[Dict[str, Any]] = None,
        ai_summary: Optional[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        self.run_id = run_id
        self.blueprint_name = blueprint_name
        self.owner_id = owner_id
        self.status = status
        self.execution_mode = execution_mode
        self.request_payload = request_payload or {}
        self.result = result or {}
        self.execution_trace = execution_trace or []
        self.performance = performance or {}
        self.ai_summary = ai_summary
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "blueprint_name": self.blueprint_name,
            "owner_id": self.owner_id,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "request_payload": self.request_payload,
            "result": self.result,
            "execution_trace": self.execution_trace,
            "performance": self.performance,
            "ai_summary": self.ai_summary,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class BlueprintStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._store: Dict[str, BlueprintRecord] = {}

    async def save(
        self,
        name: str,
        blueprint: Dict[str, Any],
        *,
        owner_id: str = "system",
        status: BlueprintStatus = BlueprintStatus.DRAFT,
    ) -> BlueprintRecord:
        async with self._lock:
            existing = self._store.get(name)
            now = datetime.now(timezone.utc)
            record = BlueprintRecord(
                name=name,
                data=blueprint,
                owner_id=owner_id,
                status=status,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._store[name] = record
            return record

    async def get(self, name: str, *, owner_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        async with self._lock:
            record = self._store.get(name)
            if not record:
                return None
            if owner_id and record.owner_id != owner_id and record.owner_id != "system":
                return None
            return record.data

    async def get_record(self, name: str) -> Optional[BlueprintRecord]:
        async with self._lock:
            return self._store.get(name)

    async def update_status(self, name: str, status: BlueprintStatus) -> Optional[BlueprintRecord]:
        async with self._lock:
            record = self._store.get(name)
            if not record:
                return None
            record.status = status
            record.updated_at = datetime.now(timezone.utc)
            return record

    async def list_names(self, *, owner_id: Optional[str] = None) -> List[str]:
        async with self._lock:
            if owner_id:
                return sorted(
                    name
                    for name, rec in self._store.items()
                    if rec.owner_id == owner_id or rec.owner_id == "system"
                )
            return sorted(self._store.keys())

    async def list_records(self, *, owner_id: Optional[str] = None) -> List[BlueprintRecord]:
        async with self._lock:
            records = list(self._store.values())
            if owner_id:
                records = [r for r in records if r.owner_id == owner_id or r.owner_id == "system"]
            return sorted(records, key=lambda r: r.created_at, reverse=True)


class RunStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._store: Dict[str, RunRecord] = {}

    async def save(self, record: RunRecord) -> RunRecord:
        async with self._lock:
            now = datetime.now(timezone.utc)
            record.updated_at = now
            if record.run_id not in self._store:
                record.created_at = now
            self._store[record.run_id] = record
            return record

    async def get(self, run_id: str) -> Optional[RunRecord]:
        async with self._lock:
            return self._store.get(run_id)

    async def list_runs(
        self,
        *,
        blueprint_name: Optional[str] = None,
        owner_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[RunRecord]:
        async with self._lock:
            records = list(self._store.values())
            if blueprint_name:
                records = [r for r in records if r.blueprint_name == blueprint_name]
            if owner_id:
                records = [r for r in records if r.owner_id == owner_id or r.owner_id == "system"]
            records.sort(key=lambda r: r.created_at, reverse=True)
            return records[:limit]


class PostgresBlueprintStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._db: Optional[AsyncPGDatabase] = None
        self._lock = asyncio.Lock()
        self._ready = False

    async def _get_db(self) -> AsyncPGDatabase:
        if self._db:
            return self._db
        self._db = await AsyncPGDatabase.get_shared(self._dsn)
        return self._db

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            db = await self._get_db()
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS saga_blueprints (
                    name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                """
            )
            self._ready = True

    @staticmethod
    def _row_value(row: Any, key: str, default: Any = None) -> Any:
        if row is None:
            return default
        try:
            return row[key]
        except Exception:
            return default

    @classmethod
    def _row_to_record(cls, row: Any) -> BlueprintRecord:
        data = cls._row_value(row, "data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        status_value = cls._row_value(row, "status", BlueprintStatus.DRAFT.value)
        try:
            status = BlueprintStatus(status_value)
        except ValueError:
            status = BlueprintStatus.DRAFT
        return BlueprintRecord(
            name=cls._row_value(row, "name"),
            data=data or {},
            owner_id=cls._row_value(row, "owner_id", "system"),
            status=status,
            created_at=cls._row_value(row, "created_at"),
            updated_at=cls._row_value(row, "updated_at"),
        )

    async def save(
        self,
        name: str,
        blueprint: Dict[str, Any],
        *,
        owner_id: str = "system",
        status: BlueprintStatus = BlueprintStatus.DRAFT,
    ) -> BlueprintRecord:
        await self._ensure_table()
        db = await self._get_db()
        now = datetime.now(timezone.utc)
        row = await db.fetchrow(
            """
            INSERT INTO saga_blueprints (name, owner_id, status, data, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (name) DO UPDATE SET
                owner_id = EXCLUDED.owner_id,
                status = EXCLUDED.status,
                data = EXCLUDED.data,
                updated_at = EXCLUDED.updated_at,
                created_at = saga_blueprints.created_at
            RETURNING name, owner_id, status, data, created_at, updated_at;
            """,
            name,
            owner_id,
            status.value,
            json.dumps(blueprint),
            now,
            now,
        )
        return self._row_to_record(row)

    async def get(self, name: str, *, owner_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        await self._ensure_table()
        db = await self._get_db()
        row = await db.fetchrow(
            """
            SELECT name, owner_id, status, data, created_at, updated_at
            FROM saga_blueprints
            WHERE name = $1
            """,
            name,
        )
        if not row:
            return None
        owner_value = self._row_value(row, "owner_id")
        if owner_id and owner_value != owner_id and owner_value != "system":
            return None
        record = self._row_to_record(row)
        return record.data

    async def get_record(self, name: str) -> Optional[BlueprintRecord]:
        await self._ensure_table()
        db = await self._get_db()
        row = await db.fetchrow(
            """
            SELECT name, owner_id, status, data, created_at, updated_at
            FROM saga_blueprints
            WHERE name = $1
            """,
            name,
        )
        if not row:
            return None
        return self._row_to_record(row)

    async def update_status(self, name: str, status: BlueprintStatus) -> Optional[BlueprintRecord]:
        await self._ensure_table()
        db = await self._get_db()
        row = await db.fetchrow(
            """
            UPDATE saga_blueprints
            SET status = $2, updated_at = $3
            WHERE name = $1
            RETURNING name, owner_id, status, data, created_at, updated_at;
            """,
            name,
            status.value,
            datetime.now(timezone.utc),
        )
        if not row:
            return None
        return self._row_to_record(row)

    async def list_names(self, *, owner_id: Optional[str] = None) -> List[str]:
        await self._ensure_table()
        db = await self._get_db()
        if owner_id:
            rows = await db.fetch(
                """
                SELECT name FROM saga_blueprints
                WHERE owner_id = $1 OR owner_id = 'system'
                ORDER BY created_at DESC
                """,
                owner_id,
            )
        else:
            rows = await db.fetch(
                """
                SELECT name FROM saga_blueprints
                ORDER BY created_at DESC
                """
            )
        return [row["name"] for row in rows]

    async def list_records(self, *, owner_id: Optional[str] = None) -> List[BlueprintRecord]:
        await self._ensure_table()
        db = await self._get_db()
        if owner_id:
            rows = await db.fetch(
                """
                SELECT name, owner_id, status, data, created_at, updated_at
                FROM saga_blueprints
                WHERE owner_id = $1 OR owner_id = 'system'
                ORDER BY created_at DESC
                """,
                owner_id,
            )
        else:
            rows = await db.fetch(
                """
                SELECT name, owner_id, status, data, created_at, updated_at
                FROM saga_blueprints
                ORDER BY created_at DESC
                """
            )
        return [self._row_to_record(row) for row in rows]


class PostgresRunStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._db: Optional[AsyncPGDatabase] = None
        self._lock = asyncio.Lock()
        self._ready = False

    async def _get_db(self) -> AsyncPGDatabase:
        if self._db:
            return self._db
        self._db = await AsyncPGDatabase.get_shared(self._dsn)
        return self._db

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            db = await self._get_db()
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS saga_runs (
                    run_id TEXT PRIMARY KEY,
                    blueprint_name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    request_payload JSONB NOT NULL,
                    result JSONB NOT NULL,
                    execution_trace JSONB NOT NULL,
                    performance JSONB NOT NULL,
                    ai_summary TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                """
            )
            self._ready = True

    @staticmethod
    def _row_value(row: Any, key: str, default: Any = None) -> Any:
        if row is None:
            return default
        try:
            return row[key]
        except Exception:
            return default

    @classmethod
    def _row_to_record(cls, row: Any) -> RunRecord:
        def _load(value: Any) -> Any:
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return {}
            return value

        return RunRecord(
            run_id=cls._row_value(row, "run_id"),
            blueprint_name=cls._row_value(row, "blueprint_name"),
            owner_id=cls._row_value(row, "owner_id", "system"),
            status=cls._row_value(row, "status", "unknown"),
            execution_mode=cls._row_value(row, "execution_mode", "LIVE"),
            request_payload=_load(cls._row_value(row, "request_payload")) or {},
            result=_load(cls._row_value(row, "result")) or {},
            execution_trace=_load(cls._row_value(row, "execution_trace")) or [],
            performance=_load(cls._row_value(row, "performance")) or {},
            ai_summary=cls._row_value(row, "ai_summary"),
            created_at=cls._row_value(row, "created_at"),
            updated_at=cls._row_value(row, "updated_at"),
        )

    async def save(self, record: RunRecord) -> RunRecord:
        await self._ensure_table()
        db = await self._get_db()
        now = datetime.now(timezone.utc)
        row = await db.fetchrow(
            """
            INSERT INTO saga_runs (
                run_id, blueprint_name, owner_id, status, execution_mode,
                request_payload, result, execution_trace, performance, ai_summary,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (run_id) DO UPDATE SET
                status = EXCLUDED.status,
                execution_mode = EXCLUDED.execution_mode,
                request_payload = EXCLUDED.request_payload,
                result = EXCLUDED.result,
                execution_trace = EXCLUDED.execution_trace,
                performance = EXCLUDED.performance,
                ai_summary = EXCLUDED.ai_summary,
                updated_at = EXCLUDED.updated_at
            RETURNING run_id, blueprint_name, owner_id, status, execution_mode,
                      request_payload, result, execution_trace, performance, ai_summary,
                      created_at, updated_at;
            """,
            record.run_id,
            record.blueprint_name,
            record.owner_id,
            record.status,
            record.execution_mode,
            json.dumps(record.request_payload),
            json.dumps(record.result),
            json.dumps(record.execution_trace),
            json.dumps(record.performance),
            record.ai_summary,
            record.created_at,
            now,
        )
        return self._row_to_record(row)

    async def get(self, run_id: str) -> Optional[RunRecord]:
        await self._ensure_table()
        db = await self._get_db()
        row = await db.fetchrow(
            """
            SELECT run_id, blueprint_name, owner_id, status, execution_mode,
                   request_payload, result, execution_trace, performance, ai_summary,
                   created_at, updated_at
            FROM saga_runs
            WHERE run_id = $1
            """,
            run_id,
        )
        if not row:
            return None
        return self._row_to_record(row)

    async def list_runs(
        self,
        *,
        blueprint_name: Optional[str] = None,
        owner_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[RunRecord]:
        await self._ensure_table()
        db = await self._get_db()
        clauses = []
        params: List[Any] = []
        if blueprint_name:
            clauses.append(f"blueprint_name = ${len(params) + 1}")
            params.append(blueprint_name)
        if owner_id:
            clauses.append(f"(owner_id = ${len(params) + 1} OR owner_id = 'system')")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            "SELECT run_id, blueprint_name, owner_id, status, execution_mode, "
            "request_payload, result, execution_trace, performance, ai_summary, "
            "created_at, updated_at "
            "FROM saga_runs "
            f"{where} "
            "ORDER BY created_at DESC "
            "LIMIT "
            + str(max(1, min(limit, 500)))
        )
        rows = await db.fetch(query, *params)
        return [self._row_to_record(row) for row in rows]


def _get_blueprint_store():
    dsn = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL")
    storage = (os.getenv("SEED_BLUEPRINT_STORAGE") or "").lower().strip()
    if dsn and (storage in ("postgres", "pg", "postgre") or storage == ""):
        return PostgresBlueprintStore(dsn)
    return BlueprintStore()


def _get_run_store():
    dsn = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL")
    storage = (os.getenv("SEED_RUN_STORAGE") or "").lower().strip()
    if dsn and (storage in ("postgres", "pg", "postgre") or storage == ""):
        return PostgresRunStore(dsn)
    return RunStore()


blueprint_store = _get_blueprint_store()
run_store = _get_run_store()
