from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.infrastructure.db.postgres import AsyncPGDatabase


class HotOfferStore:
    def __init__(self, db: AsyncPGDatabase) -> None:
        self._db = db

    async def ingest_sales_stats(self, stats: Iterable[Dict[str, Any]]) -> int:
        rows = [dict(item) for item in stats]
        if not rows:
            return 0

        count = 0
        for row in rows:
            await self._db.execute(
                """
                INSERT INTO sales_stats (
                    stat_id,
                    location_id,
                    day_of_week,
                    hour_of_day,
                    category,
                    recipe_name,
                    avg_units_sold
                )
                VALUES (
                    gen_random_uuid(),
                    $1, $2, $3, $4, $5, $6
                )
                """,
                row.get("location_id"),
                int(row.get("day_of_week") or 0),
                int(row.get("hour_of_day") or 0),
                row.get("category"),
                row.get("recipe_name"),
                float(row.get("avg_units_sold") or 0.0),
            )
            count += 1
        return count

    async def get_pending_offer(self, offer_id: str) -> Optional[Dict[str, Any]]:
        row = await self._db.fetchrow(
            """
            SELECT offer_id, status, offer_payload, validation_scores, created_at, updated_at
            FROM pending_offers
            WHERE offer_id = $1
            """,
            offer_id,
        )
        return dict(row) if row else None

    async def update_pending_offer(
        self,
        offer_id: str,
        *,
        status: str,
        validation_scores: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> None:
        scores_payload = validation_scores or {}
        await self._db.execute(
            """
            UPDATE pending_offers
            SET status = $2,
                validation_scores = $3,
                updated_at = now()
            WHERE offer_id = $1
            """,
            offer_id,
            status,
            scores_payload,
        )

        if status == "approved":
            row = await self.get_pending_offer(offer_id)
            if row:
                await self._db.execute(
                    """
                    INSERT INTO hot_offer_history (offer_id, status, offer_payload, notes)
                    VALUES ($1, 'active', $2, $3)
                    """,
                    offer_id,
                    row.get("offer_payload"),
                    notes,
                )
