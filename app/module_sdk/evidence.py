from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.module_sdk.package import (
    ModulePackage,
    run_module_package_tests,
    validate_module_package,
)
from app.module_sdk.sandbox import sandbox_module_package


EVIDENCE_SCHEMA_VERSION = "1.0"
REQUIRED_EVIDENCE_KINDS = ("validation", "test", "sandbox")
EVIDENCE_KINDS = (*REQUIRED_EVIDENCE_KINDS, "transition", "publish", "deprecate", "reject")
DEFAULT_EVIDENCE_ROOT = Path(".seed_artifacts/module_evidence")
_IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}
_NEXT_LIFECYCLE = {
    "draft": "validated",
    "validated": "tested",
    "tested": "sandboxed",
    "sandboxed": "approved",
    "published": "deprecated",
}
_DRAFT_RESET_SOURCES = {"validated", "tested", "sandboxed", "approved"}
_TRANSITION_REQUIREMENTS = {
    "draft": (),
    "validated": ("validation",),
    "tested": ("validation", "test"),
    "sandboxed": REQUIRED_EVIDENCE_KINDS,
    "approved": REQUIRED_EVIDENCE_KINDS,
    "deprecated": (),
}
_HARDENED_SANDBOX_LIMITS = {
    "read_only_rootfs": ("sandbox.root_filesystem_isolation_missing", "read-only root filesystem"),
    "capabilities_dropped": ("sandbox.capabilities_drop_missing", "dropped Linux capabilities"),
    "no_new_privileges": ("sandbox.no_new_privileges_missing", "no-new-privileges enforcement"),
    "non_root_user": ("sandbox.non_root_user_missing", "non-root container user"),
    "memory_enforced": ("sandbox.memory_limit_missing", "memory limit"),
    "process_limit_enforced": ("sandbox.process_limit_missing", "process limit"),
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_json_bytes(value)).hexdigest()}"


def _signing_key_bytes(signing_key: str) -> bytes:
    value = signing_key.encode("utf-8")
    if len(value) < 32:
        raise ValueError("module evidence signing key must contain at least 32 UTF-8 bytes")
    return value


def _signature(value: Any, signing_key: str) -> Dict[str, str]:
    key = _signing_key_bytes(signing_key)
    return {
        "algorithm": "hmac-sha256",
        "key_id": f"sha256:{hashlib.sha256(key).hexdigest()[:16]}",
        "value": hmac.new(key, _json_bytes(value), hashlib.sha256).hexdigest(),
    }


def _signature_status(record: Dict[str, Any], signing_key: Optional[str]) -> str:
    signature = record.get("signature") if isinstance(record.get("signature"), dict) else None
    if signature is None:
        return "unsigned"
    if signing_key is None:
        return "unverified"
    if signature.get("algorithm") != "hmac-sha256":
        return "invalid"
    try:
        expected = _signature({key: value for key, value in record.items() if key != "signature"}, signing_key)
    except ValueError:
        return "invalid"
    if signature.get("key_id") != expected["key_id"]:
        return "invalid"
    return "valid" if hmac.compare_digest(str(signature.get("value") or ""), expected["value"]) else "invalid"


def _safe_component(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()).strip("._")
    return normalized or fallback


def _module_identity(package: ModulePackage) -> tuple[str, str]:
    try:
        manifest = package.load_manifest()
    except Exception:  # noqa: BLE001
        manifest = {}
    fallback_id = package.root.name if package.manifest_path.stem == "module" else package.manifest_path.stem
    module_id = _safe_component(str(manifest.get("mode_id") or fallback_id), "unknown_module")
    module_version = _safe_component(str(manifest.get("module_version") or "unknown"), "unknown")
    return module_id, module_version


def module_package_files(package: ModulePackage) -> list[tuple[str, Path]]:
    files = []
    candidates = (
        package.root.rglob("*")
        if package.manifest_path.stem == "module"
        else [package.manifest_path, package.handler_path]
    )
    for path in candidates:
        if path is None:
            continue
        if path.is_symlink():
            raise ValueError(f"module evidence fingerprint does not allow symlinks: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(package.root)
        if any(part in _IGNORED_PARTS for part in relative.parts) or path.suffix in _IGNORED_SUFFIXES:
            continue
        files.append((relative.as_posix(), path))
    return sorted(files)


def fingerprint_module_package(package: ModulePackage) -> str:
    digest = hashlib.sha256()
    for relative, path in module_package_files(package):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path == package.manifest_path:
            try:
                manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                manifest = None
            if isinstance(manifest, dict):
                manifest = dict(manifest)
                manifest.pop("lifecycle", None)
                digest.update(_json_bytes(manifest))
            else:
                digest.update(path.read_bytes())
        else:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def record_module_evidence(
    package: ModulePackage,
    *,
    kind: str,
    report: Dict[str, Any],
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f"unsupported module evidence kind: {kind}")
    module_id, module_version = _module_identity(package)
    fingerprint = fingerprint_module_package(package)
    evidence_id = f"ev-{uuid.uuid4().hex}"
    recorded_at = datetime.now(timezone.utc).isoformat()
    record_payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "kind": kind,
        "recorded_at": recorded_at,
        "module": {
            "mode_id": module_id,
            "module_version": module_version,
            "fingerprint": fingerprint,
        },
        "report_sha256": _sha256(report),
        "report": report,
    }
    record = {**record_payload, "record_sha256": _sha256(record_payload)}
    if signing_key is not None:
        record["signature"] = _signature(record, signing_key)
    target = (
        evidence_root
        / module_id
        / module_version
        / fingerprint.removeprefix("sha256:")
        / f"{kind}-{evidence_id}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {**record, "path": str(target)}


def load_module_evidence(
    package: ModulePackage,
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    module_id, _ = _module_identity(package)
    fingerprint = fingerprint_module_package(package)
    records = []
    invalid = []
    module_root = evidence_root / module_id
    for path in sorted(module_root.glob("**/*.json")) if module_root.exists() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("evidence record must be a JSON object")
            if record.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
                raise ValueError("unsupported evidence schema version")
            if record.get("kind") not in EVIDENCE_KINDS:
                raise ValueError("unsupported evidence kind")
            if record.get("report_sha256") != _sha256(record.get("report")):
                raise ValueError("report integrity hash mismatch")
            record_payload = {
                key: value
                for key, value in record.items()
                if key not in {"record_sha256", "signature"}
            }
            if record.get("record_sha256") != _sha256(record_payload):
                raise ValueError("evidence envelope integrity hash mismatch")
            signature_status = _signature_status(record, signing_key)
            if signature_status == "invalid":
                raise ValueError("evidence signature invalid")
            module = record.get("module") if isinstance(record.get("module"), dict) else {}
            if str(module.get("mode_id") or "") != module_id:
                raise ValueError("module identity mismatch")
            records.append({**record, "path": str(path), "signature_status": signature_status})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            invalid.append({"path": str(path), "message": str(exc)})
    matching = [
        record
        for record in records
        if str((record.get("module") or {}).get("fingerprint") or "") == fingerprint
    ]
    return {
        "root": str(evidence_root),
        "fingerprint": fingerprint,
        "records": records,
        "matching": matching,
        "stale": [record for record in records if record not in matching],
        "invalid": invalid,
    }


def _latest_by_kind(records: list[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for record in sorted(
        records,
        key=lambda item: (str(item.get("recorded_at") or ""), str(item.get("evidence_id") or "")),
    ):
        latest[str(record.get("kind") or "")] = record
    return latest


def _verified_lifecycle(records: list[Dict[str, Any]]) -> tuple[str, int]:
    lifecycle = "draft"
    verified_count = 0
    for record in sorted(
        records,
        key=lambda item: (str(item.get("recorded_at") or ""), str(item.get("evidence_id") or "")),
    ):
        if record.get("kind") == "publish":
            report = record.get("report") if isinstance(record.get("report"), dict) else {}
            if (
                report.get("ok")
                and report.get("decision") == "allow"
                and str(report.get("from_lifecycle") or "") == lifecycle == "approved"
                and str(report.get("to_lifecycle") or "") == "published"
                and record.get("signature_status") == "valid"
            ):
                lifecycle = "published"
                verified_count += 1
            continue
        if record.get("kind") == "deprecate":
            report = record.get("report") if isinstance(record.get("report"), dict) else {}
            if (
                report.get("ok")
                and report.get("decision") == "allow"
                and str(report.get("from_lifecycle") or "") == lifecycle == "published"
                and str(report.get("to_lifecycle") or "") == "deprecated"
                and record.get("signature_status") == "valid"
            ):
                lifecycle = "deprecated"
                verified_count += 1
            continue
        if record.get("kind") != "transition":
            continue
        report = record.get("report") if isinstance(record.get("report"), dict) else {}
        if not report.get("ok"):
            continue
        if (
            str(report.get("to_lifecycle") or "") == "draft"
            and str(report.get("from_lifecycle") or "") in _DRAFT_RESET_SOURCES
            and str(report.get("actor") or "").strip()
            and str(report.get("reason") or "").strip()
        ):
            lifecycle = "draft"
            verified_count += 1
            continue
        if (
            str(report.get("from_lifecycle") or "") == lifecycle
            and str(report.get("to_lifecycle") or "") == _NEXT_LIFECYCLE.get(lifecycle)
            and str(report.get("actor") or "").strip()
            and str(report.get("reason") or "").strip()
        ):
            lifecycle = str(report["to_lifecycle"])
            verified_count += 1
    return lifecycle, verified_count


def assess_module_readiness(
    package: ModulePackage,
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    module_id, module_version = _module_identity(package)
    try:
        manifest = package.load_manifest()
    except Exception:  # noqa: BLE001
        manifest = {}
    evidence = load_module_evidence(package, evidence_root=evidence_root, signing_key=signing_key)
    latest = _latest_by_kind(evidence["matching"])
    diagnostics = []
    current_validation = validate_module_package(package)
    diagnostics.extend(current_validation["diagnostics"])
    checks: Dict[str, Any] = {}
    for kind in REQUIRED_EVIDENCE_KINDS:
        record = latest.get(kind)
        passed = bool(record and isinstance(record.get("report"), dict) and record["report"].get("ok"))
        checks[kind] = {
            "passed": passed,
            "evidence_id": record.get("evidence_id") if record else None,
            "recorded_at": record.get("recorded_at") if record else None,
            "path": record.get("path") if record else None,
            "record_sha256": record.get("record_sha256") if record else None,
            "signature_status": record.get("signature_status") if record else None,
        }
        if record is None:
            diagnostics.append(
                {
                    "code": f"evidence.{kind}_missing",
                    "path": f"$.checks.{kind}",
                    "message": f"matching {kind} evidence is required",
                }
            )
        elif not passed:
            diagnostics.append(
                {
                    "code": f"evidence.{kind}_failed",
                    "path": f"$.checks.{kind}",
                    "message": f"latest matching {kind} evidence did not pass",
                }
            )
    for item in evidence["invalid"]:
        diagnostics.append(
            {
                "code": "evidence.integrity_invalid",
                "path": item["path"],
                "message": item["message"],
            }
        )

    approval_ready = not diagnostics
    publication_blockers = []
    lifecycle = str(manifest.get("lifecycle") or "")
    verified_lifecycle, verified_transition_count = _verified_lifecycle(evidence["matching"])
    lifecycle_verified = lifecycle == verified_lifecycle
    if not lifecycle_verified:
        diagnostics.append(
            {
                "code": "lifecycle.unverified_state",
                "path": "$.lifecycle",
                "message": (
                    f"manifest lifecycle '{lifecycle}' does not match evidence-backed lifecycle "
                    f"'{verified_lifecycle}'"
                ),
            }
        )
        approval_ready = False
    if lifecycle not in {"approved", "published"}:
        publication_blockers.append(
            {
                "code": "lifecycle.approval_required",
                "path": "$.lifecycle",
                "message": "module lifecycle must be 'approved' before publication",
            }
        )
    sandbox_record = latest.get("sandbox") or {}
    sandbox_report = sandbox_record.get("report") if isinstance(sandbox_record.get("report"), dict) else {}
    sandbox_evidence = sandbox_report.get("evidence") if isinstance(sandbox_report.get("evidence"), dict) else {}
    runtime = sandbox_evidence.get("runtime") if isinstance(sandbox_evidence.get("runtime"), dict) else {}
    limits = sandbox_evidence.get("limits") if isinstance(sandbox_evidence.get("limits"), dict) else {}
    capability_report = (
        sandbox_evidence.get("capability_report")
        if isinstance(sandbox_evidence.get("capability_report"), dict)
        else {}
    )
    secret_report = (
        sandbox_evidence.get("secret_report")
        if isinstance(sandbox_evidence.get("secret_report"), dict)
        else {}
    )
    dependency_report = (
        sandbox_evidence.get("dependency_report")
        if isinstance(sandbox_evidence.get("dependency_report"), dict)
        else {}
    )
    if sandbox_record.get("signature_status") != "valid":
        publication_blockers.append(
            {
                "code": "evidence.sandbox_signature_required",
                "path": "$.checks.sandbox.signature_status",
                "message": "publication requires sandbox evidence signed by the configured evidence authority",
            }
        )
    if runtime.get("adapter") != "docker":
        publication_blockers.append(
            {
                "code": "sandbox.hardened_adapter_required",
                "path": "$.checks.sandbox.runtime.adapter",
                "message": "publication requires evidence from the Docker hardened runtime adapter",
            }
        )
    for name in ("network", "filesystem"):
        if not bool(limits.get(f"{name}_enforced")):
            publication_blockers.append(
                {
                    "code": f"sandbox.{name}_isolation_missing",
                    "path": f"$.checks.sandbox.limits.{name}_enforced",
                    "message": f"hardened {name} isolation evidence is required before publication",
                }
            )
    for field, (code, label) in _HARDENED_SANDBOX_LIMITS.items():
        if not bool(limits.get(field)):
            publication_blockers.append(
                {
                    "code": code,
                    "path": f"$.checks.sandbox.limits.{field}",
                    "message": f"hardened {label} evidence is required before publication",
                }
            )
    if capability_report.get("enforcement") != "python_audit_hook":
        publication_blockers.append(
            {
                "code": "sandbox.capability_observation_missing",
                "path": "$.checks.sandbox.capability_report.enforcement",
                "message": "publication requires operation-level capability observation evidence",
            }
        )
    capability_violation_count = capability_report.get("violation_count")
    if (
        capability_report.get("enforcement") == "python_audit_hook"
        and (
            not isinstance(capability_violation_count, int)
            or isinstance(capability_violation_count, bool)
            or capability_violation_count < 0
        )
    ):
        publication_blockers.append(
            {
                "code": "sandbox.capability_observation_invalid",
                "path": "$.checks.sandbox.capability_report.violation_count",
                "message": "publication requires a valid capability violation count",
            }
        )
    elif isinstance(capability_violation_count, int) and capability_violation_count > 0:
        publication_blockers.append(
            {
                "code": "sandbox.capability_violations_detected",
                "path": "$.checks.sandbox.capability_report.violation_count",
                "message": "publication rejects sandbox evidence containing capability violations",
            }
        )
    security = manifest.get("security") if isinstance(manifest.get("security"), dict) else {}
    secret_refs = security.get("secret_refs")
    declared_secret_refs = list(secret_refs) if isinstance(secret_refs, list) else []
    expected_secret_policy = not declared_secret_refs
    if secret_report.get("enforcement") != "no_secret_forwarding":
        publication_blockers.append(
            {
                "code": "sandbox.secret_policy_missing",
                "path": "$.checks.sandbox.secret_report.enforcement",
                "message": "publication requires no-secret-forwarding evidence",
            }
        )
    elif (
        secret_report.get("declared_refs") != declared_secret_refs
        or secret_report.get("forwarded_refs") != []
        or secret_report.get("broker") != "unavailable"
        or secret_report.get("policy_satisfied") is not expected_secret_policy
    ):
        publication_blockers.append(
            {
                "code": "sandbox.secret_policy_invalid",
                "path": "$.checks.sandbox.secret_report",
                "message": "sandbox secret policy evidence does not match the module contract",
            }
        )
    if declared_secret_refs:
        publication_blockers.append(
            {
                "code": "sandbox.secret_broker_required",
                "path": "$.security.secret_refs",
                "message": "publication blocks secret-dependent modules until a verified secret broker is available",
            }
        )
    dependencies = manifest.get("dependencies") if isinstance(manifest.get("dependencies"), dict) else {}
    python_dependencies = dependencies.get("python")
    declared_python = list(python_dependencies) if isinstance(python_dependencies, list) else []
    expected_dependency_policy = not declared_python
    if dependency_report.get("enforcement") != "static_import_allowlist":
        publication_blockers.append(
            {
                "code": "sandbox.dependency_policy_missing",
                "path": "$.checks.sandbox.dependency_report.enforcement",
                "message": "publication requires dependency policy evidence",
            }
        )
    elif (
        dependency_report.get("declared_python") != declared_python
        or dependency_report.get("installed_bundle") != []
        or dependency_report.get("installer") != "disabled"
        or dependency_report.get("policy_satisfied") is not expected_dependency_policy
    ):
        publication_blockers.append(
            {
                "code": "sandbox.dependency_policy_invalid",
                "path": "$.checks.sandbox.dependency_report",
                "message": "sandbox dependency policy evidence does not match the module contract",
            }
        )
    if declared_python:
        publication_blockers.append(
            {
                "code": "sandbox.dependency_bundle_required",
                "path": "$.dependencies.python",
                "message": "publication blocks external Python dependencies until a verified bundle is available",
            }
        )
    if not approval_ready:
        publication_blockers.extend(diagnostics)

    recommended_lifecycle = lifecycle
    if lifecycle_verified:
        for candidate in ("validated", "tested", "sandboxed", "approved"):
            requirements = _TRANSITION_REQUIREMENTS[candidate]
            if _NEXT_LIFECYCLE.get(lifecycle) == candidate and all(checks[kind]["passed"] for kind in requirements):
                recommended_lifecycle = candidate
                break

    return {
        "ok": approval_ready,
        "module_id": module_id,
        "module_version": module_version,
        "lifecycle": lifecycle,
        "lifecycle_verified": lifecycle_verified,
        "evidence_backed_lifecycle": verified_lifecycle,
        "fingerprint": evidence["fingerprint"],
        "approval_ready": approval_ready,
        "recommended_lifecycle": recommended_lifecycle,
        "checks": checks,
        "diagnostics": diagnostics,
        "warnings": [
            {
                "code": "evidence.stale_records",
                "path": "$.evidence.stale",
                "message": f"{len(evidence['stale'])} evidence record(s) belong to an older package fingerprint",
            }
        ]
        if evidence["stale"]
        else [],
        "publication": {
            "ready": not publication_blockers,
            "blockers": publication_blockers,
        },
        "evidence": {
            "root": evidence["root"],
            "matching_count": len(evidence["matching"]),
            "stale_count": len(evidence["stale"]),
            "invalid_count": len(evidence["invalid"]),
            "transition_count": sum(1 for record in evidence["matching"] if record.get("kind") == "transition"),
            "verified_transition_count": verified_transition_count,
            "signed_count": sum(1 for record in evidence["matching"] if record.get("signature_status") == "valid"),
        },
    }


def qualify_module_package(
    package: ModulePackage,
    *,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: Optional[float] = None,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    sandbox_runtime: str = "subprocess",
    sandbox_image: Optional[str] = None,
    docker_executable: str = "docker",
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    reports = {
        "validation": validate_module_package(package),
        "test": run_module_package_tests(package),
        "sandbox": sandbox_module_package(
            package,
            inputs=inputs,
            timeout_seconds=timeout_seconds,
            runtime=sandbox_runtime,
            image=sandbox_image,
            docker_executable=docker_executable,
        ),
    }
    records = [
        record_module_evidence(
            package,
            kind=kind,
            report=report,
            evidence_root=evidence_root,
            signing_key=signing_key,
        )
        for kind, report in reports.items()
    ]
    assessment = assess_module_readiness(package, evidence_root=evidence_root, signing_key=signing_key)
    return {
        **assessment,
        "qualification_records": [
            {
                "evidence_id": record["evidence_id"],
                "kind": record["kind"],
                "path": record["path"],
                "report_sha256": record["report_sha256"],
                "record_sha256": record["record_sha256"],
            }
            for record in records
        ],
    }


def transition_module_lifecycle(
    package: ModulePackage,
    *,
    target: str,
    actor: str,
    reason: str,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = package.load_manifest()
    module_id, module_version = _module_identity(package)
    current = str(manifest.get("lifecycle") or "")
    target = target.strip().lower()
    actor = actor.strip()
    reason = reason.strip()
    diagnostics = []
    if not actor:
        diagnostics.append(
            {"code": "lifecycle.actor_required", "path": "$.actor", "message": "transition actor is required"}
        )
    if not reason:
        diagnostics.append(
            {"code": "lifecycle.reason_required", "path": "$.reason", "message": "transition reason is required"}
        )
    if target == "published":
        diagnostics.append(
            {
                "code": "lifecycle.publish_command_required",
                "path": "$.target",
                "message": "publication requires the dedicated publish gate",
            }
        )
    elif target == "deprecated":
        diagnostics.append(
            {
                "code": "lifecycle.deprecate_command_required",
                "path": "$.target",
                "message": "deprecation requires the dedicated deprecate gate",
            }
        )
    elif target == "draft":
        if current not in _DRAFT_RESET_SOURCES:
            diagnostics.append(
                {
                    "code": "lifecycle.invalid_transition",
                    "path": "$.target",
                    "message": f"cannot reset module from '{current}' to 'draft'",
                }
            )
    elif _NEXT_LIFECYCLE.get(current) != target:
        diagnostics.append(
            {
                "code": "lifecycle.invalid_transition",
                "path": "$.target",
                "message": f"cannot transition module from '{current}' to '{target}'",
            }
        )

    assessment = assess_module_readiness(package, evidence_root=evidence_root, signing_key=signing_key)
    if target != "draft" and not assessment["lifecycle_verified"]:
        diagnostics.append(
            {
                "code": "lifecycle.unverified_state",
                "path": "$.lifecycle",
                "message": "current lifecycle is not backed by an ordered transition evidence chain",
            }
        )
    for kind in _TRANSITION_REQUIREMENTS.get(target, ()):
        check = assessment["checks"][kind]
        if not check["passed"]:
            diagnostics.append(
                {
                    "code": f"lifecycle.{kind}_evidence_required",
                    "path": f"$.checks.{kind}",
                    "message": f"passing matching {kind} evidence is required for '{target}'",
                }
            )

    report = {
        "ok": not diagnostics,
        "status": "succeeded" if not diagnostics else "failed",
        "module_id": module_id,
        "module_version": module_version,
        "from_lifecycle": current,
        "to_lifecycle": target,
        "actor": actor,
        "reason": reason,
        "diagnostics": diagnostics,
        "evidence_refs": {
            kind: {
                "evidence_id": check["evidence_id"],
                "record_sha256": check["record_sha256"],
                "signature_status": check["signature_status"],
            }
            for kind, check in assessment["checks"].items()
        },
    }
    if not diagnostics:
        manifest["lifecycle"] = target
        package.manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    record = record_module_evidence(
        package,
        kind="transition",
        report=report,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    readiness = assess_module_readiness(package, evidence_root=evidence_root, signing_key=signing_key)
    return {
        **report,
        "lifecycle": str(package.load_manifest().get("lifecycle") or ""),
        "transition_evidence": {
            "evidence_id": record["evidence_id"],
            "path": record["path"],
            "report_sha256": record["report_sha256"],
            "record_sha256": record["record_sha256"],
        },
        "readiness": readiness,
    }
