from __future__ import annotations

import asyncio
import json
import subprocess
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
    load_module_evidence,
    load_module_version_history,
    publish_module_package,
    qualify_module_package,
    record_module_evidence,
    run_module_package_tests,
    sandbox_module_package,
    transition_module_lifecycle,
    validate_module_package,
)
from app.module_sdk.package import resolve_module_package
from app.module_sdk.package import validate_handler_dependencies


def _hardened_limits(report: dict) -> None:
    report["evidence"]["runtime"] = {"adapter": "docker", "image": "fixture", "engine_version": "fixture"}
    report["evidence"]["limits"].update(
        {
            "network_enforced": True,
            "filesystem_enforced": True,
            "read_only_rootfs": True,
            "capabilities_dropped": True,
            "no_new_privileges": True,
            "non_root_user": True,
            "memory_enforced": True,
            "process_limit_enforced": True,
        }
    )
    report["evidence"]["capability_report"] = {
        "enforcement": "python_audit_hook",
        "policy": {},
        "operations": [],
        "operation_count": 0,
        "violation_count": 0,
        "truncated": False,
    }


def _observed_operation(report: dict, operation: str, outcome: str) -> dict:
    return next(
        item
        for item in report["evidence"]["capability_report"]["operations"]
        if item["operation"] == operation and item["outcome"] == outcome
    )


def _fake_docker_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
    if len(command) > 1 and command[1] == "version":
        return subprocess.CompletedProcess(command, 0, stdout="29.1.3\n", stderr="")
    if len(command) > 1 and command[1] == "rm":
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    io_mount = next(value for value in command if isinstance(value, str) and "target=/io" in value)
    io_root = Path(io_mount.split("source=", 1)[1].split(",target=/io", 1)[0])
    (io_root / "response.json").write_text(
        json.dumps(
            {
                "ok": True,
                "status": "succeeded",
                "result": {
                    "status": "succeeded",
                    "output": {"result": "docker"},
                    "error": None,
                    "diagnostics": [],
                },
                "diagnostics": [],
                "evidence": {
                    "worker_duration_ms": 1.0,
                    "limits": {"cpu_enforced": True, "memory_enforced": True},
                    "capability_report": {
                        "enforcement": "python_audit_hook",
                        "policy": {},
                        "operations": [],
                        "operation_count": 0,
                        "violation_count": 0,
                        "truncated": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _approve_hardened_package(package, *, evidence_root: Path, signing_key: str, monkeypatch) -> None:
    monkeypatch.setattr("app.module_sdk.docker_sandbox.shutil.which", lambda _name: "docker")
    monkeypatch.setattr("app.module_sdk.docker_sandbox.subprocess.run", _fake_docker_run)
    qualify_module_package(
        package,
        evidence_root=evidence_root,
        sandbox_runtime="docker",
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )


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


def test_dependency_allowlist_rejects_internal_sdk_submodule_import(tmp_path: Path) -> None:
    handler = tmp_path / "handler.py"
    handler.write_text("from app.module_sdk.sandbox_worker import _run\n", encoding="utf-8")

    diagnostics = validate_handler_dependencies(handler, allowed=[])

    assert any(item.code == "sdk.internal_sdk_import" for item in diagnostics)


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
    assert report["evidence"]["runtime"]["adapter"] == "subprocess"


def test_docker_sandbox_enforces_hardened_container_profile(tmp_path: Path, monkeypatch) -> None:
    package = create_module_package("sandbox_docker", registry_root=tmp_path)
    commands = []
    authority_key = "must-not-enter-container-" + "a" * 32

    def capture_run(command: list[str], **kwargs):
        commands.append(command)
        return _fake_docker_run(command, **kwargs)

    monkeypatch.setattr("app.module_sdk.docker_sandbox.shutil.which", lambda _name: "docker")
    monkeypatch.setattr("app.module_sdk.docker_sandbox.subprocess.run", capture_run)
    monkeypatch.setenv("SEED_MODULE_EVIDENCE_SIGNING_KEY", authority_key)

    report = sandbox_module_package(package, inputs={"request": "docker"}, runtime="docker")

    assert report["ok"] is True
    assert report["result"]["output"] == {"result": "docker"}
    assert report["evidence"]["runtime"]["adapter"] == "docker"
    assert report["evidence"]["limits"]["network_enforced"] is True
    assert report["evidence"]["limits"]["filesystem_enforced"] is True
    assert report["evidence"]["secret_report"]["policy_satisfied"] is True
    assert report["evidence"]["dependency_report"]["policy_satisfied"] is True
    run_command = next(command for command in commands if len(command) > 1 and command[1] == "run")
    assert ["--network", "none"] == run_command[run_command.index("--network") : run_command.index("--network") + 2]
    assert "--read-only" in run_command
    assert ["--cap-drop", "ALL"] == run_command[run_command.index("--cap-drop") : run_command.index("--cap-drop") + 2]
    assert ["--user", "65534:65534"] == run_command[run_command.index("--user") : run_command.index("--user") + 2]
    assert all(authority_key not in item for item in run_command)


def test_docker_sandbox_returns_structured_error_when_engine_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    package = create_module_package("sandbox_no_docker", registry_root=tmp_path)
    monkeypatch.setattr("app.module_sdk.docker_sandbox.shutil.which", lambda _name: None)

    report = sandbox_module_package(package, inputs={"request": "docker"}, runtime="docker")

    assert report["ok"] is False
    assert report["evidence"]["runtime"]["adapter"] == "docker"
    assert report["evidence"]["limits"]["network_enforced"] is False
    assert report["evidence"]["policy"]["enforced"] is None
    assert report["evidence"]["secret_report"]["policy_satisfied"] is True
    assert report["evidence"]["dependency_report"]["policy_satisfied"] is True
    assert any(item["code"] == "sandbox.docker_unavailable" for item in report["diagnostics"])


def test_docker_qualification_records_signed_hardened_evidence(tmp_path: Path, monkeypatch) -> None:
    package = create_module_package("docker_qualified", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "docker-qualification-" + "a" * 32
    monkeypatch.setattr("app.module_sdk.docker_sandbox.shutil.which", lambda _name: "docker")
    monkeypatch.setattr("app.module_sdk.docker_sandbox.subprocess.run", _fake_docker_run)

    report = qualify_module_package(
        package,
        evidence_root=evidence_root,
        sandbox_runtime="docker",
        signing_key=signing_key,
    )

    assert report["ok"] is True
    assert report["checks"]["sandbox"]["signature_status"] == "valid"
    blocker_codes = {item["code"] for item in report["publication"]["blockers"]}
    assert blocker_codes == {"lifecycle.approval_required"}


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
    assert report["evidence"]["secret_report"]["policy_satisfied"] is True
    assert report["evidence"]["secret_report"]["forwarded_refs"] == []
    assert report["evidence"]["dependency_report"]["policy_satisfied"] is True


def test_sandbox_reports_unavailable_secret_and_dependency_brokers(tmp_path: Path) -> None:
    package = create_module_package("sandbox_policy_requirements", registry_root=tmp_path)
    manifest = package.load_manifest()
    manifest["security"]["secret_refs"] = ["provider_api_key"]
    manifest["dependencies"]["python"] = ["httpx"]
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is True
    assert report["evidence"]["secret_report"] == {
        "enforcement": "no_secret_forwarding",
        "declared_refs": ["provider_api_key"],
        "forwarded_refs": [],
        "broker": "unavailable",
        "policy_satisfied": False,
    }
    assert report["evidence"]["dependency_report"] == {
        "enforcement": "static_import_allowlist",
        "declared_python": ["httpx"],
        "installed_bundle": [],
        "installer": "disabled",
        "policy_satisfied": False,
    }


def test_sandbox_blocks_undeclared_filesystem_write(tmp_path: Path) -> None:
    package = create_module_package("sandbox_fs_block", registry_root=tmp_path)
    assert package.handler_path is not None
    package.handler_path.write_text(
        """
class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        with open("blocked.txt", "w", encoding="utf-8") as handle:
            handle.write("blocked")
        return {"result": "unexpected"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is False
    assert report["result"]["error"]["code"] == "sandbox.capability_violation"
    assert report["evidence"]["capability_report"]["violation_count"] == 1
    assert _observed_operation(report, "filesystem.write", "blocked")
    assert any(item["code"] == "sandbox.capability_violation" for item in report["diagnostics"])


def test_sandbox_allows_declared_read_only_filesystem_access(tmp_path: Path) -> None:
    package = create_module_package("sandbox_fs_read", registry_root=tmp_path)
    assert package.handler_path is not None
    (package.root / "fixture.txt").write_text("allowed", encoding="utf-8")
    manifest = package.load_manifest()
    manifest["effects"]["filesystem_access"] = "read_only"
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    package.handler_path.write_text(
        """
from pathlib import Path


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        return {"result": Path(__file__).with_name("fixture.txt").read_text(encoding="utf-8")}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is True
    assert report["result"]["output"] == {"result": "allowed"}
    capability = report["evidence"]["capability_report"]
    assert capability["violation_count"] == 0
    assert any(item["operation"] == "filesystem.read" and item["outcome"] == "allowed" for item in capability["operations"])


def test_sandbox_blocks_undeclared_network_access(tmp_path: Path) -> None:
    package = create_module_package("sandbox_network_block", registry_root=tmp_path)
    assert package.handler_path is not None
    package.handler_path.write_text(
        """
import socket


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        with socket.socket() as client:
            client.connect(("127.0.0.1", 9))
        return {"result": "unexpected"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is False
    operation = _observed_operation(report, "network", "blocked")
    assert operation["operation"] == "network"
    assert operation["outcome"] == "blocked"


def test_sandbox_blocks_import_time_network_access(tmp_path: Path) -> None:
    package = create_module_package("sandbox_import_network_block", registry_root=tmp_path)
    assert package.handler_path is not None
    manifest = package.load_manifest()
    manifest["effects"]["network_access"] = "allowlist"
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    package.handler_path.write_text(
        """
import socket

with socket.socket() as client:
    client.connect(("127.0.0.1", 9))


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        return {"result": "unexpected"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is False
    assert report["result"]["error"]["code"] == "sandbox.capability_violation"
    operation = _observed_operation(report, "network", "blocked")
    assert operation["operation"] == "network"
    assert operation["outcome"] == "blocked"


def test_sandbox_blocks_import_time_arbitrary_file_read(tmp_path: Path) -> None:
    package = create_module_package("sandbox_import_fs_block", registry_root=tmp_path)
    assert package.handler_path is not None
    (package.root / "fixture.txt").write_text("blocked", encoding="utf-8")
    manifest = package.load_manifest()
    manifest["effects"]["filesystem_access"] = "read_only"
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    package.handler_path.write_text(
        """
from pathlib import Path

VALUE = Path(__file__).with_name("fixture.txt").read_text(encoding="utf-8")


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        return {"result": VALUE}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is False
    assert report["result"]["error"]["code"] == "sandbox.capability_violation"
    operation = _observed_operation(report, "filesystem.read", "blocked")
    assert operation["target"].endswith("fixture.txt")


def test_sandbox_blocks_child_process_execution(tmp_path: Path) -> None:
    package = create_module_package("sandbox_process_block", registry_root=tmp_path)
    assert package.handler_path is not None
    package.handler_path.write_text(
        """
import subprocess
import sys


class Handler:
    async def execute(self, context, inputs):
        del context, inputs
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        return {"result": "unexpected"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = sandbox_module_package(package, inputs={"request": "sandbox"})

    assert report["ok"] is False
    operation = _observed_operation(report, "process", "blocked")
    assert operation["operation"] == "process"
    assert operation["outcome"] == "blocked"


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


def test_signed_module_evidence_requires_matching_authority_key(tmp_path: Path) -> None:
    package = create_module_package("evidence_signed", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "authority-key-" + "a" * 32
    record_module_evidence(
        package,
        kind="validation",
        report=validate_module_package(package),
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    verified = load_module_evidence(package, evidence_root=evidence_root, signing_key=signing_key)
    wrong_key = load_module_evidence(
        package,
        evidence_root=evidence_root,
        signing_key="wrong-authority-" + "b" * 32,
    )

    assert verified["matching"][0]["signature_status"] == "valid"
    assert wrong_key["matching"] == []
    assert wrong_key["invalid"][0]["message"] == "evidence signature invalid"


def test_publish_gate_blocks_local_subprocess_sandbox(tmp_path: Path) -> None:
    package = create_module_package("publish_blocked", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    qualify_module_package(package, evidence_root=evidence_root)
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt local release",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert report["decision"] == "block"
    assert report["lifecycle"] == "approved"
    assert report["publish_evidence"]["signature"]["algorithm"] == "hmac-sha256"
    assert any(item["code"] == "evidence.sandbox_signature_required" for item in report["diagnostics"])
    assert any(item["code"] == "sandbox.hardened_adapter_required" for item in report["diagnostics"])
    assert any(item["code"] == "sandbox.network_isolation_missing" for item in report["diagnostics"])


def test_publish_gate_rejects_incomplete_docker_hardening_profile(tmp_path: Path) -> None:
    package = create_module_package("publish_partial_hardening", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    qualify_module_package(package, evidence_root=evidence_root)
    partial = sandbox_module_package(package, inputs={"request": "partial"})
    partial["evidence"]["runtime"] = {"adapter": "docker", "image": "fixture", "engine_version": "fixture"}
    partial["evidence"]["limits"]["network_enforced"] = True
    partial["evidence"]["limits"]["filesystem_enforced"] = True
    record_module_evidence(
        package,
        kind="sandbox",
        report=partial,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt incomplete hardening release",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert any(item["code"] == "sandbox.root_filesystem_isolation_missing" for item in report["diagnostics"])


def test_publish_gate_requires_capability_observation(tmp_path: Path) -> None:
    package = create_module_package("publish_missing_observation", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    qualify_module_package(package, evidence_root=evidence_root)
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    _hardened_limits(hardened)
    hardened["evidence"].pop("capability_report")
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt release without capability observation",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert any(item["code"] == "sandbox.capability_observation_missing" for item in report["diagnostics"])


def test_publish_gate_rejects_observed_capability_violations(tmp_path: Path) -> None:
    package = create_module_package("publish_capability_violation", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    qualify_module_package(package, evidence_root=evidence_root)
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    _hardened_limits(hardened)
    hardened["evidence"]["capability_report"]["violation_count"] = 1
    hardened["evidence"]["capability_report"]["operations"] = [
        {
            "event": "socket.connect",
            "operation": "network",
            "target": "example.invalid:443",
            "outcome": "blocked",
            "policy": "network_access=none",
        }
    ]
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt release with observed capability violation",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert any(item["code"] == "sandbox.capability_violations_detected" for item in report["diagnostics"])


def test_publish_gate_requires_secret_and_dependency_policy_evidence(tmp_path: Path) -> None:
    package = create_module_package("publish_missing_policy_reports", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    qualify_module_package(package, evidence_root=evidence_root)
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    _hardened_limits(hardened)
    hardened["evidence"].pop("secret_report")
    hardened["evidence"].pop("dependency_report")
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt release without policy reports",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    blocker_codes = {item["code"] for item in report["diagnostics"]}
    assert report["ok"] is False
    assert "sandbox.secret_policy_missing" in blocker_codes
    assert "sandbox.dependency_policy_missing" in blocker_codes


def test_publish_gate_blocks_secret_dependent_module_without_broker(tmp_path: Path) -> None:
    package = create_module_package("publish_secret_requirement", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    manifest = package.load_manifest()
    manifest["security"]["secret_refs"] = ["provider_api_key"]
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    qualify_module_package(package, evidence_root=evidence_root)
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    _hardened_limits(hardened)
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt secret-dependent release",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert any(item["code"] == "sandbox.secret_broker_required" for item in report["diagnostics"])
    assert not any(item["code"] == "sandbox.secret_policy_invalid" for item in report["diagnostics"])


def test_publish_gate_blocks_external_dependency_without_bundle(tmp_path: Path) -> None:
    package = create_module_package("publish_dependency_requirement", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    manifest = package.load_manifest()
    manifest["dependencies"]["python"] = ["httpx"]
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    qualify_module_package(package, evidence_root=evidence_root)
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    _hardened_limits(hardened)
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt dependency-backed release",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert any(item["code"] == "sandbox.dependency_bundle_required" for item in report["diagnostics"])
    assert not any(item["code"] == "sandbox.dependency_policy_invalid" for item in report["diagnostics"])


def test_publish_gate_allows_signed_hardened_sandbox_evidence(tmp_path: Path, monkeypatch) -> None:
    package = create_module_package("publish_allowed", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    monkeypatch.setattr("app.module_sdk.docker_sandbox.shutil.which", lambda _name: "docker")
    monkeypatch.setattr("app.module_sdk.docker_sandbox.subprocess.run", _fake_docker_run)
    qualify_module_package(
        package,
        evidence_root=evidence_root,
        sandbox_runtime="docker",
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="signed hardened evidence passed",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is True
    assert report["decision"] == "allow"
    assert report["lifecycle"] == "published"
    assert report["publish_evidence"]["signature"]["algorithm"] == "hmac-sha256"
    assert report["evidence_refs"]["sandbox"]["record_sha256"].startswith("sha256:")
    assert report["approval_ref"]["record_sha256"].startswith("sha256:")
    assert report["readiness"]["lifecycle_verified"] is True
    assert report["readiness"]["publication"]["ready"] is True


def test_published_version_history_survives_working_package_change(tmp_path: Path, monkeypatch) -> None:
    package = create_module_package("history_durable", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    versions_root = tmp_path / "versions"
    signing_key = "history-authority-" + "a" * 32
    _approve_hardened_package(
        package,
        evidence_root=evidence_root,
        signing_key=signing_key,
        monkeypatch=monkeypatch,
    )

    published = publish_module_package(
        package,
        actor="release-manager",
        reason="record durable release",
        evidence_root=evidence_root,
        versions_root=versions_root,
        signing_key=signing_key,
    )
    assert package.handler_path is not None
    package.handler_path.write_text(
        package.handler_path.read_text(encoding="utf-8") + "\n# next working revision\n",
        encoding="utf-8",
    )
    history = load_module_version_history(
        "history_durable",
        versions_root=versions_root,
        signing_key=signing_key,
    )

    assert published["version_snapshot"]["signature_status"] == "valid"
    assert published["version_snapshot"]["publication"]["publish_evidence"]["record_sha256"].startswith("sha256:")
    assert history["ok"] is True
    assert history["version_count"] == 1
    assert history["versions"][0]["module"]["fingerprint"] == published["fingerprint"]
    snapshot_package = resolve_module_package(Path(history["versions"][0]["package_path"]))
    assert snapshot_package.load_manifest()["lifecycle"] == "published"
    assert fingerprint_module_package(snapshot_package) == published["fingerprint"]
    assert fingerprint_module_package(package) != published["fingerprint"]


def test_publish_gate_blocks_reusing_version_for_different_package(tmp_path: Path, monkeypatch) -> None:
    evidence_root = tmp_path / "evidence"
    versions_root = tmp_path / "versions"
    signing_key = "history-authority-" + "b" * 32
    first = create_module_package("history_conflict", registry_root=tmp_path / "modules-a")
    second = create_module_package("history_conflict", registry_root=tmp_path / "modules-b")
    assert second.handler_path is not None
    second.handler_path.write_text(
        second.handler_path.read_text(encoding="utf-8") + "\n# incompatible revision\n",
        encoding="utf-8",
    )
    _approve_hardened_package(
        first,
        evidence_root=evidence_root,
        signing_key=signing_key,
        monkeypatch=monkeypatch,
    )
    first_publish = publish_module_package(
        first,
        actor="release-manager",
        reason="publish first package",
        evidence_root=evidence_root,
        versions_root=versions_root,
        signing_key=signing_key,
    )
    _approve_hardened_package(
        second,
        evidence_root=evidence_root,
        signing_key=signing_key,
        monkeypatch=monkeypatch,
    )

    conflict = publish_module_package(
        second,
        actor="release-manager",
        reason="attempt version reuse",
        evidence_root=evidence_root,
        versions_root=versions_root,
        signing_key=signing_key,
    )

    assert first_publish["ok"] is True
    assert conflict["ok"] is False
    assert conflict["lifecycle"] == "approved"
    assert any(item["code"] == "version.version_conflict" for item in conflict["diagnostics"])


def test_module_version_history_detects_snapshot_tampering(tmp_path: Path, monkeypatch) -> None:
    package = create_module_package("history_tampered", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    versions_root = tmp_path / "versions"
    signing_key = "history-authority-" + "c" * 32
    _approve_hardened_package(
        package,
        evidence_root=evidence_root,
        signing_key=signing_key,
        monkeypatch=monkeypatch,
    )
    published = publish_module_package(
        package,
        actor="release-manager",
        reason="publish before tamper test",
        evidence_root=evidence_root,
        versions_root=versions_root,
        signing_key=signing_key,
    )
    snapshot_handler = Path(published["version_snapshot"]["package_path"]) / "handler.py"
    snapshot_handler.write_text(snapshot_handler.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    history = load_module_version_history(
        "history_tampered",
        versions_root=versions_root,
        signing_key=signing_key,
    )

    assert history["ok"] is False
    assert history["version_count"] == 0
    assert "snapshot file hash mismatch" in history["invalid"][0]["message"]


def test_publish_gate_rejects_evidence_added_after_approval(tmp_path: Path) -> None:
    package = create_module_package("publish_stale_approval", registry_root=tmp_path / "modules")
    evidence_root = tmp_path / "evidence"
    signing_key = "publish-authority-" + "a" * 32
    qualify_module_package(package, evidence_root=evidence_root)
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
        )
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    _hardened_limits(hardened)
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="attempt release with stale approval",
        evidence_root=evidence_root,
        signing_key=signing_key,
    )

    assert report["ok"] is False
    assert any(item["code"] == "publish.approval_evidence_stale" for item in report["diagnostics"])


def test_publish_gate_rejects_short_signing_key_without_exception(tmp_path: Path) -> None:
    package = create_module_package("publish_short_key", registry_root=tmp_path / "modules")

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="invalid key check",
        evidence_root=tmp_path / "evidence",
        signing_key="too-short",
    )

    assert report["ok"] is False
    assert report["publish_evidence"]["signature"] is None
    assert any(item["code"] == "publish.signing_key_invalid" for item in report["diagnostics"])


def test_publish_gate_blocks_invalid_policy_shapes_without_exception(tmp_path: Path) -> None:
    package = create_module_package("publish_invalid_policy_shapes", registry_root=tmp_path / "modules")
    manifest = package.load_manifest()
    manifest["security"] = "invalid"
    manifest["dependencies"] = "invalid"
    package.manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="invalid policy shape check",
        evidence_root=tmp_path / "evidence",
        signing_key="publish-authority-" + "a" * 32,
    )

    assert report["ok"] is False
    assert any(item["code"] == "contract.invalid_value" for item in report["diagnostics"])


def test_publish_gate_records_unsigned_block_when_authority_key_is_missing(tmp_path: Path) -> None:
    package = create_module_package("publish_missing_key", registry_root=tmp_path / "modules")

    report = publish_module_package(
        package,
        actor="release-manager",
        reason="missing key check",
        evidence_root=tmp_path / "evidence",
    )

    assert report["ok"] is False
    assert report["publish_evidence"]["signature"] is None
    assert any(item["code"] == "publish.signing_key_required" for item in report["diagnostics"])
