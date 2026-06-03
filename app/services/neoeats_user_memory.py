from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple


SCHEMA_VERSION = "neoeats_user_memory_v1"
MAX_FACTS = 80
MAX_RECENT_MESSAGES = 8

DIET_MARKERS = {
    "vegan": ["vegan", "plant based", "plant-based", "веган"],
    "vegetarian": ["vegetarian", "veggie", "вегетариан"],
    "halal": ["halal", "халяль"],
    "kosher": ["kosher", "кошер"],
    "keto": ["keto", "кетo", "кето"],
    "gluten_free": ["gluten free", "gluten-free", "без глютена"],
    "lactose_free": ["lactose free", "lactose-free", "без лактозы"],
}

GOAL_MARKERS = {
    "high_protein": ["high protein", "protein", "белок", "белков"],
    "healthy": ["healthy", "lean", "light", "здоров", "легк"],
    "quick": ["quick", "fast", "15 min", "быстр"],
    "budget": ["budget", "cheap", "under ", "дешев", "бюджет"],
    "zero_waste": ["zero waste", "expire", "expiring", "use first", "не выбрасывать", "истека"],
}

CUISINE_MARKERS = {
    "italian": ["italian", "pasta", "итальян"],
    "asian": ["asian", "soy sauce", "азиат"],
    "indian": ["indian", "curry", "индий"],
    "japanese": ["japanese", "sushi", "ramen", "япон"],
    "mexican": ["mexican", "taco", "мексикан"],
    "mediterranean": ["mediterranean", "greek", "средизем"],
    "norwegian": ["norwegian", "nordic", "норвеж"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _fact_id(kind: str, value: str) -> str:
    digest = hashlib.sha1(f"{kind}:{value}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def _ensure_memory(value: Any) -> Dict[str, Any]:
    memory = dict(value) if isinstance(value, dict) else {}
    memory.setdefault("schema_version", SCHEMA_VERSION)
    memory.setdefault("facts", [])
    memory.setdefault("signals", {})
    memory.setdefault("recent_messages", [])
    memory.setdefault("ingredient_counts", {})
    return memory


def _append_unique(items: List[str], value: str, limit: int = 24) -> None:
    normalized = _normalize_token(value)
    if not normalized:
        return
    if normalized not in items:
        items.append(normalized)
    del items[limit:]


def _upsert_fact(memory: Dict[str, Any], kind: str, value: str, evidence: str, confidence: float = 0.75) -> bool:
    normalized_value = _normalize_token(value)
    if not normalized_value:
        return False

    facts = memory.setdefault("facts", [])
    now = _now_iso()
    fid = _fact_id(kind, normalized_value)
    for fact in facts:
        if isinstance(fact, dict) and fact.get("id") == fid:
            fact["confidence"] = max(float(fact.get("confidence") or 0.0), confidence)
            fact["updated_at"] = now
            fact["evidence"] = evidence[:240]
            return True

    facts.append(
        {
            "id": fid,
            "kind": kind,
            "value": normalized_value,
            "confidence": max(0.0, min(1.0, confidence)),
            "evidence": evidence[:240],
            "created_at": now,
            "updated_at": now,
        }
    )
    del facts[:-MAX_FACTS]
    return True


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker in text for marker in markers)


def _capture_after_patterns(text: str, patterns: Iterable[str]) -> List[str]:
    matches: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _normalize_token(match.group(1))
            value = re.split(r"[,.;!?]|\band\b|\bor\b", value)[0].strip()
            if value and len(value.split()) <= 4:
                matches.append(value)
    return matches


def learn_user_memory(
    memory: Any,
    *,
    message: str,
    intent: str,
    detected_items: List[Dict[str, Any]] | None = None,
) -> Tuple[Dict[str, Any], bool]:
    next_memory = _ensure_memory(memory)
    changed = False
    text = _normalize_token(message)
    signals = next_memory.setdefault("signals", {})

    for key in ("diet_tags", "goals", "cuisines", "likes", "dislikes", "constraints"):
        value = signals.get(key)
        signals[key] = list(value) if isinstance(value, list) else []

    for diet, markers in DIET_MARKERS.items():
        if _contains_any(text, markers):
            _append_unique(signals["diet_tags"], diet)
            changed = _upsert_fact(next_memory, "diet", diet, message, 0.86) or changed

    for goal, markers in GOAL_MARKERS.items():
        if _contains_any(text, markers):
            _append_unique(signals["goals"], goal)
            changed = _upsert_fact(next_memory, "goal", goal, message, 0.72) or changed

    for cuisine, markers in CUISINE_MARKERS.items():
        if _contains_any(text, markers):
            _append_unique(signals["cuisines"], cuisine)
            changed = _upsert_fact(next_memory, "cuisine", cuisine, message, 0.68) or changed

    for item in _capture_after_patterns(
        text,
        [
            r"(?:allergic to|allergy to|avoid|do not eat|don't eat|no)\s+([a-zа-яё0-9 _-]{2,40})",
            r"(?:не ем|без)\s+([a-zа-яё0-9 _-]{2,40})",
        ],
    ):
        _append_unique(signals["constraints"], item)
        _append_unique(signals["dislikes"], item)
        changed = _upsert_fact(next_memory, "constraint", item, message, 0.9) or changed

    for item in _capture_after_patterns(
        text,
        [
            r"(?:love|like|favorite|prefer)\s+([a-zа-яё0-9 _-]{2,40})",
            r"(?:люблю|нравится|предпочитаю)\s+([a-zа-яё0-9 _-]{2,40})",
        ],
    ):
        _append_unique(signals["likes"], item)
        changed = _upsert_fact(next_memory, "like", item, message, 0.68) or changed

    if detected_items:
        counts = next_memory.setdefault("ingredient_counts", {})
        for item in detected_items:
            name = _normalize_token(item.get("canonical_name") or item.get("name"))
            if not name:
                continue
            counts[name] = int(counts.get(name) or 0) + 1
            changed = _upsert_fact(next_memory, "frequent_ingredient", name, f"intent={intent}", 0.55) or changed

    recent = next_memory.setdefault("recent_messages", [])
    if text:
        recent.append({"message": message[:240], "intent": str(intent or "CHAT").upper(), "at": _now_iso()})
        del recent[:-MAX_RECENT_MESSAGES]
        changed = True

    if changed:
        next_memory["updated_at"] = _now_iso()

    return next_memory, changed


def retrieve_user_memory_context(memory: Any, *, message: str, limit: int = 12) -> Dict[str, Any]:
    safe_memory = _ensure_memory(memory)
    text = _normalize_token(message)
    tokens = {token for token in re.split(r"[^a-zа-яё0-9_]+", text) if len(token) >= 3}
    facts = [fact for fact in safe_memory.get("facts", []) if isinstance(fact, dict)]

    def score_fact(fact: Dict[str, Any]) -> float:
        value = _normalize_token(fact.get("value"))
        kind = _normalize_token(fact.get("kind"))
        score = float(fact.get("confidence") or 0.0)
        if kind in {"constraint", "diet"}:
            score += 0.45
        if value and value in text:
            score += 0.6
        if tokens and any(token in value for token in tokens):
            score += 0.35
        return score

    retrieved = sorted(facts, key=score_fact, reverse=True)[:limit]
    signals = safe_memory.get("signals") if isinstance(safe_memory.get("signals"), dict) else {}

    return {
        "schema_version": SCHEMA_VERSION,
        "signals": signals,
        "retrieved_facts": retrieved,
        "profile_summary": {
            "diet_tags": signals.get("diet_tags") or [],
            "goals": signals.get("goals") or [],
            "cuisines": signals.get("cuisines") or [],
            "constraints": signals.get("constraints") or [],
            "likes": signals.get("likes") or [],
            "dislikes": signals.get("dislikes") or [],
        },
    }


def merge_memory_into_taste_profile(profile: Dict[str, Any], memory_context: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(profile or {})
    summary = memory_context.get("profile_summary") if isinstance(memory_context, dict) else {}
    if not isinstance(summary, dict):
        return merged

    tags = list(merged.get("tags") or [])
    constraints = list(merged.get("constraints") or [])
    for value in summary.get("diet_tags") or []:
        _append_unique(tags, str(value))
    for value in (summary.get("constraints") or []) + (summary.get("dislikes") or []):
        _append_unique(constraints, str(value))

    if tags:
        merged["tags"] = tags
    if constraints:
        merged["constraints"] = constraints
    merged["memory"] = summary
    return merged
