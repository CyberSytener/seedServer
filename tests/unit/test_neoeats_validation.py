from __future__ import annotations

from app.core.blocks import build_default_registry
from app.services.saga_architect import SagaArchitect


def _architect() -> SagaArchitect:
    return SagaArchitect(build_default_registry())


def test_order_saga_requires_core_blocks() -> None:
    blueprint = {
        "name": "order_checkout",
        "version": "v1",
        "steps": [
            {
                "id": "reserve",
                "block": "inventory_block",
                "inputs": {"action": "reserve", "order_id": "o1", "items": []},
            },
            {
                "id": "account",
                "block": "accounting_block",
                "inputs": {"order_id": "o1", "receipt_id": "r1", "total": 10},
            },
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is False
    assert any("order saga missing required blocks" in err for err in result["errors"])


def test_order_saga_detection_does_not_match_substrings() -> None:
    blueprint = {
        "name": "visually_reordered_demo",
        "version": "v1",
        "steps": [
            {
                "id": "scan",
                "block": "market_scanner",
                "inputs": {"user_id": {"from": "user_id"}},
            }
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is True


def test_order_saga_block_ordering() -> None:
    blueprint = {
        "name": "order_checkout",
        "version": "v1",
        "steps": [
            {
                "id": "bill",
                "block": "billing_block",
                "inputs": {
                    "order_id": "o1",
                    "cogs_total": 10,
                    "margin_pct": 0.2,
                    "vat_pct": 0.25,
                },
            },
            {
                "id": "reserve",
                "block": "inventory_block",
                "inputs": {"action": "reserve", "order_id": "o1", "items": []},
            },
            {
                "id": "account",
                "block": "accounting_block",
                "inputs": {"order_id": "o1", "receipt_id": "r1", "total": 10},
            },
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is False
    assert any("order saga blocks must be ordered" in err for err in result["errors"])


def test_daily_expiry_requires_alert_or_notification() -> None:
    blueprint = {
        "name": "daily_expiry",
        "version": "v1",
        "steps": [
            {
                "id": "scan",
                "block": "daily_expiry_scan",
                "inputs": {"window_days": 7},
            }
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is False
    assert any("daily expiry saga requires alert_block" in err for err in result["errors"])


def test_daily_expiry_scan_before_alert() -> None:
    blueprint = {
        "name": "daily_expiry",
        "version": "v1",
        "steps": [
            {
                "id": "alert",
                "block": "alert_block",
                "inputs": {"expiring_items": []},
            },
            {
                "id": "scan",
                "block": "daily_expiry_scan",
                "inputs": {"window_days": 7},
            },
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is False
    assert any("daily_expiry_scan must occur before alert_block" in err for err in result["errors"])


def test_hot_offer_requires_blocks() -> None:
    blueprint = {
        "name": "hot_offer_flow",
        "version": "v1",
        "steps": [
            {
                "id": "priority_scan",
                "block": "priority_inventory_scan",
                "inputs": {},
            },
            {
                "id": "generate_offer",
                "block": "hot_offer_generator",
                "inputs": {"priority_items": []},
            },
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is False
    assert any("hot offer saga missing required blocks" in err for err in result["errors"])


def test_hot_offer_ordering() -> None:
    blueprint = {
        "name": "hot_offer_flow",
        "version": "v1",
        "steps": [
            {
                "id": "generate_offer",
                "block": "hot_offer_generator",
                "inputs": {"priority_items": []},
            },
            {
                "id": "priority_scan",
                "block": "priority_inventory_scan",
                "inputs": {},
            },
            {
                "id": "sales_stats",
                "block": "sales_stats_fetch",
                "inputs": {},
            },
            {
                "id": "validate",
                "block": "culinary_validator",
                "inputs": {"offer": {}},
            },
            {
                "id": "approval",
                "block": "approval_block",
                "inputs": {"offer_id": "o1", "approved": False},
            },
        ],
    }

    result = _architect().validate_blueprint(blueprint)
    assert result["ok"] is False
    assert any("hot offer saga blocks must be ordered" in err for err in result["errors"])
