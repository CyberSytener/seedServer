from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.module_sdk.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    _module_identity,
    _safe_component,
    _sha256,
    _signature,
    _signature_status,
    fingerprint_module_package,
    module_package_files,
)
from app.module_sdk.package import ModulePackage, resolve_module_package


REJECTION_SCHEMA_VERSION = "1.0"
DEFAULT_REJECTION_HISTORY_ROOT = Path(".seed_artifacts/module_rejections")


def resolve_rejection_history_root(
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    rejections_root: Optional[Path] = None,
) -> Path:
    if rejections_root is not None:
        return rejections_root
    if evidence_root == DEFAULT_EVIDENCE_ROOT:
        return DEFAULT_REJECTION_HISTORY_ROOT
    return evidence_root.parent / "module_rejections"


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _validate_relative_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"invalid rejected candidate file path: {value}")
    return path


def _load_rejection(path: Path, *, signing_key: Optional[str]) -> Dict[str, Any]:
    record = json.loads((path / "rejection.json").read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("rejection record must be a JSON object")
    if record.get("schema_version") != REJECTION_SCHEMA_VERSION:
        raise ValueError("unsupported rejection schema version")
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"record_sha256", "signature"}
    }
    if record.get("record_sha256") != _sha256(payload):
        raise ValueError("rejection record integrity hash mismatch")
    signature_status = _signature_status(record, signing_key)
    if signature_status == "invalid":
        raise ValueError("rejection record signature invalid")
    if signature_status == "unsigned":
        raise ValueError("rejection record signature missing")

    module = record.get("module") if isinstance(record.get("module"), dict) else {}
    module_id = str(module.get("mode_id") or "")
    module_version = str(module.get("module_version") or "")
    fingerprint = str(module.get("fingerprint") or "")
    if (
        path.name != str(record.get("rejection_id") or "")
        or path.parent.name != fingerprint.removeprefix("sha256:")
        or path.parent.parent.name != _safe_component(module_version, "unknown")
        or path.parent.parent.parent.name != _safe_component(module_id, "unknown_module")
    ):
        raise ValueError("rejection identity does not match its history path")

    package_root = path / "package"
    actual_files: Dict[str, Path] = {}
    for candidate in package_root.rglob("*") if package_root.exists() else []:
        if candidate.is_symlink():
            raise ValueError(f"rejected candidate snapshot does not allow symlinks: {candidate}")
        if candidate.is_file():
            actual_files[candidate.relative_to(package_root).as_posix()] = candidate
    declared_files = record.get("files") if isinstance(record.get("files"), list) else None
    if declared_files is None:
        raise ValueError("rejection record files must be a list")
    declared_paths = set()
    for item in declared_files:
        if not isinstance(item, dict):
            raise ValueError("rejection record file entries must be objects")
        relative = _validate_relative_path(str(item.get("path") or "")).as_posix()
        if relative in declared_paths:
            raise ValueError(f"duplicate rejected candidate file path: {relative}")
        declared_paths.add(relative)
        candidate = actual_files.get(relative)
        if candidate is None:
            raise ValueError(f"rejected candidate file missing: {relative}")
        if item.get("sha256") != _file_sha256(candidate):
            raise ValueError(f"rejected candidate file hash mismatch: {relative}")
        if item.get("size") != candidate.stat().st_size:
            raise ValueError(f"rejected candidate file size mismatch: {relative}")
    if declared_paths != set(actual_files):
        raise ValueError("rejected candidate package contains undeclared files")

    package = resolve_module_package(package_root)
    if fingerprint_module_package(package) != fingerprint:
        raise ValueError("rejected candidate package fingerprint mismatch")
    try:
        manifest = package.load_manifest()
    except Exception:  # noqa: BLE001
        manifest = {}
    if "mode_id" in manifest:
        manifest_id = _safe_component(str(manifest.get("mode_id") or ""), "unknown_module")
        if manifest_id != module_id:
            raise ValueError("rejected candidate package identity mismatch")
    if "module_version" in manifest:
        manifest_version = _safe_component(str(manifest.get("module_version") or ""), "unknown")
        if manifest_version != module_version:
            raise ValueError("rejected candidate package identity mismatch")
    return {
        **record,
        "path": str(path),
        "package_path": str(package_root),
        "signature_status": signature_status,
    }


def load_module_rejection_history(
    module_id: str,
    *,
    rejections_root: Path = DEFAULT_REJECTION_HISTORY_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = _safe_component(module_id, "unknown_module")
    module_root = rejections_root / normalized
    rejections = []
    invalid = []
    for path in sorted(module_root.glob("*/*/*")) if module_root.exists() else []:
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            rejections.append(_load_rejection(path, signing_key=signing_key))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            invalid.append({"path": str(path), "message": str(exc)})
    rejections.sort(
        key=lambda item: (str(item.get("rejected_at") or ""), str(item.get("rejection_id") or ""))
    )
    diagnostics = [
        {
            "code": "rejection.snapshot_invalid",
            "path": item["path"],
            "message": item["message"],
        }
        for item in invalid
    ]
    return {
        "ok": not invalid,
        "module_id": normalized,
        "root": str(rejections_root),
        "rejection_count": len(rejections),
        "rejections": rejections,
        "invalid": invalid,
        "diagnostics": diagnostics,
    }


def record_rejected_module_candidate(
    package: ModulePackage,
    *,
    decision: Dict[str, Any],
    repair_context: Dict[str, Any],
    rejections_root: Path = DEFAULT_REJECTION_HISTORY_ROOT,
    signing_key: str,
) -> Dict[str, Any]:
    module_id, module_version = _module_identity(package)
    fingerprint = fingerprint_module_package(package)
    rejection_id = f"rej-{uuid.uuid4().hex}"
    target = (
        rejections_root
        / module_id
        / module_version
        / fingerprint.removeprefix("sha256:")
        / rejection_id
    )
    temporary = target.parent / f".{rejection_id}-{uuid.uuid4().hex}.tmp"
    package_root = temporary / "package"
    try:
        files = []
        for relative, source in module_package_files(package):
            destination = package_root / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            files.append(
                {
                    "path": relative,
                    "sha256": _file_sha256(destination),
                    "size": destination.stat().st_size,
                }
            )
        payload = {
            "schema_version": REJECTION_SCHEMA_VERSION,
            "rejection_id": rejection_id,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "module": {
                "mode_id": module_id,
                "module_version": module_version,
                "fingerprint": fingerprint,
            },
            "decision": decision,
            "repair_context": repair_context,
            "files": files,
        }
        record = {**payload, "record_sha256": _sha256(payload)}
        record["signature"] = _signature(record, signing_key)
        temporary.mkdir(parents=True, exist_ok=True)
        (temporary / "rejection.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return _load_rejection(target, signing_key=signing_key)
