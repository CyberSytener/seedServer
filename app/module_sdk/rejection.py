from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.module_sdk.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    REQUIRED_EVIDENCE_KINDS,
    assess_module_readiness,
    load_module_evidence,
    record_module_evidence,
)
from app.module_sdk.package import ModulePackage
from app.module_sdk.rejection_history import (
    record_rejected_module_candidate,
    resolve_rejection_history_root,
)


def reject_module_package(
    package: ModulePackage,
    *,
    actor: str,
    reason: str,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    rejections_root: Optional[Path] = None,
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
    evidence = load_module_evidence(
        package,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    qualification_reports = {}
    for record in sorted(
        evidence["matching"],
        key=lambda item: (str(item.get("recorded_at") or ""), str(item.get("evidence_id") or "")),
    ):
        kind = str(record.get("kind") or "")
        if kind in REQUIRED_EVIDENCE_KINDS:
            qualification_reports[kind] = {
                "evidence_id": record.get("evidence_id"),
                "record_sha256": record.get("record_sha256"),
                "signature_status": record.get("signature_status"),
                "report": record.get("report"),
            }
    blockers = []
    if not actor:
        blockers.append(
            {"code": "reject.actor_required", "path": "$.actor", "message": "rejection actor is required"}
        )
    if not reason:
        blockers.append(
            {"code": "reject.reason_required", "path": "$.reason", "message": "rejection reason is required"}
        )
    if signing_key is None:
        blockers.append(
            {
                "code": "reject.signing_key_required",
                "path": "$.signature",
                "message": "rejection decisions require SEED_MODULE_EVIDENCE_SIGNING_KEY",
            }
        )
    elif usable_signing_key is None:
        blockers.append(
            {
                "code": "reject.signing_key_invalid",
                "path": "$.signature",
                "message": "rejection signing key must contain at least 32 UTF-8 bytes",
            }
        )
    if (
        readiness["lifecycle"] in {"published", "deprecated"}
        or readiness["evidence_backed_lifecycle"] in {"published", "deprecated"}
    ):
        blockers.append(
            {
                "code": "reject.unpublished_candidate_required",
                "path": "$.lifecycle",
                "message": "published releases must use the deprecation gate instead of candidate rejection",
            }
        )

    report = {
        "ok": not blockers,
        "status": "succeeded" if not blockers else "failed",
        "decision": "reject" if not blockers else "block",
        "module_id": readiness["module_id"],
        "module_version": readiness["module_version"],
        "fingerprint": readiness["fingerprint"],
        "lifecycle": readiness["lifecycle"],
        "actor": actor,
        "reason": reason,
        "diagnostics": blockers,
    }
    decision_record = record_module_evidence(
        package,
        kind="reject",
        report=report,
        evidence_root=evidence_root,
        signing_key=usable_signing_key,
    )
    rejection_snapshot = None
    resolved_rejections_root = resolve_rejection_history_root(
        evidence_root=evidence_root,
        rejections_root=rejections_root,
    )
    if report["ok"] and usable_signing_key is not None:
        rejection_snapshot = record_rejected_module_candidate(
            package,
            decision={
                "actor": actor,
                "reason": reason,
                "lifecycle": readiness["lifecycle"],
                "rejection_evidence": {
                    "evidence_id": decision_record["evidence_id"],
                    "record_sha256": decision_record["record_sha256"],
                },
            },
            repair_context={
                "recommended_lifecycle": readiness["recommended_lifecycle"],
                "approval_ready": readiness["approval_ready"],
                "diagnostics": readiness["diagnostics"],
                "warnings": readiness["warnings"],
                "publication_blockers": readiness["publication"]["blockers"],
                "checks": readiness["checks"],
                "qualification_reports": qualification_reports,
            },
            rejections_root=resolved_rejections_root,
            signing_key=usable_signing_key,
        )
    return {
        **report,
        "rejection_evidence": {
            "evidence_id": decision_record["evidence_id"],
            "path": decision_record["path"],
            "record_sha256": decision_record["record_sha256"],
            "signature": decision_record.get("signature"),
        },
        "rejection_snapshot": rejection_snapshot,
        "repair_context": rejection_snapshot.get("repair_context") if rejection_snapshot else None,
    }
