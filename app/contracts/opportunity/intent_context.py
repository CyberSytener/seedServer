from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, JsonValue, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from .primitives import (
    ConfidenceValueV1,
    ConfirmationClass,
    NonEmptyText,
    OpportunityPrimitiveModel,
    SemanticVersion,
    StableReference,
    StableStringEnum,
)


INTENT_CONTEXT_SCHEMA_VERSION = "1.0.0"
CAPABILITY_ID_PATTERN = r"^[a-z][a-z0-9._-]{1,127}$"
OBJECTIVE_KEY_PATTERN = r"^[a-z][a-z0-9._-]{1,127}$"

CapabilityId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, pattern=CAPABILITY_ID_PATTERN),
]
ObjectiveKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, pattern=OBJECTIVE_KEY_PATTERN),
]


class GoalOrigin(StableStringEnum):
    EXPLICIT = "explicit"
    CONFIRMED_INFERENCE = "confirmed_inference"


class InterestOrigin(StableStringEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class PreferenceSource(StableStringEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    LEARNED = "learned"


class PermissionDecision(StableStringEnum):
    ALLOW = "allow"
    DENY = "deny"


class CapabilityEffectClass(StableStringEnum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    CONSEQUENTIAL = "consequential"


class OptimizationDirection(StableStringEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    TARGET = "target"
    MAINTAIN = "maintain"


class ConstraintOperator(StableStringEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    AT_MOST = "at_most"
    AT_LEAST = "at_least"
    IN_SET = "in_set"
    NOT_IN_SET = "not_in_set"


class ConfirmationRecordV1(OpportunityPrimitiveModel):
    actor_id: StableReference
    confirmed_at: AwareDatetime
    confirmation_version: SemanticVersion
    method: Literal["explicit_user", "confirmed_inference", "authorized_delegate"]


class InterestSignalV1(OpportunityPrimitiveModel):
    interest_id: StableReference
    statement: NonEmptyText
    origin: InterestOrigin
    confidence: ConfidenceValueV1
    confirmation: ConfirmationRecordV1 | None = None

    @model_validator(mode="after")
    def explicit_interest_requires_confirmation(self) -> "InterestSignalV1":
        if self.origin is InterestOrigin.EXPLICIT and self.confirmation is None:
            raise PydanticCustomError(
                "opportunity.intent_explicit_interest_confirmation_required",
                "explicit interests require a confirmation record",
            )
        return self

    @property
    def is_confirmed(self) -> bool:
        return self.confirmation is not None


class ConfirmedGoalV1(OpportunityPrimitiveModel):
    goal_id: StableReference
    statement: NonEmptyText
    origin: GoalOrigin
    confirmation: ConfirmationRecordV1
    derived_from_interest_ids: tuple[StableReference, ...] = ()

    @model_validator(mode="after")
    def inference_origin_requires_links(self) -> "ConfirmedGoalV1":
        if (
            self.origin is GoalOrigin.CONFIRMED_INFERENCE
            and not self.derived_from_interest_ids
        ):
            raise PydanticCustomError(
                "opportunity.intent_inferred_goal_interest_link_required",
                "confirmed inferred goals require linked interest IDs",
            )
        if self.origin is GoalOrigin.EXPLICIT and self.derived_from_interest_ids:
            raise PydanticCustomError(
                "opportunity.intent_explicit_goal_interest_links_forbidden",
                "explicit goals must not claim inferred-interest lineage",
            )
        return self


class IntentConstraintV1(OpportunityPrimitiveModel):
    constraint_id: StableReference
    key: ObjectiveKey
    operator: ConstraintOperator
    value: JsonValue
    reason: NonEmptyText | None = None


class UserPreferenceV1(OpportunityPrimitiveModel):
    preference_id: StableReference
    key: ObjectiveKey
    value: JsonValue
    source: PreferenceSource
    confidence: ConfidenceValueV1
    confirmation: ConfirmationRecordV1 | None = None


class CapabilityPermissionV1(OpportunityPrimitiveModel):
    capability_id: CapabilityId
    decision: PermissionDecision
    effect_class: CapabilityEffectClass
    confirmation_class: ConfirmationClass = ConfirmationClass.NONE
    requires_runtime_confirmation: bool = False
    confirmation: ConfirmationRecordV1 | None = None
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_consequential_permission(self) -> "CapabilityPermissionV1":
        if self.decision is PermissionDecision.DENY:
            return self

        if self.effect_class is CapabilityEffectClass.CONSEQUENTIAL:
            if self.confirmation is None:
                raise PydanticCustomError(
                    "opportunity.intent_consequential_permission_confirmation_required",
                    "allowed consequential capabilities require intent confirmation",
                )
            if self.confirmation_class is ConfirmationClass.NONE:
                raise PydanticCustomError(
                    "opportunity.intent_consequential_confirmation_class_required",
                    "allowed consequential capabilities require a confirmation class",
                )
            if not self.requires_runtime_confirmation:
                raise PydanticCustomError(
                    "opportunity.intent_consequential_runtime_confirmation_required",
                    "allowed consequential capabilities require runtime confirmation",
                )

        if self.capability_id == "execute_financial_actions":
            if self.effect_class is not CapabilityEffectClass.CONSEQUENTIAL:
                raise PydanticCustomError(
                    "opportunity.intent_financial_capability_must_be_consequential",
                    "execute_financial_actions must be classified as consequential",
                )
            if self.confirmation_class not in {
                ConfirmationClass.ELEVATED,
                ConfirmationClass.DUAL_CONTROL,
            }:
                raise PydanticCustomError(
                    "opportunity.intent_financial_confirmation_too_weak",
                    "execute_financial_actions requires elevated or dual-control confirmation",
                )
        return self


class OptimizationTargetV1(OpportunityPrimitiveModel):
    target_id: StableReference
    objective_key: ObjectiveKey
    direction: OptimizationDirection
    priority: int = Field(ge=1, le=100)
    target_value: JsonValue | None = None
    rationale: NonEmptyText

    @model_validator(mode="after")
    def target_direction_requires_value(self) -> "OptimizationTargetV1":
        if self.direction is OptimizationDirection.TARGET and self.target_value is None:
            raise PydanticCustomError(
                "opportunity.intent_target_value_required",
                "target optimization requires target_value",
            )
        return self


class ForbiddenObjectiveV1(OpportunityPrimitiveModel):
    objective_id: StableReference
    objective_key: ObjectiveKey
    reason: NonEmptyText


class IntentContextV1(OpportunityPrimitiveModel):
    schema_version: Literal["1.0.0"] = INTENT_CONTEXT_SCHEMA_VERSION
    context_id: StableReference
    tenant_id: StableReference
    user_id: StableReference
    goals: tuple[ConfirmedGoalV1, ...] = Field(min_length=1)
    interests: tuple[InterestSignalV1, ...] = ()
    constraints: tuple[IntentConstraintV1, ...] = ()
    preferences: tuple[UserPreferenceV1, ...] = ()
    permissions: tuple[CapabilityPermissionV1, ...] = ()
    optimization_targets: tuple[OptimizationTargetV1, ...] = Field(min_length=1)
    forbidden_objectives: tuple[ForbiddenObjectiveV1, ...] = Field(min_length=1)
    confirmation: ConfirmationRecordV1

    @model_validator(mode="after")
    def validate_context_invariants(self) -> "IntentContextV1":
        self._require_unique("goal_id", self.goals)
        self._require_unique("interest_id", self.interests)
        self._require_unique("constraint_id", self.constraints)
        self._require_unique("preference_id", self.preferences)
        self._require_unique("capability_id", self.permissions)
        self._require_unique("target_id", self.optimization_targets)
        self._require_unique("objective_id", self.forbidden_objectives)

        interest_by_id = {item.interest_id: item for item in self.interests}
        for goal in self.goals:
            if goal.origin is not GoalOrigin.CONFIRMED_INFERENCE:
                continue
            for interest_id in goal.derived_from_interest_ids:
                interest = interest_by_id.get(interest_id)
                if interest is None:
                    raise PydanticCustomError(
                        "opportunity.intent_goal_interest_not_found",
                        "confirmed inferred goal references an unknown interest",
                        {"interest_id": interest_id},
                    )
                if not interest.is_confirmed:
                    raise PydanticCustomError(
                        "opportunity.intent_unconfirmed_interest_promotion",
                        "an inferred interest cannot become a confirmed goal without confirmation",
                        {"interest_id": interest_id},
                    )

        forbidden_keys = {
            objective.objective_key for objective in self.forbidden_objectives
        }
        conflicts = sorted(
            target.objective_key
            for target in self.optimization_targets
            if target.objective_key in forbidden_keys
        )
        if conflicts:
            raise PydanticCustomError(
                "opportunity.intent_forbidden_optimization_conflict",
                "optimization targets conflict with forbidden objectives",
                {"objective_keys": conflicts},
            )
        return self

    @staticmethod
    def _require_unique(attribute: str, items: tuple[Any, ...]) -> None:
        values = [getattr(item, attribute) for item in items]
        if len(values) != len(set(values)):
            raise PydanticCustomError(
                "opportunity.intent_duplicate_identifier",
                "intent context contains duplicate identifiers",
                {"attribute": attribute},
            )

    def permission_for(self, capability_id: str) -> CapabilityPermissionV1 | None:
        return next(
            (
                permission
                for permission in self.permissions
                if permission.capability_id == capability_id
            ),
            None,
        )

    def is_capability_allowed(self, capability_id: str) -> bool:
        permission = self.permission_for(capability_id)
        return bool(
            permission is not None
            and permission.decision is PermissionDecision.ALLOW
        )

    @property
    def execute_financial_actions(self) -> bool:
        """Default-deny financial execution permission."""

        return self.is_capability_allowed("execute_financial_actions")


def intent_context_schema_v1() -> dict[str, Any]:
    return IntentContextV1.model_json_schema(mode="validation")
