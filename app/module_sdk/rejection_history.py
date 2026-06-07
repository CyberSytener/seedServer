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
REPAIR_ATTEMPT_SCHEMA_VERSION = "1.0"
MAX_REPAIR_ATTEMPTS = 3
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
    repair_attempts = _load_repair_attempts(path, record=record, signing_key=signing_key)
    return {
        **record,
        "path": str(path),
        "package_path": str(package_root),
        "signature_status": signature_status,
        "repair_attempts": repair_attempts,
        "attempt_count": len(repair_attempts),
        "attempts_remaining": max(0, MAX_REPAIR_ATTEMPTS - len(repair_attempts)),
        "latest_attempt": repair_attempts[-1] if repair_attempts else None,
        "repair_status": (
            "succeeded"
            if repair_attempts and repair_attempts[-1].get("report", {}).get("ok")
            else "failed"
            if repair_attempts
            else "not_attempted"
        ),
    }


def _load_repair_attempt(
    path: Path,
    *,
    rejection_record: Dict[str, Any],
    signing_key: Optional[str],
) -> Dict[str, Any]:
    record = json.loads((path / "repair.json").read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("repair attempt record must be a JSON object")
    if record.get("schema_version") != REPAIR_ATTEMPT_SCHEMA_VERSION:
        raise ValueError("unsupported repair attempt schema version")
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"record_sha256", "signature"}
    }
    if record.get("record_sha256") != _sha256(payload):
        raise ValueError("repair attempt record integrity hash mismatch")
    signature_status = _signature_status(record, signing_key)
    if signature_status == "invalid":
        raise ValueError("repair attempt signature invalid")
    if signature_status == "unsigned":
        raise ValueError("repair attempt signature missing")
    source = record.get("source_rejection") if isinstance(record.get("source_rejection"), dict) else {}
    if (
        source.get("rejection_id") != rejection_record.get("rejection_id")
        or source.get("record_sha256") != rejection_record.get("record_sha256")
    ):
        raise ValueError("repair attempt source rejection mismatch")

    candidate = record.get("candidate") if isinstance(record.get("candidate"), dict) else {}
    fingerprint = str(candidate.get("fingerprint") or "")
    package_root = path / "package"
    actual_files: Dict[str, Path] = {}
    for candidate_path in package_root.rglob("*") if package_root.exists() else []:
        if candidate_path.is_symlink():
            raise ValueError(f"repair attempt snapshot does not allow symlinks: {candidate_path}")
        if candidate_path.is_file():
            actual_files[candidate_path.relative_to(package_root).as_posix()] = candidate_path
    declared_files = record.get("files") if isinstance(record.get("files"), list) else None
    if declared_files is None:
        raise ValueError("repair attempt files must be a list")
    declared_paths = set()
    for item in declared_files:
        if not isinstance(item, dict):
            raise ValueError("repair attempt file entries must be objects")
        relative = _validate_relative_path(str(item.get("path") or "")).as_posix()
        if relative in declared_paths:
            raise ValueError(f"duplicate repair attempt file path: {relative}")
        declared_paths.add(relative)
        candidate_path = actual_files.get(relative)
        if candidate_path is None:
            raise ValueError(f"repair attempt file missing: {relative}")
        if item.get("sha256") != _file_sha256(candidate_path):
            raise ValueError(f"repair attempt file hash mismatch: {relative}")
        if item.get("size") != candidate_path.stat().st_size:
            raise ValueError(f"repair attempt file size mismatch: {relative}")
    if declared_paths != set(actual_files):
        raise ValueError("repair attempt package contains undeclared files")
    package = resolve_module_package(package_root)
    if fingerprint_module_package(package) != fingerprint:
        raise ValueError("repair attempt package fingerprint mismatch")
    source_module = (
        rejection_record.get("module")
        if isinstance(rejection_record.get("module"), dict)
        else {}
    )
    if (
        (
            source_module.get("mode_id") != "unknown_module"
            and candidate.get("mode_id") != source_module.get("mode_id")
        )
        or (
            source_module.get("module_version") != "unknown"
            and candidate.get("module_version") != source_module.get("module_version")
        )
    ):
        raise ValueError("repair attempt candidate identity mismatch")
    return {
        **record,
        "path": str(path),
        "package_path": str(package_root),
        "signature_status": signature_status,
    }


def _load_repair_attempts(
    rejection_path: Path,
    *,
    record: Dict[str, Any],
    signing_key: Optional[str],
) -> list[Dict[str, Any]]:
    attempts = []
    attempts_root = rejection_path / "repairs"
    for path in sorted(attempts_root.iterdir()) if attempts_root.exists() else []:
        if path.is_dir() and not path.name.startswith("."):
            attempts.append(_load_repair_attempt(path, rejection_record=record, signing_key=signing_key))
    attempts.sort(key=lambda item: int(item.get("attempt") or 0))
    expected = list(range(1, len(attempts) + 1))
    if [int(item.get("attempt") or 0) for item in attempts] != expected:
        raise ValueError("repair attempt sequence is not contiguous")
    source_module = record.get("module") if isinstance(record.get("module"), dict) else {}
    expected_id = str(source_module.get("mode_id") or "")
    expected_version = str(source_module.get("module_version") or "")
    if attempts and expected_id == "unknown_module":
        expected_id = str(attempts[0]["candidate"].get("mode_id") or "")
    if attempts and expected_version == "unknown":
        expected_version = str(attempts[0]["candidate"].get("module_version") or "")
    if any(
        attempt["candidate"].get("mode_id") != expected_id
        or attempt["candidate"].get("module_version") != expected_version
        for attempt in attempts
    ):
        raise ValueError("repair attempt sequence changes candidate identity")
    return attempts


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


def record_module_repair_attempt(
    rejection_record: Dict[str, Any],
    package: ModulePackage,
    *,
    provenance: Dict[str, Any],
    report: Dict[str, Any],
    signing_key: str,
) -> Dict[str, Any]:
    rejection_path = Path(str(rejection_record.get("path") or ""))
    verified = _load_rejection(rejection_path, signing_key=signing_key)
    if verified["signature_status"] != "valid":
        raise ValueError("repair attempts require a rejection signed by the configured authority")
    attempt = int(verified["attempt_count"]) + 1
    if attempt > MAX_REPAIR_ATTEMPTS:
        raise ValueError(f"repair attempt budget exhausted ({MAX_REPAIR_ATTEMPTS})")

    module_id, module_version = _module_identity(package)
    fingerprint = fingerprint_module_package(package)
    attempt_id = f"repair-{uuid.uuid4().hex}"
    target = rejection_path / "repairs" / f"{attempt:02d}-{attempt_id}"
    temporary = target.parent / f".{attempt_id}-{uuid.uuid4().hex}.tmp"
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
            "schema_version": REPAIR_ATTEMPT_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "attempt": attempt,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_rejection": {
                "rejection_id": verified["rejection_id"],
                "record_sha256": verified["record_sha256"],
            },
            "candidate": {
                "mode_id": module_id,
                "module_version": module_version,
                "fingerprint": fingerprint,
            },
            "provenance": provenance,
            "report": report,
            "files": files,
        }
        record = {**payload, "record_sha256": _sha256(payload)}
        record["signature"] = _signature(record, signing_key)
        temporary.mkdir(parents=True, exist_ok=True)
        (temporary / "repair.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return _load_repair_attempt(target, rejection_record=verified, signing_key=signing_key)
