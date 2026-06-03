from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


MEMORY_SCHEMA_VERSION = "neoeats_rag_memory_v1"
DEFAULT_MEMORY_EMBEDDING_MODEL = "text-embedding-004"
DEFAULT_BACKFILL_STATUSES = ["pending", "failed", "unavailable"]

logger = logging.getLogger(__name__)


def _safe_embedding_statuses(statuses: Optional[Iterable[str]] = None) -> List[str]:
    safe_statuses = [
        str(status).strip().lower()
        for status in (statuses or DEFAULT_BACKFILL_STATUSES)
        if str(status).strip()
    ]
    return safe_statuses or list(DEFAULT_BACKFILL_STATUSES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _tokens(value: Any) -> set[str]:
    text = _normalize_text(value).lower()
    return {token for token in re.split(r"[^a-z0-9_]+", text) if len(token) >= 3}


def _clamp_confidence(value: Any, default: float = 0.72) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    if parsed > 1.0:
        parsed = parsed / 100.0
    return max(0.0, min(1.0, parsed))


def _clamp_similarity(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except Exception:
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, min(1.0, parsed))


def _normalize_embedding(values: Any) -> List[float]:
    if not isinstance(values, (list, tuple)):
        return []
    if values and isinstance(values[0], (list, tuple)):
        values = values[0]
    out: List[float] = []
    for value in values:
        try:
            parsed = float(value)
        except Exception:
            continue
        if math.isfinite(parsed):
            out.append(parsed)
    return out


def _embedding_to_pgvector_literal(values: Any) -> Optional[str]:
    embedding = _normalize_embedding(values)
    if not embedding:
        return None
    return "[" + ",".join(f"{value:.8g}" for value in embedding) + "]"


def embedding_provider_available(embedding_provider: Any) -> bool:
    if embedding_provider is None:
        return False
    if hasattr(embedding_provider, "embedding_available"):
        try:
            return bool(getattr(embedding_provider, "embedding_available"))
        except Exception:
            return False
    return any(
        hasattr(embedding_provider, method_name)
        for method_name in ("embed_text", "embed_texts", "embed_content")
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _invoke_embedding_method(method: Any, *args: Any, **kwargs: Any) -> Any:
    async def _invoke_async() -> Any:
        try:
            return await _maybe_await(method(*args, **kwargs))
        except TypeError:
            return await _maybe_await(method(*args))

    def _invoke_sync() -> Any:
        try:
            return method(*args, **kwargs)
        except TypeError:
            return method(*args)

    if inspect.iscoroutinefunction(method):
        return await _invoke_async()
    return await asyncio.to_thread(_invoke_sync)


async def _call_embedding_provider(
    embedding_provider: Any,
    text: str,
    *,
    model: str,
    task_type: str,
) -> List[float]:
    if embedding_provider is None or not _normalize_text(text):
        return []

    if hasattr(embedding_provider, "embed_text"):
        embed_text = getattr(embedding_provider, "embed_text")
        result = await _invoke_embedding_method(embed_text, text, model=model, task_type=task_type)
        return _normalize_embedding(result)

    if hasattr(embedding_provider, "embed_texts"):
        embed_texts = getattr(embedding_provider, "embed_texts")
        result = await _invoke_embedding_method(embed_texts, [text], model=model, task_type=task_type)
        return _normalize_embedding(result)

    if hasattr(embedding_provider, "embed_content"):
        embed_content = getattr(embedding_provider, "embed_content")

        def _embed_content_sync() -> Any:
            try:
                return embed_content(content=text, model=model, task_type=task_type)
            except TypeError:
                try:
                    return embed_content(text, model=model, task_type=task_type)
                except TypeError:
                    return embed_content(text)

        result = await asyncio.to_thread(_embed_content_sync)
        return _normalize_embedding(result)

    return []


async def _store_memory_event_embedding(
    db: Any,
    *,
    user_id: str,
    event_type: str,
    event_hash: str,
    text: str,
    embedding_provider: Any,
    embedding_model: str,
) -> str:
    status = "failed"
    try:
        embedding = await _call_embedding_provider(
            embedding_provider,
            text,
            model=embedding_model,
            task_type="retrieval_document",
        )
        vector_literal = _embedding_to_pgvector_literal(embedding)
        if not vector_literal:
            status = "unavailable"
            raise ValueError("embedding provider returned no vector")
        await db.execute(
            """
            UPDATE neoeats_user_memory_events
            SET embedding = $1::vector,
                embedding_model = $2,
                embedding_status = 'ready',
                updated_at = now()
            WHERE user_id = $3 AND event_type = $4 AND event_hash = $5
            """,
            vector_literal,
            embedding_model,
            user_id,
            event_type,
            event_hash,
        )
        return "ready"
    except Exception as exc:  # noqa: BLE001
        logger.debug("NeoEats memory embedding write skipped: %s", exc)
        try:
            await db.execute(
                """
                UPDATE neoeats_user_memory_events
                SET embedding_status = $1,
                    embedding_model = $2,
                    updated_at = now()
                WHERE user_id = $3 AND event_type = $4 AND event_hash = $5
                """,
                status,
                embedding_model,
                user_id,
                event_type,
                event_hash,
            )
        except Exception:
            logger.debug("NeoEats memory embedding status update failed", exc_info=True)
        return status


def _age_days(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    if not hasattr(value, "astimezone"):
        return None
    try:
        current = value.astimezone(timezone.utc)
    except Exception:
        return None
    return max(0.0, (_now() - current).total_seconds() / 86400.0)


def _event_hash(
    *,
    user_id: str,
    event_type: str,
    source: str,
    subject: Optional[str],
    text: str,
    payload: Dict[str, Any],
) -> str:
    stable_payload = {
        key: payload.get(key)
        for key in sorted(payload)
        if key in {"item_id", "product_id", "canonical_name", "recipe_id", "detection_id", "receipt_id"}
    }
    raw = json.dumps(
        {
            "user_id": user_id,
            "event_type": event_type,
            "source": source,
            "subject": subject or "",
            "text": text,
            "stable_payload": stable_payload,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_memory_event_text(
    *,
    event_type: str,
    source: str,
    subject: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    text: Optional[str] = None,
) -> str:
    """Build compact retrieval text for a NeoEats memory event."""

    explicit = _normalize_text(text)
    if explicit:
        return explicit[:1200]

    payload = payload if isinstance(payload, dict) else {}
    subject_text = _normalize_text(subject)
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else {}

    if event_type in {"pantry_item_confirmed", "scan_item_confirmed", "receipt_item_confirmed"}:
        name = _normalize_text(
            subject_text
            or item.get("display_name")
            or item.get("name")
            or payload.get("display_name")
            or payload.get("name")
        )
        category = _normalize_text(item.get("category") or payload.get("category"))
        quantity = _normalize_text(item.get("quantity") or payload.get("quantity"))
        unit = _normalize_text(item.get("unit") or payload.get("unit"))
        if event_type == "receipt_item_confirmed":
            parts = [f"User confirmed receipt item: {name}" if name else "User confirmed a receipt item"]
        else:
            parts = [f"User confirmed pantry item: {name}" if name else "User confirmed a pantry item"]
        if quantity or unit:
            parts.append(f"quantity {quantity} {unit}".strip())
        if category:
            parts.append(f"category {category}")
        merchant = _normalize_text(payload.get("merchant_name"))
        if merchant:
            parts.append(f"merchant {merchant}")
        parts.append(f"source {source}")
        return ". ".join(parts)[:1200]

    if event_type == "cooking_completed":
        name = _normalize_text(subject_text or recipe.get("name") or payload.get("recipe_name"))
        ingredients = payload.get("ingredients")
        ingredient_names: List[str] = []
        if isinstance(ingredients, list):
            for entry in ingredients[:12]:
                if isinstance(entry, dict):
                    item_name = _normalize_text(entry.get("name"))
                    if item_name:
                        ingredient_names.append(item_name)
        parts = [f"User completed cooking: {name}" if name else "User completed a cooking session"]
        if ingredient_names:
            parts.append("used " + ", ".join(ingredient_names))
        return ". ".join(parts)[:1200]

    if event_type.startswith("chat_"):
        message = _normalize_text(payload.get("message") or subject_text)
        intent = _normalize_text(payload.get("intent") or event_type.replace("chat_", ""))
        return f"User chat intent {intent}: {message}".strip()[:1200]

    if event_type.startswith("recipe_feedback_"):
        feedback = _normalize_text(payload.get("feedback") or event_type.replace("recipe_feedback_", ""))
        action = _normalize_text(payload.get("action"))
        recipe_name = _normalize_text(subject_text or payload.get("recipe_name") or payload.get("name"))
        ingredients = payload.get("ingredients")
        ingredient_names: List[str] = []
        if isinstance(ingredients, list):
            for entry in ingredients[:12]:
                if isinstance(entry, dict):
                    item_name = _normalize_text(entry.get("name"))
                    if item_name:
                        ingredient_names.append(item_name)
                else:
                    item_name = _normalize_text(entry)
                    if item_name:
                        ingredient_names.append(item_name)
        parts = [
            f"User {feedback or 'rated'} recipe recommendation: {recipe_name}"
            if recipe_name
            else f"User {feedback or 'rated'} a recipe recommendation"
        ]
        if action:
            parts.append(f"action {action}")
        rating = payload.get("rating")
        if isinstance(rating, (int, float)):
            parts.append(f"rating {int(rating)}/5")
        reason_code = _normalize_text(payload.get("reason_code"))
        if reason_code:
            parts.append(f"reason code {reason_code}")
        reason_tags = payload.get("reason_tags")
        if isinstance(reason_tags, list):
            tags = [_normalize_text(tag) for tag in reason_tags[:8]]
            tags = [tag for tag in tags if tag]
            if tags:
                parts.append("reason tags " + ", ".join(tags))
        if ingredient_names:
            parts.append("ingredients " + ", ".join(ingredient_names))
        reason = _normalize_text(payload.get("reason"))
        if reason:
            parts.append(f"reason {reason}")
        return ". ".join(parts)[:1200]

    if event_type.startswith("profile_dietary"):
        diet_tags = payload.get("diet_tags") if isinstance(payload.get("diet_tags"), list) else []
        allergies = payload.get("allergies") if isinstance(payload.get("allergies"), list) else []
        avoided = payload.get("avoided_ingredients") if isinstance(payload.get("avoided_ingredients"), list) else []
        goals = payload.get("goals") if isinstance(payload.get("goals"), list) else []
        cuisines = payload.get("favorite_cuisines") if isinstance(payload.get("favorite_cuisines"), list) else []
        parts = ["User updated dietary profile"]
        if diet_tags:
            parts.append("diet " + ", ".join(_normalize_text(item) for item in diet_tags[:8] if _normalize_text(item)))
        if allergies:
            parts.append("allergies " + ", ".join(_normalize_text(item) for item in allergies[:10] if _normalize_text(item)))
        if avoided:
            parts.append("avoid " + ", ".join(_normalize_text(item) for item in avoided[:10] if _normalize_text(item)))
        if goals:
            parts.append("goals " + ", ".join(_normalize_text(item) for item in goals[:8] if _normalize_text(item)))
        if cuisines:
            parts.append("cuisines " + ", ".join(_normalize_text(item) for item in cuisines[:8] if _normalize_text(item)))
        return ". ".join(part for part in parts if part).strip()[:1200]

    return " ".join(part for part in [event_type, source, subject_text] if part).strip()[:1200]


async def record_memory_event(
    db: Any,
    *,
    user_id: str,
    event_type: str,
    source: str,
    subject: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    text: Optional[str] = None,
    confidence: float = 0.72,
    embedding_provider: Optional[Any] = None,
    embedding_model: str = DEFAULT_MEMORY_EMBEDDING_MODEL,
) -> Optional[str]:
    safe_payload = _safe_json(payload)
    event_text = build_memory_event_text(
        event_type=event_type,
        source=source,
        subject=subject,
        payload=safe_payload,
        text=text,
    )
    if not _normalize_text(user_id) or not _normalize_text(event_type) or not event_text:
        return None

    event_id = str(uuid.uuid4())
    dedupe_hash = _event_hash(
        user_id=user_id,
        event_type=event_type,
        source=source,
        subject=subject,
        text=event_text,
        payload=safe_payload,
    )
    payload_json = json.dumps(safe_payload, ensure_ascii=False, default=str)
    await db.execute(
        """
        INSERT INTO neoeats_user_memory_events
          (id, user_id, event_type, source, subject, text, event_hash, confidence, payload, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, now())
        ON CONFLICT (user_id, event_type, event_hash) DO UPDATE
        SET confidence = GREATEST(neoeats_user_memory_events.confidence, EXCLUDED.confidence),
            payload = neoeats_user_memory_events.payload || EXCLUDED.payload,
            text = EXCLUDED.text,
            updated_at = now()
        """,
        event_id,
        user_id,
        event_type,
        source,
        subject,
        event_text,
        dedupe_hash,
        _clamp_confidence(confidence),
        payload_json,
    )
    if embedding_provider is not None:
        await _store_memory_event_embedding(
            db,
            user_id=user_id,
            event_type=event_type,
            event_hash=dedupe_hash,
            text=event_text,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model or DEFAULT_MEMORY_EMBEDDING_MODEL,
        )
    return event_id


async def record_memory_events(db: Any, events: Iterable[Dict[str, Any]]) -> List[str]:
    recorded: List[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = await record_memory_event(
            db,
            user_id=str(event.get("user_id") or ""),
            event_type=str(event.get("event_type") or ""),
            source=str(event.get("source") or "unknown"),
            subject=event.get("subject"),
            payload=event.get("payload") if isinstance(event.get("payload"), dict) else {},
            text=event.get("text"),
            confidence=float(event.get("confidence") or 0.72),
        )
        if event_id:
            recorded.append(event_id)
    return recorded


async def backfill_memory_event_embeddings(
    db: Any,
    *,
    user_id: str,
    embedding_provider: Optional[Any] = None,
    embedding_model: str = DEFAULT_MEMORY_EMBEDDING_MODEL,
    limit: int = 50,
    statuses: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    safe_limit = max(1, min(250, int(limit or 50)))
    safe_statuses = _safe_embedding_statuses(statuses)
    provider_ready = embedding_provider_available(embedding_provider)
    summary: Dict[str, Any] = {
        "provider_available": provider_ready,
        "embedding_model": embedding_model or DEFAULT_MEMORY_EMBEDDING_MODEL,
        "limit": safe_limit,
        "statuses": safe_statuses,
        "attempted": 0,
        "ready": 0,
        "unavailable": 0,
        "failed": 0,
        "skipped": 0,
        "event_ids": [],
    }
    if not provider_ready:
        summary["skipped"] = safe_limit
        summary["reason"] = "embedding_provider_unavailable"
        return summary

    rows = await db.fetch(
        """
        SELECT id, user_id, event_type, event_hash, text, embedding_status
        FROM neoeats_user_memory_events
        WHERE user_id = $1
          AND COALESCE(embedding_status, 'pending') = ANY($2::text[])
          AND text IS NOT NULL
          AND length(trim(text)) > 0
        ORDER BY updated_at DESC, created_at DESC
        LIMIT $3
        """,
        user_id,
        safe_statuses,
        safe_limit,
    )
    for row in rows or []:
        data = dict(row)
        event_hash = str(data.get("event_hash") or "").strip()
        event_type = str(data.get("event_type") or "").strip()
        event_text = _normalize_text(data.get("text"))
        if not event_hash or not event_type or not event_text:
            summary["skipped"] += 1
            continue
        status = await _store_memory_event_embedding(
            db,
            user_id=user_id,
            event_type=event_type,
            event_hash=event_hash,
            text=event_text,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model or DEFAULT_MEMORY_EMBEDDING_MODEL,
        )
        summary["attempted"] += 1
        summary[str(status)] = int(summary.get(str(status), 0)) + 1
        if data.get("id"):
            summary["event_ids"].append(str(data.get("id")))
    return summary


async def memory_embedding_global_stats(
    db: Any,
    *,
    statuses: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    safe_statuses = _safe_embedding_statuses(statuses)
    row = await db.fetchrow(
        """
        SELECT COUNT(*) AS count,
               COUNT(DISTINCT user_id) AS user_count,
               MAX(updated_at) AS last_updated_at
        FROM neoeats_user_memory_events
        """,
    )
    embedding_rows = await db.fetch(
        """
        SELECT COALESCE(embedding_status, 'pending') AS embedding_status,
               COUNT(*) AS count,
               COUNT(DISTINCT user_id) AS user_count
        FROM neoeats_user_memory_events
        GROUP BY embedding_status
        ORDER BY count DESC, embedding_status
        """,
    )
    backlog_row = await db.fetchrow(
        """
        SELECT COUNT(*) AS count,
               COUNT(DISTINCT user_id) AS user_count
        FROM neoeats_user_memory_events
        WHERE COALESCE(embedding_status, 'pending') = ANY($1::text[])
          AND text IS NOT NULL
          AND length(trim(text)) > 0
        """,
        safe_statuses,
    )
    data = dict(row or {})
    backlog = dict(backlog_row or {})
    updated_at = data.get("last_updated_at")
    event_count = int(data.get("count") or 0)
    embedding_status_counts = {
        str(item.get("embedding_status") or "pending"): int(item.get("count") or 0)
        for item in [dict(entry) for entry in (embedding_rows or [])]
        if str(item.get("embedding_status") or "pending")
    }
    embedding_status_user_counts = {
        str(item.get("embedding_status") or "pending"): int(item.get("user_count") or 0)
        for item in [dict(entry) for entry in (embedding_rows or [])]
        if str(item.get("embedding_status") or "pending")
    }
    embedding_ready_count = int(embedding_status_counts.get("ready") or 0)
    return {
        "event_count": event_count,
        "user_count": int(data.get("user_count") or 0),
        "last_updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "by_embedding_status": embedding_status_counts,
        "users_by_embedding_status": embedding_status_user_counts,
        "embedding_ready_count": embedding_ready_count,
        "embedding_coverage_pct": round((embedding_ready_count / event_count) * 100.0, 2) if event_count else 0.0,
        "backlog_statuses": safe_statuses,
        "backlog_event_count": int(backlog.get("count") or 0),
        "backlog_user_count": int(backlog.get("user_count") or 0),
    }


async def backfill_memory_event_embeddings_for_all_users(
    db: Any,
    *,
    embedding_provider: Optional[Any] = None,
    embedding_model: str = DEFAULT_MEMORY_EMBEDDING_MODEL,
    limit_per_user: int = 50,
    max_users: int = 25,
    statuses: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    safe_limit_per_user = max(1, min(250, int(limit_per_user or 50)))
    safe_max_users = max(1, min(200, int(max_users or 25)))
    safe_statuses = _safe_embedding_statuses(statuses)
    provider_ready = embedding_provider_available(embedding_provider)
    candidate_rows = await db.fetch(
        """
        SELECT user_id,
               COUNT(*) AS candidate_count,
               MAX(updated_at) AS last_updated_at
        FROM neoeats_user_memory_events
        WHERE COALESCE(embedding_status, 'pending') = ANY($1::text[])
          AND text IS NOT NULL
          AND length(trim(text)) > 0
        GROUP BY user_id
        ORDER BY last_updated_at DESC NULLS LAST, user_id
        LIMIT $2
        """,
        safe_statuses,
        safe_max_users,
    )
    summary: Dict[str, Any] = {
        "provider_available": provider_ready,
        "embedding_model": embedding_model or DEFAULT_MEMORY_EMBEDDING_MODEL,
        "limit_per_user": safe_limit_per_user,
        "max_users": safe_max_users,
        "statuses": safe_statuses,
        "dry_run": bool(dry_run),
        "users_considered": 0,
        "attempted": 0,
        "ready": 0,
        "unavailable": 0,
        "failed": 0,
        "skipped": 0,
        "event_ids": [],
        "users": [],
    }

    for row in candidate_rows or []:
        data = dict(row)
        user_id = str(data.get("user_id") or "").strip()
        candidate_count = int(data.get("candidate_count") or 0)
        if not user_id:
            continue
        user_entry: Dict[str, Any] = {
            "user_id": user_id,
            "candidate_count": candidate_count,
            "last_updated_at": data.get("last_updated_at").isoformat()
            if hasattr(data.get("last_updated_at"), "isoformat")
            else data.get("last_updated_at"),
        }
        summary["users_considered"] += 1

        if dry_run or not provider_ready:
            skipped = min(candidate_count, safe_limit_per_user)
            summary["skipped"] += skipped
            user_entry.update(
                {
                    "attempted": 0,
                    "ready": 0,
                    "unavailable": 0,
                    "failed": 0,
                    "skipped": skipped,
                    "event_ids": [],
                }
            )
            summary["users"].append(user_entry)
            continue

        user_summary = await backfill_memory_event_embeddings(
            db,
            user_id=user_id,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model or DEFAULT_MEMORY_EMBEDDING_MODEL,
            limit=safe_limit_per_user,
            statuses=safe_statuses,
        )
        for key in ("attempted", "ready", "unavailable", "failed", "skipped"):
            summary[key] = int(summary.get(key, 0)) + int(user_summary.get(key) or 0)
        event_ids = [str(event_id) for event_id in (user_summary.get("event_ids") or []) if str(event_id)]
        summary["event_ids"].extend(event_ids)
        user_entry.update(
            {
                "attempted": int(user_summary.get("attempted") or 0),
                "ready": int(user_summary.get("ready") or 0),
                "unavailable": int(user_summary.get("unavailable") or 0),
                "failed": int(user_summary.get("failed") or 0),
                "skipped": int(user_summary.get("skipped") or 0),
                "event_ids": event_ids,
            }
        )
        summary["users"].append(user_entry)

    if dry_run:
        summary["reason"] = "dry_run"
    elif not provider_ready:
        summary["reason"] = "embedding_provider_unavailable"
    return summary


def _row_to_event(row: Any) -> Dict[str, Any]:
    data = dict(row)
    payload = data.get("payload")
    if isinstance(payload, str):
        payload = _safe_json(payload)
    if not isinstance(payload, dict):
        payload = {}
    created_at = data.get("created_at")
    updated_at = data.get("updated_at")
    event = {
        "id": str(data.get("id") or ""),
        "event_type": str(data.get("event_type") or ""),
        "source": str(data.get("source") or ""),
        "subject": data.get("subject"),
        "text": str(data.get("text") or ""),
        "confidence": _clamp_confidence(data.get("confidence")),
        "payload": payload,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else data.get("created_at"),
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else data.get("updated_at"),
    }
    if data.get("embedding_model") is not None:
        event["embedding_model"] = str(data.get("embedding_model") or "")
    if data.get("embedding_status") is not None:
        event["embedding_status"] = str(data.get("embedding_status") or "")
    vector_similarity = _clamp_similarity(data.get("vector_similarity"))
    if vector_similarity is not None:
        event["vector_similarity"] = vector_similarity
    return event


def score_memory_event(event: Dict[str, Any], *, query: str) -> float:
    query_tokens = _tokens(query)
    event_text = " ".join(
        str(part or "")
        for part in [
            event.get("event_type"),
            event.get("subject"),
            event.get("text"),
            json.dumps(event.get("payload") or {}, ensure_ascii=False, default=str),
        ]
    )
    event_tokens = _tokens(event_text)
    overlap = len(query_tokens.intersection(event_tokens))
    token_score = overlap / math.sqrt(max(1, len(query_tokens)) * max(1, len(event_tokens))) if query_tokens else 0.0
    confidence = _clamp_confidence(event.get("confidence"))
    event_type = str(event.get("event_type") or "")
    type_boost = 0.18 if event_type in {"pantry_item_confirmed", "scan_item_confirmed", "receipt_item_confirmed", "cooking_completed"} else 0.0
    if event_type.startswith("chat_"):
        type_boost += 0.08
    subject_tokens = _tokens(event.get("subject"))
    subject_boost = 0.12 if query_tokens and subject_tokens and query_tokens.intersection(subject_tokens) else 0.0
    age = _age_days(event.get("updated_at") or event.get("created_at"))
    recency_boost = 0.0 if age is None else max(0.0, 0.1 * (1.0 - min(age, 90.0) / 90.0))
    return round(token_score + (confidence * 0.28) + type_boost + subject_boost + recency_boost, 4)


def explain_memory_event_match(event: Dict[str, Any], *, query: str) -> List[str]:
    reasons: List[str] = []
    query_tokens = _tokens(query)
    event_tokens = _tokens(
        " ".join(
            str(part or "")
            for part in [
                event.get("event_type"),
                event.get("subject"),
                event.get("text"),
                json.dumps(event.get("payload") or {}, ensure_ascii=False, default=str),
            ]
        )
    )
    overlap = sorted(query_tokens.intersection(event_tokens))
    if overlap:
        reasons.append("token_overlap:" + ",".join(overlap[:6]))
    if _clamp_confidence(event.get("confidence")) >= 0.8:
        reasons.append("high_confidence")
    event_type = str(event.get("event_type") or "")
    if event_type in {"pantry_item_confirmed", "scan_item_confirmed", "receipt_item_confirmed", "cooking_completed"}:
        reasons.append("confirmed_user_event")
    if event_type.startswith("chat_"):
        reasons.append("chat_signal")
    age = _age_days(event.get("updated_at") or event.get("created_at"))
    if age is not None and age <= 14:
        reasons.append("recent")
    return reasons


async def _fetch_vector_memory_events(
    db: Any,
    *,
    user_id: str,
    query: str,
    limit: int,
    event_types: List[str],
    embedding_provider: Any,
    embedding_model: str,
) -> List[Dict[str, Any]]:
    query_embedding = await _call_embedding_provider(
        embedding_provider,
        query,
        model=embedding_model,
        task_type="retrieval_query",
    )
    vector_literal = _embedding_to_pgvector_literal(query_embedding)
    if not vector_literal:
        return []

    if event_types:
        rows = await db.fetch(
            """
            SELECT id, event_type, source, subject, text, confidence, payload, created_at, updated_at,
                   embedding_model, embedding_status,
                   1 - (embedding <=> $3::vector) AS vector_similarity
            FROM neoeats_user_memory_events
            WHERE user_id = $1
              AND event_type = ANY($2::text[])
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $3::vector
            LIMIT $4
            """,
            user_id,
            event_types,
            vector_literal,
            limit,
        )
    else:
        rows = await db.fetch(
            """
            SELECT id, event_type, source, subject, text, confidence, payload, created_at, updated_at,
                   embedding_model, embedding_status,
                   1 - (embedding <=> $2::vector) AS vector_similarity
            FROM neoeats_user_memory_events
            WHERE user_id = $1
              AND embedding IS NOT NULL
            ORDER BY embedding <=> $2::vector
            LIMIT $3
            """,
            user_id,
            vector_literal,
            limit,
        )
    return [_row_to_event(row) for row in rows or []]


async def retrieve_memory_events(
    db: Any,
    *,
    user_id: str,
    query: str,
    limit: int = 8,
    lookback: int = 120,
    event_types: Optional[Iterable[str]] = None,
    embedding_provider: Optional[Any] = None,
    embedding_model: str = DEFAULT_MEMORY_EMBEDDING_MODEL,
) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(30, int(limit or 8)))
    safe_lookback = max(safe_limit, min(500, int(lookback or 120)))
    types = [str(item) for item in (event_types or []) if str(item).strip()]
    vector_events: List[Dict[str, Any]] = []

    if embedding_provider is not None and _normalize_text(query):
        try:
            vector_events = await _fetch_vector_memory_events(
                db,
                user_id=user_id,
                query=query,
                limit=max(safe_limit, min(30, safe_limit * 2)),
                event_types=types,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model or DEFAULT_MEMORY_EMBEDDING_MODEL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("NeoEats vector memory retrieval unavailable: %s", exc)

    if types:
        rows = await db.fetch(
            """
            SELECT id, event_type, source, subject, text, confidence, payload, created_at, updated_at,
                   embedding_model, embedding_status
            FROM neoeats_user_memory_events
            WHERE user_id = $1 AND event_type = ANY($2::text[])
            ORDER BY created_at DESC
            LIMIT $3
            """,
            user_id,
            types,
            safe_lookback,
        )
    else:
        rows = await db.fetch(
            """
            SELECT id, event_type, source, subject, text, confidence, payload, created_at, updated_at,
                   embedding_model, embedding_status
            FROM neoeats_user_memory_events
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            safe_lookback,
        )

    events_by_id: Dict[str, Dict[str, Any]] = {}
    for event in vector_events:
        event_id = str(event.get("id") or "")
        if event_id:
            events_by_id[event_id] = event
    for event in [_row_to_event(row) for row in rows or []]:
        event_id = str(event.get("id") or "")
        if event_id in events_by_id:
            merged = dict(event)
            merged.update({key: value for key, value in events_by_id[event_id].items() if value is not None})
            events_by_id[event_id] = merged
        elif event_id:
            events_by_id[event_id] = event

    events = list(events_by_id.values())
    for event in events:
        lexical_score = score_memory_event(event, query=query)
        vector_similarity = _clamp_similarity(event.get("vector_similarity"))
        if vector_similarity is not None:
            event["score"] = round(lexical_score + (vector_similarity * 0.45) + 0.08, 4)
            event["retrieval_mode"] = "hybrid_vector_lexical"
            reasons = explain_memory_event_match(event, query=query)
            reasons.insert(0, f"vector_similarity:{vector_similarity:.3f}")
            event["match_reasons"] = reasons
        else:
            event["score"] = lexical_score
            event["retrieval_mode"] = "lexical"
            event["match_reasons"] = explain_memory_event_match(event, query=query)
    return sorted(events, key=lambda event: (float(event.get("score") or 0.0), str(event.get("created_at") or "")), reverse=True)[:safe_limit]


def memory_context_from_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    safe_events = [event for event in events if isinstance(event, dict)]
    has_vector_matches = any(event.get("vector_similarity") is not None for event in safe_events)
    ranking = (
        ["vector_similarity", "token_overlap", "confidence", "event_type", "subject", "recency"]
        if has_vector_matches
        else ["token_overlap", "confidence", "event_type", "subject", "recency"]
    )
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "retrieval": {
            "mode": "hybrid_vector_lexical_rag" if has_vector_matches else "lexical_event_rag",
            "embedding_status": "active" if has_vector_matches else "prepared_not_active",
            "ranking": ranking,
            "event_count": len(safe_events),
        },
        "retrieved_events": safe_events,
        "summary": [
            {
                "event_type": event.get("event_type"),
                "subject": event.get("subject"),
                "source": event.get("source"),
                "text": event.get("text"),
                "confidence": event.get("confidence"),
                "score": event.get("score"),
                "vector_similarity": event.get("vector_similarity"),
                "match_reasons": event.get("match_reasons") or [],
            }
            for event in safe_events
        ],
    }


async def memory_event_stats(db: Any, *, user_id: str) -> Dict[str, Any]:
    row = await db.fetchrow(
        """
        SELECT COUNT(*) AS count, MAX(updated_at) AS last_updated_at
        FROM neoeats_user_memory_events
        WHERE user_id = $1
        """,
        user_id,
    )
    type_rows = await db.fetch(
        """
        SELECT event_type, COUNT(*) AS count
        FROM neoeats_user_memory_events
        WHERE user_id = $1
        GROUP BY event_type
        ORDER BY count DESC, event_type
        """,
        user_id,
    )
    embedding_rows = await db.fetch(
        """
        SELECT COALESCE(embedding_status, 'pending') AS embedding_status, COUNT(*) AS count
        FROM neoeats_user_memory_events
        WHERE user_id = $1
        GROUP BY embedding_status
        ORDER BY count DESC, embedding_status
        """,
        user_id,
    )
    data = dict(row or {})
    updated_at = data.get("last_updated_at")
    event_count = int(data.get("count") or 0)
    embedding_status_counts = {
        str(item.get("embedding_status") or "pending"): int(item.get("count") or 0)
        for item in [dict(entry) for entry in (embedding_rows or [])]
        if str(item.get("embedding_status") or "pending")
    }
    embedding_ready_count = int(embedding_status_counts.get("ready") or 0)
    return {
        "event_count": event_count,
        "last_updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "by_event_type": {
            str(item.get("event_type") or ""): int(item.get("count") or 0)
            for item in [dict(entry) for entry in (type_rows or [])]
            if str(item.get("event_type") or "")
        },
        "by_embedding_status": embedding_status_counts,
        "embedding_ready_count": embedding_ready_count,
        "embedding_coverage_pct": round((embedding_ready_count / event_count) * 100.0, 2) if event_count else 0.0,
    }


async def export_memory_events(db: Any, *, user_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(1000, int(limit or 500)))
    rows = await db.fetch(
        """
        SELECT id, event_type, source, subject, text, confidence, payload, created_at, updated_at
        FROM neoeats_user_memory_events
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id,
        safe_limit,
    )
    return [_row_to_event(row) for row in rows or []]


async def delete_memory_events(db: Any, *, user_id: str) -> None:
    await db.execute(
        "DELETE FROM neoeats_user_memory_events WHERE user_id = $1",
        user_id,
    )
