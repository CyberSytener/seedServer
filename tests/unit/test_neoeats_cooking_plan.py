from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cooking import (
    _normalize_plan_steps,
    _parse_plan_json,
    router,
)


def test_parse_plan_json_rejects_non_object_payload() -> None:
    assert _parse_plan_json('["not", "a", "plan"]') is None


def test_parse_plan_json_extracts_fenced_object() -> None:
    parsed = _parse_plan_json(
        """
        Here is the plan:
        ```json
        {"servings": 2, "steps": [{"title": "Prep", "instruction": "Chop tomatoes."}]}
        ```
        """
    )
    assert parsed is not None
    assert parsed["servings"] == 2
    assert parsed["steps"][0]["title"] == "Prep"


def test_normalize_plan_steps_handles_malformed_llm_shape() -> None:
    steps = _normalize_plan_steps(
        {
            "steps": [
                {
                    "title": 123,
                    "instruction": ["bad shape"],
                    "duration_sec": -10,
                    "tips": "Keep the pan hot.",
                    "warnings": {"not": "a-list"},
                    "ingredients_used": [
                        "Tomato",
                        {"name": "Rice", "quantity": "2", "unit": "dl"},
                        {"quantity": 1},
                        42,
                    ],
                },
                "Stir everything together and serve warm.",
            ]
        }
    )

    assert len(steps) == 3
    assert steps[0].title == "123"
    assert steps[0].instruction == "Continue cooking with your prepared ingredients."
    assert steps[0].duration_sec == 60
    assert steps[0].tips == ["Keep the pan hot."]
    assert steps[0].warnings == []
    assert steps[0].ingredients_used[0]["name"] == "Tomato"
    assert steps[0].ingredients_used[1]["name"] == "Rice"
    assert steps[1].instruction == "Stir everything together and serve warm."
    assert steps[2].title == "Step 3"


class _MalformedLLM:
    enabled = True

    def _generate_content(self, **_: object) -> str:
        return """
        {
          "servings": 999,
          "chef_note": {"bad": "shape"},
          "steps": [
            {
              "title": "Sear",
              "instruction": "Sear the tomatoes quickly.",
              "duration_sec": 99999,
              "tips": ["Use medium-high heat.", {"skip": true}],
              "warnings": "Pan may be hot.",
              "ingredients_used": ["Tomato"]
            }
          ]
        }
        """


def test_generate_cooking_plan_endpoint_normalizes_malformed_llm_response() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.llm_engine = _MalformedLLM()
    client = TestClient(app)

    response = client.post(
        "/api/v1/cooking/generate-plan",
        json={
            "recipe_name": "Tomato Rice",
            "servings": 2,
            "ingredients": [{"name": "Tomato", "quantity": 2, "unit": "pcs"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "cooking_plan_v1"
    assert payload["servings"] == 2
    assert payload["chef_note"] == "Enjoy your Tomato Rice!"
    assert len(payload["steps"]) == 3
    assert payload["steps"][0]["duration_sec"] == 900
    assert payload["steps"][0]["tips"] == ["Use medium-high heat."]
    assert payload["steps"][0]["warnings"] == ["Pan may be hot."]
    assert payload["steps"][0]["timers"][0]["duration_sec"] == 900
