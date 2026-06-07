from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from app.module_sdk import (
    ModuleExecutionContext,
    ModuleSDKError,
    assess_module_readiness,
    create_module_package,
    execute_module,
    fingerprint_module_package,
    qualify_module_package,
    record_module_evidence,
    run_module_package_tests,
    sandbox_module_package,
    transition_module_lifecycle,
    validate_module_package,
)
from app.module_sdk.package import resolve_module_package
from app.module_sdk.package import validate_handler_dependencies


class _EchoHandler:
    async def execute(self, context: ModuleExecutionContext, inputs: dict) -> dict:
        return {"result": f"{context.module_id}:{inputs['request']}"}


class _BadOutputHandler:
    async def execute(self, context: ModuleExecutionContext, inputs: dict) -> dict:
        del context, inputs
        return {"wrong": True}


class _DeclaredFailureHandler:
    async def execute(self, context: ModuleExecutionContext, inputs: dict) -> dict:
        del context, inputs
        raise ModuleSDKError("demo_failed", "Expected failure", retryable=True)


class _InvalidEnvelopeHandler:
    async def execute(self, context: ModuleExecutionContext, inputs: dict) -> str:
        del context, inputs
        return "not-an-envelope"


def _context() -> ModuleExecutionContext:
    return ModuleExecutionContext(module_id="demo_module", run_id="test-run")


def _input_schema() -> dict:
    return {
        "type": "object",
        "required": ["request"],
        "properties": {"request": {"type": "string"}},
    }


def _output_schema() -> dict:
    return {
        "type": "object",
        "required": ["result"],
        "properties": {"result": {"type": "string"}},
    }


def test_execute_module_validates_input_and_output() -> None:
    invalid_input = asyncio.run(
        execute_module(
            _EchoHandler(),
            context=_context(),
            inputs={},
            input_schema=_input_schema(),
            output_schema=_output_schema(),
        )
    )
    invalid_output = asyncio.run(
        execute_module(
            _BadOutputHandler(),
            context=_context(),
            inputs={"request": "hello"},
            input_schema=_input_schema(),
            output_schema=_output_schema(),
        )
    )

    assert invalid_input.error is not None
    assert invalid_input.error.code == "sdk.input_invalid"
    assert invalid_output.error is not None
    assert invalid_output.error.code == "sdk.output_invalid"


def test_execute_module_preserves_declared_sdk_error() -> None:
    result = asyncio.run(
        execute_module(
            _DeclaredFailureHandler(),
            context=_context(),
            inputs={"request": "hello"},
            input_schema=_input_schema(),
            output_schema=_output_schema(),
        )
    )

    assert result.error is not None
    assert result.error.code == "demo_failed"
    assert result.error.retryable is True


def test_execute_module_rejects_invalid_handler_result() -> None:
    result = asyncio.run(
        execute_module(
            _InvalidEnvelopeHandler(),
            context=_context(),
            inputs={"request": "hello"},
            input_schema=_input_schema(),
            output_schema=_output_schema(),
        )
    )

    assert result.error is not None
    assert result.error.code == "sdk.invalid_handler_result"


def test_generated_package_validates_and_passes_golden_case(tmp_path: Path) -> None:
    package = create_module_package("demo_module", registry_root=tmp_path)

    validation = validate_module_package(package)
    test_report = run_module_package_tests(package)
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "app" / "contracts" / "module_contract_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert validation["ok"] is True
    assert test_report["ok"] is True
    assert test_report["passed"] == 1
    assert list(Draft202012Validator(schema).iter_errors(package.load_manifest())) == []
    assert (tmp_path / "demo_module" / "README.md").exists()


def test_create_module_package_refuses_overwrite(tmp_path: Path) -> None:
    create_module_package("demo_module", registry_root=tmp_path)

    try:
        create_module_package("demo_module", registry_root=tmp_path)
    except FileExistsError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")


def test_dependency_allowlist_rejects_platform_internal_import(tmp_path: Path) -> None:
    handler = tmp_path / "handler.py"
    handler.write_text("from app.services import module_registry\n", encoding="utf-8")

    diagnostics = validate_handler_dependencies(handler, allowed=["app"])

    assert any(item.code == "sdk.platform_internal_import" for item in diagnostics)


def test_dependency_allowlist_rejects_relative_import(tmp_path: Path) -> None:
    handler = tmp_path / "handler.py"
    handler.write_text("from .helpers import normalize\n", encoding="utf-8")

    diagnostics = validate_handler_dependencies(handler, allowed=[])

    assert any(item.code == "sdk.relative_import_not_allowed" for item in diagnostics)


def test_sandbox_module_package_runs_in_isolated_subprocess(tmp_path: Path) -> None:
    package = create_module_package("sandbox_demo", registry_root=tmp_path)

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is True
    assert report["status"] == "succeeded"
    assert report["result"]["output"] == {"result": "sandbox"}
    assert report["evidence"]["limits"]["isolated_python"] is True
    assert report["evidence"]["limits"]["sanitized_environment"] is True
    assert report["evidence"]["limits"]["package_copy"] is True
    assert report["evidence"]["limits"]["network_enforced"] is False
    assert report["evidence"]["limits"]["filesystem_enforced"] is False
    assert report["evidence"]["exit_code"] == 0


def test_sandbox_module_package_sanitizes_environment_and_captures_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package = create_module_package("sandbox_env", registry_root=tmp_path)
    assert package.handler_path is not None
    package.handler_path.write_text(
        """
from __future__ import annotations

import os


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        print("handler-log")
        return {"result": str(os.getenv("SDK_TEST_SECRET"))}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SDK_TEST_SECRET", "must-not-leak")

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is True
    assert report["result"]["output"] == {"result": "None"}
    assert report["evidence"]["handler_stdout"].splitlines() == ["handler-log"]


def test_sandbox_module_package_enforces_wall_timeout(tmp_path: Path) -> None:
    package = create_module_package("sandbox_timeout", registry_root=tmp_path)
    assert package.handler_path is not None
    package.handler_path.write_text(
        """
from __future__ import annotations

import time


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        time.sleep(2)
        return {"result": "late"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"}, timeout_seconds=0.2)

    assert report["ok"] is False
    assert report["evidence"]["timed_out"] is True
    assert any(item["code"] == "sandbox.timeout" for item in report["diagnostics"])


def test_sandbox_module_package_limits_captured_output(tmp_path: Path) -> None:
    package = create_module_package("sandbox_output", registry_root=tmp_path)
    assert package.handler_path is not None
    package.handler_path.write_text(
        """
from __future__ import annotations


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        print("x" * 40000)
        return {"result": "ok"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is True
    assert report["evidence"]["handler_stdout_truncated"] is True
    assert len(report["evidence"]["handler_stdout"]) == 32768


def test_sandbox_module_package_rejects_non_sdk_pipeline() -> None:
    package = resolve_module_package("general_assistant")

    report = sandbox_module_package(package, inputs={"user_request": "hello"})

    assert report["ok"] is False
    assert any(item["code"] == "sandbox.unsupported_pipeline" for item in report["diagnostics"])


def test_sandbox_module_package_returns_manifest_validation_failure(tmp_path: Path) -> None:
    package = create_module_package("sandbox_invalid", registry_root=tmp_path)
    package.manifest_path.write_text("not: [valid", encoding="utf-8")

    report = sandbox_module_package(package, inputs={"request": "hello"})

    assert report["ok"] is False
    assert report["status"] == "failed"
    assert any(item["code"] == "sdk.manifest_unreadable" for item in report["diagnostics"])


def test_sandbox_timeout_cannot_exceed_manifest_limit(tmp_path: Path) -> None:
    package = create_module_package("sandbox_cap", registry_root=tmp_path)
    manifest = package.load_manifest()
    manifest["execution"]["timeout_seconds"] = 1
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    report = sandbox_module_package(package, inputs={"request": "hello"}, timeout_seconds=10)

    assert report["ok"] is True
    assert report["evidence"]["limits"]["wall_timeout_seconds"] == 1


def test_module_package_fingerprint_changes_with_package_content(tmp_path: Path) -> None:
    package = create_module_package("evidence_fingerprint", registry_root=tmp_path)
    original = fingerprint_module_package(package)
    (package.root / "__pycache__").mkdir()
    (package.root / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")

    assert fingerprint_module_package(package) == original

    assert package.handler_path is not None
    package.handler_path.write_text(package.handler_path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    assert fingerprint_module_package(package) != original


def test_module_package_fingerprint_ignores_lifecycle_transition(tmp_path: Path) -> None:
    package = create_module_package("evidence_lifecycle", registry_root=tmp_path)
    original = fingerprint_module_package(package)
    manifest = package.load_manifest()
    manifest["lifecycle"] = "sandboxed"
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    assert fingerprint_module_package(package) == original


def test_module_readiness_rejects_manual_lifecycle_promotion(tmp_path: Path) -> None:
    package = create_module_package("evidence_manual_promotion", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    qualify_module_package(package, evidence_root=evidence_root)
    manifest = package.load_manifest()
    manifest["lifecycle"] = "approved"
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    report = assess_module_readiness(package, evidence_root=evidence_root)

    assert report["ok"] is False
    assert report["lifecycle_verified"] is False
    assert report["evidence_backed_lifecycle"] == "draft"
    assert any(item["code"] == "lifecycle.unverified_state" for item in report["diagnostics"])


def test_module_qualification_records_matching_evidence(tmp_path: Path) -> None:
    package = create_module_package("evidence_ready", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"

    report = qualify_module_package(package, evidence_root=evidence_root)

    assert report["ok"] is True
    assert report["approval_ready"] is True
    assert report["recommended_lifecycle"] == "validated"
    assert report["evidence"]["matching_count"] == 3
    assert {item["kind"] for item in report["qualification_records"]} == {"validation", "test", "sandbox"}
    assert report["publication"]["ready"] is False
    assert any(item["code"] == "lifecycle.approval_required" for item in report["publication"]["blockers"])
    assert any(item["code"] == "sandbox.network_isolation_missing" for item in report["publication"]["blockers"])


def test_module_qualification_records_invalid_manifest_evidence(tmp_path: Path) -> None:
    package = create_module_package("evidence_invalid", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    package.manifest_path.write_text("not: [valid", encoding="utf-8")

    report = qualify_module_package(package, evidence_root=evidence_root)

    assert report["ok"] is False
    assert report["evidence"]["matching_count"] == 3
    assert any(item["code"] == "evidence.validation_failed" for item in report["diagnostics"])


def test_module_readiness_rejects_stale_evidence_after_package_change(tmp_path: Path) -> None:
    package = create_module_package("evidence_stale", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    qualify_module_package(package, evidence_root=evidence_root)
    assert package.handler_path is not None
    package.handler_path.write_text(package.handler_path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    report = assess_module_readiness(package, evidence_root=evidence_root)

    assert report["ok"] is False
    assert report["evidence"]["matching_count"] == 0
    assert report["evidence"]["stale_count"] == 3
    assert any(item["code"] == "evidence.validation_missing" for item in report["diagnostics"])
    assert report["warnings"][0]["code"] == "evidence.stale_records"


def test_module_readiness_rejects_tampered_evidence(tmp_path: Path) -> None:
    package = create_module_package("evidence_tampered", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    validation = validate_module_package(package)
    record = record_module_evidence(package, kind="validation", report=validation, evidence_root=evidence_root)
    path = Path(record["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["report"]["ok"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = assess_module_readiness(package, evidence_root=evidence_root)

    assert report["ok"] is False
    assert report["evidence"]["invalid_count"] == 1
    assert any(item["code"] == "evidence.integrity_invalid" for item in report["diagnostics"])


def test_module_readiness_rejects_tampered_evidence_envelope(tmp_path: Path) -> None:
    package = create_module_package("evidence_envelope", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    validation = validate_module_package(package)
    record = record_module_evidence(package, kind="validation", report=validation, evidence_root=evidence_root)
    path = Path(record["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["module"]["fingerprint"] = "sha256:forged"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = assess_module_readiness(package, evidence_root=evidence_root)

    assert report["ok"] is False
    assert report["evidence"]["invalid_count"] == 1
    assert any("envelope integrity hash mismatch" in item["message"] for item in report["diagnostics"])


def test_module_lifecycle_requires_ordered_evidence_backed_transitions(tmp_path: Path) -> None:
    package = create_module_package("evidence_transition", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    qualify_module_package(package, evidence_root=evidence_root)

    for target in ("validated", "tested", "sandboxed", "approved"):
        report = transition_module_lifecycle(
            package,
            target=target,
            actor="portfolio-reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
        )
        assert report["ok"] is True
        assert report["lifecycle"] == target

    status = assess_module_readiness(package, evidence_root=evidence_root)
    assert status["lifecycle"] == "approved"
    assert status["lifecycle_verified"] is True
    assert status["evidence"]["transition_count"] == 4
    assert status["evidence"]["verified_transition_count"] == 4
    assert status["publication"]["ready"] is False
    assert not any(item["code"] == "lifecycle.approval_required" for item in status["publication"]["blockers"])


def test_module_lifecycle_rejects_skipped_stage_and_direct_publish(tmp_path: Path) -> None:
    package = create_module_package("evidence_guard", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    qualify_module_package(package, evidence_root=evidence_root)

    skipped = transition_module_lifecycle(
        package,
        target="sandboxed",
        actor="reviewer",
        reason="try to skip",
        evidence_root=evidence_root,
    )
    published = transition_module_lifecycle(
        package,
        target="published",
        actor="reviewer",
        reason="try to publish",
        evidence_root=evidence_root,
    )

    assert skipped["ok"] is False
    assert any(item["code"] == "lifecycle.invalid_transition" for item in skipped["diagnostics"])
    assert published["ok"] is False
    assert any(item["code"] == "lifecycle.publish_command_required" for item in published["diagnostics"])
    assert package.load_manifest()["lifecycle"] == "draft"


def test_module_lifecycle_can_reset_changed_approved_module_to_draft(tmp_path: Path) -> None:
    package = create_module_package("evidence_reset", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    qualify_module_package(package, evidence_root=evidence_root)
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
        )
    assert package.handler_path is not None
    package.handler_path.write_text(package.handler_path.read_text(encoding="utf-8") + "\n# revision\n", encoding="utf-8")

    stale = assess_module_readiness(package, evidence_root=evidence_root)
    reset = transition_module_lifecycle(
        package,
        target="draft",
        actor="reviewer",
        reason="start a new review after code revision",
        evidence_root=evidence_root,
    )

    assert stale["lifecycle_verified"] is False
    assert reset["ok"] is True
    assert reset["lifecycle"] == "draft"
    assert reset["readiness"]["lifecycle_verified"] is True
    assert reset["readiness"]["approval_ready"] is False
