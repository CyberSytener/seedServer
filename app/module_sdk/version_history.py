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


VERSION_HISTORY_SCHEMA_VERSION = "1.0"
DEFAULT_VERSION_HISTORY_ROOT = Path(".seed_artifacts/module_versions")


def resolve_version_history_root(
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    versions_root: Optional[Path] = None,
) -> Path:
    if versions_root is not None:
        return versions_root
    if evidence_root == DEFAULT_EVIDENCE_ROOT:
        return DEFAULT_VERSION_HISTORY_ROOT
    return evidence_root.parent / "module_versions"


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _snapshot_target(
    module_id: str,
    module_version: str,
    fingerprint: str,
    *,
    versions_root: Path,
) -> Path:
    return (
        versions_root
        / _safe_component(module_id, "unknown_module")
        / _safe_component(module_version, "unknown")
        / fingerprint.removeprefix("sha256:")
    )


def _validate_relative_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"invalid snapshot file path: {value}")
    return path


def _load_version_snapshot(path: Path, *, signing_key: Optional[str]) -> Dict[str, Any]:
    metadata_path = path / "version.json"
    record = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("version record must be a JSON object")
    if record.get("schema_version") != VERSION_HISTORY_SCHEMA_VERSION:
        raise ValueError("unsupported version history schema version")
    record_payload = {
        key: value
        for key, value in record.items()
        if key not in {"record_sha256", "signature"}
    }
    if record.get("record_sha256") != _sha256(record_payload):
        raise ValueError("version record integrity hash mismatch")
    signature_status = _signature_status(record, signing_key)
    if signature_status == "invalid":
        raise ValueError("version record signature invalid")

    module = record.get("module") if isinstance(record.get("module"), dict) else {}
    module_id = str(module.get("mode_id") or "")
    module_version = str(module.get("module_version") or "")
    fingerprint = str(module.get("fingerprint") or "")
    if _snapshot_target(
        module_id,
        module_version,
        fingerprint,
        versions_root=path.parents[2],
    ) != path:
        raise ValueError("version record identity does not match its history path")

    declared_files = record.get("files") if isinstance(record.get("files"), list) else None
    if declared_files is None:
        raise ValueError("version record files must be a list")
    package_root = path / "package"
    actual_files: Dict[str, Path] = {}
    for candidate in package_root.rglob("*") if package_root.exists() else []:
        if candidate.is_symlink():
            raise ValueError(f"version snapshot does not allow symlinks: {candidate}")
        if candidate.is_file():
            actual_files[candidate.relative_to(package_root).as_posix()] = candidate

    declared_paths = set()
    for item in declared_files:
        if not isinstance(item, dict):
            raise ValueError("version record file entries must be objects")
        relative = _validate_relative_path(str(item.get("path") or "")).as_posix()
        if relative in declared_paths:
            raise ValueError(f"duplicate snapshot file path: {relative}")
        declared_paths.add(relative)
        candidate = actual_files.get(relative)
        if candidate is None:
            raise ValueError(f"snapshot file missing: {relative}")
        if item.get("sha256") != _file_sha256(candidate):
            raise ValueError(f"snapshot file hash mismatch: {relative}")
        if item.get("size") != candidate.stat().st_size:
            raise ValueError(f"snapshot file size mismatch: {relative}")
    if declared_paths != set(actual_files):
        raise ValueError("snapshot package contains undeclared files")

    package = resolve_module_package(package_root)
    manifest = package.load_manifest()
    if str(manifest.get("lifecycle") or "") != "published":
        raise ValueError("snapshot manifest lifecycle must be published")
    if fingerprint_module_package(package) != fingerprint:
        raise ValueError("snapshot package fingerprint mismatch")
    return {
        **record,
        "path": str(path),
        "package_path": str(package_root),
        "signature_status": signature_status,
    }


def load_module_version_history(
    module_id: str,
    *,
    versions_root: Path = DEFAULT_VERSION_HISTORY_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = _safe_component(module_id, "unknown_module")
    module_root = versions_root / normalized
    versions = []
    invalid = []
    if module_root.exists():
        for version_root in sorted(path for path in module_root.iterdir() if path.is_dir()):
            for snapshot_path in sorted(path for path in version_root.iterdir() if path.is_dir()):
                if snapshot_path.name.startswith("."):
                    continue
                try:
                    versions.append(_load_version_snapshot(snapshot_path, signing_key=signing_key))
                except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
                    invalid.append(
                        {
                            "path": str(snapshot_path),
                            "module_version": version_root.name,
                            "message": str(exc),
                        }
                    )
    diagnostics = [
        {
            "code": "version.snapshot_invalid",
            "path": item["path"],
            "message": item["message"],
        }
        for item in invalid
    ]
    return {
        "ok": not invalid,
        "module_id": normalized,
        "root": str(versions_root),
        "version_count": len(versions),
        "versions": versions,
        "invalid": invalid,
        "diagnostics": diagnostics,
    }


def assess_module_version_slot(
    package: ModulePackage,
    *,
    versions_root: Path = DEFAULT_VERSION_HISTORY_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    module_id, module_version = _module_identity(package)
    fingerprint = fingerprint_module_package(package)
    history = load_module_version_history(
        module_id,
        versions_root=versions_root,
        signing_key=signing_key,
    )
    same_version = [
        record
        for record in history["versions"]
        if str((record.get("module") or {}).get("module_version") or "") == module_version
    ]
    invalid = [
        item
        for item in history["invalid"]
        if str(item.get("module_version") or "") == module_version
    ]
    blockers = [
        {
            "code": "version.history_invalid",
            "path": item["path"],
            "message": f"published version history is invalid: {item['message']}",
        }
        for item in invalid
    ]
    conflicting = [
        record
        for record in same_version
        if str((record.get("module") or {}).get("fingerprint") or "") != fingerprint
    ]
    if conflicting:
        blockers.append(
            {
                "code": "version.version_conflict",
                "path": "$.module_version",
                "message": (
                    f"module version {module_version} is already published with a different package fingerprint"
                ),
            }
        )
    existing = next(
        (
            record
            for record in same_version
            if str((record.get("module") or {}).get("fingerprint") or "") == fingerprint
        ),
        None,
    )
    return {
        "ok": not blockers,
        "root": str(versions_root),
        "module_id": module_id,
        "module_version": module_version,
        "fingerprint": fingerprint,
        "existing": existing,
        "blockers": blockers,
    }


def record_published_module_version(
    package: ModulePackage,
    *,
    publication: Dict[str, Any],
    versions_root: Path = DEFAULT_VERSION_HISTORY_ROOT,
    signing_key: str,
) -> Dict[str, Any]:
    if str(package.load_manifest().get("lifecycle") or "") != "published":
        raise ValueError("version snapshots require a published module lifecycle")
    module_id, module_version = _module_identity(package)
    fingerprint = fingerprint_module_package(package)
    target = _snapshot_target(
        module_id,
        module_version,
        fingerprint,
        versions_root=versions_root,
    )
    if target.exists():
        return _load_version_snapshot(target, signing_key=signing_key)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}-{uuid.uuid4().hex}.tmp"
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
        record_payload = {
            "schema_version": VERSION_HISTORY_SCHEMA_VERSION,
            "version_id": f"ver-{uuid.uuid4().hex}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "module": {
                "mode_id": module_id,
                "module_version": module_version,
                "fingerprint": fingerprint,
            },
            "publication": publication,
            "files": files,
        }
        record = {**record_payload, "record_sha256": _sha256(record_payload)}
        record["signature"] = _signature(record, signing_key)
        temporary.mkdir(parents=True, exist_ok=True)
        (temporary / "version.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return _load_version_snapshot(target, signing_key=signing_key)
