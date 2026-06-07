from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from app.module_sdk.package import ModulePackage, validate_module_package
from app.module_sdk.sandbox import (
    SANDBOX_PROTOCOL_VERSION,
    _default_input,
    _diagnostic,
    _failure_report,
    _truncate,
)


DEFAULT_DOCKER_SANDBOX_IMAGE = "seed-module-sandbox:local"
DOCKER_STARTUP_GRACE_SECONDS = 10
DOCKER_PIDS_LIMIT = 32
DOCKER_CPU_LIMIT = 1.0
DOCKER_TMPFS_SIZE_MB = 16
_CONTAINER_ENVIRONMENT = (
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONHASHSEED",
    "PYTHONIOENCODING",
    "SEED_MODULE_SANDBOX",
)


def _runtime_evidence(*, image: str, engine_version: Optional[str]) -> Dict[str, Any]:
    return {
        "adapter": "docker",
        "image": image,
        "engine_version": engine_version,
    }


def _limits_evidence(*, timeout_seconds: float, memory_mb: int, enforced: bool) -> Dict[str, Any]:
    return {
        "wall_timeout_seconds": timeout_seconds,
        "memory_mb": memory_mb,
        "cpu_limit": DOCKER_CPU_LIMIT,
        "pids_limit": DOCKER_PIDS_LIMIT,
        "isolated_python": True,
        "sanitized_environment": True,
        "package_copy": True,
        "explicit_environment": list(_CONTAINER_ENVIRONMENT),
        "host_environment_forwarded": [],
        "network_enforced": enforced,
        "filesystem_enforced": enforced,
        "read_only_rootfs": enforced,
        "package_read_only": enforced,
        "io_workspace_only": enforced,
        "capabilities_dropped": enforced,
        "no_new_privileges": enforced,
        "non_root_user": enforced,
        "memory_enforced": enforced,
        "process_limit_enforced": enforced,
        "cpu_enforced": enforced,
    }


def _engine_version(docker_executable: str) -> tuple[Optional[str], Optional[str]]:
    if shutil.which(docker_executable) is None:
        return None, f"Docker executable not found: {docker_executable}"
    try:
        process = subprocess.run(  # noqa: S603
            [docker_executable, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DOCKER_STARTUP_GRACE_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    version = process.stdout.strip()
    if process.returncode != 0 or not version:
        return None, process.stderr.strip() or "Docker engine is unavailable"
    return version, None


def _mount(source: Path, target: str, *, read_only: bool = False) -> str:
    value = f"type=bind,source={source.resolve()},target={target}"
    return f"{value},readonly" if read_only else value


def _container_command(
    *,
    docker_executable: str,
    container_name: str,
    package_root: Path,
    io_root: Path,
    image: str,
    memory_mb: int,
) -> list[str]:
    return [
        docker_executable,
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        container_name,
        "--network",
        "none",
        "--ipc",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        "65534:65534",
        "--pids-limit",
        str(DOCKER_PIDS_LIMIT),
        "--memory",
        f"{memory_mb}m",
        "--memory-swap",
        f"{memory_mb}m",
        "--cpus",
        str(DOCKER_CPU_LIMIT),
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,size={DOCKER_TMPFS_SIZE_MB}m",
        "--mount",
        _mount(package_root, "/module", read_only=True),
        "--mount",
        _mount(io_root, "/io"),
        "--workdir",
        "/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONHASHSEED=0",
        "--env",
        "PYTHONIOENCODING=utf-8",
        "--env",
        "SEED_MODULE_SANDBOX=1",
        "--entrypoint",
        "python",
        image,
        "-m",
        "app.module_sdk.sandbox_worker",
        "/io/request.json",
        "/io/response.json",
    ]


def _remove_container(docker_executable: str, container_name: str) -> None:
    try:
        subprocess.run(  # noqa: S603
            [docker_executable, "rm", "-f", container_name],
            capture_output=True,
            timeout=DOCKER_STARTUP_GRACE_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def docker_sandbox_module_package(
    package: ModulePackage,
    *,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[float] = None,
    image: Optional[str] = None,
    docker_executable: str = "docker",
) -> Dict[str, Any]:
    validation = validate_module_package(package)
    module_id = str(validation.get("module_id") or "")
    sandbox_id = f"sdk-docker-{uuid.uuid4().hex}"
    selected_image = (image or os.getenv("SEED_MODULE_SANDBOX_IMAGE") or DEFAULT_DOCKER_SANDBOX_IMAGE).strip()
    if not selected_image:
        raise ValueError("Docker sandbox image must not be empty")
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
    engine_version, engine_error = _engine_version(docker_executable)
    base_evidence = {
        "protocol_version": SANDBOX_PROTOCOL_VERSION,
        "runtime": _runtime_evidence(image=selected_image, engine_version=engine_version),
        "limits": _limits_evidence(timeout_seconds=effective_timeout, memory_mb=memory_mb, enforced=False),
        "policy": {
            "declared": {
                "network_access": str((manifest.get("effects") or {}).get("network_access") or "none"),
                "filesystem_access": str((manifest.get("effects") or {}).get("filesystem_access") or "none"),
                "secret_refs": list((manifest.get("security") or {}).get("secret_refs") or []),
            },
            "requested": {
                "network_access": "none",
                "filesystem_access": "read_only_package_and_io_workspace",
                "secret_refs": [],
            },
            "enforced": None,
        },
    }
    if engine_error:
        return _failure_report(
            module_id=module_id,
            sandbox_id=sandbox_id,
            diagnostics=[_diagnostic("sandbox.docker_unavailable", "$.runtime", engine_error)],
            evidence=base_evidence,
        )

    with tempfile.TemporaryDirectory(prefix="seed-module-docker-") as temp:
        workspace = Path(temp)
        package_copy = workspace / "module"
        io_root = workspace / "io"
        shutil.copytree(
            package.root,
            package_copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        io_root.mkdir()
        try:
            io_root.chmod(0o777)
        except OSError:
            pass
        manifest_path = f"/module/{package.manifest_path.relative_to(package.root).as_posix()}"
        handler_path = (
            f"/module/{package.handler_path.relative_to(package.root).as_posix()}"
            if package.handler_path is not None
            else ""
        )
        request_path = io_root / "request.json"
        response_path = io_root / "response.json"
        request_path.write_text(
            json.dumps(
                {
                    "protocol_version": SANDBOX_PROTOCOL_VERSION,
                    "sandbox_id": sandbox_id,
                    "manifest_path": manifest_path,
                    "handler_path": handler_path,
                    "inputs": sandbox_input,
                    "timeout_seconds": effective_timeout,
                    "memory_mb": memory_mb,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        container_name = sandbox_id
        command = _container_command(
            docker_executable=docker_executable,
            container_name=container_name,
            package_root=package_copy,
            io_root=io_root,
            image=selected_image,
            memory_mb=memory_mb,
        )
        started = time.monotonic()
        try:
            process = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout + DOCKER_STARTUP_GRACE_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _remove_container(docker_executable, container_name)
            stdout, stdout_truncated = _truncate(str(exc.stdout or ""))
            stderr, stderr_truncated = _truncate(str(exc.stderr or ""))
            evidence = {
                **base_evidence,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "exit_code": None,
                "timed_out": True,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[
                    _diagnostic(
                        "sandbox.timeout",
                        "$.execution.timeout_seconds",
                        f"module exceeded Docker sandbox timeout of {effective_timeout:g} seconds",
                    )
                ],
                evidence=evidence,
            )
        except OSError as exc:
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[_diagnostic("sandbox.docker_failed", "$.runtime", str(exc))],
                evidence=base_evidence,
            )

        stdout, stdout_truncated = _truncate(process.stdout)
        stderr, stderr_truncated = _truncate(process.stderr)
        evidence = {
            **base_evidence,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "exit_code": process.returncode,
            "timed_out": False,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
        if not response_path.exists():
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[
                    _diagnostic(
                        "sandbox.docker_failed",
                        "$.runtime",
                        f"Docker sandbox exited without a response (exit code {process.returncode})",
                    )
                ],
                evidence=evidence,
            )
        try:
            worker_report = json.loads(response_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return _failure_report(
                module_id=module_id,
                sandbox_id=sandbox_id,
                diagnostics=[_diagnostic("sandbox.response_invalid", "$", str(exc))],
                evidence=evidence,
            )
        enforced_limits = _limits_evidence(
            timeout_seconds=effective_timeout,
            memory_mb=memory_mb,
            enforced=True,
        )
        worker_evidence = worker_report.get("evidence") if isinstance(worker_report.get("evidence"), dict) else {}
        enforced_policy = {
            **base_evidence["policy"],
            "enforced": base_evidence["policy"]["requested"],
        }
        worker_limits = (
            worker_evidence.get("limits")
            if isinstance(worker_evidence.get("limits"), dict)
            else {}
        )
        return {
            "ok": bool(worker_report.get("ok")) and process.returncode == 0,
            "status": str(worker_report.get("status") or "failed"),
            "module_id": module_id,
            "sandbox_id": sandbox_id,
            "result": worker_report.get("result"),
            "diagnostics": worker_report.get("diagnostics") or [],
            "evidence": {
                **worker_evidence,
                **evidence,
                "runtime": base_evidence["runtime"],
                "policy": enforced_policy,
                "limits": {
                    **worker_limits,
                    **enforced_limits,
                },
            },
        }
