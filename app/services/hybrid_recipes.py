from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.models.neoeats import HybridRecipeSuggestion


_RECIPE_TEMPLATES = [
    {
        "id": "taco_melt",
        "name": "Taco Melt",
        "description": "Cheesy tacos with a quick pan finish.",
        "must_have": ["cheese"],
        "missing": ["taco shells", "salsa", "ground beef"],
    },
    {
        "id": "pasta_alfredo",
        "name": "Creamy Alfredo Pasta",
        "description": "Silky pasta with a creamy finish.",
        "must_have": ["cheese", "butter"],
        "missing": ["pasta", "cream", "parmesan"],
    },
    {
        "id": "nordic_brunch",
        "name": "Nordic Brunch Plate",
        "description": "Light brunch with rye and salmon.",
        "must_have": ["eggs"],
        "missing": ["rye bread", "smoked salmon", "dill"],
    },
    {
        "id": "veggie_stir_fry",
        "name": "Veggie Stir Fry",
        "description": "Quick wok with bright vegetables.",
        "must_have": ["garlic"],
        "missing": ["soy sauce", "ginger", "noodles"],
    },
]


def _normalize(value: str) -> str:
    return value.strip().lower()


def _names_from_items(items: Iterable[Dict[str, Any]], *, key: str = "name") -> List[str]:
    names = []
    for item in items:
        name = item.get(key) or ""
        if name:
            names.append(_normalize(str(name)))
    return names


def suggest_hybrid_recipes(
    user_items: Iterable[Dict[str, Any]],
    store_items: Iterable[Dict[str, Any]],
    *,
    max_results: int = 5,
) -> List[HybridRecipeSuggestion]:
    user_names = set(_names_from_items(user_items))
    store_names = set(_names_from_items(store_items))

    suggestions: List[HybridRecipeSuggestion] = []
    for template in _RECIPE_TEMPLATES:
        must_have = {_normalize(item) for item in template["must_have"]}
        if not must_have.issubset(user_names):
            continue

        missing = [
            item for item in template["missing"]
            if _normalize(item) in store_names
        ]
        if not missing:
            continue

        confidence = round(0.6 + (0.1 * min(len(missing), 3)), 2)
        suggestions.append(
            HybridRecipeSuggestion(
                recipe_id=template["id"],
                name=template["name"],
                description=template["description"],
                available_items=sorted(list(must_have)),
                missing_items=missing,
                confidence=confidence,
            )
        )

        if len(suggestions) >= max_results:
            break

    return suggestions
