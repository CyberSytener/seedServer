from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Any, ClassVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError


SHARED_PRIMITIVES_SCHEMA_VERSION = "1.0.0"
SHARED_PRIMITIVES_COMPATIBILITY_POLICY = (
    "Shared primitive v1 models reject unknown fields. Additive or breaking "
    "shape changes require an explicit schema-version update and snapshot review."
)

SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"
POLICY_ID_PATTERN = r"^[a-z][a-z0-9._-]{1,127}$"
CURRENCY_PATTERN = r"^[A-Z][A-Z0-9]{2,11}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=512),
]
StableReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, pattern=REFERENCE_PATTERN),
]
SemanticVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, pattern=SEMVER_PATTERN),
]


class OpportunityPrimitiveModel(BaseModel):
    """Strict immutable base for versioned Intent-to-Outcome primitives."""

    compatibility_policy: ClassVar[str] = SHARED_PRIMITIVES_COMPATIBILITY_POLICY
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class StableStringEnum(str, Enum):
    """String enum with stable JSON values and readable ``str()`` output."""

    def __str__(self) -> str:
        return self.value


class SensitivityClass(StableStringEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class RetentionClass(StableStringEnum):
    EPHEMERAL = "ephemeral"
    SESSION = "session"
    SHORT_TERM = "short_term"
    USER_MANAGED = "user_managed"
    LONG_TERM = "long_term"


class EvidenceRelationType(StableStringEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    DUPLICATES = "duplicates"
    SUPERSEDES = "supersedes"


class ConfirmationClass(StableStringEnum):
    NONE = "none"
    USER = "user"
    ELEVATED = "elevated"
    DUAL_CONTROL = "dual_control"


class ReversibilityClass(StableStringEnum):
    FULLY_REVERSIBLE = "fully_reversible"
    COMPENSATABLE = "compensatable"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"


class HypothesisStatus(StableStringEnum):
    PROPOSED = "proposed"
    TESTING = "testing"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OpportunityStatus(StableStringEnum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    APPROVED_FOR_EXPERIMENT = "approved_for_experiment"
    ACTIVE = "active"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class ActionProposalStatus(StableStringEnum):
    PROPOSED = "proposed"
    POLICY_DENIED = "policy_denied"
    WAITING_CONFIRMATION = "waiting_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class OutcomeStatus(StableStringEnum):
    RECORDED = "recorded"
    REVIEWED = "reviewed"
    INCONCLUSIVE = "inconclusive"
    SUPERSEDED = "superseded"


class ConfidenceValueV1(OpportunityPrimitiveModel):
    value: float = Field(ge=0.0, le=1.0)

    @field_validator("value", mode="before")
    @classmethod
    def validate_confidence(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PydanticCustomError(
                "opportunity.confidence_number_required",
                "confidence must be a JSON number",
            )
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0.0 or normalized > 1.0:
            raise PydanticCustomError(
                "opportunity.confidence_out_of_range",
                "confidence must be between 0.0 and 1.0 inclusive",
            )
        return normalized


class SourceTimestampsV1(OpportunityPrimitiveModel):
    observed_at: AwareDatetime
    ingested_at: AwareDatetime
    source_updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def ingestion_cannot_precede_observation(self) -> "SourceTimestampsV1":
        if self.ingested_at < self.observed_at:
            raise PydanticCustomError(
                "opportunity.timestamps_ingestion_before_observation",
                "ingested_at must not be earlier than observed_at",
            )
        return self


class ProvenanceStepV1(OpportunityPrimitiveModel):
    step_id: StableReference
    operation: NonEmptyText
    processor_id: StableReference
    processor_version: SemanticVersion
    performed_at: AwareDatetime
    input_refs: tuple[StableReference, ...] = ()
    output_ref: StableReference | None = None


class MoneyAmountV1(OpportunityPrimitiveModel):
    currency: Annotated[
        str,
        StringConstraints(strip_whitespace=True, strict=True, pattern=CURRENCY_PATTERN),
    ]
    minor_units: StrictInt = Field(ge=0)


class PolicyVersionRefV1(OpportunityPrimitiveModel):
    policy_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, strict=True, pattern=POLICY_ID_PATTERN),
    ]
    version: SemanticVersion
    digest_sha256: Annotated[
        str,
        StringConstraints(strip_whitespace=True, strict=True, pattern=SHA256_PATTERN),
    ] | None = None


ENUM_TYPES: tuple[type[StableStringEnum], ...] = (
    SensitivityClass,
    RetentionClass,
    EvidenceRelationType,
    ConfirmationClass,
    ReversibilityClass,
    HypothesisStatus,
    OpportunityStatus,
    ActionProposalStatus,
    OutcomeStatus,
)
MODEL_TYPES: tuple[type[OpportunityPrimitiveModel], ...] = (
    ConfidenceValueV1,
    SourceTimestampsV1,
    ProvenanceStepV1,
    MoneyAmountV1,
    PolicyVersionRefV1,
)


def shared_primitives_schema_snapshot_v1() -> dict[str, Any]:
    """Return the portable versioned schema contract used by snapshot tests."""

    return {
        "schema_version": SHARED_PRIMITIVES_SCHEMA_VERSION,
        "compatibility_policy": SHARED_PRIMITIVES_COMPATIBILITY_POLICY,
        "enums": {
            enum_type.__name__: [member.value for member in enum_type]
            for enum_type in ENUM_TYPES
        },
        "models": {
            model_type.__name__: model_type.model_json_schema(mode="validation")
            for model_type in MODEL_TYPES
        },
    }
