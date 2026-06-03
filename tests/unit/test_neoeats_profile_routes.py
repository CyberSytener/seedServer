from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.neoeats_profile_routes import build_neoeats_profile_router
from app.core.auth import issue_key_for_user
from app.infrastructure.db.sqlite import DB


class _FakeNeoEatsDB:
    def __init__(self) -> None:
        self.inventory_rows = [
            {
                "name": "Milk",
                "quantity": 1,
                "unit": "l",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
                "metadata": {"user_id": "real_user", "category": "dairy"},
            },
            {
                "name": "Oats",
                "quantity": 500,
                "unit": "g",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=9),
                "metadata": {"user_id": "real_user", "category": "grain"},
            },
        ]
        self.order_rows = [
            {
                "state": "PAYMENT_PENDING",
                "payload": {"user_id": "real_user", "order_id": "abc123456789"},
                "result": {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        ]
        self.receipt_row = {
            "count": 1,
            "total_spend": 59.0,
            "currency": "NOK",
            "last_uploaded_at": datetime.now(timezone.utc),
        }
        self.store_rows = [
            {
                "item_id": "cat-noodles",
                "sku": "NOD-001",
                "name": "Noodles",
                "category": "pantry",
                "unit": "pack",
                "last_price_paid": 11.5,
                "quantity_available": 6,
            },
            {
                "item_id": "cat-eggs",
                "sku": "EGG-006",
                "name": "Eggs",
                "category": "dairy",
                "unit": "pcs",
                "last_price_paid": 4.0,
                "quantity_available": 12,
            },
        ]
        self.memory_rows = [
            {
                "id": "mem-1",
                "user_id": "real_user",
                "event_type": "receipt_item_confirmed",
                "source": "receipt_confirm",
                "subject": "salmon",
                "text": "User confirmed receipt item: salmon category seafood",
                "event_hash": "hash-salmon",
                "confidence": 0.86,
                "payload": {"canonical_name": "salmon", "category": "seafood"},
                "embedding_status": "pending",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
            {
                "id": "mem-2",
                "user_id": "other_user",
                "event_type": "receipt_item_confirmed",
                "source": "receipt_confirm",
                "subject": "milk",
                "text": "Other user confirmed milk",
                "event_hash": "hash-milk",
                "confidence": 0.99,
                "payload": {"canonical_name": "milk"},
                "embedding_status": "pending",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ]
        self.deleted_memory_for: str | None = None

    async def fetch(self, query: str, *_args: Any) -> list[dict[str, Any]]:
        user_id = str(_args[0]) if _args else ""
        if "FROM storage_item" in query:
            return self.inventory_rows
        if "FROM inventory_item" in query:
            return self.store_rows
        if "FROM sagas" in query:
            return self.order_rows
        if "FROM neoeats_user_memory_events" in query and "GROUP BY user_id" in query:
            statuses = {str(status) for status in (_args[0] if _args else [])}
            limit = int(_args[1]) if len(_args) > 1 else 25
            grouped: dict[str, dict[str, Any]] = {}
            for row in self.memory_rows:
                status = str(row.get("embedding_status") or "pending")
                text = str(row.get("text") or "").strip()
                if status not in statuses or not text:
                    continue
                entry = grouped.setdefault(
                    row["user_id"],
                    {"user_id": row["user_id"], "candidate_count": 0, "last_updated_at": row.get("updated_at")},
                )
                entry["candidate_count"] += 1
                if row.get("updated_at") and (entry.get("last_updated_at") is None or row["updated_at"] > entry["last_updated_at"]):
                    entry["last_updated_at"] = row["updated_at"]
            return list(grouped.values())[:limit]
        if "FROM neoeats_user_memory_events" in query and "GROUP BY event_type" in query:
            counts: dict[str, int] = {}
            for row in self.memory_rows:
                if row["user_id"] == user_id:
                    counts[row["event_type"]] = counts.get(row["event_type"], 0) + 1
            return [{"event_type": key, "count": count} for key, count in counts.items()]
        if (
            "FROM neoeats_user_memory_events" in query
            and "GROUP BY embedding_status" in query
            and "COUNT(DISTINCT user_id)" in query
        ):
            counts: dict[str, int] = {}
            users: dict[str, set[str]] = {}
            for row in self.memory_rows:
                status = str(row.get("embedding_status") or "pending")
                counts[status] = counts.get(status, 0) + 1
                users.setdefault(status, set()).add(row["user_id"])
            return [
                {"embedding_status": key, "count": count, "user_count": len(users.get(key, set()))}
                for key, count in counts.items()
            ]
        if "FROM neoeats_user_memory_events" in query and "GROUP BY embedding_status" in query:
            counts: dict[str, int] = {}
            for row in self.memory_rows:
                if row["user_id"] == user_id:
                    status = str(row.get("embedding_status") or "pending")
                    counts[status] = counts.get(status, 0) + 1
            return [{"embedding_status": key, "count": count} for key, count in counts.items()]
        if "FROM neoeats_user_memory_events" in query and "event_hash" in query:
            statuses = {str(status) for status in (_args[1] if len(_args) > 1 else [])}
            limit = int(_args[2]) if len(_args) > 2 else 50
            return [
                row
                for row in self.memory_rows
                if row["user_id"] == user_id and str(row.get("embedding_status") or "pending") in statuses
            ][:limit]
        if "FROM neoeats_user_memory_events" in query:
            return [row for row in self.memory_rows if row["user_id"] == user_id]
        raise AssertionError(f"Unexpected fetch query: {query}")

    async def fetchrow(self, query: str, *_args: Any) -> dict[str, Any]:
        user_id = str(_args[0]) if _args else ""
        if "FROM neoeats_user_memory_events" in query and "COUNT(DISTINCT user_id)" in query and "WHERE COALESCE" in query:
            statuses = {str(status) for status in (_args[0] if _args else [])}
            rows = [
                row
                for row in self.memory_rows
                if str(row.get("embedding_status") or "pending") in statuses
                and str(row.get("text") or "").strip()
            ]
            return {"count": len(rows), "user_count": len({row["user_id"] for row in rows})}
        if "FROM neoeats_user_memory_events" in query and "COUNT(DISTINCT user_id)" in query:
            last_updated = max((row["updated_at"] for row in self.memory_rows), default=None)
            return {
                "count": len(self.memory_rows),
                "user_count": len({row["user_id"] for row in self.memory_rows}),
                "last_updated_at": last_updated,
            }
        if "FROM receipts" in query:
            return self.receipt_row
        if "FROM neoeats_user_memory_events" in query:
            rows = [row for row in self.memory_rows if row["user_id"] == user_id]
            last_updated = max((row["updated_at"] for row in rows), default=None)
            return {"count": len(rows), "last_updated_at": last_updated}
        raise AssertionError(f"Unexpected fetchrow query: {query}")

    async def execute(self, query: str, *_args: Any) -> None:
        if "INSERT INTO neoeats_user_memory_events" in query:
            event_id, user_id, event_type, source, subject, text, event_hash, confidence, payload_json = _args
            self.memory_rows.append(
                {
                    "id": str(event_id),
                    "user_id": str(user_id),
                    "event_type": str(event_type),
                    "source": str(source),
                    "subject": subject,
                    "text": str(text),
                    "event_hash": str(event_hash),
                    "confidence": float(confidence),
                    "payload": json.loads(str(payload_json)),
                    "embedding_status": "pending",
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            return
        if "SET embedding = " in query or "SET embedding =" in query:
            _vector, model, user_id, event_type, event_hash = _args
            for row in self.memory_rows:
                if (
                    row["user_id"] == str(user_id)
                    and row["event_type"] == str(event_type)
                    and row.get("event_hash") == str(event_hash)
                ):
                    row["embedding_status"] = "ready"
                    row["embedding_model"] = str(model)
            return
        if "SET embedding_status = " in query or "SET embedding_status =" in query:
            status, model, user_id, event_type, event_hash = _args
            for row in self.memory_rows:
                if (
                    row["user_id"] == str(user_id)
                    and row["event_type"] == str(event_type)
                    and row.get("event_hash") == str(event_hash)
                ):
                    row["embedding_status"] = str(status)
                    row["embedding_model"] = str(model)
            return
        if "DELETE FROM neoeats_user_memory_events" in query:
            user_id = str(_args[0]) if _args else ""
            self.deleted_memory_for = user_id
            self.memory_rows = [row for row in self.memory_rows if row["user_id"] != user_id]
            return
        raise AssertionError(f"Unexpected execute query: {query}")


class _FakeEmbeddingEngine:
    embedding_available = True
    embedding_model = "stub-embedding"

    async def embed_text(self, _text: str, **_kwargs: Any) -> list[float]:
        return [0.1, 0.2, 0.3]


def _build_client(tmp_path, *, llm_engine: Any | None = None) -> tuple[TestClient, DB, str]:
    db = DB(str(tmp_path / "neoeats_profile.db"))
    db.init_schema()
    meta = {
        "username": "real_user",
        "neoeats_memory": {
            "signals": {
                "goals": ["high_protein"],
                "diet_tags": ["vegan"],
                "cuisines": ["norwegian"],
                "likes": ["spicy ramen"],
            },
            "facts": [
                {
                    "id": "goal:protein",
                    "kind": "goal",
                    "value": "high_protein",
                    "confidence": 0.8,
                    "updated_at": "2026-05-06T00:00:00+00:00",
                }
            ],
        },
    }
    db.execute(
        "INSERT INTO users(id, email, meta_json, is_admin, is_banned) VALUES(?,?,?,?,?)",
        ("real_user", "real@example.com", json.dumps(meta), 0, 0),
    )
    token = issue_key_for_user(db, "real_user")

    fake_neoeats_db = _FakeNeoEatsDB()

    async def _get_neoeats_db(_app: FastAPI) -> _FakeNeoEatsDB:
        return fake_neoeats_db

    app = FastAPI()
    if llm_engine is not None:
        app.state.llm_engine = llm_engine
    app.include_router(build_neoeats_profile_router(db=db, get_neoeats_db=_get_neoeats_db))
    return TestClient(app), db, token


def test_profile_is_derived_from_user_meta_memory_and_real_events(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.get(
            "/api/v1/neoeats/profile",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == "real_user"
        assert payload["username"] == "real_user"
        assert payload["email"] == "real@example.com"
        assert payload["payment_methods"] == []
        assert payload["preferences"]["protein_focus"] == 75
        assert payload["preferences"]["vegan_preference"] == 85
        assert payload["preferences"]["local_ingredients"] == 70
        assert "vegan" in payload["dietary_profile"]["diet_tags"]
        assert "high_protein" in payload["dietary_profile"]["goals"]
        assert "norwegian" in payload["dietary_profile"]["favorite_cuisines"]
        assert payload["sustainability"]["eco_points"] > 0
        assert payload["data_sources"]["payments"] == "not_connected"
        assert payload["memory_controls"]["learning_enabled"] is True
        assert payload["memory_controls"]["rag_retrieval_enabled"] is True
        assert payload["ai_insights"][0]["id"] == "goal:protein"
        assert "high protein" in payload["ai_insights"][0]["text"]
    finally:
        db.close()


def test_memory_endpoint_returns_controls_stats_and_user_scoped_events(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.get(
            "/api/v1/neoeats/memory?query=salmon&limit=5",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["memory_controls"]["learning_enabled"] is True
        assert payload["memory_stats"]["event_count"] == 1
        assert payload["memory_stats"]["by_event_type"] == {"receipt_item_confirmed": 1}
        events = payload["rag_memory"]["retrieved_events"]
        assert [event["id"] for event in events] == ["mem-1"]
        assert payload["rag_memory"]["retrieval"]["mode"] == "lexical_event_rag"
        assert "confirmed_user_event" in events[0]["match_reasons"]
    finally:
        db.close()


def test_memory_settings_disable_rag_retrieval_without_deleting_events(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.patch(
            "/api/v1/neoeats/memory/settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"rag_retrieval_enabled": False, "sources": {"chat": False}},
        )

        assert response.status_code == 200
        controls = response.json()["memory_controls"]
        assert controls["rag_retrieval_enabled"] is False
        assert controls["sources"]["chat"] is False

        follow_up = client.get(
            "/api/v1/neoeats/memory?query=salmon",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow_up.status_code == 200
        payload = follow_up.json()
        assert payload["memory_stats"]["event_count"] == 1
        assert payload["rag_memory"]["retrieved_events"] == []
        assert payload["data_sources"]["rag_retrieval_enabled"] is False
    finally:
        db.close()


def test_memory_export_and_clear_are_user_scoped(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        exported = client.get(
            "/api/v1/neoeats/memory/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert exported.status_code == 200
        assert exported.json()["schema_version"] == "neoeats_memory_export_v1"
        assert [event["id"] for event in exported.json()["rag_events"]] == ["mem-1"]

        cleared = client.delete(
            "/api/v1/neoeats/memory",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cleared.status_code == 200
        assert cleared.json()["rag_events_cleared"] is True
        assert cleared.json()["structured_memory"]["facts"] == []

        follow_up = client.get(
            "/api/v1/neoeats/memory?query=salmon",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow_up.status_code == 200
        assert follow_up.json()["memory_stats"]["event_count"] == 0
        assert follow_up.json()["rag_memory"]["retrieved_events"] == []
    finally:
        db.close()


def test_memory_embedding_backfill_reports_unavailable_provider(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/neoeats/memory/embeddings/backfill?limit=5",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["reason"] == "embedding_provider_unavailable"
        assert payload["backfill"]["attempted"] == 0
        assert payload["backfill"]["skipped"] == 5
    finally:
        db.close()


def test_memory_embedding_backfill_updates_current_user_events(tmp_path) -> None:
    client, db, token = _build_client(tmp_path, llm_engine=_FakeEmbeddingEngine())
    try:
        response = client.post(
            "/api/v1/neoeats/memory/embeddings/backfill?limit=5",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["backfill"]["provider_available"] is True
        assert payload["backfill"]["attempted"] == 1
        assert payload["backfill"]["ready"] == 1
        assert payload["backfill"]["event_ids"] == ["mem-1"]
        assert payload["memory_stats"]["by_embedding_status"] == {"ready": 1}
        assert payload["memory_stats"]["embedding_coverage_pct"] == 100.0
    finally:
        db.close()


def test_admin_embedding_status_requires_admin_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SEED_ADMIN_KEY", "neoeats_admin")
    client, db, _token = _build_client(tmp_path)
    try:
        denied = client.get("/api/v1/neoeats/memory/embeddings/admin/status")
        assert denied.status_code == 401
        assert denied.json()["detail"] == "admin key required"

        response = client.get(
            "/api/v1/neoeats/memory/embeddings/admin/status",
            headers={"X-Admin-Key": "neoeats_admin"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["memory_embedding_stats"]["event_count"] == 2
        assert payload["memory_embedding_stats"]["backlog_event_count"] == 2
        assert payload["data_sources"]["rag_embedding_provider_available"] is False
    finally:
        db.close()


def test_admin_embedding_backfill_updates_multiple_users(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SEED_ADMIN_KEY", "neoeats_admin")
    client, db, _token = _build_client(tmp_path, llm_engine=_FakeEmbeddingEngine())
    try:
        response = client.post(
            "/api/v1/neoeats/memory/embeddings/admin/backfill?limit_per_user=1&max_users=5",
            headers={"X-Admin-Key": "neoeats_admin"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["backfill"]["provider_available"] is True
        assert payload["backfill"]["users_considered"] == 2
        assert payload["backfill"]["attempted"] == 2
        assert payload["backfill"]["ready"] == 2
        assert sorted(payload["backfill"]["event_ids"]) == ["mem-1", "mem-2"]
        assert payload["memory_embedding_stats"]["embedding_coverage_pct"] == 100.0
    finally:
        db.close()


def test_admin_embedding_backfill_dry_run_does_not_write(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SEED_ADMIN_KEY", "neoeats_admin")
    client, db, _token = _build_client(tmp_path, llm_engine=_FakeEmbeddingEngine())
    try:
        response = client.post(
            "/api/v1/neoeats/memory/embeddings/admin/backfill?dry_run=true&limit_per_user=1",
            headers={"X-Admin-Key": "neoeats_admin"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["backfill"]["reason"] == "dry_run"
        assert payload["backfill"]["attempted"] == 0
        assert payload["backfill"]["skipped"] == 2
        assert payload["memory_embedding_stats"]["embedding_coverage_pct"] == 0.0
    finally:
        db.close()


def test_recipe_feedback_records_user_scoped_memory_event(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/neoeats/recipes/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "recipe_id": "recipe-salmon-bowl",
                "recipe_name": "Salmon Bowl",
                "feedback": "accepted",
                "action": "saved",
                "ingredients": [{"name": "salmon", "status": "owned"}, {"name": "rice", "status": "missing"}],
                "missing_items": ["rice"],
                "available_items": ["salmon"],
                "reason": "User explicitly liked this recommendation.",
                "reason_code": "looks_good",
                "reason_tags": ["taste_fit", "positive_signal"],
                "rating": 5,
                "score": 91,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["memory_recorded"] is True
        assert payload["event_type"] == "recipe_feedback_accepted"

        memory = client.get(
            "/api/v1/neoeats/memory?query=salmon%20bowl",
            headers={"Authorization": f"Bearer {token}"},
        )
        events = memory.json()["rag_memory"]["retrieved_events"]
        assert any(event["event_type"] == "recipe_feedback_accepted" for event in events)
        feedback_events = [event for event in events if event["event_type"] == "recipe_feedback_accepted"]
        assert feedback_events[0]["payload"]["recipe_id"] == "recipe-salmon-bowl"
        assert feedback_events[0]["payload"]["feedback"] == "accepted"
        assert feedback_events[0]["payload"]["reason_code"] == "looks_good"
        assert feedback_events[0]["payload"]["reason_tags"] == ["taste_fit", "positive_signal"]
        assert feedback_events[0]["payload"]["rating"] == 5
    finally:
        db.close()


def test_recipe_feedback_respects_recipe_memory_source_toggle(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        settings = client.patch(
            "/api/v1/neoeats/memory/settings",
            headers={"Authorization": f"Bearer {token}"},
            json={"sources": {"recipe": False}},
        )
        assert settings.status_code == 200
        assert settings.json()["memory_controls"]["sources"]["recipe"] is False

        response = client.post(
            "/api/v1/neoeats/recipes/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "recipe_id": "recipe-nope",
                "recipe_name": "Nope Bowl",
                "feedback": "rejected",
                "action": "not_for_me",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["memory_recorded"] is False
        assert payload["reason"] == "recipe_memory_disabled"

        memory = client.get(
            "/api/v1/neoeats/memory?query=nope",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert all(event["subject"] != "Nope Bowl" for event in memory.json()["rag_memory"]["retrieved_events"])
    finally:
        db.close()


def test_launch_events_record_user_activation_signals(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        first_food = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "event_type": "first_food_added",
                "payload": {
                    "items_count": 3,
                    "method": "quick_add_scan",
                    "item_names": ["milk", "oats", "eggs"],
                    "debug_blob": {"nested": {"ignored_after_depth": "safe"}},
                },
            },
        )
        assert first_food.status_code == 200
        payload = first_food.json()
        assert payload["ok"] is True
        assert payload["event"]["event_type"] == "first_food_added"
        assert payload["summary"]["by_event_type"]["first_food_added"] == 1
        assert payload["summary"]["activated"] is False

        recommendation = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "recommendation_requested", "payload": {"pantry_count": 3}},
        )
        assert recommendation.status_code == 200
        assert recommendation.json()["summary"]["activated"] is True

        row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", ("real_user",))
        assert row is not None
        meta = json.loads(row["meta_json"])
        events = meta["neoeats_launch_events"]
        assert [event["event_type"] for event in events] == ["first_food_added", "recommendation_requested"]
        assert events[0]["payload"]["item_names"] == ["milk", "oats", "eggs"]

        follow_up = client.get(
            "/api/v1/neoeats/launch/events?limit=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow_up.status_code == 200
        assert [event["event_type"] for event in follow_up.json()["events"]] == ["recommendation_requested"]
        assert follow_up.json()["summary"]["activated"] is True
    finally:
        db.close()


def test_launch_events_normalize_first_food_server_side(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        first_food = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "food_added", "payload": {"items_count": 2}},
        )
        assert first_food.status_code == 200
        assert first_food.json()["event"]["event_type"] == "first_food_added"

        duplicate_first = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "first_food_added", "payload": {"items_count": 1}},
        )
        assert duplicate_first.status_code == 200
        assert duplicate_first.json()["event"]["event_type"] == "food_added"

        row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", ("real_user",))
        assert row is not None
        events = json.loads(row["meta_json"])["neoeats_launch_events"]
        assert [event["event_type"] for event in events] == ["first_food_added", "food_added"]
    finally:
        db.close()


def test_launch_events_track_recommendation_outcomes(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        food = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "food_added", "payload": {"items_count": 1}},
        )
        assert food.status_code == 200
        assert food.json()["summary"]["activated"] is False

        failed = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "recommendation_failed", "payload": {"status": 503}},
        )
        assert failed.status_code == 200
        assert failed.json()["summary"]["activated"] is False

        succeeded = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "recommendation_succeeded", "payload": {"recommendation_count": 2}},
        )
        assert succeeded.status_code == 200
        assert succeeded.json()["summary"]["activated"] is True

        row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", ("real_user",))
        assert row is not None
        events = json.loads(row["meta_json"])["neoeats_launch_events"]
        assert [event["event_type"] for event in events] == [
            "first_food_added",
            "recommendation_failed",
            "recommendation_succeeded",
        ]
    finally:
        db.close()


def test_missing_list_drafts_are_server_backed_and_record_launch_event(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source": "explore",
                "recipe_id": "ramen-1",
                "recipe_name": "Ramen Bowl",
                "missing_items": [
                    {"name": "noodles", "quantity": 2, "unit": "pack", "price": 12.5, "catalog_item_id": "cat-noodles"},
                    {"name": "miso", "price": 8},
                ],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        draft = payload["draft"]
        assert draft["source"] == "explore"
        assert draft["recipe_id"] == "ramen-1"
        assert draft["recipe_name"] == "Ramen Bowl"
        assert draft["item_count"] == 2
        assert draft["total_estimate"] == 33.0
        assert draft["missing_items"][0]["catalog_item_id"] == "cat-noodles"
        assert draft["missing_items"][0]["match_status"] == "matched"
        assert draft["missing_items"][0]["stock_available"] is True
        assert draft["catalog_match_count"] == 1
        assert draft["catalog_available_count"] == 1
        assert payload["summary"]["draft_count"] == 1
        assert payload["launch_summary"]["by_event_type"]["missing_list_saved"] == 1

        follow_up = client.get(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow_up.status_code == 200
        assert follow_up.json()["drafts"][0]["id"] == draft["id"]

        row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", ("real_user",))
        assert row is not None
        meta = json.loads(row["meta_json"])
        assert meta["neoeats_missing_lists"][0]["recipe_id"] == "ramen-1"
        assert meta["neoeats_launch_events"][0]["event_type"] == "missing_list_saved"
    finally:
        db.close()


def test_missing_list_drafts_enrich_from_store_catalog(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source": "chat",
                "recipe_id": "stir-fry-1",
                "recipe_name": "Noodle Stir Fry",
                "missing_items": [
                    {"name": "noodles", "quantity": 2},
                    {"name": "dragon sauce"},
                ],
            },
        )

        assert response.status_code == 200
        draft = response.json()["draft"]
        assert draft["catalog_source"] == "inventory_item"
        assert draft["catalog_match_count"] == 1
        assert draft["catalog_unmatched_count"] == 1
        assert draft["total_estimate"] == 23.0
        noodles = draft["missing_items"][0]
        assert noodles["catalog_item_id"] == "cat-noodles"
        assert noodles["sku"] == "NOD-001"
        assert noodles["category"] == "pantry"
        assert noodles["price"] == 11.5
        assert noodles["quantity_available"] == 6.0
        assert noodles["match_confidence"] >= 0.9
        assert draft["missing_items"][1]["match_status"] == "unmatched"
    finally:
        db.close()


def test_missing_list_drafts_update_existing_and_can_be_deleted(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        first = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source": "fridge",
                "recipeId": "toast-1",
                "recipeName": "Egg Toast",
                "missingItems": ["eggs"],
            },
        )
        assert first.status_code == 200
        draft_id = first.json()["draft"]["id"]

        second = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source": "fridge",
                "recipe_id": "toast-1",
                "recipe_name": "Egg Toast",
                "missing_items": [{"name": "eggs", "quantity": 6, "unit": "pcs"}],
            },
        )
        assert second.status_code == 200
        assert second.json()["draft"]["id"] == draft_id
        assert second.json()["draft"]["missing_items"][0]["quantity"] == 6
        assert second.json()["summary"]["draft_count"] == 1

        deleted = client.delete(
            f"/api/v1/neoeats/missing-lists/{draft_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["summary"]["draft_count"] == 0
    finally:
        db.close()


def test_missing_list_drafts_can_be_confirmed(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        created = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source": "explore",
                "recipe_id": "eggs-1",
                "recipe_name": "Egg Bowl",
                "missing_items": [{"name": "eggs", "quantity": 6}],
            },
        )
        assert created.status_code == 200
        draft_id = created.json()["draft"]["id"]

        confirmed = client.post(
            f"/api/v1/neoeats/missing-lists/{draft_id}/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert confirmed.status_code == 200
        payload = confirmed.json()
        assert payload["draft"]["status"] == "confirmed"
        assert payload["draft"]["confirmed_at"]
        assert payload["summary"]["active_count"] == 0
        assert payload["launch_summary"]["by_event_type"]["missing_list_confirmed"] == 1

        row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", ("real_user",))
        assert row is not None
        meta = json.loads(row["meta_json"])
        assert meta["neoeats_missing_lists"][0]["status"] == "confirmed"
        assert [event["event_type"] for event in meta["neoeats_launch_events"]] == [
            "missing_list_saved",
            "missing_list_confirmed",
        ]
    finally:
        db.close()


def test_missing_list_drafts_reject_invalid_payload(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={"source": "orders", "recipe_id": "bad", "missing_items": ["salt"]},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_missing_list_source"

        empty = client.post(
            "/api/v1/neoeats/missing-lists",
            headers={"Authorization": f"Bearer {token}"},
            json={"source": "chat", "recipe_id": "bad", "missing_items": []},
        )
        assert empty.status_code == 400
        assert empty.json()["detail"] == "missing_items_required"
    finally:
        db.close()


def test_launch_events_reject_unknown_event_type(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "random_metric", "payload": {"value": 1}},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_launch_event_type"
    finally:
        db.close()


def test_admin_launch_events_summary_requires_admin_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SEED_ADMIN_KEY", "neoeats_admin")
    client, db, token = _build_client(tmp_path)
    try:
        client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "first_food_added", "payload": {"items_count": 1}},
        )
        client.post(
            "/api/v1/neoeats/launch/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"event_type": "recommendation_requested", "payload": {"pantry_count": 1}},
        )

        denied = client.get("/api/v1/neoeats/launch/events/admin/summary")
        assert denied.status_code == 401

        response = client.get(
            "/api/v1/neoeats/launch/events/admin/summary",
            headers={"X-Admin-Key": "neoeats_admin"},
        )
        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["user_count"] == 1
        assert summary["users_with_events"] == 1
        assert summary["activated_user_count"] == 1
        assert summary["by_event_type"]["first_food_added"] == 1
        assert summary["by_event_type"]["recommendation_requested"] == 1
    finally:
        db.close()


def test_profile_patch_persists_dietary_profile_and_records_memory(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.patch(
            "/api/v1/neoeats/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "dietary_profile": {
                    "diet_tags": ["Vegetarian", "High Protein"],
                    "allergies": ["Peanut"],
                    "avoided_ingredients": ["Cilantro"],
                    "goals": ["Budget Friendly"],
                    "favorite_cuisines": ["Japanese"],
                }
            },
        )

        assert response.status_code == 200
        payload = response.json()
        dietary = payload["dietary_profile"]
        assert dietary["diet_tags"][:2] == ["vegetarian", "high_protein"]
        assert "vegan" in dietary["diet_tags"]
        assert dietary["allergies"] == ["peanut"]
        assert dietary["avoided_ingredients"] == ["cilantro"]
        assert dietary["goals"] == ["budget_friendly", "high_protein"]
        assert dietary["favorite_cuisines"] == ["japanese", "norwegian"]

        memory = client.get(
            "/api/v1/neoeats/memory?query=peanut%20cilantro%20japanese",
            headers={"Authorization": f"Bearer {token}"},
        )
        events = memory.json()["rag_memory"]["retrieved_events"]
        profile_events = [event for event in events if event["event_type"] == "profile_dietary_updated"]
        assert profile_events
        assert profile_events[0]["source"] == "profile_preferences"
        assert profile_events[0]["payload"]["allergies"] == ["peanut"]
        assert profile_events[0]["payload"]["avoided_ingredients"] == ["cilantro"]
    finally:
        db.close()


def test_dashboard_aggregates_real_neoeats_tables(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.get(
            "/api/v1/neoeats/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["user"]["username"] == "real_user"
        assert payload["inventory"]["item_count"] == 2
        assert payload["inventory"]["expiring_soon_count"] == 1
        assert payload["inventory"]["categories"] == {"dairy": 1, "grain": 1}
        assert payload["orders"]["active_count"] == 1
        assert "ABC12345" in payload["orders"]["active_order_description"]
        assert payload["receipts"]["count"] == 1
        assert payload["receipts"]["total_spend"] == 59.0
        assert payload["data_sources"]["neoeats_db"] is True
        assert payload["data_sources"]["storage_item"] is True
    finally:
        db.close()


def test_profile_patch_persists_notification_settings(tmp_path) -> None:
    client, db, token = _build_client(tmp_path)
    try:
        response = client.patch(
            "/api/v1/neoeats/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"notifications": {"hot_offer_alerts": False}},
        )

        assert response.status_code == 200
        assert response.json()["notifications"]["hot_offer_alerts"] is False

        follow_up = client.get(
            "/api/v1/neoeats/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow_up.status_code == 200
        assert follow_up.json()["notifications"]["hot_offer_alerts"] is False
    finally:
        db.close()


def test_dashboard_marks_missing_tables_without_fake_data(tmp_path) -> None:
    class BrokenNeoEatsDB:
        async def fetch(self, *_args: Any) -> list[dict[str, Any]]:
            raise RuntimeError("table missing")

        async def fetchrow(self, *_args: Any) -> dict[str, Any]:
            raise RuntimeError("table missing")

    db = DB(str(tmp_path / "neoeats_profile_missing_tables.db"))
    db.init_schema()
    db.execute(
        "INSERT INTO users(id, email, meta_json, is_admin, is_banned) VALUES(?,?,?,?,?)",
        ("empty_user", "empty@example.com", "{}", 0, 0),
    )
    token = issue_key_for_user(db, "empty_user")

    async def _get_neoeats_db(_app: FastAPI) -> BrokenNeoEatsDB:
        return BrokenNeoEatsDB()

    app = FastAPI()
    app.include_router(build_neoeats_profile_router(db=db, get_neoeats_db=_get_neoeats_db))
    client = TestClient(app)

    try:
        response = client.get(
            "/api/v1/neoeats/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["inventory"]["item_count"] == 0
        assert payload["orders"]["active_count"] == 0
        assert payload["receipts"]["count"] == 0
        assert payload["data_sources"]["storage_item"] is False
        assert payload["data_sources"]["sagas"] is False
        assert payload["data_sources"]["receipts"] is False
    finally:
        db.close()
