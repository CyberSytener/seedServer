from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.opportunity import (
    ActionProposalStatus,
    ConfidenceValueV1,
    ConfirmationClass,
    EvidenceRelationType,
    HypothesisStatus,
    MoneyAmountV1,
    OpportunityStatus,
    OutcomeStatus,
    PolicyVersionRefV1,
    ProvenanceStepV1,
    RetentionClass,
    ReversibilityClass,
    SHARED_PRIMITIVES_COMPATIBILITY_POLICY,
    SHARED_PRIMITIVES_SCHEMA_VERSION,
    SensitivityClass,
    SourceTimestampsV1,
    shared_primitives_schema_snapshot_v1,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "opportunity"
    / "shared_primitives_v1.schema.json"
)


def _error_type(exc_info: pytest.ExceptionInfo[ValidationError]) -> str:
    return str(exc_info.value.errors(include_url=False)[0]["type"])


def test_shared_primitives_round_trip_through_json_payloads() -> None:
    observed_at = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    instances = (
        ConfidenceValueV1(value=0.75),
        SourceTimestampsV1(
            observed_at=observed_at,
            ingested_at=observed_at + timedelta(seconds=2),
            source_updated_at=observed_at - timedelta(minutes=5),
        ),
        ProvenanceStepV1(
            step_id="step:normalize:1",
            operation="normalize source claim",
            processor_id="evidence_synthesizer",
            processor_version="1.0.0",
            performed_at=observed_at,
            input_refs=("source:item:1",),
            output_ref="evidence:item:1",
        ),
        MoneyAmountV1(currency="NOK", minor_units=129900),
        PolicyVersionRefV1(
            policy_id="opportunity.scoring",
            version="1.0.0",
            digest_sha256="a" * 64,
        ),
    )

    for instance in instances:
        payload = json.loads(instance.model_dump_json())
        restored = type(instance).model_validate(payload)
        assert restored == instance
        assert restored.model_dump(mode="json") == payload


@pytest.mark.parametrize("value", (-0.01, 1.01, float("inf"), float("-inf"), float("nan")))
def test_confidence_rejects_out_of_range_values_with_stable_code(value: float) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ConfidenceValueV1(value=value)

    assert _error_type(exc_info) == "opportunity.confidence_out_of_range"


@pytest.mark.parametrize("value", ("0.5", True, None))
def test_confidence_rejects_non_numeric_values_with_stable_code(value: object) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ConfidenceValueV1(value=value)

    assert _error_type(exc_info) == "opportunity.confidence_number_required"


def test_source_timestamps_require_timezone_information() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SourceTimestampsV1(
            observed_at=datetime(2026, 7, 17, 8, 0),
            ingested_at=datetime(2026, 7, 17, 8, 1),
        )

    assert {error["type"] for error in exc_info.value.errors(include_url=False)} == {
        "timezone_aware"
    }


def test_source_timestamps_reject_ingestion_before_observation() -> None:
    observed_at = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)

    with pytest.raises(ValidationError) as exc_info:
        SourceTimestampsV1(
            observed_at=observed_at,
            ingested_at=observed_at - timedelta(seconds=1),
        )

    assert _error_type(exc_info) == (
        "opportunity.timestamps_ingestion_before_observation"
    )


@pytest.mark.parametrize("minor_units", (1.5, "100", True))
def test_money_rejects_non_integer_minor_units(minor_units: object) -> None:
    with pytest.raises(ValidationError) as exc_info:
        MoneyAmountV1(currency="NOK", minor_units=minor_units)

    assert _error_type(exc_info) == "int_type"


def test_money_rejects_negative_minor_units() -> None:
    with pytest.raises(ValidationError) as exc_info:
        MoneyAmountV1(currency="NOK", minor_units=-1)

    assert _error_type(exc_info) == "greater_than_equal"


@pytest.mark.parametrize("currency", ("nok", "NO", "US-D", ""))
def test_money_rejects_noncanonical_currency_codes(currency: str) -> None:
    with pytest.raises(ValidationError):
        MoneyAmountV1(currency=currency, minor_units=0)


def test_unknown_fields_are_rejected_by_explicit_compatibility_policy() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ConfidenceValueV1.model_validate({"value": 0.5, "future_field": True})

    assert _error_type(exc_info) == "extra_forbidden"
    assert "reject unknown fields" in SHARED_PRIMITIVES_COMPATIBILITY_POLICY


def test_shared_primitives_are_immutable() -> None:
    confidence = ConfidenceValueV1(value=0.5)

    with pytest.raises(ValidationError) as exc_info:
        confidence.value = 0.6

    assert _error_type(exc_info) == "frozen_instance"


def test_enum_values_are_stable_strings() -> None:
    expected = {
        SensitivityClass: ["public", "internal", "personal", "sensitive", "restricted"],
        RetentionClass: ["ephemeral", "session", "short_term", "user_managed", "long_term"],
        EvidenceRelationType: [
            "supports",
            "contradicts",
            "qualifies",
            "duplicates",
            "supersedes",
        ],
        ConfirmationClass: ["none", "user", "elevated", "dual_control"],
        ReversibilityClass: [
            "fully_reversible",
            "compensatable",
            "partially_reversible",
            "irreversible",
        ],
        HypothesisStatus: [
            "proposed",
            "testing",
            "supported",
            "weakened",
            "rejected",
            "expired",
        ],
        OpportunityStatus: [
            "candidate",
            "reviewed",
            "approved_for_experiment",
            "active",
            "completed",
            "dismissed",
            "expired",
        ],
        ActionProposalStatus: [
            "proposed",
            "policy_denied",
            "waiting_confirmation",
            "confirmed",
            "rejected",
            "expired",
            "submitted",
            "cancelled",
        ],
        OutcomeStatus: ["recorded", "reviewed", "inconclusive", "superseded"],
    }

    for enum_type, values in expected.items():
        assert [member.value for member in enum_type] == values
        assert [str(member) for member in enum_type] == values


def test_schema_snapshot_is_versioned_and_stable() -> None:
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert SHARED_PRIMITIVES_SCHEMA_VERSION == "1.0.0"
    assert shared_primitives_schema_snapshot_v1() == expected
