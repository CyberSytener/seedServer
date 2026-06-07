from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.module_sdk.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    assess_module_readiness,
    load_module_evidence,
    record_module_evidence,
)
from app.module_sdk.package import ModulePackage
from app.module_sdk.version_history import (
    assess_module_version_slot,
    record_published_module_version,
    resolve_version_history_root,
)


def publish_module_package(
    package: ModulePackage,
    *,
    actor: str,
    reason: str,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    versions_root: Optional[Path] = None,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    actor = actor.strip()
    reason = reason.strip()
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
    blockers = list(readiness["publication"]["blockers"])
    resolved_versions_root = resolve_version_history_root(
        evidence_root=evidence_root,
        versions_root=versions_root,
    )
    version_slot = assess_module_version_slot(
        package,
        versions_root=resolved_versions_root,
        signing_key=usable_signing_key,
    )
    blockers.extend(version_slot["blockers"])
    evidence = load_module_evidence(
        package,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    approvals = [
        record
        for record in evidence["matching"]
        if record.get("kind") == "transition"
        and isinstance(record.get("report"), dict)
        and record["report"].get("ok")
        and record["report"].get("to_lifecycle") == "approved"
    ]
    approvals.sort(
        key=lambda record: (
            str(record.get("recorded_at") or ""),
            str(record.get("evidence_id") or ""),
        )
    )
    approval = approvals[-1] if approvals else None
    approval_refs = (
        approval["report"].get("evidence_refs")
        if approval and isinstance(approval["report"].get("evidence_refs"), dict)
        else {}
    )
    if approval is None:
        blockers.append(
            {
                "code": "publish.approval_evidence_missing",
                "path": "$.approval",
                "message": "publish requires an evidence-backed approval transition",
            }
        )
    else:
        for kind, check in readiness["checks"].items():
            approved_ref = approval_refs.get(kind) if isinstance(approval_refs.get(kind), dict) else {}
            if approved_ref.get("record_sha256") != check["record_sha256"]:
                blockers.append(
                    {
                        "code": "publish.approval_evidence_stale",
                        "path": f"$.approval.evidence_refs.{kind}",
                        "message": f"approved {kind} evidence does not match the current publish candidate",
                    }
                )
    if not actor:
        blockers.append(
            {"code": "publish.actor_required", "path": "$.actor", "message": "publish actor is required"}
        )
    if not reason:
        blockers.append(
            {"code": "publish.reason_required", "path": "$.reason", "message": "publish reason is required"}
        )
    if signing_key is None:
        blockers.append(
            {
                "code": "publish.signing_key_required",
                "path": "$.signature",
                "message": "publish decisions require SEED_MODULE_EVIDENCE_SIGNING_KEY",
            }
        )
    elif usable_signing_key is None:
        blockers.append(
            {
                "code": "publish.signing_key_invalid",
                "path": "$.signature",
                "message": "publish signing key must contain at least 32 UTF-8 bytes",
            }
        )
    if readiness["lifecycle"] != "approved":
        blockers.append(
            {
                "code": "publish.approved_lifecycle_required",
                "path": "$.lifecycle",
                "message": "publish command requires an evidence-backed 'approved' lifecycle",
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
        "to_lifecycle": "published",
        "actor": actor,
        "reason": reason,
        "diagnostics": blockers,
        "evidence_refs": {
            kind: {
                "evidence_id": check["evidence_id"],
                "record_sha256": check["record_sha256"],
                "signature_status": check["signature_status"],
            }
            for kind, check in readiness["checks"].items()
        },
        "approval_ref": {
            "evidence_id": approval.get("evidence_id"),
            "record_sha256": approval.get("record_sha256"),
            "signature_status": approval.get("signature_status"),
        }
        if approval
        else None,
        "version_history": {
            "root": version_slot["root"],
            "existing_snapshot": version_slot["existing"] is not None,
        },
    }
    decision_record = record_module_evidence(
        package,
        kind="publish",
        report=report,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    version_snapshot = None
    if report["ok"] and usable_signing_key is not None:
        manifest = package.load_manifest()
        manifest["lifecycle"] = "published"
        package.manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        version_snapshot = record_published_module_version(
            package,
            publication={
                "actor": actor,
                "reason": reason,
                "publish_evidence": {
                    "evidence_id": decision_record["evidence_id"],
                    "record_sha256": decision_record["record_sha256"],
                },
                "evidence_refs": report["evidence_refs"],
                "approval_ref": report["approval_ref"],
            },
            versions_root=resolved_versions_root,
            signing_key=usable_signing_key,
        )
    status = assess_module_readiness(
        package,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    return {
        **report,
        "lifecycle": str(package.load_manifest().get("lifecycle") or ""),
        "publish_evidence": {
            "evidence_id": decision_record["evidence_id"],
            "path": decision_record["path"],
            "record_sha256": decision_record["record_sha256"],
            "signature": decision_record.get("signature"),
        },
        "version_snapshot": version_snapshot,
        "readiness": status,
    }
