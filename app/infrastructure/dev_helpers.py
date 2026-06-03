"""Dev-mode helpers — extracted from app.main."""

from __future__ import annotations

import hashlib
import json
import os

from fastapi import FastAPI

from app.infrastructure.db.sqlite import DB
from app.infrastructure.db.seed_catalog import (
    seed_dev_inventory as _seed_dev_inventory_impl,
    seed_store_inventory_catalog as _seed_store_inventory_catalog_impl,
)
from app.infrastructure.db.neoeats_db import get_neoeats_db


def dev_password_hash(username: str, password: str) -> str:
    """Create a deterministic password hash for dev users."""
    pepper = os.getenv("SEED_API_KEY_PEPPER", "")
    raw = f"seed-dev-auth|{username}|{password}|{pepper}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def seed_dev_users(db: DB) -> None:
    """Seed numbered dev users 1-10 into the database."""
    with db.transaction() as conn:
        for index in range(1, 11):
            username = str(index)
            password_hash = dev_password_hash(username, username)
            payload = {
                "dev_user": True,
                "username": username,
                "password_hash": password_hash,
                "role": "developer",
                "scopes": [
                    "runs:read",
                    "runs:write",
                    "modules:read",
                    "modules:write",
                    "flows:*",
                    "providers:read",
                    "providers:use:real",
                ],
            }
            conn.execute(
                """
                INSERT INTO users(id, email, meta_json, is_admin, is_banned)
                VALUES(?, ?, ?, 0, 0)
                ON CONFLICT(id) DO UPDATE SET
                    email=excluded.email,
                    meta_json=excluded.meta_json,
                    is_banned=0
                """,
                (username, f"dev{username}@localhost", json.dumps(payload, ensure_ascii=False)),
            )


async def seed_dev_inventory(app: FastAPI, user_id: str) -> None:
    """Seed dev inventory items for a specific user."""
    await _seed_dev_inventory_impl(app, user_id, get_neoeats_db=get_neoeats_db)


async def seed_store_inventory_catalog(app: FastAPI) -> None:
    """Seed the store inventory catalog."""
    await _seed_store_inventory_catalog_impl(app, get_neoeats_db=get_neoeats_db)
