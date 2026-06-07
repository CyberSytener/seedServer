from __future__ import annotations

import asyncio
import contextlib
import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict

from app.module_sdk.package import _load_handler, resolve_module_package
from app.module_sdk.runtime import ModuleExecutionContext, execute_module
from app.module_sdk.sandbox import MAX_CAPTURE_CHARS, SANDBOX_PROTOCOL_VERSION


class _LimitedTextBuffer(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.truncated = False

    def write(self, value: str) -> int:
        remaining = MAX_CAPTURE_CHARS - len(self.getvalue())
        if remaining > 0:
            super().write(value[:remaining])
        if len(value) > remaining:
            self.truncated = True
        return len(value)


def _apply_resource_limits(*, memory_mb: int, timeout_seconds: float) -> Dict[str, Any]:
    limits = {
        "cpu_enforced": False,
        "memory_enforced": False,
    }
    try:
        import resource
    except ImportError:
        return limits

    cpu_seconds = max(1, math.ceil(timeout_seconds))
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        limits["cpu_enforced"] = True
    except (OSError, ValueError):
        pass
    try:
        memory_bytes = max(1, memory_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_DATA, (memory_bytes, memory_bytes))
        limits["memory_enforced"] = True
    except (AttributeError, OSError, ValueError):
        pass
    return limits


def _write_response(path: Path, report: Dict[str, Any]) -> None:
    path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")


def _run(request: Dict[str, Any]) -> Dict[str, Any]:
    if request.get("protocol_version") != SANDBOX_PROTOCOL_VERSION:
        raise ValueError("unsupported sandbox protocol version")

    package = resolve_module_package(Path(str(request["manifest_path"])))
    manifest = package.load_manifest()
    limits = _apply_resource_limits(
        memory_mb=int(request.get("memory_mb") or 128),
        timeout_seconds=float(request.get("timeout_seconds") or 30),
    )
    stdout = _LimitedTextBuffer()
    stderr = _LimitedTextBuffer()
    started = time.monotonic()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        handler = _load_handler(Path(str(request["handler_path"])))
        context = ModuleExecutionContext(
            module_id=str(manifest.get("mode_id") or "unknown"),
            run_id=str(request.get("sandbox_id") or "sdk-sandbox"),
            execution_mode="sandbox",
            capabilities=[str(item) for item in manifest.get("capabilities") or []],
            metadata={"sandbox_protocol": SANDBOX_PROTOCOL_VERSION},
        )
        result = asyncio.run(
            execute_module(
                handler,
                context=context,
                inputs=request.get("inputs") if isinstance(request.get("inputs"), dict) else {},
                input_schema=manifest.get("input_schema") if isinstance(manifest.get("input_schema"), dict) else {},
                output_schema=manifest.get("output_schema") if isinstance(manifest.get("output_schema"), dict) else {},
            )
        )
    return {
        "ok": result.status == "succeeded",
        "status": result.status,
        "result": result.model_dump(),
        "diagnostics": [item.model_dump() for item in result.diagnostics],
        "evidence": {
            "worker_duration_ms": round((time.monotonic() - started) * 1000, 2),
            "handler_stdout": stdout.getvalue(),
            "handler_stderr": stderr.getvalue(),
            "handler_stdout_truncated": stdout.truncated,
            "handler_stderr_truncated": stderr.truncated,
            "limits": limits,
        },
    }


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    request_path = Path(sys.argv[1])
    response_path = Path(sys.argv[2])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        report = _run(request)
        _write_response(response_path, report)
        return 0 if report["ok"] else 1
    except Exception as exc:  # noqa: BLE001
        _write_response(
            response_path,
            {
                "ok": False,
                "status": "failed",
                "result": None,
                "diagnostics": [
                    {
                        "code": "sandbox.worker_exception",
                        "path": "$",
                        "message": str(exc) or exc.__class__.__name__,
                    }
                ],
                "evidence": {},
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
