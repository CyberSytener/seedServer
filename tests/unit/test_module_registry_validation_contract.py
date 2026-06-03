from __future__ import annotations

from pathlib import Path

from scripts import validate_modules as vm


def _base_spec() -> dict:
    return {
        "mode_id": "general_assistant",
        "pipeline": "llm_pipeline",
        "input_schema": {"type": "object", "properties": {"user_request": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        "module_version": "1.2.3",
        "breaking_changes": False,
        "migrations": [],
        "prompt_versions": ["general_assistant.prompt.v1"],
        "rubric_versions": ["general_assistant.rubric.v1"],
        "tests": {
            "golden": [
                {
                    "input": {"user_request": "Summarize this text"},
                    "expect_fields": ["answer"],
                }
            ],
            "cost_regression": {"max_avg_cost_units": 3.0},
        },
    }


def test_module_registry_contract_accepts_valid_spec():
    errors = vm._validate(Path("modules/general_assistant.yaml"), _base_spec())
    assert errors == []


def test_module_registry_contract_requires_semver_key():
    spec = _base_spec()
    spec.pop("module_version")
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert any("missing key: module_version" in err for err in errors)


def test_module_registry_contract_rejects_invalid_semver_value():
    spec = _base_spec()
    spec["module_version"] = "1.2"
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert "module_version must be valid semver (e.g. 1.2.3)" in errors


def test_module_registry_contract_requires_boolean_breaking_changes():
    spec = _base_spec()
    spec["breaking_changes"] = "false"
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert "breaking_changes must be boolean" in errors


def test_module_registry_contract_requires_prompt_and_rubric_versions():
    spec = _base_spec()
    spec["prompt_versions"] = []
    spec["rubric_versions"] = [""]
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert "prompt_versions must be non-empty list" in errors
    assert "rubric_versions[0] must be non-empty string" in errors


def test_module_registry_contract_requires_migration_entries_to_be_objects():
    spec = _base_spec()
    spec["migrations"] = ["001_initial"]
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert "migrations[0] must be object" in errors
