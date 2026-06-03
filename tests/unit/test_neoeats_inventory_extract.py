from __future__ import annotations

from app.services.neoeats_inventory_extract import (
    build_inventory_extract_response,
    extract_inventory_items,
    looks_like_inventory_text,
)


class FakeLlm:
    def orchestrate_chat(self, **kwargs):
        return {
            "intent": "ADD_FOOD",
            "detected_items": [
                {"name": "Greek yogurt", "quantity": 2, "unit": "pack", "confidence": 0.93},
                {"name": "blueberries", "quantity": 300, "unit": "g", "confidence": 87},
            ],
            "recommendations": [{"name": "Should be ignored"}],
        }


def test_extract_inventory_items_uses_llm_detected_items():
    items = extract_inventory_items("bought yogurt and blueberries", llm_engine=FakeLlm())

    assert [item["name"] for item in items] == ["Greek yogurt", "blueberries"]
    assert items[0]["quantity"] == 2.0
    assert items[0]["unit"] == "pack"
    assert items[0]["confidence"] == 93.0
    assert items[1]["confidence"] == 87.0


def test_extract_inventory_items_falls_back_to_text_parser():
    items = extract_inventory_items("Bought 500g chicken breast, 1 kg rice and 6 tomatoes")

    assert [(item["name"], item["canonical_name"], item["quantity"], item["unit"]) for item in items] == [
        ("chicken breast", "chicken", 500.0, "g"),
        ("rice", "rice", 1.0, "kg"),
        ("tomatoes", "tomatoes", 6.0, "pcs"),
    ]


def test_extract_inventory_items_rejects_recipe_intent():
    assert looks_like_inventory_text("cook healthy dinner") is False
    assert extract_inventory_items("cook healthy dinner") == []


def test_build_inventory_extract_response_never_returns_recommendations():
    response = build_inventory_extract_response("milk, eggs")

    assert response["inventory_persisted"] is False
    assert response["recommendations"] == []
    assert response["flavor_architect"] == []
    assert response["pantry_updates"] == [
        {"name": "milk", "quantity": 1.0, "unit": "l"},
        {"name": "eggs", "quantity": 6.0, "unit": "pcs"},
    ]
    assert response["detected_items"] == response["items"]
