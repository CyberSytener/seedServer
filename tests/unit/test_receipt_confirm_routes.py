from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.receipts import build_receipts_router
from app.core.auth import issue_key_for_user
from app.infrastructure.db.sqlite import DB


class _FakeTransaction:
    def __init__(self, db: "_FakeReceiptDB") -> None:
        self.db = db

    async def __aenter__(self) -> "_FakeReceiptDB":
        return self.db

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeReceiptDB:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.receipts: list[dict[str, Any]] = []
        self.storage_items: list[dict[str, Any]] = []
        self.memory_events: list[dict[str, Any]] = []

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "FROM inventory_item" in query:
            return None
        if "FROM storage_item" in query:
            return None
        raise AssertionError(f"Unexpected fetchrow query: {query}")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "FROM receipts" in query:
            user_id = str(args[0])
            return [row for row in self.receipts if row["user_id"] == user_id]
        raise AssertionError(f"Unexpected fetch query: {query}")

    async def execute(self, query: str, *args: Any) -> None:
        self.executed.append((query, args))
        if "INSERT INTO receipts" in query:
            self.receipts.append(
                {
                    "id": args[0],
                    "user_id": args[1],
                    "image_url": args[2],
                    "total_amount": args[3],
                    "currency": args[4],
                    "merchant_name": args[5],
                    "scanned_at": args[6],
                    "created_at": datetime.now(timezone.utc),
                }
            )
        elif "INSERT INTO storage_item" in query:
            self.storage_items.append(
                {
                    "storage_id": args[0],
                    "name": args[1],
                    "quantity": args[2],
                    "unit": args[3],
                    "metadata": json.loads(args[5]),
                    "price_paid": args[6],
                    "receipt_id": args[7],
                }
            )
        elif "INSERT INTO neoeats_user_memory_events" in query:
            self.memory_events.append(
                {
                    "id": args[0],
                    "user_id": args[1],
                    "event_type": args[2],
                    "source": args[3],
                    "subject": args[4],
                    "text": args[5],
                    "payload": json.loads(args[8]),
                }
            )


def _build_client(tmp_path) -> tuple[TestClient, DB, str, _FakeReceiptDB]:
    db = DB(str(tmp_path / "receipt_confirm.db"))
    db.init_schema()
    db.execute(
        "INSERT INTO users(id, email, meta_json, is_admin, is_banned) VALUES(?,?,?,?,?)",
        ("receipt_user", "receipt@example.com", "{}", 0, 0),
    )
    token = issue_key_for_user(db, "receipt_user")

    fake_neoeats_db = _FakeReceiptDB()

    async def _get_neoeats_db(_app: FastAPI) -> _FakeReceiptDB:
        return fake_neoeats_db

    app = FastAPI()
    app.state.seed = SimpleNamespace(db=db)
    app.include_router(build_receipts_router(_get_neoeats_db))
    return TestClient(app), db, token, fake_neoeats_db


def test_receipt_confirm_persists_history_storage_and_memory(tmp_path) -> None:
    client, db, token, fake_neoeats_db = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/vision/receipt/confirm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "merchant_name": "Neo Market",
                "total_amount": 42.5,
                "currency": "NOK",
                "scanned_at": "2026-05-19T12:00:00Z",
                "items": [
                    {
                        "name": "Salmon Fillet",
                        "canonical_name": "salmon",
                        "original_name": "SALMON FILLET",
                        "qty": 2,
                        "unit": "pcs",
                        "price": 42.5,
                        "category": "seafood",
                        "match_id": "catalog-salmon",
                        "action": "CREATE",
                    }
                ],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["items_saved"] == 1
        assert payload["store_prices_updated"] == 1

        history = client.get(
            "/api/v1/vision/receipt/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert history.status_code == 200
        assert history.json()[0]["merchant_name"] == "Neo Market"
        assert history.json()[0]["total_amount"] == 42.5

        assert fake_neoeats_db.storage_items[0]["metadata"]["source"] == "receipt_confirm"
        assert fake_neoeats_db.storage_items[0]["metadata"]["receipt_id"] == payload["receipt_id"]
        assert fake_neoeats_db.memory_events[0]["event_type"] == "receipt_item_confirmed"
        assert fake_neoeats_db.memory_events[0]["subject"] == "salmon"
        assert fake_neoeats_db.memory_events[0]["payload"]["receipt_id"] == payload["receipt_id"]
    finally:
        db.close()
