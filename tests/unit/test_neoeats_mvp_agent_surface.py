from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agent_integration import router as agent_router
from app.api.saga_blueprints import _run_saga
from app.core.blocks import build_default_registry
from app.core.neoeats_blocks import (
    NeoEatsInventoryGetBlock,
    NeoEatsInventoryNormalizeBlock,
    NeoEatsRecipeCompileStrictBlock,
    NeoEatsRecipeValidateBlock,
)
from app.core.realtime.sagas.flows.dynamic_saga import ExecutionMode
from app.core.saga_blueprints import BlueprintStore
from scripts import validate_catalog


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_recipe_pipeline_v2() -> Dict[str, Any]:
    path = _repo_root() / "app" / "catalog" / "domains" / "neoeats" / "examples" / "recipe_pipeline_v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_recipe_pipeline_v3() -> Dict[str, Any]:
    path = _repo_root() / "app" / "catalog" / "domains" / "neoeats" / "examples" / "recipe_pipeline_v3.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _sample_recipe_payload() -> Dict[str, Any]:
    return {
        "user_id": "neo-user-1",
        "ingredients": ["Eggs", "Spinach", "Tomato", "Olive Oil"],
        "constraints": {
            "diet": "vegetarian",
            "allergens": ["peanut"],
            "calories_target": 520,
            "cuisine": "mediterranean",
            "time_limit": "30 min",
            "servings": 2,
        },
    }


def _build_agent_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("SEED_ADMIN_KEY", "test_admin")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "1")
    app = FastAPI()
    app.include_router(agent_router)
    app.state.seed = SimpleNamespace(db=object())
    app.state.agent_blueprint_store = BlueprintStore()
    return TestClient(app)


def _headers(
    token: str = "test_neoeats-dev|developer|catalog:read,blueprints:write,runs:write",
) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_catalog_validation_passes_with_neoeats_mvp_nodes() -> None:
    catalog_root = Path("app/catalog")
    errors: list[str] = []
    errors.extend(validate_catalog._validate_tree(catalog_root))
    errors.extend(validate_catalog._validate_modules(catalog_root))
    assert errors == []

    tree = json.loads((catalog_root / "tree.json").read_text(encoding="utf-8"))
    node_paths = {
        str(node.get("path"))
        for node in (tree.get("nodes") or [])
        if isinstance(node, dict)
    }
    assert "modules/neoeats.input.normalize.json" in node_paths
    assert "modules/neoeats.inventory.get.json" in node_paths
    assert "modules/neoeats.inventory.normalize.json" in node_paths
    assert "modules/neoeats.recipe.generate.json" in node_paths
    assert "modules/neoeats.recipe.compile_strict.json" in node_paths
    assert "modules/neoeats.recipe.validate.json" in node_paths
    assert "domains/neoeats/nutrition_table_v0.json" in node_paths
    assert "domains/neoeats/examples/recipe_pipeline_v2.json" in node_paths
    assert "domains/neoeats/examples/recipe_pipeline_v3.json" in node_paths


def test_recipe_pipeline_v2_dry_run_returns_trace_and_recipe_shape(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    result = asyncio.run(
        _run_saga(
            _load_recipe_pipeline_v2(),
            _sample_recipe_payload(),
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
        )
    )
    assert result["status"] == "succeeded"
    trace = result.get("execution_trace") or []
    assert [entry.get("step") for entry in trace] == [
        "normalize_input",
        "generate_recipe",
        "validate_recipe",
    ]

    recipe = result["result"]["recipe"]
    assert isinstance(recipe.get("title"), str) and recipe["title"]
    assert isinstance(recipe.get("ingredients"), list) and recipe["ingredients"]
    assert isinstance(recipe.get("steps"), list) and recipe["steps"]
    assert isinstance(recipe.get("tags"), list) and recipe["tags"]


def test_recipe_validate_flags_allergen_with_string_match() -> None:
    block = NeoEatsRecipeValidateBlock(engine=SimpleNamespace(), params={})
    recipe = {
        "title": "Quick Peanut Bowl",
        "ingredients": [
            {"name": "peanut butter", "quantity": 20, "unit": "g"},
            {"name": "rice", "quantity": 120, "unit": "g"},
        ],
        "steps": ["Mix all ingredients and serve."],
    }
    result = asyncio.run(
        block.execute(
            {},
            {
                "recipe": recipe,
                "constraints": {"allergens": ["peanut"]},
            },
        )
    )
    assert result["ok"] is False
    assert any(item.get("type") == "allergen" for item in (result.get("violations") or []))


def test_recipe_validate_flags_inventory_and_nutrition_missing() -> None:
    block = NeoEatsRecipeValidateBlock(engine=SimpleNamespace(), params={})
    result = asyncio.run(
        block.execute(
            {},
            {
                "recipe": {
                    "title": "Inventory Drift Bowl",
                    "ingredients": [{"name": "truffle", "quantity": 10, "unit": "g"}],
                    "steps": ["Mix and serve."],
                },
                "constraints": {"servings": 1},
                "normalized_inventory": [{"name": "tomato", "quantity": 2, "unit": "pcs"}],
            },
        )
    )
    assert result["ok"] is False
    violation_types = {str(item.get("type")) for item in (result.get("violations") or [])}
    assert "ingredients_not_in_inventory" in violation_types
    assert "nutrition_missing" in violation_types


def test_recipe_pipeline_dry_run_does_not_call_external_http(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    class _ForbiddenHttpClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401
            raise AssertionError("External HTTP client must not be constructed in recipe DRY_RUN")

    monkeypatch.setattr("app.core.neoeats_blocks.httpx.AsyncClient", _ForbiddenHttpClient)

    result = asyncio.run(
        _run_saga(
            _load_recipe_pipeline_v2(),
            _sample_recipe_payload(),
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
        )
    )
    assert result["status"] == "succeeded"


def test_inventory_get_stub_is_deterministic_and_respects_include_expired() -> None:
    block = NeoEatsInventoryGetBlock(engine=SimpleNamespace(_execution_mode=ExecutionMode.DRY_RUN), params={})

    first = asyncio.run(block.execute({}, {"user_id": "inventory-user-1"}))
    second = asyncio.run(block.execute({}, {"user_id": "inventory-user-1"}))
    with_expired = asyncio.run(
        block.execute({}, {"user_id": "inventory-user-1", "include_expired": True})
    )

    assert first["inventory"] == second["inventory"]
    assert first["updated_at"] == "stub://inventory/v1"
    assert all(item.get("name") != "expired milk" for item in (first.get("inventory") or []))
    assert any(item.get("name") == "expired milk" for item in (with_expired.get("inventory") or []))


def test_inventory_normalize_merges_duplicates_and_canonicalizes_aliases() -> None:
    block = NeoEatsInventoryNormalizeBlock(engine=SimpleNamespace(), params={})
    result = asyncio.run(
        block.execute(
            {},
            {
                "inventory": [
                    {"name": "Tomatoes", "quantity": 2, "unit": "pcs"},
                    {"name": "tomato", "quantity": 1, "unit": "piece"},
                    {"name": "Olive Oil", "quantity": 1, "unit": "l"},
                    {"name": "olive oil", "quantity": 500, "unit": "ml"},
                ],
                "aliases": {"tomatoes": "tomato"},
            },
        )
    )

    normalized = result.get("normalized_inventory") or []
    tomato_row = next(
        item for item in normalized if item.get("name") == "tomato" and item.get("unit") == "pcs"
    )
    oil_row = next(
        item for item in normalized if item.get("name") == "olive oil" and item.get("unit") == "ml"
    )
    assert float(tomato_row.get("quantity") or 0.0) == 3.0
    assert float(oil_row.get("quantity") or 0.0) == 1500.0
    assert any(note.startswith("duplicates_merged:") for note in (result.get("notes") or []))


def test_inventory_blocks_dry_run_without_postgres_dsn(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    blueprint = {
        "name": "inventory_probe_pipeline_v1",
        "version": "v1",
        "steps": [
            {
                "id": "load_inventory",
                "block": "neoeats.inventory.get",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "include_expired": False,
                },
            },
            {
                "id": "normalize_inventory",
                "block": "neoeats.inventory.normalize",
                "inputs": {
                    "inventory": {"from": "load_inventory.inventory"},
                    "aliases": {"from": "payload.aliases", "default": {}},
                },
            },
        ],
    }

    result = asyncio.run(
        _run_saga(
            blueprint,
            {"user_id": "neo-inventory-user", "aliases": {"tomatoes": "tomato"}},
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
        )
    )
    assert result["status"] == "succeeded"
    trace = result.get("execution_trace") or []
    assert [entry.get("step") for entry in trace] == ["load_inventory", "normalize_inventory"]
    normalized = result.get("result", {}).get("normalized_inventory")
    assert isinstance(normalized, list) and normalized


def test_compile_strict_flags_non_inventory_ingredients() -> None:
    block = NeoEatsRecipeCompileStrictBlock(engine=SimpleNamespace(), params={})
    result = asyncio.run(
        block.execute(
            {},
            {
                "draft_recipe": {
                    "title": "Fancy Bowl",
                    "servings": 2,
                    "ingredients": [
                        {"name": "egg", "quantity": 2, "unit": "pcs"},
                        {"name": "truffle", "quantity": 30, "unit": "g"},
                    ],
                    "steps": ["Cook and serve."],
                },
                "normalized_inventory": [
                    {"name": "egg", "quantity": 6, "unit": "pcs"},
                    {"name": "tomato", "quantity": 3, "unit": "pcs"},
                ],
                "constraints": {"servings": 2},
                "pantry_staples": [],
            },
        )
    )
    recipe_ingredients = result.get("recipe", {}).get("ingredients") or []
    assert all(str(item.get("name")) != "truffle" for item in recipe_ingredients)
    assert any(str(item.get("name")) == "truffle" for item in (result.get("missing_items") or []))


def test_compile_strict_always_outputs_nutrition_fields() -> None:
    block = NeoEatsRecipeCompileStrictBlock(engine=SimpleNamespace(), params={})
    result = asyncio.run(
        block.execute(
            {},
            {
                "draft_recipe": {
                    "title": "Unknown Root Stew",
                    "ingredients": [{"name": "mystery root", "quantity": 200, "unit": "g"}],
                    "steps": ["Boil and serve."],
                    "servings": 2,
                },
                "normalized_inventory": [
                    {"name": "mystery root", "quantity": 500, "unit": "g"},
                ],
                "constraints": {"servings": 2},
                "pantry_staples": [],
            },
        )
    )
    nutrition = result.get("nutrition") or {}
    assert isinstance(nutrition.get("kcal_total"), int)
    assert "protein_g" in nutrition
    assert "fat_g" in nutrition
    assert "carbs_g" in nutrition
    assert isinstance(nutrition.get("per_serving"), dict)


def test_recipe_pipeline_v3_dry_run_returns_nutrition_and_missing_items(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    payload = dict(_sample_recipe_payload())
    payload["ingredients"] = ["Eggs", "Tomato", "Truffle"]

    result = asyncio.run(
        _run_saga(
            _load_recipe_pipeline_v3(),
            payload,
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
        )
    )
    assert result["status"] == "succeeded"
    trace = result.get("execution_trace") or []
    assert [entry.get("step") for entry in trace] == [
        "load_inventory",
        "normalize_inventory",
        "normalize_input",
        "generate_recipe_draft",
        "compile_recipe",
        "validate_recipe",
    ]
    final = result.get("result") or {}
    assert isinstance(final.get("nutrition"), dict)
    assert isinstance(final.get("missing_items"), list)


def test_neoeats_golden_loop_context_generate_validate_dry_run_publish(monkeypatch) -> None:
    client = _build_agent_client(monkeypatch)

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        return _load_recipe_pipeline_v2(), {"model_name": "mock", "model_tier": model_tier or "cheap"}

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)

    headers = _headers()
    context_pack = client.post(
        "/v1/catalog/context-pack",
        headers=headers,
        json={
            "domain": "neoeats",
            "intent": "recipe_from_inventory_strict",
            "constraints": {"diet": "vegetarian", "time_limit": 30},
            "max_modules": 50,
        },
    )
    assert context_pack.status_code == 200
    pack = context_pack.json()
    module_ids = {
        str(item.get("module_id"))
        for item in (pack.get("module_candidates") or [])
        if isinstance(item, dict)
    }
    assert "neoeats.inventory.get" in module_ids
    assert "neoeats.inventory.normalize" in module_ids
    assert "neoeats.input.normalize" in module_ids
    assert "neoeats.recipe.generate" in module_ids
    assert "neoeats.recipe.compile_strict" in module_ids
    assert "neoeats.recipe.validate" in module_ids

    generated = client.post(
        "/v1/blueprints/generate",
        headers=headers,
        json={
            "prompt": "Make me a recipe from pantry and constraints",
            "domain": "neoeats",
        },
    )
    assert generated.status_code == 200
    blueprint = generated.json()["blueprint"]

    validated = client.post(
        "/v1/blueprints/validate",
        headers=headers,
        json={"blueprint": blueprint},
    )
    assert validated.status_code == 200
    assert validated.json()["ok"] is True

    dry_run = client.post(
        "/v1/blueprints/dry-run",
        headers=headers,
        json={
            "blueprint": blueprint,
            "sample_input": _sample_recipe_payload(),
            "mode": "STUB",
        },
    )
    assert dry_run.status_code == 200
    trace_steps = [item.get("step") for item in (dry_run.json().get("execution_trace") or [])]
    assert trace_steps == ["normalize_input", "generate_recipe", "validate_recipe"]

    published = client.post(
        "/v1/blueprints/publish",
        headers=headers,
        json={
            "name": "neoeats_recipe_pipeline_v2",
            "version": "v2",
            "blueprint": blueprint,
            "policy": {"target_status": "SANDBOXED", "require_admin_approval": True},
        },
    )
    assert published.status_code == 200
    assert published.json()["status"] == "SANDBOXED"
