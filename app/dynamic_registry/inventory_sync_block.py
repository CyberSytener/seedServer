from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.blocks import BlockBase


class InventorySyncBlock(BlockBase):
    """Sync and check inventory against the stock_levels table."""

    NAME = "inventory_sync"
    DESCRIPTION = "Sync inventory updates and check ingredient availability against stock_levels."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "sync or check"},
            "ingredient_name": {"type": "string"},
            "barcode": {"type": "string"},
            "quantity": {"type": "number"},
            "unit": {"type": "string"},
            "image_metadata": {"type": "object"},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ingredient_name": {"type": "string"},
                        "name": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                    },
                },
            },
        },
        "required": [],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "updated": {"type": "boolean"},
            "ingredient_name": {"type": "string"},
            "barcode": {"type": "string"},
            "quantity": {"type": "number"},
            "unit": {"type": "string"},
            "is_available": {"type": "boolean"},
            "missing_ingredients": {"type": "array", "items": {"type": "object"}},
            "available_ingredients": {"type": "array", "items": {"type": "object"}},
            "error": {"type": "string"},
        },
        "required": ["status"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        action = str(inputs.get("action") or "sync").strip().lower()
        if action == "check":
            ingredients = inputs.get("ingredients") or []
            return await self.check_availability(ingredients)

        return await self._sync_stock(inputs)

    async def check_availability(self, ingredients: List[Any]) -> Dict[str, Any]:
        db = self._resolve_db()
        normalized = self._normalize_ingredients(ingredients)
        if not normalized:
            return {"status": "error", "error": "no_ingredients"}

        names = [entry["ingredient_name"] for entry in normalized]
        rows = await db.fetch(
            """
            SELECT ingredient_name, quantity, unit, barcode
            FROM stock_levels
            WHERE ingredient_name = ANY($1)
            """,
            names,
        )
        available_map = {
            row["ingredient_name"]: {
                "ingredient_name": row["ingredient_name"],
                "quantity": row["quantity"],
                "unit": row["unit"],
                "barcode": row["barcode"],
            }
            for row in rows
        }

        missing: List[Dict[str, Any]] = []
        available: List[Dict[str, Any]] = []
        for entry in normalized:
            name = entry["ingredient_name"]
            required_qty = entry.get("quantity")
            stocked = available_map.get(name)
            if not stocked:
                missing.append({"ingredient_name": name, "required": required_qty, "available": 0})
                continue
            stocked_qty = stocked.get("quantity")
            if required_qty is not None and _safe_float(stocked_qty) < _safe_float(required_qty):
                missing.append(
                    {
                        "ingredient_name": name,
                        "required": required_qty,
                        "available": stocked_qty,
                        "unit": stocked.get("unit"),
                    }
                )
                continue
            available.append({"ingredient_name": name, "available": stocked_qty, "unit": stocked.get("unit")})

        return {
            "status": "succeeded",
            "is_available": len(missing) == 0,
            "missing_ingredients": missing,
            "available_ingredients": available,
        }

    async def _sync_stock(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = self._resolve_db()
        ingredient_name = self._resolve_ingredient_name(inputs)
        barcode = inputs.get("barcode")
        quantity = inputs.get("quantity")
        unit = inputs.get("unit") or None
        metadata = inputs.get("image_metadata") or {}

        if not ingredient_name and barcode:
            ingredient_name = await self._resolve_name_by_barcode(db, barcode)
        if not ingredient_name:
            return {"status": "error", "error": "missing ingredient_name"}

        quantity = _safe_float(quantity)
        metadata_payload = metadata if metadata else None

        update_result = await db.execute(
            """
            UPDATE stock_levels
            SET barcode = $2,
                quantity = $3,
                unit = $4,
                metadata = $5,
                updated_at = NOW()
            WHERE ingredient_name = $1
            """,
            ingredient_name,
            barcode,
            quantity,
            unit,
            metadata_payload,
        )

        updated = _updated_rows(update_result)
        if updated == 0:
            await db.execute(
                """
                INSERT INTO stock_levels (ingredient_name, barcode, quantity, unit, metadata, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                ingredient_name,
                barcode,
                quantity,
                unit,
                metadata_payload,
            )

        return {
            "status": "succeeded",
            "updated": True,
            "ingredient_name": ingredient_name,
            "barcode": barcode,
            "quantity": quantity,
            "unit": unit,
        }

    @staticmethod
    def _normalize_ingredients(ingredients: List[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in ingredients:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    normalized.append({"ingredient_name": name})
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("ingredient_name") or item.get("name")
            if not name:
                continue
            normalized.append(
                {
                    "ingredient_name": str(name).strip(),
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit"),
                }
            )
        return normalized

    @staticmethod
    def _resolve_ingredient_name(inputs: Dict[str, Any]) -> Optional[str]:
        name = inputs.get("ingredient_name")
        if name:
            return str(name).strip()
        meta = inputs.get("image_metadata") or {}
        for key in ("ingredient_name", "label", "name"):
            value = meta.get(key)
            if value:
                return str(value).strip()
        return None

    async def _resolve_name_by_barcode(self, db: Any, barcode: str) -> Optional[str]:
        row = await db.fetchrow(
            """
            SELECT ingredient_name
            FROM stock_levels
            WHERE barcode = $1
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            barcode,
        )
        if row:
            return row.get("ingredient_name") if isinstance(row, dict) else row["ingredient_name"]
        return None

    def _resolve_db(self) -> Any:
        engine = self._engine
        db = getattr(engine, "db", None) if engine else None
        if db is None:
            raise RuntimeError("InventorySyncBlock requires engine.db")
        return db


def _updated_rows(result: Any) -> int:
    if result is None:
        return 0
    if isinstance(result, str):
        parts = result.strip().split()
        if len(parts) == 2 and parts[0].upper() in {"UPDATE", "INSERT"}:
            try:
                return int(parts[1])
            except ValueError:
                return 0
    return 0


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
