from app.services.neoeats_user_memory import (
    learn_user_memory,
    merge_memory_into_taste_profile,
    retrieve_user_memory_context,
)


def test_learns_diet_constraints_and_goals_from_message():
    memory, changed = learn_user_memory(
        {},
        message="I am vegan, allergic to peanuts, and want high protein dinners",
        intent="COOK",
    )

    assert changed is True
    summary = retrieve_user_memory_context(memory, message="what can I cook?")["profile_summary"]
    assert "vegan" in summary["diet_tags"]
    assert "high_protein" in summary["goals"]
    assert "peanuts" in summary["constraints"]


def test_learns_frequent_ingredients_from_detected_items():
    memory, changed = learn_user_memory(
        {},
        message="add food",
        intent="ADD_FOOD",
        detected_items=[{"name": "Chicken Breast", "canonical_name": "chicken breast"}],
    )

    assert changed is True
    assert memory["ingredient_counts"]["chicken breast"] == 1
    retrieved = retrieve_user_memory_context(memory, message="make chicken")["retrieved_facts"]
    assert any(fact["value"] == "chicken breast" for fact in retrieved)


def test_merge_memory_into_taste_profile_preserves_existing_profile():
    memory, _ = learn_user_memory({}, message="I prefer vegan and avoid milk", intent="CHAT")
    context = retrieve_user_memory_context(memory, message="dinner")
    merged = merge_memory_into_taste_profile({"tags": ["quick"]}, context)

    assert "quick" in merged["tags"]
    assert "vegan" in merged["tags"]
    assert "milk" in merged["constraints"]
