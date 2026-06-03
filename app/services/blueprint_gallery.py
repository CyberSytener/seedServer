from __future__ import annotations

from typing import Any, Dict, List

from app.core.saga_blueprints import blueprint_store


def _standard_job_alert() -> Dict[str, Any]:
    return {
        "name": "standard_job_alert",
        "version": "v1",
        "steps": [
            {
                "id": "scan_jobs",
                "block": "market_scanner",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                },
            },
            {
                "id": "score_jobs",
                "block": "job_scorer",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                    "jobs": {"from": "scan_jobs.jobs"},
                    "scan_id": {"from": "scan_jobs.scan_id"},
                    "persist": True,
                },
            },
            {
                "id": "notify_user",
                "block": "notification_block",
                "inputs": {
                    "items": {"from": "score_jobs.scored_jobs"},
                    "message_body": {"from": "request.message_body", "default": ""},
                    "recipient_info": {"from": "request.recipient_info", "default": {}},
                },
                "params": {
                    "top_n": 3,
                },
            },
        ],
    }


def _silent_audit() -> Dict[str, Any]:
    return {
        "name": "silent_audit",
        "version": "v1",
        "steps": [
            {
                "id": "scan_jobs",
                "block": "market_scanner",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                },
            },
            {
                "id": "score_jobs",
                "block": "job_scorer",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                    "jobs": {"from": "scan_jobs.jobs"},
                    "scan_id": {"from": "scan_jobs.scan_id"},
                    "persist": True,
                },
            },
        ],
    }


def _meta_test() -> Dict[str, Any]:
    return {
        "name": "meta_test",
        "version": "v1",
        "steps": [
            {
                "id": "run_child",
                "block": "sub_saga",
                "inputs": {
                    "blueprint_name": "standard_job_alert",
                    "payload": {
                        "user_id": {"from": "user_id"},
                        "persona": {"from": "persona"},
                        "message_body": {"from": "request.message_body", "default": ""},
                        "recipient_info": {"from": "request.recipient_info", "default": {}},
                    },
                },
            }
        ],
    }


def _inventory_recipe_flow() -> Dict[str, Any]:
    return {
        "name": "inventory_recipe_flow",
        "version": "v1",
        "steps": [
            {
                "id": "check_inventory",
                "block": "inventory_sync",
                "inputs": {
                    "action": "check",
                    "ingredients": {"from": "request.ingredients", "default": []},
                },
            },
            {
                "id": "generate_recipe",
                "block": "recipe_generator",
                "inputs": {
                    "dish_name": {"from": "request.dish_name", "default": "Chef Special"},
                    "available_ingredients": {"from": "check_inventory.available_ingredients", "default": []},
                    "missing_ingredients": {"from": "check_inventory.missing_ingredients", "default": []},
                    "servings": {"from": "request.servings", "default": 1},
                },
            },
        ],
    }


def _hot_offer_flow() -> Dict[str, Any]:
    return {
        "name": "hot_offer_flow",
        "version": "v1",
        "steps": [
            {
                "id": "priority_scan",
                "block": "priority_inventory_scan",
                "inputs": {
                    "expiry_days": {"from": "request.expiry_days", "default": 3},
                    "overstock_threshold": {"from": "request.overstock_threshold", "default": 10},
                    "location_id": {"from": "request.location_id", "default": None},
                },
            },
            {
                "id": "sales_stats",
                "block": "sales_stats_fetch",
                "inputs": {
                    "day_of_week": {"from": "request.day_of_week", "default": None},
                    "hour_of_day": {"from": "request.hour_of_day", "default": None},
                    "location_id": {"from": "request.location_id", "default": None},
                    "limit": {"from": "request.sales_limit", "default": 50},
                },
            },
            {
                "id": "generate_offer",
                "block": "hot_offer_generator",
                "inputs": {
                    "priority_items": {"from": "priority_scan.items"},
                    "sales_stats": {"from": "sales_stats.stats"},
                    "currency": {"from": "request.currency", "default": "NOK"},
                    "margin_pct": {"from": "request.margin_pct", "default": 0.25},
                    "waste_overhead": {"from": "request.waste_overhead", "default": 0.0},
                },
            },
            {
                "id": "validate_offer",
                "block": "culinary_validator",
                "inputs": {
                    "offer": {"from": "generate_offer.offer"},
                    "threshold": {"from": "request.threshold", "default": 8},
                    "terminate_on_reject": {"from": "request.terminate_on_reject", "default": True},
                },
            },
            {
                "id": "approval",
                "block": "approval_block",
                "inputs": {
                    "offer_id": {"from": "generate_offer.offer_id"},
                    "approved": {"from": "request.approved", "default": False},
                    "notes": {"from": "request.notes", "default": ""},
                },
            },
        ],
    }


def _neoeats_recipe_pipeline() -> Dict[str, Any]:
    return {
        "name": "neoeats_recipe_pipeline",
        "version": "v1",
        "steps": [
            {
                "id": "load_inventory",
                "block": "neoeats.inventory.get",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "source": {"from": "payload.inventory_source", "default": "stub"},
                    "include_expired": {"from": "payload.include_expired", "default": False},
                },
            },
            {
                "id": "normalize_inventory",
                "block": "neoeats.inventory.normalize",
                "inputs": {
                    "inventory": {"from": "load_inventory.inventory", "default": []},
                    "pantry_staples": {"from": "payload.pantry_staples", "default": []},
                    "aliases": {"from": "payload.aliases", "default": {}},
                },
            },
            {
                "id": "normalize_input",
                "block": "neoeats.input.normalize",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "ingredients": {"from": "payload.ingredients", "default": []},
                    "constraints": {"from": "payload.constraints", "default": {}},
                },
            },
            {
                "id": "generate_recipe_draft",
                "block": "neoeats.recipe.generate",
                "inputs": {
                    "normalized": {"from": "normalize_input.normalized"},
                    "inventory": {"from": "normalize_inventory.normalized_inventory", "default": []},
                },
            },
            {
                "id": "compile_recipe",
                "block": "neoeats.recipe.compile_strict",
                "inputs": {
                    "draft_recipe": {"from": "generate_recipe_draft.recipe"},
                    "normalized_inventory": {"from": "normalize_inventory.normalized_inventory", "default": []},
                    "constraints": {"from": "normalize_input.normalized.constraints", "default": {}},
                    "pantry_staples": {"from": "payload.pantry_staples", "default": []},
                },
            },
            {
                "id": "validate_recipe",
                "block": "neoeats.recipe.validate",
                "inputs": {
                    "recipe": {"from": "compile_recipe.recipe"},
                    "constraints": {"from": "normalize_input.normalized.constraints", "default": {}},
                    "normalized_inventory": {"from": "normalize_inventory.normalized_inventory", "default": []},
                    "nutrition": {"from": "compile_recipe.nutrition", "default": {}},
                },
            },
        ],
    }


async def seed_blueprint_gallery() -> List[str]:
    from app.core.saga_blueprints import BlueprintStatus

    blueprints = [
        _standard_job_alert(),
        _silent_audit(),
        _meta_test(),
        _inventory_recipe_flow(),
        _hot_offer_flow(),
        _neoeats_recipe_pipeline(),
    ]
    for blueprint in blueprints:
        await blueprint_store.save(
            blueprint["name"], blueprint,
            owner_id="system", status=BlueprintStatus.ACTIVE,
        )
    return [blueprint["name"] for blueprint in blueprints]
