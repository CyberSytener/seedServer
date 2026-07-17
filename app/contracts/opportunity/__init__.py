"""Portable versioned contracts for the Intent-to-Outcome Candidate surface.

This package must remain independent of FastAPI, persistence adapters, provider
clients, and UI code. Versioned primitives reject unknown fields by policy so
contract evolution is explicit and reviewable.
"""

from .primitives import (
    ActionProposalStatus,
    ConfidenceValueV1,
    ConfirmationClass,
    EvidenceRelationType,
    HypothesisStatus,
    MoneyAmountV1,
    OpportunityPrimitiveModel,
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
    StableStringEnum,
    shared_primitives_schema_snapshot_v1,
)

__all__ = (
    "ActionProposalStatus",
    "ConfidenceValueV1",
    "ConfirmationClass",
    "EvidenceRelationType",
    "HypothesisStatus",
    "MoneyAmountV1",
    "OpportunityPrimitiveModel",
    "OpportunityStatus",
    "OutcomeStatus",
    "PolicyVersionRefV1",
    "ProvenanceStepV1",
    "RetentionClass",
    "ReversibilityClass",
    "SHARED_PRIMITIVES_COMPATIBILITY_POLICY",
    "SHARED_PRIMITIVES_SCHEMA_VERSION",
    "SensitivityClass",
    "SourceTimestampsV1",
    "StableStringEnum",
    "shared_primitives_schema_snapshot_v1",
)
