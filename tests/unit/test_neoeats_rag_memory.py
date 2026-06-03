from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.neoeats_memory_controls import (
    memory_controls_from_meta,
    memory_learning_enabled,
    memory_retrieval_enabled,
    patch_memory_controls,
)
from app.services.neoeats_rag_memory import (
    backfill_memory_event_embeddings,
    backfill_memory_event_embeddings_for_all_users,
    build_memory_event_text,
    delete_memory_events,
    embedding_provider_available,
    export_memory_events,
    memory_context_from_events,
    memory_embedding_global_stats,
    memory_event_stats,
    record_memory_event,
    retrieve_memory_events,
    score_memory_event,
)


def test_memory_controls_default_patch_and_source_gating():
    meta = {}
    controls = memory_controls_from_meta(meta)

    assert controls["learning_enabled"] is True
    assert controls["sources"]["receipt"] is True
    assert controls["sources"]["recipe"] is True
    assert controls["sources"]["profile"] is True
    assert memory_learning_enabled(meta, source="receipt_confirm") is True
    assert memory_learning_enabled(meta, source="recipe_feedback") is True
    assert memory_learning_enabled(meta, source="profile_preferences") is True

    patch_memory_controls(meta, {"rag_retrieval_enabled": False, "sources": {"receipt": False, "recipe": False, "profile": False}})

    assert memory_retrieval_enabled(meta) is False
    assert memory_learning_enabled(meta, source="receipt_confirm") is False
    assert memory_learning_enabled(meta, source="recipe_feedback") is False
    assert memory_learning_enabled(meta, source="profile_preferences") is False
    assert memory_learning_enabled(meta, source="neoeats_chat") is True


class FakeMemoryDB:
    def __init__(self):
        self.executed = []
        self.rows = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "DELETE FROM neoeats_user_memory_events" in query:
            user_id = args[0]
            self.rows = [row for row in self.rows if row["user_id"] != user_id]

    async def fetch(self, query, *args):
        user_id = args[0]
        if "GROUP BY event_type" in query:
            counts = {}
            for row in self.rows:
                if row["user_id"] == user_id:
                    counts[row["event_type"]] = counts.get(row["event_type"], 0) + 1
            return [{"event_type": key, "count": value} for key, value in counts.items()]
        if "GROUP BY embedding_status" in query:
            counts = {}
            for row in self.rows:
                if row["user_id"] == user_id:
                    status = row.get("embedding_status") or "pending"
                    counts[status] = counts.get(status, 0) + 1
            return [{"embedding_status": key, "count": value} for key, value in counts.items()]
        return [row for row in self.rows if row["user_id"] == user_id]

    async def fetchrow(self, query, *args):
        user_id = args[0]
        rows = [row for row in self.rows if row["user_id"] == user_id]
        last_updated = max((row["updated_at"] for row in rows), default=None)
        return {"count": len(rows), "last_updated_at": last_updated}


class FakeEmbeddingProvider:
    embedding_model = "stub-embedding"
    embedding_available = True

    def __init__(self):
        self.calls = []

    async def embed_text(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return [0.1, 0.2, 0.3]


class VectorMemoryDB(FakeMemoryDB):
    async def fetch(self, query, *args):
        if "<=>" in query:
            user_id = args[0]
            return [
                {**row, "vector_similarity": 0.91}
                for row in self.rows
                if row["user_id"] == user_id and row.get("embedding_status") == "ready"
            ]
        return await super().fetch(query, *args)


class GlobalMemoryDB(FakeMemoryDB):
    async def fetch(self, query, *args):
        if "GROUP BY user_id" in query:
            statuses = set(args[0])
            limit = int(args[1])
            users = {}
            for row in self.rows:
                status = str(row.get("embedding_status") or "pending")
                text = str(row.get("text") or "").strip()
                if status in statuses and text:
                    entry = users.setdefault(
                        row["user_id"],
                        {"user_id": row["user_id"], "candidate_count": 0, "last_updated_at": row.get("updated_at")},
                    )
                    entry["candidate_count"] += 1
                    if row.get("updated_at") and (entry.get("last_updated_at") is None or row["updated_at"] > entry["last_updated_at"]):
                        entry["last_updated_at"] = row["updated_at"]
            return list(users.values())[:limit]
        if "GROUP BY embedding_status" in query:
            counts = {}
            users = {}
            for row in self.rows:
                status = str(row.get("embedding_status") or "pending")
                counts[status] = counts.get(status, 0) + 1
                users.setdefault(status, set()).add(row["user_id"])
            return [
                {"embedding_status": status, "count": count, "user_count": len(users.get(status, set()))}
                for status, count in counts.items()
            ]
        if "event_hash" in query:
            user_id = args[0]
            statuses = set(args[1])
            limit = int(args[2])
            return [
                row
                for row in self.rows
                if row["user_id"] == user_id
                and str(row.get("embedding_status") or "pending") in statuses
                and str(row.get("text") or "").strip()
            ][:limit]
        return await super().fetch(query, *args)

    async def fetchrow(self, query, *args):
        if "COUNT(DISTINCT user_id)" in query and "WHERE COALESCE" in query:
            statuses = set(args[0])
            rows = [
                row
                for row in self.rows
                if str(row.get("embedding_status") or "pending") in statuses
                and str(row.get("text") or "").strip()
            ]
            return {"count": len(rows), "user_count": len({row["user_id"] for row in rows})}
        if "COUNT(DISTINCT user_id)" in query:
            last_updated = max((row["updated_at"] for row in self.rows), default=None)
            return {
                "count": len(self.rows),
                "user_count": len({row["user_id"] for row in self.rows}),
                "last_updated_at": last_updated,
            }
        return await super().fetchrow(query, *args)

    async def execute(self, query, *args):
        await super().execute(query, *args)
        if "SET embedding =" in query:
            _vector, model, user_id, event_type, event_hash = args
            for row in self.rows:
                if row["user_id"] == user_id and row["event_type"] == event_type and row.get("event_hash") == event_hash:
                    row["embedding_status"] = "ready"
                    row["embedding_model"] = model
        elif "SET embedding_status =" in query:
            status, model, user_id, event_type, event_hash = args
            for row in self.rows:
                if row["user_id"] == user_id and row["event_type"] == event_type and row.get("event_hash") == event_hash:
                    row["embedding_status"] = status
                    row["embedding_model"] = model


def test_build_memory_event_text_for_confirmed_pantry_item():
    text = build_memory_event_text(
        event_type="scan_item_confirmed",
        source="vision_analyze_confirmed",
        payload={
            "item": {
                "display_name": "Milk 1L",
                "quantity": 1,
                "unit": "pcs",
                "category": "Dairy",
            }
        },
    )

    assert "User confirmed pantry item: Milk 1L" in text
    assert "category Dairy" in text
    assert "source vision_analyze_confirmed" in text


def test_build_memory_event_text_for_confirmed_receipt_item():
    text = build_memory_event_text(
        event_type="receipt_item_confirmed",
        source="receipt_confirm",
        subject="salmon",
        payload={
            "name": "Salmon Fillet",
            "quantity": 2,
            "unit": "pcs",
            "category": "seafood",
            "merchant_name": "Neo Market",
            "receipt_id": "receipt-1",
        },
    )

    assert "User confirmed receipt item: salmon" in text
    assert "quantity 2 pcs" in text
    assert "category seafood" in text
    assert "merchant Neo Market" in text


def test_build_memory_event_text_for_recipe_feedback():
    text = build_memory_event_text(
        event_type="recipe_feedback_accepted",
        source="recipe_feedback",
        subject="Salmon Bowl",
        payload={
            "feedback": "accepted",
            "action": "saved",
            "ingredients": [{"name": "salmon"}, {"name": "rice"}],
            "reason": "high protein dinner",
            "reason_code": "looks_good",
            "reason_tags": ["taste_fit", "positive_signal"],
            "rating": 5,
        },
    )

    assert "User accepted recipe recommendation: Salmon Bowl" in text
    assert "action saved" in text
    assert "rating 5/5" in text
    assert "reason code looks_good" in text
    assert "reason tags taste_fit, positive_signal" in text
    assert "ingredients salmon, rice" in text
    assert "reason high protein dinner" in text


def test_build_memory_event_text_for_profile_dietary_update():
    text = build_memory_event_text(
        event_type="profile_dietary_updated",
        source="profile_preferences",
        subject="dietary profile",
        payload={
            "diet_tags": ["vegan"],
            "allergies": ["peanut"],
            "avoided_ingredients": ["cilantro"],
            "goals": ["high_protein"],
            "favorite_cuisines": ["japanese"],
        },
    )

    assert "User updated dietary profile" in text
    assert "diet vegan" in text
    assert "allergies peanut" in text
    assert "avoid cilantro" in text
    assert "goals high_protein" in text
    assert "cuisines japanese" in text


def test_embedding_provider_available_respects_provider_contract():
    assert embedding_provider_available(None) is False
    assert embedding_provider_available(FakeEmbeddingProvider()) is True

    class DisabledProvider:
        embedding_available = False

        def embed_text(self, _text):
            return [0.1]

    assert embedding_provider_available(DisabledProvider()) is False


@pytest.mark.asyncio
async def test_record_memory_event_writes_append_only_payload():
    db = FakeMemoryDB()

    event_id = await record_memory_event(
        db,
        user_id="user-a",
        event_type="pantry_item_confirmed",
        source="inventory_items",
        subject="Tomato",
        payload={"canonical_name": "tomato", "product_id": "prod-tomato"},
        confidence=0.91,
    )

    assert event_id
    assert db.executed
    _, args = db.executed[0]
    assert args[1] == "user-a"
    assert args[2] == "pantry_item_confirmed"
    assert args[3] == "inventory_items"
    assert args[7] == 0.91


@pytest.mark.asyncio
async def test_record_memory_event_stores_embedding_when_provider_available():
    db = FakeMemoryDB()
    provider = FakeEmbeddingProvider()

    event_id = await record_memory_event(
        db,
        user_id="user-a",
        event_type="pantry_item_confirmed",
        source="inventory_items",
        subject="Tomato",
        payload={"canonical_name": "tomato", "product_id": "prod-tomato"},
        confidence=0.91,
        embedding_provider=provider,
        embedding_model="stub-embedding",
    )

    assert event_id
    assert len(db.executed) == 2
    embedding_query, embedding_args = db.executed[1]
    assert "embedding_status = 'ready'" in embedding_query
    assert embedding_args[0] == "[0.1,0.2,0.3]"
    assert embedding_args[1] == "stub-embedding"
    assert provider.calls[0][1]["task_type"] == "retrieval_document"


def test_score_memory_event_prefers_matching_user_context():
    event = {
        "event_type": "pantry_item_confirmed",
        "subject": "Tomato",
        "text": "User confirmed pantry item: Tomato category Vegetables",
        "confidence": 0.9,
        "payload": {"canonical_name": "tomato"},
    }
    unrelated = {
        "event_type": "chat_message",
        "subject": "budget",
        "text": "User asked about cheap dinner",
        "confidence": 0.6,
        "payload": {},
    }

    assert score_memory_event(event, query="what can I cook with tomato") > score_memory_event(
        unrelated,
        query="what can I cook with tomato",
    )


@pytest.mark.asyncio
async def test_retrieve_memory_events_is_user_scoped_and_ranked():
    now = datetime.now(timezone.utc)
    db = FakeMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "pantry_item_confirmed",
            "source": "inventory_items",
            "subject": "Tomato",
            "text": "User confirmed pantry item: Tomato category Vegetables",
            "confidence": 0.9,
            "payload": {"canonical_name": "tomato"},
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "2",
            "user_id": "user-a",
            "event_type": "chat_message",
            "source": "neoeats_chat",
            "subject": "budget",
            "text": "User asked for budget dinners",
            "confidence": 0.62,
            "payload": {},
            "created_at": now - timedelta(minutes=5),
            "updated_at": now - timedelta(minutes=5),
        },
        {
            "id": "3",
            "user_id": "user-b",
            "event_type": "pantry_item_confirmed",
            "source": "inventory_items",
            "subject": "Tomato",
            "text": "Other user confirmed tomato",
            "confidence": 0.99,
            "payload": {"canonical_name": "tomato"},
            "created_at": now,
            "updated_at": now,
        },
    ]

    events = await retrieve_memory_events(
        db,
        user_id="user-a",
        query="tomato recipe",
        limit=2,
    )

    assert [event["id"] for event in events] == ["1", "2"]
    assert all(event["id"] != "3" for event in events)
    assert "confirmed_user_event" in events[0]["match_reasons"]


@pytest.mark.asyncio
async def test_retrieve_memory_events_uses_vector_matches_when_available():
    now = datetime.now(timezone.utc)
    db = VectorMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "pantry_item_confirmed",
            "source": "inventory_items",
            "subject": "Greek yogurt",
            "text": "User confirmed pantry item: Greek yogurt category Dairy",
            "confidence": 0.84,
            "payload": {"canonical_name": "greek yogurt"},
            "embedding_status": "ready",
            "embedding_model": "stub-embedding",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "2",
            "user_id": "user-a",
            "event_type": "pantry_item_confirmed",
            "source": "inventory_items",
            "subject": "Tomato",
            "text": "User confirmed pantry item: Tomato category Vegetables",
            "confidence": 0.9,
            "payload": {"canonical_name": "tomato"},
            "embedding_status": "pending",
            "created_at": now - timedelta(minutes=5),
            "updated_at": now - timedelta(minutes=5),
        },
    ]

    events = await retrieve_memory_events(
        db,
        user_id="user-a",
        query="creamy breakfast protein",
        limit=2,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model="stub-embedding",
    )

    assert events[0]["id"] == "1"
    assert events[0]["vector_similarity"] == 0.91
    assert events[0]["retrieval_mode"] == "hybrid_vector_lexical"
    assert events[0]["match_reasons"][0] == "vector_similarity:0.910"

    context = memory_context_from_events(events)
    assert context["retrieval"]["mode"] == "hybrid_vector_lexical_rag"
    assert context["retrieval"]["embedding_status"] == "active"
    assert context["retrieval"]["ranking"][0] == "vector_similarity"


@pytest.mark.asyncio
async def test_backfill_memory_event_embeddings_updates_pending_events():
    now = datetime.now(timezone.utc)
    db = FakeMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "receipt_item_confirmed",
            "source": "receipt_confirm",
            "subject": "Salmon",
            "text": "User confirmed receipt item: Salmon",
            "event_hash": "hash-salmon",
            "confidence": 0.86,
            "payload": {"canonical_name": "salmon"},
            "embedding_status": "pending",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "2",
            "user_id": "user-b",
            "event_type": "receipt_item_confirmed",
            "source": "receipt_confirm",
            "subject": "Milk",
            "text": "Other user confirmed milk",
            "event_hash": "hash-milk",
            "confidence": 0.99,
            "payload": {"canonical_name": "milk"},
            "embedding_status": "pending",
            "created_at": now,
            "updated_at": now,
        },
    ]

    summary = await backfill_memory_event_embeddings(
        db,
        user_id="user-a",
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model="stub-embedding",
        limit=10,
    )

    assert summary["provider_available"] is True
    assert summary["attempted"] == 1
    assert summary["ready"] == 1
    assert summary["event_ids"] == ["1"]
    assert any("embedding_status = 'ready'" in query for query, _args in db.executed)


@pytest.mark.asyncio
async def test_backfill_memory_event_embeddings_skips_without_provider():
    db = FakeMemoryDB()

    summary = await backfill_memory_event_embeddings(
        db,
        user_id="user-a",
        embedding_provider=None,
        limit=7,
    )

    assert summary["provider_available"] is False
    assert summary["attempted"] == 0
    assert summary["skipped"] == 7
    assert summary["reason"] == "embedding_provider_unavailable"
    assert db.executed == []


@pytest.mark.asyncio
async def test_memory_embedding_global_stats_counts_backlog():
    now = datetime.now(timezone.utc)
    db = GlobalMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "receipt_item_confirmed",
            "source": "receipt_confirm",
            "subject": "Salmon",
            "text": "User confirmed salmon",
            "event_hash": "hash-salmon",
            "confidence": 0.86,
            "payload": {},
            "embedding_status": "ready",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "2",
            "user_id": "user-a",
            "event_type": "profile_dietary_updated",
            "source": "profile_preferences",
            "subject": "dietary profile",
            "text": "User avoids peanuts",
            "event_hash": "hash-peanut",
            "confidence": 0.96,
            "payload": {},
            "embedding_status": "pending",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "3",
            "user_id": "user-b",
            "event_type": "recipe_feedback_rejected",
            "source": "recipe_feedback",
            "subject": "Ratatouille",
            "text": "User rejected recipe due missing ingredients",
            "event_hash": "hash-ratatouille",
            "confidence": 0.82,
            "payload": {},
            "embedding_status": "failed",
            "created_at": now,
            "updated_at": now,
        },
    ]

    stats = await memory_embedding_global_stats(db)

    assert stats["event_count"] == 3
    assert stats["user_count"] == 2
    assert stats["by_embedding_status"] == {"ready": 1, "pending": 1, "failed": 1}
    assert stats["embedding_ready_count"] == 1
    assert stats["embedding_coverage_pct"] == 33.33
    assert stats["backlog_event_count"] == 2
    assert stats["backlog_user_count"] == 2


@pytest.mark.asyncio
async def test_backfill_memory_event_embeddings_for_all_users_updates_bounded_backlog():
    now = datetime.now(timezone.utc)
    db = GlobalMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "profile_dietary_updated",
            "source": "profile_preferences",
            "subject": "dietary profile",
            "text": "User avoids peanuts",
            "event_hash": "hash-peanut",
            "confidence": 0.96,
            "payload": {},
            "embedding_status": "pending",
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "2",
            "user_id": "user-b",
            "event_type": "recipe_feedback_rejected",
            "source": "recipe_feedback",
            "subject": "Ratatouille",
            "text": "User rejected recipe due missing ingredients",
            "event_hash": "hash-ratatouille",
            "confidence": 0.82,
            "payload": {},
            "embedding_status": "failed",
            "created_at": now,
            "updated_at": now,
        },
    ]

    summary = await backfill_memory_event_embeddings_for_all_users(
        db,
        embedding_provider=FakeEmbeddingProvider(),
        embedding_model="stub-embedding",
        limit_per_user=1,
        max_users=2,
    )

    assert summary["provider_available"] is True
    assert summary["users_considered"] == 2
    assert summary["attempted"] == 2
    assert summary["ready"] == 2
    assert summary["event_ids"] == ["1", "2"]
    assert {row["embedding_status"] for row in db.rows} == {"ready"}


@pytest.mark.asyncio
async def test_backfill_memory_event_embeddings_for_all_users_dry_run_does_not_write():
    now = datetime.now(timezone.utc)
    db = GlobalMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "profile_dietary_updated",
            "source": "profile_preferences",
            "subject": "dietary profile",
            "text": "User avoids peanuts",
            "event_hash": "hash-peanut",
            "confidence": 0.96,
            "payload": {},
            "embedding_status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    ]

    summary = await backfill_memory_event_embeddings_for_all_users(
        db,
        embedding_provider=FakeEmbeddingProvider(),
        dry_run=True,
    )

    assert summary["reason"] == "dry_run"
    assert summary["users_considered"] == 1
    assert summary["attempted"] == 0
    assert summary["skipped"] == 1
    assert db.executed == []


def test_memory_context_from_events_exposes_rag_summary():
    context = memory_context_from_events(
        [
            {
                "id": "1",
                "event_type": "pantry_item_confirmed",
                "source": "inventory_items",
                "subject": "Tomato",
                "text": "User confirmed pantry item: Tomato",
                "confidence": 0.9,
                "score": 0.7,
            }
        ]
    )

    assert context["schema_version"] == "neoeats_rag_memory_v1"
    assert context["retrieval"]["mode"] == "lexical_event_rag"
    assert context["retrieved_events"][0]["subject"] == "Tomato"
    assert context["summary"][0]["source"] == "inventory_items"


@pytest.mark.asyncio
async def test_memory_stats_export_and_delete_are_user_scoped():
    now = datetime.now(timezone.utc)
    db = FakeMemoryDB()
    db.rows = [
        {
            "id": "1",
            "user_id": "user-a",
            "event_type": "receipt_item_confirmed",
            "source": "receipt_confirm",
            "subject": "Salmon",
            "text": "User confirmed receipt item: Salmon",
            "confidence": 0.86,
            "payload": {"canonical_name": "salmon"},
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "2",
            "user_id": "user-b",
            "event_type": "receipt_item_confirmed",
            "source": "receipt_confirm",
            "subject": "Milk",
            "text": "Other user confirmed milk",
            "confidence": 0.99,
            "payload": {"canonical_name": "milk"},
            "created_at": now,
            "updated_at": now,
        },
    ]

    stats = await memory_event_stats(db, user_id="user-a")
    exported = await export_memory_events(db, user_id="user-a")
    await delete_memory_events(db, user_id="user-a")

    assert stats["event_count"] == 1
    assert stats["by_event_type"] == {"receipt_item_confirmed": 1}
    assert stats["by_embedding_status"] == {"pending": 1}
    assert stats["embedding_coverage_pct"] == 0.0
    assert [event["id"] for event in exported] == ["1"]
    assert [row["id"] for row in db.rows] == ["2"]
