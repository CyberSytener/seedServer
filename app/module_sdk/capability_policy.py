from __future__ import annotations

import contextlib
import os
import sys
from typing import Any, Dict, Iterator

from app.module_sdk.runtime import ModuleSDKError


MAX_OBSERVED_OPERATIONS = 256
MAX_TARGET_CHARS = 512
_IMPORT_LOADER_SUFFIXES = (".py", ".pyc", ".pyo", ".pyd", ".so")
_FILESYSTEM_READ_EVENTS = {"os.listdir", "os.scandir"}
_FILESYSTEM_WRITE_EVENTS = {
    "os.chmod",
    "os.chown",
    "os.link",
    "os.mkdir",
    "os.remove",
    "os.rename",
    "os.replace",
    "os.rmdir",
    "os.symlink",
    "os.truncate",
    "os.utime",
}
_NETWORK_EVENTS = {
    "socket.bind",
    "socket.connect",
    "socket.connect_ex",
    "socket.getaddrinfo",
    "socket.gethostbyaddr",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
    "socket.sendto",
}
_PROCESS_EVENTS = {
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.system",
    "subprocess.Popen",
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _safe_target(value: Any) -> str:
    try:
        rendered = os.fspath(value) if isinstance(value, (str, bytes, os.PathLike)) else repr(value)
    except (OSError, TypeError, ValueError):
        rendered = value.__class__.__name__
    if isinstance(rendered, bytes):
        rendered = rendered.decode("utf-8", errors="replace")
    text = str(rendered)
    return text if len(text) <= MAX_TARGET_CHARS else f"{text[:MAX_TARGET_CHARS]}..."


def _open_operation(args: tuple[Any, ...]) -> tuple[str, str]:
    target = _safe_target(args[0] if args else "")
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    writes = (
        isinstance(mode, str)
        and any(marker in mode for marker in ("w", "a", "x", "+"))
    ) or (isinstance(flags, int) and bool(flags & _WRITE_FLAGS))
    return ("filesystem.write" if writes else "filesystem.read", target)


def _event_operation(event: str, args: tuple[Any, ...]) -> tuple[str, str] | None:
    if event == "open":
        return _open_operation(args)
    if event in _FILESYSTEM_READ_EVENTS:
        return "filesystem.read", _safe_target(args[0] if args else "")
    if event in _FILESYSTEM_WRITE_EVENTS:
        targets = [_safe_target(value) for value in args[:2] if isinstance(value, (str, bytes, os.PathLike))]
        return "filesystem.write", " -> ".join(targets)
    if event in _NETWORK_EVENTS:
        return "network", _safe_target(args[-1] if args else "")
    if event in _PROCESS_EVENTS:
        return "process", _safe_target(args[:2])
    return None


class CapabilityObserver:
    def __init__(self, manifest: Dict[str, Any]) -> None:
        effects = manifest.get("effects") if isinstance(manifest.get("effects"), dict) else {}
        security = manifest.get("security") if isinstance(manifest.get("security"), dict) else {}
        self.policy = {
            "network_access": str(effects.get("network_access") or "none"),
            "filesystem_access": str(effects.get("filesystem_access") or "none"),
            "process_access": "none",
            "secret_refs": [str(item) for item in security.get("secret_refs") or []],
        }
        self.operations: list[Dict[str, Any]] = []
        self.operation_count = 0
        self.violation_count = 0
        self.truncated = False
        self._active = False
        self._import_phase = False
        sys.addaudithook(self._audit)

    def _allowed(self, operation: str, event: str, target: str) -> tuple[bool, str]:
        if self._import_phase:
            if operation == "filesystem.read" and event == "open" and target.lower().endswith(_IMPORT_LOADER_SUFFIXES):
                return True, "handler import loader code reads are allowed"
            return False, "handler import side effects are blocked"
        if operation == "network":
            declared = self.policy["network_access"]
            return declared != "none", f"network_access={declared}"
        if operation == "filesystem.read":
            declared = self.policy["filesystem_access"]
            return declared in {"read_only", "sandbox"}, f"filesystem_access={declared}"
        if operation == "filesystem.write":
            declared = self.policy["filesystem_access"]
            return declared == "sandbox", f"filesystem_access={declared}"
        return False, "process execution is not representable in Module Contract v1"

    def _audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not self._active:
            return
        observed = _event_operation(event, args)
        if observed is None:
            return
        operation, target = observed
        allowed, reason = self._allowed(operation, event, target)
        record = {
            "event": event,
            "operation": operation,
            "target": target,
            "outcome": "allowed" if allowed else "blocked",
            "policy": reason,
        }
        self.operation_count += 1
        if len(self.operations) < MAX_OBSERVED_OPERATIONS:
            self.operations.append(record)
        else:
            self.truncated = True
        if allowed:
            return
        self.violation_count += 1
        raise ModuleSDKError(
            "sandbox.capability_violation",
            f"blocked undeclared {operation} operation: {target}",
            details=record,
        )

    @contextlib.contextmanager
    def enforce(self, *, import_phase: bool = False) -> Iterator[None]:
        previous_active = self._active
        previous_import_phase = self._import_phase
        self._active = True
        self._import_phase = import_phase
        try:
            yield
        finally:
            self._active = previous_active
            self._import_phase = previous_import_phase

    def report(self) -> Dict[str, Any]:
        return {
            "enforcement": "python_audit_hook",
            "policy": self.policy,
            "operations": self.operations,
            "operation_count": self.operation_count,
            "violation_count": self.violation_count,
            "truncated": self.truncated,
        }

    def diagnostics(self) -> list[Dict[str, str]]:
        return [
            {
                "code": "sandbox.capability_violation",
                "path": f"$.evidence.capability_report.operations.{index}",
                "message": f"blocked undeclared {item['operation']} operation: {item['target']}",
            }
            for index, item in enumerate(self.operations)
            if item["outcome"] == "blocked"
        ]
