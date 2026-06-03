"""NeoEats chat handler — extracted from main.py (Task 1.2).

Single public entry-point: :func:`handle_neoeats_chat`.

All previously-inline closures have been promoted to module-level helpers
(prefixed with ``_``) so they remain private but are no longer nested ~800
lines deep inside ``create_app()``.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.hybrid_recipes import suggest_hybrid_recipes
from app.services.neoeats_recipe_card import (
    build_chat_recommendation_from_recipe_card,
    build_safe_error_recipe_card,
    compile_recipe_card_v1,
)
from app.services.neoeats_user_memory import (
    learn_user_memory,
    merge_memory_into_taste_profile,
    retrieve_user_memory_context,
)
from app.services.pantry_normalizer import (
    canonicalize_product,
    extract_items_from_message,
    normalize_quantity_unit,
)

# ---------------------------------------------------------------------------
# Pure / near-pure helpers
# ---------------------------------------------------------------------------


def _extract_message(action: Any, payload: dict) -> str:
    """Pull the user message from action.params or raw payload."""
    params = action.params or {}
    if isinstance(params, dict):
        msg = str(params.get("message") or params.get("text") or "").strip()
        if msg:
            return msg
    return str((((payload.get("action") or {}).get("args") or {}).get("message")) or "").strip()


def _infer_intent(message: str) -> str:
    text = (message or "").lower()
    cook_markers = [
        "what can i cook", "what should i cook", "recipe", "recipes", "meal", "cook",
        "hybrid", "suggest", "recommend", "lunch", "dinner", "breakfast", "brunch",
        "snack", "dessert", "plan", "prepare", "make me", "high-protein", "low-carb",
        "healthy", "quick", "what to eat", "hungry", "приготов", "рецепт", "обед",
        "ужин", "завтрак", "перекус", "предложи", "порекомендуй",
    ]
    add_markers = [
        "add", "added", "put", "store", "fridge", "inventory", "bought", "receipt", "scan",
        "купил", "купила", "добавь", "добавил", "холодильник", "инвентарь",
        "kjopt", "kjøpt", "legg til", "kjoleskap", "kjøleskap",
    ]
    if any(marker in text for marker in cook_markers):
        return "cook"
    if any(marker in text for marker in add_markers):
        return "add_food"
    return "chat"


def _extract_structured_items(action: Any) -> List[Dict[str, Any]]:
    params = action.params or {}
    candidates: list = []
    if isinstance(params, dict):
        if isinstance(params.get("items"), list):
            candidates = params.get("items")
        elif isinstance(params.get("item"), dict):
            candidates = [params.get("item")]

    normalized: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        brand = str(item.get("brand") or "").strip() or None
        canonicalized = canonicalize_product(name, brand=brand, preferred_language="en")
        quantity, unit = normalize_quantity_unit(
            item.get("quantity"),
            item.get("unit"),
            name=name,
        )
        normalized.append(
            {
                "name": str(canonicalized.get("display_name") or name).strip(),
                "canonical_name": str(canonicalized.get("canonical_name") or "").strip(),
                "display_name": str(canonicalized.get("display_name") or name).strip(),
                "category": item.get("category") or canonicalized.get("category"),
                "quantity": quantity,
                "unit": unit,
                "confidence": float(item.get("confidence") or 0.9),
                "expires_at": item.get("expires_at"),
                "brand": brand,
                "original_name": name,
            }
        )
    return normalized


def _extract_taste_profile(params: Dict[str, Any]) -> Dict[str, Any]:
    value = params.get("user_taste_profile") or params.get("taste_profile")
    return dict(value) if isinstance(value, dict) else {}


def _extract_context_payload(params: Dict[str, Any]) -> Dict[str, Any]:
    value = params.get("context")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _inventory_names(inv: List[Dict[str, Any]]) -> List[str]:
    return [str(item.get("name") or "").strip().lower() for item in inv if str(item.get("name") or "").strip()]


def _has_basic_products(inv: List[Dict[str, Any]]) -> bool:
    names = _inventory_names(inv)
    basic_markers = ["bread", "egg", "eggs"]
    return any(any(marker in name for marker in basic_markers) for name in names)


def _is_vegan_profile(profile: Dict[str, Any]) -> bool:
    if not isinstance(profile, dict):
        return False
    blob_parts: List[str] = []
    for key in ["tags", "diet", "constraints", "preferences", "profile", "notes"]:
        value = profile.get(key)
        if isinstance(value, list):
            blob_parts.extend([str(x) for x in value])
        elif value is not None:
            blob_parts.append(str(value))
    blob_parts.extend([f"{k}:{v}" for k, v in profile.items() if not isinstance(v, (dict, list))])
    blob = " ".join(blob_parts).lower()
    return "vegan" in blob


def _has_vegan_friendly_items(inv: List[Dict[str, Any]]) -> bool:
    names = _inventory_names(inv)
    if not names:
        return False
    non_vegan_markers = [
        "beef", "steak", "chicken", "pork", "fish", "salmon", "tuna", "shrimp", "egg", "eggs",
        "milk", "cheese", "yogurt", "butter", "cream",
    ]
    for name in names:
        if not any(marker in name for marker in non_vegan_markers):
            return True
    return False


def _zero_day_items(
    inv: List[Dict[str, Any]],
    coerce_date_safe: Callable,
) -> List[str]:
    today = datetime.now(timezone.utc).date()
    critical: List[str] = []
    for item in inv:
        parsed = coerce_date_safe(item.get("expires_at"))
        if parsed is not None and parsed <= today:
            name = str(item.get("name") or "").strip()
            if name:
                critical.append(name)
    return critical


def _extract_recipe_constraints(user_message: str, base: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    lowered = str(user_message or "").lower()
    budget_match = re.search(r"(?:under|below|max|<=)\s*(\d{2,4})\s*(?:nok|kr)?", lowered)
    if budget_match and not any(
        merged.get(key) is not None
        for key in ("budget_limit_nok", "budget_nok", "max_budget_nok", "budget_limit", "budget")
    ):
        merged["budget_limit_nok"] = float(budget_match.group(1))
    if any(token in lowered for token in ("healthy", "health", "high protein", "lean", "light")):
        merged.setdefault("goal", "healthy")
        merged.setdefault("prefer_healthy", True)
    return merged


def _recommendation_rank_score(recommendation: Dict[str, Any]) -> float:
    if not isinstance(recommendation, dict):
        return 0.0
    recipe_card = recommendation.get("recipe_card_v1")
    if isinstance(recipe_card, dict):
        breakdown = recipe_card.get("match_breakdown")
        if isinstance(breakdown, dict):
            try:
                return float(breakdown.get("overall_score_0_100") or recipe_card.get("match_pct") or 0.0)
            except Exception:
                logging.debug("Suppressed exception", exc_info=True)
        try:
            return float(recipe_card.get("match_pct") or 0.0)
        except Exception:
            return 0.0
    try:
        return float(recommendation.get("match_score") or recommendation.get("score") or 0.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Flavor-architect normalisation (previously ~220 LOC inline)
# ---------------------------------------------------------------------------

_ALLOWED_CATEGORIES = {
    "Meat", "Vegetables", "Fruit", "Fish", "Dairy",
    "Bakery", "Staples (Spices/Oil)", "Ready Meals", "Staples",
}


def _normalize_category(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in _ALLOWED_CATEGORIES:
        return "Staples (Spices/Oil)" if raw == "Staples" else raw
    lowered = raw.lower()
    if lowered in {"staples", "spices", "oil"}:
        return "Staples (Spices/Oil)"
    if lowered == "vegetable":
        return "Vegetables"
    return "Staples (Spices/Oil)"


def _fallback_rationale(pantry_names: List[str], recipe_name: str) -> str:
    if len(pantry_names) >= 2:
        return (
            f"I paired your {pantry_names[0]} with {pantry_names[1]} in {recipe_name} so the pantry items complement "
            "each other and stay balanced."
        )
    if pantry_names:
        return (
            f"I used your {pantry_names[0]} as the anchor for {recipe_name} and built supporting flavors around it."
        )
    return f"Built {recipe_name} from the available pantry snapshot with a focus on balance."


def _fallback_ingredients(pantry_names: List[str], pantry_ids: Dict[str, Any]) -> List[Dict[str, Any]]:
    if pantry_names:
        first_name = pantry_names[0]
        second_name = pantry_names[1] if len(pantry_names) > 1 else pantry_names[0]
        return [
            {
                "name": first_name,
                "category": "Staples",
                "status": "owned",
                "pantry_item_id": pantry_ids.get(first_name.lower()),
                "amount": "150g",
            },
            {
                "name": second_name,
                "category": "Staples",
                "status": "owned",
                "pantry_item_id": pantry_ids.get(second_name.lower()),
                "amount": "120g",
            },
            {"name": "Garlic", "category": "Staples", "status": "missing", "price_est": 15, "amount": "2 cloves"},
        ]
    return [
        {"name": "Garlic", "category": "Staples", "status": "missing", "price_est": 15, "amount": "2 cloves"},
        {"name": "Lemon", "category": "Fruit", "status": "missing", "price_est": 12, "amount": "1 pc"},
    ]


def _default_amount_for_ingredient(name: str) -> str:
    lowered = str(name or "").strip().lower()
    if "egg" in lowered:
        return "2 pcs"
    if any(token in lowered for token in ("oil", "milk", "water", "broth", "sauce")):
        return "120 ml"
    if any(token in lowered for token in ("salt", "pepper", "spice", "herb")):
        return "1 tsp"
    return "120 g"


def _safe_flavor_architect_payload(
    payload_in: Optional[Any],
    *,
    user_inventory_rows: List[Dict[str, Any]],
    store_inventory_rows: List[Dict[str, Any]],
    warning: Optional[str],
) -> List[Dict[str, Any]]:
    if isinstance(payload_in, list):
        raw_recipes = payload_in
    elif isinstance(payload_in, dict) and isinstance(payload_in.get("recipes"), list):
        raw_recipes = payload_in.get("recipes")
    elif isinstance(payload_in, dict):
        raw_recipes = [payload_in]
    else:
        raw_recipes = []

    pantry_items = [row for row in user_inventory_rows if str(row.get("name") or "").strip()]
    pantry_names = [str(row.get("name") or "").strip() for row in pantry_items]
    pantry_ids: Dict[str, Any] = {
        str(row.get("name") or "").strip().lower(): row.get("storage_id")
        for row in pantry_items
    }

    normalized: List[Dict[str, Any]] = []
    seen_rationales: set[str] = set()
    for index, row in enumerate(raw_recipes[:3]):
        if not isinstance(row, dict):
            continue
        recipe_name = str(row.get("name") or row.get("recipe_name") or "").strip() or f"Adaptive Pantry Rescue {index + 1}"
        try:
            match_score = int(float(row.get("match_score") or 70))
        except Exception:
            match_score = 70
        match_score = max(0, min(100, match_score))

        ingredients: List[Dict[str, Any]] = []
        for ing in row.get("ingredients") or []:
            if not isinstance(ing, dict):
                continue
            ing_name = str(ing.get("name") or "").strip()
            if not ing_name:
                continue
            status = str(ing.get("status") or "missing").strip().lower()
            if status not in {"owned", "missing"}:
                status = "missing"
            pantry_item_id = ing.get("pantry_item_id") or ing.get("pantry_id")
            if status == "owned" and pantry_item_id is None:
                pantry_item_id = pantry_ids.get(ing_name.lower())
            amount_value = str(ing.get("amount") or "").strip()
            if not amount_value:
                raw_quantity = ing.get("quantity")
                raw_unit = str(ing.get("unit") or "").strip()
                if raw_quantity is not None and raw_unit:
                    try:
                        amount_value = f"{float(raw_quantity):g} {raw_unit}"
                    except Exception:
                        amount_value = ""
            if not amount_value:
                amount_value = _default_amount_for_ingredient(ing_name)
            ingredient: Dict[str, Any] = {
                "name": ing_name,
                "category": _normalize_category(ing.get("category") or "Staples"),
                "status": status,
                "amount": amount_value,
            }
            if status == "owned":
                ingredient["pantry_item_id"] = pantry_item_id
            if status == "missing" and ing.get("price_est") is not None:
                ingredient["price_est"] = ing.get("price_est")
            ingredients.append(ingredient)

        if not ingredients:
            ingredients = _fallback_ingredients(pantry_names, pantry_ids)

        rationale = str(row.get("rationale_for_user") or "").strip()
        if not rationale:
            rationale = _fallback_rationale(pantry_names, recipe_name)
        if warning:
            rationale = f"{warning} {rationale}".strip()
        if rationale in seen_rationales:
            rationale = f"{rationale} Alternative focus: {recipe_name}."
        seen_rationales.add(rationale)

        zero_waste_score = str(row.get("zero_waste_score") or "med").strip().lower()
        if zero_waste_score not in {"high", "med", "low"}:
            zero_waste_score = "med"

        normalized.append(
            {
                "name": recipe_name,
                "recipe_name": recipe_name,
                "match_score": match_score,
                "rationale_for_user": rationale,
                "rationale": rationale,
                "key_ingredients": [
                    str(ing.get("name") or "").strip()
                    for ing in ingredients
                    if str(ing.get("name") or "").strip()
                ],
                "ingredients": ingredients,
                "zero_waste_score": zero_waste_score,
            }
        )

    if not normalized:
        normalized.append(
            {
                "name": "Adaptive Pantry Rescue",
                "recipe_name": "Adaptive Pantry Rescue",
                "match_score": 70,
                "rationale_for_user": _fallback_rationale(pantry_names, "Adaptive Pantry Rescue"),
                "rationale": _fallback_rationale(pantry_names, "Adaptive Pantry Rescue"),
                "ingredients": _fallback_ingredients(pantry_names, pantry_ids),
                "key_ingredients": [
                    str(ing.get("name") or "").strip()
                    for ing in _fallback_ingredients(pantry_names, pantry_ids)
                    if str(ing.get("name") or "").strip()
                ],
                "zero_waste_score": "med",
            }
        )

    if len(normalized) == 1:
        fb_ingredients = _fallback_ingredients(pantry_names, pantry_ids)
        second_name = "Pantry Contrast Bowl"
        second_rationale = _fallback_rationale(pantry_names, second_name)
        if warning:
            second_rationale = f"{warning} {second_rationale}".strip()
        normalized.append(
            {
                "name": second_name,
                "recipe_name": second_name,
                "match_score": 64,
                "rationale_for_user": second_rationale,
                "rationale": second_rationale,
                "ingredients": fb_ingredients,
                "key_ingredients": [
                    str(ing.get("name") or "").strip()
                    for ing in fb_ingredients
                    if str(ing.get("name") or "").strip()
                ],
                "zero_waste_score": "med",
            }
        )

    return normalized


# ---------------------------------------------------------------------------
# Recipe-card builder
# ---------------------------------------------------------------------------

async def _build_facts_first_recommendation(
    recipe_payload: Dict[str, Any],
    *,
    recipe_id_prefix: str,
    user_inventory: List[Dict[str, Any]],
    constraints_payload: Dict[str, Any],
) -> Dict[str, Any]:
    recipe_name = str(recipe_payload.get("name") or recipe_payload.get("recipe_name") or "NeoEats Recipe").strip() or "NeoEats Recipe"
    recipe_id = f"{recipe_id_prefix}_{uuid.uuid4().hex[:8]}"
    draft_recipe = {
        "title": recipe_name,
        "ingredients": list(recipe_payload.get("ingredients") or []),
        "steps": list(recipe_payload.get("steps") or []),
        "servings": 2,
        "time_minutes": 30,
        "tags": ["neoeats", "facts_first"],
    }
    try:
        recipe_card = await compile_recipe_card_v1(
            recipe=draft_recipe,
            normalized_inventory=user_inventory,
            constraints=constraints_payload,
            recipe_id=recipe_id,
            explain=str(recipe_payload.get("rationale_for_user") or recipe_payload.get("rationale") or "").strip() or None,
        )
    except Exception:
        logging.exception("Recipe card compilation failed")
        recipe_card = build_safe_error_recipe_card(
            recipe_id=recipe_id,
            title=recipe_name,
            message="Recipe card compilation failed.",
        )
    return build_chat_recommendation_from_recipe_card(
        recipe_card,
        rationale=str(recipe_payload.get("rationale_for_user") or recipe_payload.get("rationale") or "").strip() or None,
        steps=list(recipe_payload.get("steps") or []),
    )


# ---------------------------------------------------------------------------
# Detected-item normalisation + persistence
# ---------------------------------------------------------------------------

def _normalize_detected_items(detected_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Canonicalise and normalise a list of detected food items."""
    normalized: List[Dict[str, Any]] = []
    for entry in detected_items:
        if not isinstance(entry, dict):
            continue
        raw_name = str(entry.get("canonical_name") or entry.get("name") or entry.get("product_name") or "").strip()
        if not raw_name:
            continue
        brand = str(entry.get("brand") or "").strip() or None
        canonicalized = canonicalize_product(raw_name, brand=brand, preferred_language="en")
        canonical_name = str(canonicalized.get("canonical_name") or raw_name).strip().lower()
        display_name = str(canonicalized.get("display_name") or canonical_name).strip()
        quantity, unit = normalize_quantity_unit(
            entry.get("quantity"),
            entry.get("unit"),
            name=display_name,
        )
        expiry_date = (
            entry.get("expiry_date")
            if entry.get("expiry_date") is not None
            else entry.get("expires_at")
        )
        try:
            confidence_raw = float(entry.get("confidence") or entry.get("confidence_score") or 0.8)
        except Exception:
            confidence_raw = 0.8
        confidence_ratio = confidence_raw / 100.0 if confidence_raw > 1.0 else confidence_raw
        confidence_pct = max(0.0, min(100.0, confidence_ratio * 100.0))
        normalized.append(
            {
                **entry,
                "name": display_name,
                "canonical_name": canonical_name,
                "display_name": display_name,
                "category": entry.get("category") or canonicalized.get("category"),
                "quantity": quantity,
                "unit": unit,
                "expiry_date": expiry_date,
                "confidence": confidence_pct,
                "confidence_score": confidence_ratio,
                "brand": brand,
                "original_name": str(entry.get("original_name") or entry.get("name") or raw_name).strip(),
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

async def handle_neoeats_chat(
    *,
    app: Any,
    action: Any,
    ctx: Any,
    payload: dict,
    get_neoeats_db: Callable,
    persist_detected_items: Callable,
    coerce_date_safe: Callable,
    load_user_memory: Optional[Callable[[str], Dict[str, Any]]] = None,
    save_user_memory: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    load_rag_memory_context: Optional[Callable[[str, str], Any]] = None,
    record_user_memory_event: Optional[Callable[..., Any]] = None,
) -> dict:
    """Process a NeoEats chat action.

    Parameters
    ----------
    app:
        FastAPI application (used for ``app.state.llm_engine`` etc.)
    action:
        Parsed ``RealtimeAction`` with ``.name == "chat"``.
    ctx:
        Auth context (has ``.user_id``).
    payload:
        Raw request JSON.
    get_neoeats_db:
        Async callable returning the NeoEats database connection.
    persist_detected_items:
        ``async (user_id, detected_items, *, source) -> List[FridgeItem]``
    coerce_date_safe:
        ``(value) -> Optional[date]`` — safe date coercion.
    """

    message = _extract_message(action, payload)
    params = action.params if isinstance(action.params, dict) else {}

    user_taste_profile = _extract_taste_profile(params)
    context_payload = _extract_context_payload(params)
    user_memory: Dict[str, Any] = {}
    memory_context: Dict[str, Any] = {}
    rag_memory_context: Dict[str, Any] = {}
    user_inventory: List[Dict[str, Any]] = []
    store_inventory: List[Dict[str, Any]] = []

    if load_user_memory is not None:
        try:
            loaded = load_user_memory(ctx.user_id)
            user_memory = loaded if isinstance(loaded, dict) else {}
        except Exception:
            logging.exception("NeoEats user memory load failed")

    try:
        neoeats_db = await get_neoeats_db()
        user_rows = await neoeats_db.fetch(
            """
            SELECT storage_id, name, quantity, unit, expires_at, metadata
            FROM storage_item
            WHERE (metadata->>'user_id') = $1
            ORDER BY updated_at DESC NULLS LAST
            """,
            ctx.user_id,
        )
        store_rows = await neoeats_db.fetch(
            """
            SELECT ii.item_id,
                   ii.sku,
                   ii.name,
                   ii.category,
                   ii.unit,
                   COALESCE(SUM(il.quantity_available), 0) AS quantity_available
            FROM inventory_item ii
            LEFT JOIN inventory_lot il ON il.item_id = ii.item_id
            WHERE ii.is_active = true
            GROUP BY ii.item_id, ii.sku, ii.name, ii.category, ii.unit
            ORDER BY ii.name
            """,
        )
        user_inventory = [dict(row) for row in (user_rows or [])]
        store_inventory = [dict(row) for row in (store_rows or [])]
    except Exception:
        logging.exception("Chat context fetch failed")

    base_constraints = params.get("constraints") if isinstance(params.get("constraints"), dict) else {}
    constraints_payload = _extract_recipe_constraints(message, base_constraints)
    memory_context = retrieve_user_memory_context(user_memory, message=message)
    if load_rag_memory_context is not None:
        try:
            loaded_rag_context = await load_rag_memory_context(ctx.user_id, message)
            rag_memory_context = loaded_rag_context if isinstance(loaded_rag_context, dict) else {}
        except Exception:
            logging.exception("NeoEats RAG memory context load failed")
    if memory_context.get("retrieved_facts") or memory_context.get("profile_summary"):
        context_payload = {
            **context_payload,
            "user_memory": memory_context,
        }
        user_taste_profile = merge_memory_into_taste_profile(user_taste_profile, memory_context)
    if rag_memory_context.get("retrieved_events"):
        context_payload = {
            **context_payload,
            "user_memory_events": rag_memory_context,
        }

    inferred_intent = _infer_intent(message)
    memory_updated = False

    async def _store_memory_snapshot(intent_value: str, detected: Optional[List[Dict[str, Any]]] = None) -> bool:
        nonlocal user_memory, memory_updated
        changed = False
        try:
            next_memory, changed = learn_user_memory(
                user_memory,
                message=message,
                intent=intent_value,
                detected_items=detected or [],
            )
            if changed:
                user_memory = next_memory
                memory_updated = True
                if save_user_memory is not None:
                    save_user_memory(ctx.user_id, next_memory)
        except Exception:
            logging.exception("NeoEats user memory save failed")
        if record_user_memory_event is not None and (message or detected):
            try:
                normalized_intent = str(intent_value or "CHAT").strip().upper()
                event_type = {
                    "ADD_FOOD": "chat_add_food",
                    "COOK": "chat_cook",
                    "CHAT": "chat_message",
                }.get(normalized_intent, f"chat_{normalized_intent.lower()}")
                await record_user_memory_event(
                    ctx.user_id,
                    event_type=event_type,
                    source="neoeats_chat",
                    subject=message[:160] if message else normalized_intent,
                    text=message,
                    payload={
                        "message": message,
                        "intent": normalized_intent,
                        "detected_items": detected or [],
                        "structured_memory_changed": changed,
                    },
                    confidence=0.74 if normalized_intent in {"ADD_FOOD", "COOK"} else 0.62,
                )
            except Exception:
                logging.exception("NeoEats RAG memory event save failed")
        return changed

    if inferred_intent == "cook":
        inventory_count = len([item for item in user_inventory if str(item.get("name") or "").strip()])
        if inventory_count < 2 and not _has_basic_products(user_inventory):
            flavor_fallback = _safe_flavor_architect_payload(
                None,
                user_inventory_rows=user_inventory,
                store_inventory_rows=store_inventory,
                warning="Low inventory mode",
            )
            facts_recommendations: List[Dict[str, Any]] = []
            for recipe in flavor_fallback:
                if not isinstance(recipe, dict):
                    continue
                facts_recommendations.append(
                    await _build_facts_first_recommendation(
                        recipe,
                        recipe_id_prefix="low_inventory",
                        user_inventory=user_inventory,
                        constraints_payload=constraints_payload,
                    )
                )
            facts_recommendations = sorted(
                facts_recommendations,
                key=_recommendation_rank_score,
                reverse=True,
            )
            await _store_memory_snapshot("COOK")
            return {
                "type": "action.result",
                "session_id": action.metadata.session_id,
                "action_id": action.id,
                "action_type": "chat",
                "status": "ok",
                "result": {
                    "persona_message": "\u0412\u0430\u0448 \u0445\u043e\u043b\u043e\u0434\u0438\u043b\u044c\u043d\u0438\u043a \u043f\u043e\u0447\u0442\u0438 \u043f\u0443\u0441\u0442. \u0425\u043e\u0442\u0438\u0442\u0435 \u0437\u0430\u043a\u0430\u0437\u0430\u0442\u044c '\u0411\u0430\u0437\u043e\u0432\u0443\u044e \u043a\u043e\u0440\u0437\u0438\u043d\u0443' \u0437\u0430 200 NOK?",
                    "detected_items": [],
                    "recommendations": facts_recommendations,
                    "flavor_architect": flavor_fallback,
                    "memory_updated": memory_updated,
                    "user_memory_context": memory_context,
                    "user_rag_memory_context": rag_memory_context,
                },
                "error": None,
            }

    # --- LLM orchestration ---
    try:
        llm_result = app.state.llm_engine.orchestrate_chat(
            message=message,
            user_inventory=user_inventory,
            store_inventory=store_inventory,
            user_taste_profile=user_taste_profile,
            context=context_payload,
        )
    except Exception:
        logging.exception("LLM orchestration failed")
        llm_result = {
            "intent": "CHAT",
            "persona_message": "Kitchen systems are syncing. Please retry in a moment.",
            "detected_items": [],
            "recommendations": [],
        }

    intent = str(llm_result.get("intent") or "CHAT").upper()
    detected_items = list(llm_result.get("detected_items") or [])
    recommendations = list(llm_result.get("recommendations") or [])
    persona_message = str(llm_result.get("persona_message") or "").strip()
    flavor_architect: List[Dict[str, Any]] = []
    inventory_persisted = False

    # Override LLM intent when pre-classifier is confident and LLM disagrees.
    if inferred_intent == "cook" and intent != "COOK":
        logging.info("Intent override: LLM said %s but pre-classifier says COOK", intent)
        intent = "COOK"
        detected_items = []
        persona_message = ""  # Let downstream set appropriate message
    elif inferred_intent == "add_food" and intent == "COOK":
        # Trust LLM for COOK->ADD_FOOD only if there are actual detected items
        if not detected_items:
            intent = "COOK"

    if not detected_items:
        detected_items = _extract_structured_items(action)

    # Only attempt message-based item extraction when LLM explicitly
    # signalled ADD_FOOD intent.  Previously this fallback ran on every
    # message (including plain CHAT), which caused conversational phrases
    # like "plan a healthy dinner" to be persisted as pantry products.
    if not detected_items and message and intent == "ADD_FOOD":
        detected_items = extract_items_from_message(message)

    detected_items = _normalize_detected_items(detected_items)

    # Sanity guard: reject "items" that look like sentences, not food names.
    # Real food names are at most 4–5 words (e.g. "extra virgin olive oil").
    detected_items = [
        item for item in detected_items
        if len(str(item.get("name") or "").split()) <= 5
    ]

    if intent == "ADD_FOOD" and detected_items:
        try:
            await persist_detected_items(ctx.user_id, detected_items, source="actions_invoke")
            inventory_persisted = True
            persona_message = persona_message or "Got it! I've added the items to your Neural Pantry. Anything else?"
        except Exception:
            logging.exception("Detected item persistence failed")
            persona_message = "I detected items, but saving failed. Please retry."

    if intent == "COOK" and not recommendations:
        try:
            fallback_recs = suggest_hybrid_recipes(user_inventory, store_inventory)
            recommendations = [item.model_dump() for item in fallback_recs]
        except Exception:
            recommendations = []
        if not recommendations:
            available_names = [str(item.get("name") or "") for item in user_inventory if item.get("name")]
            store_names = [str(item.get("name") or "") for item in store_inventory if item.get("name")]
            recommendations = [
                {
                    "recipe_id": f"quick_{uuid.uuid4().hex[:8]}",
                    "name": "Chef Quick Fusion Bowl",
                    "description": "Fast bowl built from what you have and top store add-ons.",
                    "available_items": available_names[:4],
                    "missing_items": [name for name in store_names[:5] if name not in available_names][:3],
                    "confidence": 0.72,
                }
            ]
        persona_message = persona_message or "Here are hybrid recipes based on your current inventory."

    if intent == "COOK":
        strict_mode = True
        planning_warning: Optional[str] = None
        if _is_vegan_profile(user_taste_profile) and not _has_vegan_friendly_items(user_inventory):
            strict_mode = False
            planning_warning = (
                "I see mainly non-vegan products. I can suggest a recipe from current inventory "
                "or we can add vegetables first."
            )
        force_include = _zero_day_items(user_inventory, coerce_date_safe)
        try:
            flavor_architect_raw = app.state.flavor_architect_engine.plan_dish(
                current_inventory=user_inventory,
                user_taste_profile=user_taste_profile,
                context=context_payload,
                strict_mode=strict_mode,
                warning=planning_warning,
                force_include_items=force_include,
            )
            flavor_architect = _safe_flavor_architect_payload(
                flavor_architect_raw,
                user_inventory_rows=user_inventory,
                store_inventory_rows=store_inventory,
                warning=planning_warning,
            )
            if flavor_architect:
                recommendations = []
                for recipe in flavor_architect:
                    if not isinstance(recipe, dict):
                        continue
                    recommendations.append(
                        await _build_facts_first_recommendation(
                            recipe,
                            recipe_id_prefix="flavor",
                            user_inventory=user_inventory,
                            constraints_payload=constraints_payload,
                        )
                    )
                recommendations = sorted(
                    recommendations,
                    key=_recommendation_rank_score,
                    reverse=True,
                )
                if flavor_architect:
                    persona_message = persona_message or str(flavor_architect[0].get("rationale_for_user") or "")
        except Exception:
            logging.exception("Flavor architect planning failed")
            flavor_architect = _safe_flavor_architect_payload(
                None,
                user_inventory_rows=user_inventory,
                store_inventory_rows=store_inventory,
                warning=(
                    planning_warning
                    or "Flavor engine fallback mode: add preferences or buy suggested products for better results."
                ),
            )
            recommendations = []
            for recipe in flavor_architect:
                if not isinstance(recipe, dict):
                    continue
                recommendations.append(
                    await _build_facts_first_recommendation(
                        recipe,
                        recipe_id_prefix="flavor_fallback",
                        user_inventory=user_inventory,
                        constraints_payload=constraints_payload,
                    )
                )
            recommendations = sorted(
                recommendations,
                key=_recommendation_rank_score,
                reverse=True,
            )
            if flavor_architect:
                persona_message = persona_message or str(flavor_architect[0].get("rationale_for_user") or "")

    if not persona_message:
        persona_message = "How can I help with your NeoEats flow?" if not message else f"Got it, {ctx.user_id}. {message}"

    await _store_memory_snapshot(intent, detected_items)

    return {
        "type": "action.result",
        "session_id": action.metadata.session_id,
        "action_id": action.id,
        "action_type": "chat",
        "status": "ok",
        "result": {
            "persona_message": persona_message,
            "detected_items": detected_items,
            "inventory_persisted": inventory_persisted,
            "recommendations": recommendations,
            "flavor_architect": flavor_architect,
            "memory_updated": memory_updated,
            "user_memory_context": memory_context,
            "user_rag_memory_context": rag_memory_context,
        },
        "error": None,
    }
