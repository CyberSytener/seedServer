from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Dict, Iterable, List, Literal, Mapping, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
except Exception:  # pragma: no cover
    Draft202012Validator = None
    SchemaError = Exception


SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
CONTRACT_V1_PATTERN = r"^1\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
MODE_ID_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
NonEmptyString = Annotated[str, Field(min_length=1)]


class ContractIssue(BaseModel):
    code: str
    path: str
    message: str

    def as_message(self) -> str:
        return f"[{self.code}] {self.path}: {self.message}"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Owner(ContractModel):
    team: str = Field(min_length=1)
    contact: Optional[str] = None


class ExecutionPolicy(ContractModel):
    adapter: Literal["saga_orchestrator", "block_registry", "module_sdk"]
    timeout_seconds: int = Field(gt=0, le=3600)
    max_retries: int = Field(ge=0, le=10)
    idempotent: StrictBool
    deterministic: StrictBool


class EffectsPolicy(ContractModel):
    side_effects: StrictBool
    compensation_supported: StrictBool
    network_access: Literal["none", "provider_only", "allowlist"]
    filesystem_access: Literal["none", "read_only", "sandbox"]

    @model_validator(mode="after")
    def compensation_requires_side_effects(self) -> "EffectsPolicy":
        if self.compensation_supported and not self.side_effects:
            raise ValueError("compensation_supported requires side_effects")
        return self


class SecurityPolicy(ContractModel):
    trust_level: Literal["internal", "verified", "third_party", "untrusted"]
    secret_refs: List[NonEmptyString] = Field(default_factory=list)


class ResourcePolicy(ContractModel):
    memory_mb: int = Field(gt=0, le=65536)
    max_concurrency: int = Field(gt=0, le=1000)
    max_cost_units: float = Field(gt=0)
    providers: List[NonEmptyString] = Field(min_length=1)


class CompatibilityPolicy(ContractModel):
    accepts_contract_versions: List[NonEmptyString] = Field(min_length=1)
    module_dependencies: List[NonEmptyString] = Field(default_factory=list)


class DependencyPolicy(ContractModel):
    python: List[NonEmptyString] = Field(default_factory=list)


class ErrorDeclaration(ContractModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    retryable: StrictBool
    description: str = Field(min_length=1)
    payload_schema: Dict[str, Any] = Field(default_factory=dict)


class Evidence(ContractModel):
    documentation: List[NonEmptyString] = Field(min_length=1)
    examples: List[NonEmptyString] = Field(min_length=1)


class Migration(ContractModel):
    from_version: str = Field(pattern=SEMVER_PATTERN)
    to_version: str = Field(pattern=SEMVER_PATTERN)
    description: str = Field(min_length=1)


class GoldenCase(ContractModel):
    input: Dict[str, Any]
    expect_fields: List[NonEmptyString] = Field(min_length=1)


class CostRegression(ContractModel):
    max_avg_cost_units: float = Field(gt=0)


class ContractTests(ContractModel):
    golden: List[GoldenCase] = Field(min_length=1)
    cost_regression: CostRegression


class ModuleContractV1(ContractModel):
    contract_version: str = Field(pattern=CONTRACT_V1_PATTERN)
    mode_id: str = Field(pattern=MODE_ID_PATTERN)
    module_version: str = Field(pattern=SEMVER_PATTERN)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: Owner
    lifecycle: Literal["draft", "validated", "tested", "sandboxed", "approved", "published", "deprecated"]
    pipeline: Literal["llm_pipeline", "flow_block", "sdk_module"]
    task_type: str = Field(min_length=1)
    capabilities: List[NonEmptyString]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    errors: List[ErrorDeclaration] = Field(min_length=1)
    execution: ExecutionPolicy
    effects: EffectsPolicy
    security: SecurityPolicy
    resources: ResourcePolicy
    compatibility: CompatibilityPolicy
    dependencies: DependencyPolicy = Field(default_factory=DependencyPolicy)
    evidence: Evidence
    breaking_changes: StrictBool
    migrations: List[Migration]
    prompt_versions: List[NonEmptyString] = Field(min_length=1)
    rubric_versions: List[NonEmptyString] = Field(min_length=1)
    tests: ContractTests


def _location(parts: Iterable[Any]) -> str:
    rendered = ".".join(str(part) for part in parts)
    return f"$.{rendered}" if rendered else "$"


def _pydantic_issue(error: Dict[str, Any]) -> ContractIssue:
    error_type = str(error.get("type") or "value_error")
    path = _location(error.get("loc") or [])
    if error_type == "missing":
        code = "contract.required"
    elif error_type == "string_pattern_mismatch":
        code = "contract.pattern"
    elif error_type.startswith(("greater_than", "less_than")):
        code = "contract.range"
    else:
        code = "contract.invalid_value"
    return ContractIssue(code=code, path=path, message=str(error.get("msg") or error_type))


def _schema_issues(name: str, schema: Any) -> List[ContractIssue]:
    path = f"$.{name}"
    if not isinstance(schema, dict):
        return [ContractIssue(code="schema.not_object", path=path, message=f"{name} must be an object")]
    if schema.get("type") != "object":
        return [ContractIssue(code="schema.root_type", path=f"{path}.type", message="root schema type must be object")]
    if Draft202012Validator is None:
        return []
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return [
            ContractIssue(
                code="schema.invalid",
                path=_location([name, *list(getattr(exc, "path", []))]),
                message=str(exc.message),
            )
        ]
    return []


def validate_module_contract(spec: Mapping[str, Any]) -> List[ContractIssue]:
    issues: List[ContractIssue] = []
    try:
        ModuleContractV1.model_validate(dict(spec))
    except ValidationError as exc:
        issues.extend(_pydantic_issue(error) for error in exc.errors(include_url=False))

    issues.extend(_schema_issues("input_schema", spec.get("input_schema")))
    issues.extend(_schema_issues("output_schema", spec.get("output_schema")))

    capabilities = spec.get("capabilities")
    if isinstance(capabilities, list):
        normalized = [str(capability).strip() for capability in capabilities]
        if any(not capability for capability in normalized):
            issues.append(
                ContractIssue(
                    code="security.empty_capability",
                    path="$.capabilities",
                    message="capabilities must not contain empty values",
                )
            )
        if len(set(normalized)) != len(normalized):
            issues.append(
                ContractIssue(
                    code="security.duplicate_capability",
                    path="$.capabilities",
                    message="capabilities must be unique",
                )
            )

    dependencies = spec.get("dependencies") if isinstance(spec.get("dependencies"), dict) else {}
    python_dependencies = dependencies.get("python")
    if isinstance(python_dependencies, list):
        normalized_dependencies = [str(dependency).strip() for dependency in python_dependencies]
        if len(set(normalized_dependencies)) != len(normalized_dependencies):
            issues.append(
                ContractIssue(
                    code="security.duplicate_dependency",
                    path="$.dependencies.python",
                    message="python dependencies must be unique",
                )
            )

    security = spec.get("security") if isinstance(spec.get("security"), dict) else {}
    secret_refs = security.get("secret_refs")
    if isinstance(secret_refs, list):
        normalized_secret_refs = [str(secret_ref).strip() for secret_ref in secret_refs]
        if len(set(normalized_secret_refs)) != len(normalized_secret_refs):
            issues.append(
                ContractIssue(
                    code="security.duplicate_secret_ref",
                    path="$.security.secret_refs",
                    message="secret references must be unique",
                )
            )

    pipeline = str(spec.get("pipeline") or "").strip()
    execution = spec.get("execution") if isinstance(spec.get("execution"), dict) else {}
    adapter = str(execution.get("adapter") or "").strip()
    expected_adapters = {
        "llm_pipeline": "saga_orchestrator",
        "flow_block": "block_registry",
        "sdk_module": "module_sdk",
    }
    expected_adapter = expected_adapters.get(pipeline)
    if expected_adapter and adapter and adapter != expected_adapter:
        issues.append(
            ContractIssue(
                code="execution.adapter_mismatch",
                path="$.execution.adapter",
                message=f"pipeline '{pipeline}' requires execution adapter '{expected_adapter}'",
            )
        )

    return sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))


def migrate_legacy_module(spec: Mapping[str, Any]) -> Dict[str, Any]:
    migrated = deepcopy(dict(spec))
    if migrated.get("contract_version"):
        return migrated

    mode_id = str(migrated.get("mode_id") or "legacy_module").strip()
    tests = migrated.get("tests") if isinstance(migrated.get("tests"), dict) else {}
    cost_regression = tests.get("cost_regression") if isinstance(tests.get("cost_regression"), dict) else {}
    max_cost = cost_regression.get("max_avg_cost_units", 1.0)
    migrated.update(
        {
            "contract_version": "1.0.0",
            "title": str(migrated.get("title") or mode_id.replace("_", " ").title()),
            "description": str(migrated.get("description") or f"Migrated legacy module: {mode_id}."),
            "owner": migrated.get("owner") if isinstance(migrated.get("owner"), dict) else {"team": "unassigned"},
            "lifecycle": str(migrated.get("lifecycle") or "draft"),
            "task_type": str(migrated.get("task_type") or mode_id),
            "capabilities": migrated.get("capabilities") if isinstance(migrated.get("capabilities"), list) else [],
            "errors": migrated.get("errors")
            if isinstance(migrated.get("errors"), list)
            else [
                {
                    "code": "legacy_execution_failed",
                    "retryable": False,
                    "description": "Legacy module execution failed.",
                }
            ],
            "execution": migrated.get("execution")
            if isinstance(migrated.get("execution"), dict)
            else {
                "adapter": "saga_orchestrator",
                "timeout_seconds": 120,
                "max_retries": 0,
                "idempotent": False,
                "deterministic": False,
            },
            "effects": migrated.get("effects")
            if isinstance(migrated.get("effects"), dict)
            else {
                "side_effects": False,
                "compensation_supported": False,
                "network_access": "provider_only",
                "filesystem_access": "none",
            },
            "security": migrated.get("security")
            if isinstance(migrated.get("security"), dict)
            else {"trust_level": "untrusted", "secret_refs": []},
            "resources": migrated.get("resources")
            if isinstance(migrated.get("resources"), dict)
            else {
                "memory_mb": 256,
                "max_concurrency": 1,
                "max_cost_units": max_cost,
                "providers": ["stub"],
            },
            "compatibility": migrated.get("compatibility")
            if isinstance(migrated.get("compatibility"), dict)
            else {"accepts_contract_versions": ["1.x"], "module_dependencies": []},
            "dependencies": migrated.get("dependencies")
            if isinstance(migrated.get("dependencies"), dict)
            else {"python": []},
            "evidence": migrated.get("evidence")
            if isinstance(migrated.get("evidence"), dict)
            else {"documentation": ["migration-required"], "examples": ["legacy-manifest"]},
        }
    )
    execution = dict(migrated.get("execution") or {})
    execution.setdefault(
        "adapter",
        {
            "flow_block": "block_registry",
            "sdk_module": "module_sdk",
        }.get(str(migrated.get("pipeline") or ""), "saga_orchestrator"),
    )
    migrated["execution"] = execution
    return migrated


def _types(schema: Mapping[str, Any]) -> Set[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _contract_version_accepted(version: str, accepted: Iterable[Any]) -> bool:
    for raw_rule in accepted:
        rule = str(raw_rule).strip()
        if rule == version:
            return True
        if rule.endswith(".x") and version.startswith(f"{rule[:-2]}."):
            return True
    return False


def check_schema_compatibility(
    producer_output: Mapping[str, Any],
    consumer_input: Mapping[str, Any],
) -> List[ContractIssue]:
    issues: List[ContractIssue] = []
    producer_properties = producer_output.get("properties") if isinstance(producer_output.get("properties"), dict) else {}
    producer_required = producer_output.get("required") if isinstance(producer_output.get("required"), list) else []
    consumer_properties = consumer_input.get("properties") if isinstance(consumer_input.get("properties"), dict) else {}
    consumer_required = consumer_input.get("required") if isinstance(consumer_input.get("required"), list) else []

    for field in consumer_required:
        name = str(field)
        if name not in producer_properties or name not in producer_required:
            issues.append(
                ContractIssue(
                    code="compatibility.missing_required_output",
                    path=f"$.input_schema.properties.{name}",
                    message=f"producer output does not guarantee required consumer field '{name}'",
                )
            )

    for name in sorted(set(producer_properties) & set(consumer_properties)):
        producer_field = producer_properties.get(name)
        consumer_field = consumer_properties.get(name)
        if not isinstance(producer_field, dict) or not isinstance(consumer_field, dict):
            continue
        producer_types = _types(producer_field)
        consumer_types = _types(consumer_field)
        if producer_types and consumer_types and not producer_types.issubset(consumer_types):
            issues.append(
                ContractIssue(
                    code="compatibility.type_mismatch",
                    path=f"$.input_schema.properties.{name}.type",
                    message=(
                        f"producer types {sorted(producer_types)} are not accepted by consumer types "
                        f"{sorted(consumer_types)}"
                    ),
                )
            )
    return issues


def check_module_compatibility(
    producer: Mapping[str, Any],
    consumer: Mapping[str, Any],
) -> List[ContractIssue]:
    producer_version = str(producer.get("contract_version") or "")
    compatibility = consumer.get("compatibility") if isinstance(consumer.get("compatibility"), dict) else {}
    accepted = compatibility.get("accepts_contract_versions")
    issues: List[ContractIssue] = []
    if not isinstance(accepted, list) or not _contract_version_accepted(producer_version, accepted):
        issues.append(
            ContractIssue(
                code="compatibility.contract_version",
                path="$.compatibility.accepts_contract_versions",
                message=f"consumer does not accept producer contract version '{producer_version or 'missing'}'",
            )
        )

    producer_output = producer.get("output_schema") if isinstance(producer.get("output_schema"), dict) else {}
    consumer_input = consumer.get("input_schema") if isinstance(consumer.get("input_schema"), dict) else {}
    issues.extend(check_schema_compatibility(producer_output, consumer_input))
    return sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
