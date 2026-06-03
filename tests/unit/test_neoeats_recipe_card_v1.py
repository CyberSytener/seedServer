from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.services.neoeats_recipe_card import (
    _repair_mojibake_text,
    build_safe_error_recipe_card,
    compile_recipe_card_v1,
    validate_recipe_card_v1,
)


def _inventory_rows() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {
            "name": "chicken",
            "quantity": 600,
            "unit": "g",
            "expires_at": (now + timedelta(days=1)).date().isoformat(),
            "category": "protein",
            "confidence": 0.95,
        },
        {
            "name": "rice",
            "quantity": 300,
            "unit": "g",
            "expires_at": (now + timedelta(days=4)).date().isoformat(),
            "category": "grain",
            "confidence": 0.93,
        },
        {
            "name": "tomato",
            "quantity": 3,
            "unit": "pcs",
            "expires_at": (now + timedelta(days=2)).date().isoformat(),
            "category": "vegetable",
            "confidence": 0.9,
        },
    ]


def test_recipe_card_compile_core_ingredients_have_quantities() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Chicken Rice Bowl",
                "ingredients": [{"name": "chicken"}, {"name": "rice"}, {"name": "tomato"}],
                "steps": ["Cook ingredients and serve."],
            },
            normalized_inventory=_inventory_rows(),
            constraints={"servings": 2},
            recipe_id="test_recipe_core_qty",
            explain="Facts-first test card.",
        )
    )
    ingredient_map = {str(row.get("name")): row for row in (card.get("ingredients") or [])}
    for core_name in ("chicken", "rice", "tomato"):
        row = ingredient_map[core_name]
        assert row["source"] in {"inventory", "staple"}
        assert float(row["quantity"]) > 0
        assert str(row["unit"]).strip()
        assert str(row["unit"]).strip().lower() not in {"unit", "to taste"}


def test_recipe_card_compile_adds_fact_backed_protein_badge() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Protein Power Bowl",
                "ingredients": [{"name": "chicken"}, {"name": "egg"}, {"name": "rice"}],
                "steps": ["Cook and combine ingredients."],
            },
            normalized_inventory=_inventory_rows(),
            constraints={"servings": 2},
            recipe_id="test_recipe_protein_badge",
            explain="Protein-focused recipe card.",
        )
    )
    nutrition = card.get("nutrition") or {}
    assert float(nutrition.get("protein_g_total") or 0.0) > 0
    assert float(nutrition.get("protein_g_per_serving") or 0.0) > 0
    assert "protein_g" in nutrition
    badge = card.get("protein_badge")
    if float(nutrition.get("protein_g_per_serving") or 0.0) >= 30:
        assert isinstance(badge, dict)
        assert badge.get("label") == "High Protein"


def test_recipe_card_compile_sets_expiry_priority() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Expiry Priority Bowl",
                "ingredients": [{"name": "chicken"}, {"name": "rice"}],
            },
            normalized_inventory=_inventory_rows(),
            constraints={},
            recipe_id="test_recipe_expiry",
            explain="Use expiring inventory first.",
        )
    )
    expiry = card.get("expiry_priority") or {}
    used_first = expiry.get("used_first") or []
    assert isinstance(used_first, list)
    assert used_first
    first = used_first[0]
    assert first.get("name") == "chicken"
    assert isinstance(first.get("days_to_expiry"), int)


def test_recipe_card_compile_missing_items_switches_primary_cta() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Missing Cheese Bowl",
                "ingredients": [{"name": "tomato"}, {"name": "cheese"}],
            },
            normalized_inventory=_inventory_rows(),
            constraints={},
            recipe_id="test_recipe_missing",
            explain="Missing ingredient should force order CTA.",
        )
    )
    missing = card.get("missing_items") or []
    assert any(str(item.get("name")) == "cheese" for item in missing)
    actions = card.get("actions") or {}
    assert actions.get("primary_cta") == "order_missing"
    assert actions.get("missing_count") >= 1
    assert actions.get("missing_cost_nok") is None or float(actions.get("missing_cost_nok")) > 0


def test_recipe_card_compile_zero_missing_sets_start_cooking_cta_and_zero_cost() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Inventory-only Bowl",
                "ingredients": [{"name": "chicken"}, {"name": "rice"}, {"name": "tomato"}],
            },
            normalized_inventory=_inventory_rows(),
            constraints={"servings": 2},
            recipe_id="test_recipe_zero_missing",
            explain="No missing ingredients.",
        )
    )
    actions = card.get("actions") or {}
    assert actions.get("primary_cta") == "start_cooking"
    assert int(card.get("missing_items_count") or 0) == 0
    assert int(card.get("missing_cost_nok") or 0) == 0


def test_recipe_card_validator_rejects_inconsistent_missing_cost() -> None:
    payload = build_safe_error_recipe_card("recipe_invalid_cost", "Invalid Cost Card", "validator test")
    payload["missing_items"] = []
    payload["actions"]["missing_cost_nok"] = 12.0
    errors = validate_recipe_card_v1(payload, inventory_names={"tomato"}, staples_allowlist={"salt"})
    assert "missing_cost_must_be_zero_when_no_missing_items" in errors


def test_mojibake_repair_fixes_common_quote_artifact() -> None:
    repaired, changed = _repair_mojibake_text("вЂњHelloвЂќ", field_name="test")
    assert changed is True
    assert repaired == "“Hello”"


def test_recipe_card_compile_does_not_construct_external_http_client(monkeypatch) -> None:
    class _ForbiddenHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("External HTTP client must not be constructed for RecipeCard compile")

    monkeypatch.setattr("app.core.neoeats_blocks.httpx.AsyncClient", _ForbiddenHttpClient)

    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "No External Calls Bowl",
                "ingredients": [{"name": "chicken"}, {"name": "rice"}],
            },
            normalized_inventory=_inventory_rows(),
            constraints={},
            recipe_id="test_recipe_no_http",
            explain="No external calls expected.",
        )
    )
    assert card.get("schema_version") == "recipe_card_v1"


def test_recipe_card_compile_normalizes_units_and_removes_to_taste_for_non_spices() -> None:
    inventory = _inventory_rows() + [
        {"name": "milk", "quantity": 500, "unit": "ml", "expires_at": None, "category": "dairy", "confidence": 0.9},
        {"name": "olive oil", "quantity": 300, "unit": "ml", "expires_at": None, "category": "fat", "confidence": 0.9},
        {"name": "butter", "quantity": 250, "unit": "g", "expires_at": None, "category": "fat", "confidence": 0.9},
        {"name": "cheese", "quantity": 200, "unit": "g", "expires_at": None, "category": "dairy", "confidence": 0.9},
        {"name": "onion", "quantity": 2, "unit": "pcs", "expires_at": None, "category": "vegetable", "confidence": 0.9},
    ]
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Unit Normalization Bowl",
                "ingredients": [
                    {"name": "milk", "quantity": 1, "unit": "pcs"},
                    {"name": "olive oil", "quantity": 1, "unit": "pcs"},
                    {"name": "butter", "quantity": 1, "unit": "unit"},
                    {"name": "cheese", "quantity": 1, "unit": "unit"},
                    {"name": "tomato", "quantity": 1, "unit": "to taste"},
                    {"name": "onion", "quantity": 1, "unit": "to taste"},
                ],
            },
            normalized_inventory=inventory,
            constraints={"servings": 2},
            recipe_id="test_recipe_unit_normalization",
            explain="Unit normalization and to-taste guard test.",
        )
    )
    ingredient_map = {str(row.get("name")): row for row in (card.get("ingredients") or [])}
    assert ingredient_map["milk"]["unit"] == "ml"
    assert ingredient_map["olive oil"]["unit"] == "ml"
    assert ingredient_map["butter"]["unit"] == "g"
    assert ingredient_map["cheese"]["unit"] == "g"
    assert ingredient_map["tomato"]["unit"] in {"pcs", "g"}
    assert ingredient_map["onion"]["unit"] in {"pcs", "g"}

    for name, row in ingredient_map.items():
        if name in {"salt", "pepper", "paprika", "oregano"}:
            continue
        assert "to taste" not in str(row.get("unit", "")).lower()
        assert str(row.get("unit", "")).lower() not in {"unit", "units"}


def test_recipe_card_health_score_penalizes_butter_cheese_heavy_recipe() -> None:
    inventory = _inventory_rows() + [
        {"name": "butter", "quantity": 400, "unit": "g", "expires_at": None, "category": "fat", "confidence": 0.9},
        {"name": "cheese", "quantity": 350, "unit": "g", "expires_at": None, "category": "dairy", "confidence": 0.9},
        {"name": "cream", "quantity": 300, "unit": "ml", "expires_at": None, "category": "dairy", "confidence": 0.9},
        {"name": "spinach", "quantity": 250, "unit": "g", "expires_at": None, "category": "veg", "confidence": 0.9},
    ]
    lean = asyncio.run(
        compile_recipe_card_v1(
            recipe={"name": "Lean Bowl", "ingredients": [{"name": "chicken"}, {"name": "spinach"}, {"name": "tomato"}]},
            normalized_inventory=inventory,
            constraints={"servings": 2, "goal": "healthy"},
            recipe_id="test_health_lean",
            explain="lean",
        )
    )
    heavy = asyncio.run(
        compile_recipe_card_v1(
            recipe={"name": "Heavy Bowl", "ingredients": [{"name": "butter"}, {"name": "cheese"}, {"name": "cream"}]},
            normalized_inventory=inventory,
            constraints={"servings": 2, "goal": "healthy"},
            recipe_id="test_health_heavy",
            explain="heavy",
        )
    )
    lean_score = int((lean.get("match_breakdown") or {}).get("health_score_0_100") or 0)
    heavy_score = int((heavy.get("match_breakdown") or {}).get("health_score_0_100") or 0)
    assert lean_score > heavy_score


def test_recipe_card_budget_score_penalizes_over_budget() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Budget Miss Bowl",
                "ingredients": [{"name": "tomato"}, {"name": "cheese"}],
            },
            normalized_inventory=_inventory_rows(),
            constraints={"budget_limit_nok": 1},
            recipe_id="test_budget_overrun",
            explain="budget test",
        )
    )
    breakdown = card.get("match_breakdown") or {}
    budget_score = int(breakdown.get("budget_fit_0_100") or 0)
    penalties = breakdown.get("penalties") or []
    assert budget_score < 60
    assert any(str(item.get("code")) == "budget_exceeded" for item in penalties if isinstance(item, dict))


def test_recipe_card_compile_includes_cooking_plan_v1_with_min_three_steps() -> None:
    card = asyncio.run(
        compile_recipe_card_v1(
            recipe={
                "name": "Cooking Plan Bowl",
                "ingredients": [{"name": "chicken"}, {"name": "rice"}, {"name": "tomato"}],
                "steps": ["Prep all ingredients. Cook for 10 minutes. Serve warm."],
            },
            normalized_inventory=_inventory_rows(),
            constraints={"servings": 2},
            recipe_id="test_cooking_plan_shape",
            explain="cooking plan test",
        )
    )
    cooking_plan = card.get("cooking_plan") or {}
    assert cooking_plan.get("schema_version") == "cooking_plan_v1"
    steps = cooking_plan.get("steps") or []
    assert isinstance(steps, list)
    assert len(steps) >= 3
    first_step = steps[0]
    assert isinstance(first_step.get("step_id"), str)
    assert isinstance(first_step.get("instruction"), str)
    assert isinstance(first_step.get("ingredients_used"), list)
