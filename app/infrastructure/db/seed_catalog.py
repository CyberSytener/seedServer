"""Store inventory catalog seeding and dev defaults.

Extracted from ``app.main`` to reduce the god-file footprint.
All functions are module-level (no closure dependencies).
A ``get_neoeats_db`` callable is accepted to break the import cycle.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Type alias for the DB factory
# ---------------------------------------------------------------------------

GetNeoeatsDB = Callable[[Any], Awaitable[Any]]  # (app) -> AsyncPGDatabase


# ---------------------------------------------------------------------------
# Dev inventory
# ---------------------------------------------------------------------------

async def seed_dev_inventory(
    app: Any,
    user_id: str,
    *,
    get_neoeats_db: GetNeoeatsDB,
) -> None:
    """Seed a small realistic pantry for opt-in local development."""
    try:
        neoeats_db = await get_neoeats_db(app)
        existing = await neoeats_db.fetchval(
            "SELECT COUNT(*) FROM storage_item WHERE (metadata->>'user_id') = $1",
            user_id,
        )
        if int(existing or 0) > 0:
            return

        defaults = [
            ("Milk", 1.0, "l", 5),
            ("Eggs", 6.0, "pcs", 10),
            ("Tomatoes", 4.0, "pcs", 4),
        ]
        async with neoeats_db.transaction() as conn:
            for name, quantity, unit, days in defaults:
                base_date = datetime.now(timezone.utc).date()
                try:
                    days_int = int(days)
                except Exception:
                    days_int = 0
                expires_at = base_date + timedelta(days=days_int)
                await conn.execute(
                    """
                    INSERT INTO storage_item (storage_id, name, quantity, unit, expires_at, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    str(uuid.uuid4()),
                    name,
                    quantity,
                    unit,
                    expires_at,
                    json.dumps({"user_id": user_id, "seeded": True}, ensure_ascii=False),
                )
    except Exception as exc:
        logging.warning("Dev inventory seed skipped for user %s: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Store catalog
# ---------------------------------------------------------------------------

CATALOG_ITEMS: list[tuple[str, str, str, str]] = [
    ("MILK-1L", "Milk", "dairy", "L"),
    ("EGGS-12", "Eggs", "dairy", "pcs"),
    ("PASTA-500G", "Pasta", "dry", "g"),
    ("TOMATO-1KG", "Tomato", "produce", "kg"),
    ("CHICKEN-BRST", "Chicken Breast", "protein", "kg"),
    ("BASIL-FRESH", "Basil", "herbs", "pcs"),
    ("GARLIC-BULB", "Garlic", "produce", "pcs"),
    ("ONION-YELLOW", "Onion", "produce", "kg"),
    ("CARROT-1KG", "Carrot", "produce", "kg"),
    ("POTATO-2KG", "Potato", "produce", "kg"),
    ("RICE-1KG", "Rice", "dry", "kg"),
    ("BUTTER-250G", "Butter", "dairy", "g"),
    ("CREAM-300ML", "Cream", "dairy", "ml"),
    ("CHEESE-CHED", "Cheddar Cheese", "dairy", "g"),
    ("YOGURT-PLAIN", "Yogurt", "dairy", "g"),
    ("BREAD-RYE", "Rye Bread", "bakery", "pcs"),
    ("BREAD-WHITE", "White Bread", "bakery", "pcs"),
    ("FLOUR-1KG", "Flour", "dry", "kg"),
    ("SUGAR-1KG", "Sugar", "dry", "kg"),
    ("SALT-500G", "Salt", "dry", "g"),
    ("PEPPER-BLK", "Black Pepper", "spices", "g"),
    ("OLIVE-OIL", "Olive Oil", "oil", "ml"),
    ("SOY-SAUCE", "Soy Sauce", "sauces", "ml"),
    ("VINEGAR-WHT", "White Vinegar", "sauces", "ml"),
    ("TACO-SHELL", "Taco Shells", "dry", "pcs"),
    ("BEANS-KIDNY", "Kidney Beans", "canned", "pcs"),
    ("CORN-SWEET", "Sweet Corn", "canned", "pcs"),
    ("MUSHROOM-500", "Mushrooms", "produce", "g"),
    ("SPINACH-200", "Spinach", "produce", "g"),
    ("LETTUCE-HEAD", "Lettuce", "produce", "pcs"),
    ("CUCUMBER-1", "Cucumber", "produce", "pcs"),
    ("PAPRIKA-RED", "Red Bell Pepper", "produce", "pcs"),
    ("CHILI-RED", "Red Chili", "produce", "pcs"),
    ("GINGER-ROOT", "Ginger", "produce", "g"),
    ("LEMON-1", "Lemon", "produce", "pcs"),
    ("LIME-1", "Lime", "produce", "pcs"),
    ("APPLE-1KG", "Apple", "produce", "kg"),
    ("BANANA-1KG", "Banana", "produce", "kg"),
    ("ORANGE-1KG", "Orange", "produce", "kg"),
    ("BEEF-MINCE", "Ground Beef", "protein", "kg"),
    ("SALMON-FIL", "Salmon Fillet", "protein", "kg"),
    ("TUNA-CAN", "Tuna", "canned", "pcs"),
    ("BACON-200", "Bacon", "protein", "g"),
    ("HAM-200", "Ham", "protein", "g"),
    ("NOODLES-400", "Noodles", "dry", "g"),
    ("OATS-1KG", "Oats", "dry", "kg"),
    ("HONEY-350", "Honey", "sauces", "g"),
    ("TOMATO-PASTE", "Tomato Paste", "sauces", "g"),
    ("COCONUT-MLK", "Coconut Milk", "canned", "ml"),
    ("PARMESAN-200", "Parmesan", "dairy", "g"),
]


async def seed_store_inventory_catalog(
    app: Any,
    *,
    get_neoeats_db: GetNeoeatsDB,
) -> None:
    """Create inventory tables and seed the starter store catalog."""
    neoeats_db = await get_neoeats_db(app)
    await neoeats_db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_item (
            item_id uuid PRIMARY KEY,
            sku text UNIQUE NOT NULL,
            name text NOT NULL,
            category text,
            unit text,
            last_price_paid numeric,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )
    await neoeats_db.execute(
        "ALTER TABLE inventory_item ADD COLUMN IF NOT EXISTS last_price_paid numeric"
    )
    await neoeats_db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_lot (
            lot_id uuid PRIMARY KEY,
            item_id uuid NOT NULL REFERENCES inventory_item(item_id),
            expires_at date,
            quantity_total numeric NOT NULL DEFAULT 0,
            quantity_available numeric NOT NULL DEFAULT 0,
            location_id uuid,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    current = await neoeats_db.fetchval("SELECT COUNT(*) FROM inventory_item WHERE is_active = true")
    if int(current or 0) > 0:
        return

    async with neoeats_db.transaction() as conn:
        for sku, name, category, unit in CATALOG_ITEMS:
            exists = await conn.fetchrow("SELECT item_id FROM inventory_item WHERE sku = $1", sku)
            if exists:
                item_id = exists["item_id"]
            else:
                item_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO inventory_item (item_id, sku, name, category, unit, is_active)
                    VALUES ($1, $2, $3, $4, $5, true)
                    """,
                    item_id,
                    sku,
                    name,
                    category,
                    unit,
                )

            lot_exists = await conn.fetchrow("SELECT lot_id FROM inventory_lot WHERE item_id = $1 LIMIT 1", item_id)
            if lot_exists:
                continue

            await conn.execute(
                """
                INSERT INTO inventory_lot (lot_id, item_id, expires_at, quantity_total, quantity_available, location_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                str(uuid.uuid4()),
                item_id,
                datetime.now(timezone.utc).date() + timedelta(days=60),
                50,
                50,
                None,
            )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def is_expected_catalog_seed_skip(exc: Exception) -> bool:
    """Return True if *exc* signals that Postgres is simply not configured."""
    if not isinstance(exc, HTTPException):
        return False
    detail = getattr(exc, "detail", None)
    if not isinstance(detail, dict):
        return False
    return str(detail.get("error") or "").strip() == "postgres_not_configured"


def log_catalog_seed_failure(exc: Exception) -> None:
    """Log a catalog seed failure, at INFO if Postgres is not configured."""
    if is_expected_catalog_seed_skip(exc):
        logging.info("Postgres not configured; skipping catalog seed to DB.")
        return
    logging.warning("Store catalog seed failed: %s", exc)
