from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.contracts.module_contract import SEMVER_PATTERN
from app.module_sdk.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    assess_module_readiness,
    record_module_evidence,
)
from app.module_sdk.package import ModulePackage
from app.module_sdk.version_history import (
    load_module_version_history,
    record_module_deprecation,
    resolve_version_history_root,
)


def deprecate_module_package(
    package: ModulePackage,
    *,
    actor: str,
    reason: str,
    replacement_version: Optional[str] = None,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    versions_root: Optional[Path] = None,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
    replacement_version = replacement_version.strip() if replacement_version else None
    usable_signing_key = (
        signing_key
        if signing_key is not None and len(signing_key.encode("utf-8")) >= 32
        else None
    )
    readiness = assess_module_readiness(
        package,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    resolved_versions_root = resolve_version_history_root(
        evidence_root=evidence_root,
        versions_root=versions_root,
    )
    history = load_module_version_history(
        readiness["module_id"],
        versions_root=resolved_versions_root,
        signing_key=usable_signing_key,
    )
    versions = [
        version
        for version in history["versions"]
        if str((version.get("module") or {}).get("module_version") or "") == readiness["module_version"]
        and str((version.get("module") or {}).get("fingerprint") or "") == readiness["fingerprint"]
    ]
    version_record = versions[0] if versions else None
    blockers = []
    if not actor:
        blockers.append(
            {"code": "deprecate.actor_required", "path": "$.actor", "message": "deprecation actor is required"}
        )
    if not reason:
        blockers.append(
            {"code": "deprecate.reason_required", "path": "$.reason", "message": "deprecation reason is required"}
        )
    if signing_key is None:
        blockers.append(
            {
                "code": "deprecate.signing_key_required",
                "path": "$.signature",
                "message": "deprecation decisions require SEED_MODULE_EVIDENCE_SIGNING_KEY",
            }
        )
    elif usable_signing_key is None:
        blockers.append(
            {
                "code": "deprecate.signing_key_invalid",
                "path": "$.signature",
                "message": "deprecation signing key must contain at least 32 UTF-8 bytes",
            }
        )
    if readiness["lifecycle"] != "published" or not readiness["lifecycle_verified"]:
        blockers.append(
            {
                "code": "deprecate.published_lifecycle_required",
                "path": "$.lifecycle",
                "message": "deprecate command requires an evidence-backed 'published' lifecycle",
            }
        )
    if history["invalid"]:
        blockers.extend(
            {
                "code": "deprecate.version_history_invalid",
                "path": item["path"],
                "message": f"published version history is invalid: {item['message']}",
            }
            for item in history["invalid"]
        )
    if version_record is None:
        blockers.append(
            {
                "code": "deprecate.version_snapshot_required",
                "path": "$.version",
                "message": "deprecation requires the matching immutable published version snapshot",
            }
        )
    elif version_record.get("signature_status") != "valid":
        blockers.append(
            {
                "code": "deprecate.version_signature_required",
                "path": "$.version.signature",
                "message": "deprecation requires a version snapshot signed by the configured authority",
            }
        )
    elif version_record.get("latest_deprecation") is not None:
        blockers.append(
            {
                "code": "deprecate.already_deprecated",
                "path": "$.version.lifecycle",
                "message": "module version already has a deprecation record",
            }
        )
    if replacement_version == readiness["module_version"]:
        blockers.append(
            {
                "code": "deprecate.replacement_version_invalid",
                "path": "$.replacement_version",
                "message": "replacement version must differ from the deprecated version",
            }
        )
    elif replacement_version and re.fullmatch(SEMVER_PATTERN, replacement_version) is None:
        blockers.append(
            {
                "code": "deprecate.replacement_version_invalid",
                "path": "$.replacement_version",
                "message": "replacement version must be a valid semantic version",
            }
        )

    decision = "allow" if not blockers else "block"
    report = {
        "ok": decision == "allow",
        "status": "succeeded" if decision == "allow" else "failed",
        "decision": decision,
        "module_id": readiness["module_id"],
        "module_version": readiness["module_version"],
        "fingerprint": readiness["fingerprint"],
        "from_lifecycle": readiness["lifecycle"],
        "to_lifecycle": "deprecated",
        "actor": actor,
        "reason": reason,
        "replacement_version": replacement_version,
        "diagnostics": blockers,
        "version_ref": {
            "version_id": version_record.get("version_id"),
            "record_sha256": version_record.get("record_sha256"),
            "signature_status": version_record.get("signature_status"),
        }
        if version_record
        else None,
    }
    decision_record = record_module_evidence(
        package,
        kind="deprecate",
        report=report,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    deprecation_record = None
    if report["ok"] and usable_signing_key is not None and version_record is not None:
        deprecation_record = record_module_deprecation(
            version_record,
            actor=actor,
            reason=reason,
            replacement_version=replacement_version,
            deprecation_evidence={
                "evidence_id": decision_record["evidence_id"],
                "record_sha256": decision_record["record_sha256"],
            },
            signing_key=usable_signing_key,
        )
        manifest = package.load_manifest()
        manifest["lifecycle"] = "deprecated"
        package.manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    status = assess_module_readiness(
        package,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    return {
        **report,
        "lifecycle": str(package.load_manifest().get("lifecycle") or ""),
        "deprecation_evidence": {
            "evidence_id": decision_record["evidence_id"],
            "path": decision_record["path"],
            "record_sha256": decision_record["record_sha256"],
            "signature": decision_record.get("signature"),
        },
        "deprecation_record": deprecation_record,
        "readiness": status,
    }
