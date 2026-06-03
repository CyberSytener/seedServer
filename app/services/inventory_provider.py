from __future__ import annotations

import time
from typing import Dict, List, Protocol

from app.infrastructure.db.postgres import AsyncPGDatabase


class InventoryProvider(Protocol):
    async def list_stock_snapshot(self) -> List[Dict[str, object]]: ...


class PostgresInventoryProvider:
    def __init__(self, db: AsyncPGDatabase, *, cache_ttl_sec: int = 60) -> None:
        self._db = db
        self._cache_ttl_sec = max(0, int(cache_ttl_sec))
        self._cached_at = 0.0
        self._cached_snapshot: List[Dict[str, object]] = []

    async def list_stock_snapshot(self) -> List[Dict[str, object]]:
        if self._cache_ttl_sec > 0 and self._cached_snapshot:
            if (time.monotonic() - self._cached_at) < self._cache_ttl_sec:
                return list(self._cached_snapshot)

        rows = await self._db.fetch(
            """
            SELECT ii.name AS ingredient_name,
                   ii.sku AS barcode,
                   SUM(il.quantity_available) AS quantity,
                   ii.unit AS unit
            FROM inventory_item ii
            JOIN inventory_lot il ON il.item_id = ii.item_id
            WHERE ii.is_active = true AND il.quantity_available > 0
            GROUP BY ii.name, ii.sku, ii.unit
            ORDER BY ii.name
            """,
        )
        snapshot = [dict(row) for row in rows]
        self._cached_snapshot = list(snapshot)
        self._cached_at = time.monotonic()
        return list(snapshot)

    def invalidate_cache(self) -> None:
        self._cached_snapshot = []
        self._cached_at = 0.0
