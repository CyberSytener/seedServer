from __future__ import annotations

from app.infrastructure.db.sqlite import DB
from app.services.marketplace import MarketplaceService


def _build_service(tmp_path):
    db = DB(str(tmp_path / "marketplace_service.db"))
    db.init_schema()
    return MarketplaceService(db)


def test_marketplace_service_catalog_visibility_and_listing(tmp_path):
    service = _build_service(tmp_path)

    service.upsert_listing(
        mode_id="general_assistant",
        display_name="General Assistant",
        visibility="public",
    )
    service.upsert_listing(
        mode_id="internal_assistant",
        display_name="Internal Assistant",
        visibility="private",
    )

    public_rows = service.list_listings()
    assert len(public_rows) == 1
    assert public_rows[0]["mode_id"] == "general_assistant"

    all_rows = service.list_listings(include_private=True)
    mode_ids = {row["mode_id"] for row in all_rows}
    assert mode_ids == {"general_assistant", "internal_assistant"}


def test_marketplace_service_reputation_rollup(tmp_path):
    service = _build_service(tmp_path)
    service.upsert_listing(mode_id="general_assistant", visibility="public")

    service.upsert_rating(mode_id="general_assistant", user_id="u1", rating=5)
    service.upsert_rating(mode_id="general_assistant", user_id="u2", rating=4)
    reputation = service.get_reputation("general_assistant")

    assert reputation["rating_count"] == 2
    assert reputation["average_rating"] == 4.5
    assert reputation["distribution"]["4"] == 1
    assert reputation["distribution"]["5"] == 1
    assert reputation["trust_score"] > 0.0


def test_marketplace_service_sandbox_policy_enforcement(tmp_path):
    service = _build_service(tmp_path)
    service.upsert_listing(
        mode_id="general_assistant",
        visibility="public",
        sandbox_policy={
            "allowed_capabilities": ["llm.generate"],
            "blocked_capabilities": ["llm.read"],
        },
    )

    violations = service.validate_sandbox_request(
        mode_id="general_assistant",
        requested_capabilities=["llm.read"],
    )
    assert "marketplace_sandbox_capability_denied:llm.read" in violations
    assert "marketplace_sandbox_capability_blocked:llm.read" in violations


def test_marketplace_service_revenue_split_and_usage_export(tmp_path):
    service = _build_service(tmp_path)
    service.upsert_listing(
        mode_id="general_assistant",
        visibility="public",
        billing_policy={"revenue_share_creator_pct": 0.8},
    )

    event = service.record_usage_event(
        mode_id="general_assistant",
        consumer_user_id="consumer_1",
        event_type="run_started",
        credits=10.0,
        cost_usd=1.25,
    )

    assert event["creator_share_credits"] == 8.0
    assert event["platform_share_credits"] == 2.0

    export = service.export_usage(mode_id="general_assistant", hours=24)
    assert export["event_count"] == 1
    assert export["totals"]["gross_credits"] == 10.0
    assert export["totals"]["creator_share_credits"] == 8.0
    assert export["totals"]["platform_share_credits"] == 2.0


def test_marketplace_service_settlement_creates_idempotent_payout(tmp_path):
    service = _build_service(tmp_path)
    service.upsert_listing(
        mode_id="general_assistant",
        visibility="public",
        owner_tenant_id="tenant_alpha",
        billing_policy={
            "revenue_share_creator_pct": 0.8,
            "minimum_payout_credits": 5.0,
            "settlement_window_days": 30,
        },
    )
    service.record_usage_event(
        mode_id="general_assistant",
        consumer_user_id="consumer_1",
        event_type="run_completed",
        credits=10.0,
        cost_usd=1.0,
    )

    first = service.run_settlement(run_id="settlement_run_1", mode_id="general_assistant")
    assert first["created_count"] == 1
    assert first["skipped_existing_count"] == 0
    payout = first["created"][0]
    assert payout["payout_eligible"] is True
    assert payout["status"] == "ready"
    assert payout["owner_tenant_id"] == "tenant_alpha"
    assert payout["creator_share_credits"] == 8.0

    second = service.run_settlement(run_id="settlement_run_2", mode_id="general_assistant")
    assert second["created_count"] == 0
    assert second["skipped_existing_count"] == 1

    listed = service.list_payouts(mode_id="general_assistant")
    assert len(listed) == 1
    assert listed[0]["payout_id"] == payout["payout_id"]


def test_marketplace_service_settlement_marks_below_minimum(tmp_path):
    service = _build_service(tmp_path)
    service.upsert_listing(
        mode_id="general_assistant",
        visibility="public",
        owner_tenant_id="tenant_alpha",
        billing_policy={
            "revenue_share_creator_pct": 0.5,
            "minimum_payout_credits": 50.0,
            "settlement_window_days": 30,
        },
    )
    service.record_usage_event(
        mode_id="general_assistant",
        consumer_user_id="consumer_1",
        event_type="run_completed",
        credits=10.0,
        cost_usd=1.0,
    )

    result = service.run_settlement(run_id="settlement_run_3", mode_id="general_assistant")
    assert result["created_count"] == 1
    assert result["skipped_below_minimum_count"] == 1
    payout = result["created"][0]
    assert payout["payout_eligible"] is False
    assert payout["status"] == "below_minimum"
    assert payout["creator_share_credits"] == 5.0
