from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from app.contracts import check_module_compatibility, migrate_legacy_module, validate_module_contract


ROOT = Path(__file__).resolve().parents[2]


def _module() -> dict:
    return yaml.safe_load((ROOT / "modules" / "general_assistant.yaml").read_text(encoding="utf-8"))


def _module_by_id(module_id: str) -> dict:
    return yaml.safe_load((ROOT / "modules" / f"{module_id}.yaml").read_text(encoding="utf-8"))


def test_committed_contract_schema_is_valid_json_schema() -> None:
    schema = json.loads((ROOT / "app" / "contracts" / "module_contract_v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for path in sorted((ROOT / "modules").glob("*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert list(validator.iter_errors(spec)) == [], path.name


@pytest.mark.parametrize(
    "module_id",
    ["general_assistant", "market_scanner", "job_scorer", "notification_block"],
)
def test_committed_modules_satisfy_module_contract_v1(module_id: str) -> None:
    assert validate_module_contract(_module_by_id(module_id)) == []


def test_contract_errors_are_machine_readable() -> None:
    spec = _module()
    spec.pop("execution")

    issues = validate_module_contract(spec)

    assert any(issue.code == "contract.required" and issue.path == "$.execution" for issue in issues)


def test_contract_rejects_invalid_json_schema() -> None:
    spec = _module()
    spec["input_schema"] = {"type": "array"}

    issues = validate_module_contract(spec)

    assert any(issue.code == "schema.root_type" and issue.path == "$.input_schema.type" for issue in issues)


def test_contract_rejects_pipeline_adapter_mismatch() -> None:
    spec = _module()
    spec["execution"]["adapter"] = "block_registry"

    issues = validate_module_contract(spec)

    assert any(issue.code == "execution.adapter_mismatch" for issue in issues)


def test_legacy_adapter_produces_valid_draft_contract() -> None:
    legacy = _module()
    for field in (
        "contract_version",
        "title",
        "description",
        "owner",
        "lifecycle",
        "errors",
        "execution",
        "effects",
        "security",
        "resources",
        "compatibility",
        "evidence",
    ):
        legacy.pop(field)

    migrated = migrate_legacy_module(legacy)

    assert migrated["lifecycle"] == "draft"
    assert migrated["security"]["trust_level"] == "untrusted"
    assert validate_module_contract(migrated) == []


def test_compatibility_reports_missing_required_output() -> None:
    producer = _module()
    consumer = _module()
    producer["output_schema"]["properties"].pop("answer")

    issues = check_module_compatibility(producer, consumer)

    assert any(issue.code == "compatibility.missing_required_output" for issue in issues)


def test_compatibility_requires_producer_to_guarantee_output() -> None:
    producer = _module()
    consumer = _module()
    producer["output_schema"]["required"] = []
    consumer["input_schema"] = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }

    issues = check_module_compatibility(producer, consumer)

    assert any(issue.code == "compatibility.missing_required_output" for issue in issues)


def test_compatibility_reports_type_mismatch() -> None:
    producer = _module()
    consumer = _module()
    producer["output_schema"]["properties"]["answer"]["type"] = ["string", "null"]
    consumer["input_schema"] = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }

    issues = check_module_compatibility(producer, consumer)

    assert any(issue.code == "compatibility.type_mismatch" for issue in issues)


def test_compatibility_accepts_matching_contracts() -> None:
    producer = _module()
    consumer = _module()
    consumer["input_schema"] = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }

    assert check_module_compatibility(producer, consumer) == []
