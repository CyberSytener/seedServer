"""Tests for the extracted NeoEats chat handler module (Task 1.2).

Verifies that the pure helpers in ``app.api.neoeats_chat`` work correctly
after being extracted from the ``main.py`` god-file.
"""
from __future__ import annotations

import pytest

from app.api.neoeats_chat import (
    _extract_recipe_constraints,
    _has_basic_products,
    _has_vegan_friendly_items,
    _infer_intent,
    _inventory_names,
    _is_vegan_profile,
    _normalize_detected_items,
    _recommendation_rank_score,
    _safe_flavor_architect_payload,
    _zero_day_items,
)


class TestInferIntent:
    def test_cook_markers(self):
        assert _infer_intent("What can I cook tonight?") == "cook"
        assert _infer_intent("Give me a recipe") == "cook"
        assert _infer_intent("hybrid meal ideas") == "cook"

    def test_add_food_markers(self):
        assert _infer_intent("I bought some eggs") == "add_food"
        assert _infer_intent("add milk to fridge") == "add_food"

    def test_default_chat(self):
        assert _infer_intent("hello") == "chat"
        assert _infer_intent("") == "chat"


class TestInventoryHelpers:
    def test_inventory_names(self):
        inv = [{"name": "Eggs"}, {"name": ""}, {"name": "Milk"}]
        assert _inventory_names(inv) == ["eggs", "milk"]

    def test_has_basic_products_true(self):
        inv = [{"name": "bread"}, {"name": "cheese"}]
        assert _has_basic_products(inv) is True

    def test_has_basic_products_false(self):
        inv = [{"name": "salmon"}, {"name": "avocado"}]
        assert _has_basic_products(inv) is False


class TestVeganDetection:
    def test_vegan_profile(self):
        assert _is_vegan_profile({"diet": "vegan"}) is True
        assert _is_vegan_profile({"tags": ["vegan", "organic"]}) is True
        assert _is_vegan_profile({"diet": "keto"}) is False
        assert _is_vegan_profile({}) is False

    def test_vegan_friendly_items(self):
        assert _has_vegan_friendly_items([{"name": "tofu"}, {"name": "rice"}]) is True
        assert _has_vegan_friendly_items([{"name": "chicken"}, {"name": "eggs"}]) is False
        assert _has_vegan_friendly_items([]) is False


class TestZeroDayItems:
    def test_returns_expired(self):
        from datetime import date, timedelta
        yesterday = date.today() - timedelta(days=1)
        inv = [{"name": "Old Milk", "expires_at": yesterday.isoformat()}]
        result = _zero_day_items(inv, lambda v: date.fromisoformat(v) if v else None)
        assert result == ["Old Milk"]


class TestRecipeConstraints:
    def test_budget_extraction(self):
        result = _extract_recipe_constraints("cook under 200 nok", {})
        assert result["budget_limit_nok"] == 200.0

    def test_healthy_goal(self):
        result = _extract_recipe_constraints("healthy dinner", {})
        assert result.get("goal") == "healthy"
        assert result.get("prefer_healthy") is True

    def test_preserves_base(self):
        result = _extract_recipe_constraints("hello", {"servings": 4})
        assert result["servings"] == 4


class TestRecommendationRankScore:
    def test_with_recipe_card(self):
        rec = {"recipe_card_v1": {"match_breakdown": {"overall_score_0_100": 85}}}
        assert _recommendation_rank_score(rec) == 85.0

    def test_with_match_score(self):
        assert _recommendation_rank_score({"match_score": 72}) == 72.0

    def test_invalid(self):
        assert _recommendation_rank_score(None) == 0.0
        assert _recommendation_rank_score({}) == 0.0


class TestNormalizeDetectedItems:
    def test_normalizes_basic_item(self):
        items = [{"name": "Milk", "quantity": 1, "unit": "l"}]
        result = _normalize_detected_items(items)
        assert len(result) == 1
        assert result[0]["canonical_name"]
        assert result[0]["display_name"]

    def test_skips_empty(self):
        assert _normalize_detected_items([{}]) == []
        assert _normalize_detected_items([{"name": ""}]) == []


class TestSafeFlavorArchitectPayload:
    def test_fallback_when_none(self):
        result = _safe_flavor_architect_payload(
            None,
            user_inventory_rows=[{"name": "Chicken", "storage_id": "s1"}],
            store_inventory_rows=[],
            warning=None,
        )
        assert len(result) >= 1
        assert result[0]["name"]  # Has a recipe name
        assert result[0]["ingredients"]  # Has ingredients

    def test_normalizes_recipes(self):
        recipes = [
            {
                "name": "Test Dish",
                "match_score": 90,
                "ingredients": [{"name": "Egg", "status": "owned", "amount": "2 pcs"}],
                "rationale_for_user": "Good combo",
                "zero_waste_score": "high",
            }
        ]
        result = _safe_flavor_architect_payload(
            recipes,
            user_inventory_rows=[],
            store_inventory_rows=[],
            warning=None,
        )
        assert len(result) >= 1
        assert result[0]["name"] == "Test Dish"
        assert result[0]["match_score"] == 90
