from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from app.module_sdk import (
    ModuleExecutionContext,
    ModuleSDKError,
    create_module_package,
    execute_module,
    run_module_package_tests,
    sandbox_module_package,
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
