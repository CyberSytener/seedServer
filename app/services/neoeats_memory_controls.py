from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict


MEMORY_CONTROLS_SCHEMA_VERSION = "neoeats_memory_controls_v1"

DEFAULT_MEMORY_CONTROLS: Dict[str, Any] = {
    "schema_version": MEMORY_CONTROLS_SCHEMA_VERSION,
    "learning_enabled": True,
    "rag_retrieval_enabled": True,
    "personalization_enabled": True,
    "sources": {
        "chat": True,
        "pantry": True,
        "scan": True,
        "receipt": True,
        "cooking": True,
        "recipe": True,
        "profile": True,
    },
    "retention_days": 365,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_meta_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _coerce_bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _coerce_retention_days(value: Any, fallback: int = 365) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = fallback
    return max(30, min(1825, parsed))


def memory_controls_from_meta(meta: Dict[str, Any] | None) -> Dict[str, Any]:
    safe_meta = meta if isinstance(meta, dict) else {}
    stored = safe_meta.get("neoeats_memory_controls")
    stored = stored if isinstance(stored, dict) else {}
    stored_sources = stored.get("sources") if isinstance(stored.get("sources"), dict) else {}

    defaults = DEFAULT_MEMORY_CONTROLS
    default_sources = defaults["sources"]
    return {
        "schema_version": MEMORY_CONTROLS_SCHEMA_VERSION,
        "learning_enabled": _coerce_bool(stored.get("learning_enabled"), defaults["learning_enabled"]),
        "rag_retrieval_enabled": _coerce_bool(
            stored.get("rag_retrieval_enabled"),
            defaults["rag_retrieval_enabled"],
        ),
        "personalization_enabled": _coerce_bool(
            stored.get("personalization_enabled"),
            defaults["personalization_enabled"],
        ),
        "sources": {
            key: _coerce_bool(stored_sources.get(key), bool(default_sources[key]))
            for key in default_sources
        },
        "retention_days": _coerce_retention_days(stored.get("retention_days"), defaults["retention_days"]),
        "updated_at": str(stored.get("updated_at") or safe_meta.get("updated_at") or _now_iso()),
    }


def patch_memory_controls(meta: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    controls = memory_controls_from_meta(meta)
    for key in ("learning_enabled", "rag_retrieval_enabled", "personalization_enabled"):
        if key in patch:
            controls[key] = _coerce_bool(patch.get(key), bool(controls[key]))

    if "retention_days" in patch:
        controls["retention_days"] = _coerce_retention_days(patch.get("retention_days"), controls["retention_days"])

    patch_sources = patch.get("sources")
    if isinstance(patch_sources, dict):
        sources = dict(controls["sources"])
        for key in sources:
            if key in patch_sources:
                sources[key] = _coerce_bool(patch_sources.get(key), bool(sources[key]))
        controls["sources"] = sources

    controls["schema_version"] = MEMORY_CONTROLS_SCHEMA_VERSION
    controls["updated_at"] = _now_iso()
    meta["neoeats_memory_controls"] = controls
    return controls


def _source_key(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if "receipt" in normalized:
        return "receipt"
    if "cook" in normalized:
        return "cooking"
    if "recipe" in normalized or "recommend" in normalized:
        return "recipe"
    if "profile" in normalized or "preference" in normalized or "dietary" in normalized:
        return "profile"
    if "chat" in normalized:
        return "chat"
    if "vision" in normalized or "scan" in normalized:
        return "scan"
    return "pantry"


def memory_learning_enabled(meta: Dict[str, Any] | None, *, source: str = "") -> bool:
    controls = memory_controls_from_meta(meta)
    if not controls["learning_enabled"]:
        return False
    source_key = _source_key(source)
    return bool(controls["sources"].get(source_key, True))


def memory_retrieval_enabled(meta: Dict[str, Any] | None) -> bool:
    controls = memory_controls_from_meta(meta)
    return bool(controls["personalization_enabled"] and controls["rag_retrieval_enabled"])


def clear_structured_memory(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta["neoeats_memory"] = {
        "schema_version": "neoeats_user_memory_v1",
        "facts": [],
        "signals": {
            "diet_tags": [],
            "goals": [],
            "cuisines": [],
            "likes": [],
            "dislikes": [],
            "constraints": [],
        },
        "recent_messages": [],
        "ingredient_counts": {},
        "cleared_at": _now_iso(),
    }
    return meta["neoeats_memory"]
