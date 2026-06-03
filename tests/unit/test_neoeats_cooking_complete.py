from __future__ import annotations

from app.services.neoeats_cooking_complete import (
    decide_consumption_action,
    group_cooking_consumption,
)


def test_group_cooking_consumption_sums_same_pantry_item_and_unit():
    groups, failed = group_cooking_consumption([
        {"pantry_item_id": "p1", "name": "Chicken", "quantity": 100, "unit": "g"},
        {"pantry_item_id": "p1", "name": "Chicken", "quantity": 200, "unit": "g"},
    ])

    assert failed == []
    assert len(groups) == 1
    assert groups[0].pantry_item_id == "p1"
    assert groups[0].quantity == 300
    assert groups[0].unit == "g"


def test_group_cooking_consumption_reports_missing_and_mixed_units():
    groups, failed = group_cooking_consumption([
        {"name": "Rice", "quantity": 1, "unit": "kg"},
        {"pantry_item_id": "p2", "name": "Milk", "quantity": 0.5, "unit": "l"},
        {"pantry_item_id": "p2", "name": "Milk", "quantity": 250, "unit": "ml"},
    ])

    assert len(groups) == 1
    assert failed == [
        {"name": "Rice", "reason": "missing_pantry_item_id"},
        {"pantry_item_id": "p2", "name": "Milk", "reason": "mixed_units_for_same_pantry_item"},
    ]


def test_decide_consumption_action_updates_when_quantity_remains():
    assert decide_consumption_action(
        current_quantity=500,
        current_unit="g",
        requested_quantity=300,
        requested_unit="g",
    ) == {"action": "update", "next_quantity": 200}


def test_decide_consumption_action_deletes_when_quantity_consumed():
    assert decide_consumption_action(
        current_quantity=300,
        current_unit="g",
        requested_quantity=300,
        requested_unit="g",
    ) == {"action": "delete"}


def test_decide_consumption_action_rejects_unit_mismatch():
    assert decide_consumption_action(
        current_quantity=1,
        current_unit="kg",
        requested_quantity=300,
        requested_unit="g",
    ) == {
        "action": "failed",
        "reason": "unit_mismatch",
        "current_unit": "kg",
        "requested_unit": "g",
    }
