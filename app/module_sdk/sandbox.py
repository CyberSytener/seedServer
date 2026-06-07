from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from app.module_sdk.package import ModulePackage, resolve_module_package, validate_module_package


SANDBOX_PROTOCOL_VERSION = "1.0"
MAX_CAPTURE_CHARS = 32768
_ENV_ALLOWLIST = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")


def _diagnostic(code: str, path: str, message: str) -> Dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _sandbox_environment() -> Dict[str, str]:
    environment = {
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "SEED_MODULE_SANDBOX": "1",
    }
    for name in _ENV_ALLOWLIST:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _truncate(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_CAPTURE_CHARS:
        return value, False
    return value[:MAX_CAPTURE_CHARS], True


def _default_input(manifest: Dict[str, Any]) -> Dict[str, Any]:
    tests = manifest.get("tests") if isinstance(manifest.get("tests"), dict) else {}
    golden = tests.get("golden") if isinstance(tests.get("golden"), list) else []
    if golden and isinstance(golden[0], dict) and isinstance(golden[0].get("input"), dict):
        return dict(golden[0]["input"])
    return {}


def _failure_report(
    *,
    module_id: str,
    sandbox_id: str,
    diagnostics: list[Dict[str, Any]],
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "module_id": module_id,
        "sandbox_id": sandbox_id,
        "result": None,
        "diagnostics": diagnostics,
        "evidence": evidence or {},
    }


def _subprocess_sandbox_module_package(
    package: ModulePackage,
    *,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    validation = validate_module_package(package)
    module_id = str(validation.get("module_id") or "")
    sandbox_id = f"sdk-sandbox-{uuid.uuid4().hex}"
    if not validation["ok"]:
        return _failure_report(
            module_id=module_id,
            sandbox_id=sandbox_id,
            diagnostics=validation["diagnostics"],
        )
    manifest = package.load_manifest()
    if str(manifest.get("pipeline") or "") != "sdk_module":
        return _failure_report(
            module_id=module_id,
            sandbox_id=sandbox_id,
            diagnostics=[
                _diagnostic(
                    "sandbox.unsupported_pipeline",
                    "$.pipeline",
                    "module sandbox currently requires pipeline 'sdk_module'",
                )
            ],
        )

    execution = manifest.get("execution") if isinstance(manifest.get("execution"), dict) else {}
    resources = manifest.get("resources") if isinstance(manifest.get("resources"), dict) else {}
    declared_timeout = float(execution.get("timeout_seconds") or 30)
    requested_timeout = float(timeout_seconds) if timeout_seconds is not None else declared_timeout
    effective_timeout = min(declared_timeout, requested_timeout)
    if effective_timeout <= 0:
        raise ValueError("sandbox timeout must be greater than zero")
    memory_mb = int(resources.get("memory_mb") or 128)
    sandbox_input = dict(inputs) if inputs is not None else _default_input(manifest)

    with tempfile.TemporaryDirectory(prefix="seed-module-sandbox-") as temp:
        workspace = Path(temp)
        package_copy = workspace / "module"
        shutil.copytree(
            package.root,
            package_copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        copied_package = resolve_module_package(package_copy)
        request_path = workspace / "request.json"
        response_path = workspace / "response.json"
        request_path.write_text(
            json.dumps(
                {
                    "protocol_version": SANDBOX_PROTOCOL_VERSION,
                    "sandbox_id": sandbox_id,
                    "manifest_path": str(copied_package.manifest_path),
                    "handler_path": str(copied_package.handler_path or ""),
                    "inputs": sandbox_input,
                    "timeout_seconds": effective_timeout,
                    "memory_mb": memory_mb,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-I",
            "-m",
            "app.module_sdk.sandbox_worker",
            str(request_path),
            str(response_path),
        ]
        started = time.monotonic()
        try:
            process = subprocess.run(  # noqa: S603
                command,
                cwd=workspace,
                env=_sandbox_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                check=False,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            process_stdout, process_stdout_truncated = _truncate(str(exc.stdout or ""))
            process_stderr, process_stderr_truncated = _truncate(str(exc.stderr or ""))
            evidence = {
                "protocol_version": SANDBOX_PROTOCOL_VERSION,
                "runtime": {"adapter": "subprocess"},
                "duration_ms": duration_ms,
                "exit_code": None,
                "timed_out": True,
                "stdout": process_stdout,
                "stderr": process_stderr,
                "stdout_truncated": process_stdout_truncated,
                "stderr_truncated": process_stderr_truncated,
                "limits": {
                    "wall_timeout_seconds": effective_timeout,
                    "memory_mb": memory_mb,
                    "isolated_python": True,
                    "sanitized_environment": True,
                    "package_copy": True,
                    "environment_allowlist": list(_ENV_ALLOWLIST),
                    "network_enforced": False,
                    "filesystem_enforced": False,
                },
            }
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[
                    _diagnostic(
                        "sandbox.timeout",
                        "$.execution.timeout_seconds",
                        f"module exceeded sandbox timeout of {effective_timeout:g} seconds",
                    )
                ],
                evidence=evidence,
            )

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        process_stdout, process_stdout_truncated = _truncate(process.stdout)
        process_stderr, process_stderr_truncated = _truncate(process.stderr)
        base_evidence = {
            "protocol_version": SANDBOX_PROTOCOL_VERSION,
            "runtime": {"adapter": "subprocess"},
            "duration_ms": duration_ms,
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": process_stdout,
            "stderr": process_stderr,
            "stdout_truncated": process_stdout_truncated,
            "stderr_truncated": process_stderr_truncated,
            "limits": {
                "wall_timeout_seconds": effective_timeout,
                "memory_mb": memory_mb,
                "isolated_python": True,
                "sanitized_environment": True,
                "package_copy": True,
                "environment_allowlist": list(_ENV_ALLOWLIST),
                "network_enforced": False,
                "filesystem_enforced": False,
            },
        }
        if not response_path.exists():
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[
                    _diagnostic(
                        "sandbox.worker_failed",
                        "$",
                        f"sandbox worker exited without a response (exit code {process.returncode})",
                    )
                ],
                evidence=base_evidence,
            )
        try:
            worker_report = json.loads(response_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[_diagnostic("sandbox.response_invalid", "$", str(exc))],
                evidence=base_evidence,
            )

        worker_evidence = worker_report.get("evidence") if isinstance(worker_report.get("evidence"), dict) else {}
        return {
            "ok": bool(worker_report.get("ok")) and process.returncode == 0,
            "status": str(worker_report.get("status") or "failed"),
            "module_id": module_id,
            "sandbox_id": sandbox_id,
            "result": worker_report.get("result"),
            "diagnostics": worker_report.get("diagnostics") or [],
            "evidence": {
                **base_evidence,
                **worker_evidence,
                "limits": {
                    **base_evidence["limits"],
                    **(
                        worker_evidence.get("limits")
                        if isinstance(worker_evidence.get("limits"), dict)
                        else {}
                    ),
                },
            },
        }


def sandbox_module_package(
    package: ModulePackage,
    *,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[float] = None,
    runtime: str = "subprocess",
    image: Optional[str] = None,
    docker_executable: str = "docker",
) -> Dict[str, Any]:
    normalized_runtime = runtime.strip().lower()
    if normalized_runtime == "subprocess":
        return _subprocess_sandbox_module_package(
            package,
            inputs=inputs,
            timeout_seconds=timeout_seconds,
        )
    if normalized_runtime == "docker":
        from app.module_sdk.docker_sandbox import docker_sandbox_module_package

        return docker_sandbox_module_package(
            package,
            inputs=inputs,
            timeout_seconds=timeout_seconds,
            image=image,
            docker_executable=docker_executable,
        )
    raise ValueError("sandbox runtime must be 'subprocess' or 'docker'")
