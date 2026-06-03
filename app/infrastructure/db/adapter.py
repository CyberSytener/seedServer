from __future__ import annotations

from typing import Iterable, Any

from app.core.interfaces.database import DatabaseProtocol
from .sqlite import DB


class SqliteDatabaseAdapter(DatabaseProtocol):
    """Adapter that exposes the core DatabaseProtocol using the SQLite DB wrapper."""

    def __init__(self, db: DB):
        self._db = db

    def transaction(self):
        return self._db.transaction()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._db.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[tuple[Any, ...]]) -> None:
        self._db.executemany(sql, seq)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any | None:
        return self._db.fetchone(sql, params)

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        return self._db.fetchall(sql, params)

    def close(self) -> None:
        self._db.close()
