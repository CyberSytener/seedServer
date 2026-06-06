from __future__ import annotations

from pathlib import Path

import yaml

from scripts import validate_modules as vm


ROOT = Path(__file__).resolve().parents[2]


def _base_spec() -> dict:
    return yaml.safe_load((ROOT / "modules" / "general_assistant.yaml").read_text(encoding="utf-8"))


def test_module_registry_contract_accepts_valid_spec():
    errors = vm._validate(Path("modules/general_assistant.yaml"), _base_spec())
    assert errors == []


def test_module_registry_contract_requires_semver_key():
    spec = _base_spec()
    spec.pop("module_version")
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert any("[contract.required] $.module_version:" in error for error in errors)


def test_module_registry_contract_rejects_invalid_semver_value():
    spec = _base_spec()
    spec["module_version"] = "1.2"
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert any("[contract.pattern] $.module_version:" in error for error in errors)


def test_module_registry_contract_requires_boolean_breaking_changes():
    spec = _base_spec()
    spec["breaking_changes"] = "false"
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert any("$.breaking_changes:" in error for error in errors)


def test_module_registry_contract_requires_prompt_and_rubric_versions():
    spec = _base_spec()
    spec["prompt_versions"] = []
    spec["rubric_versions"] = [""]
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert any("$.prompt_versions:" in error for error in errors)
    assert any("$.rubric_versions.0:" in error for error in errors)


def test_module_registry_contract_requires_migration_entries_to_be_objects():
    spec = _base_spec()
    spec["migrations"] = ["001_initial"]
    errors = vm._validate(Path("modules/general_assistant.yaml"), spec)
    assert any("$.migrations.0:" in error for error in errors)
