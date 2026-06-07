from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.module_sdk.evidence import (
    DEFAULT_EVIDENCE_ROOT,
    _module_identity,
    _sha256,
    assess_module_readiness,
    fingerprint_module_package,
    module_package_files,
    qualify_module_package,
    record_module_evidence,
)
from app.module_sdk.package import ModulePackage
from app.module_sdk.rejection_history import (
    MAX_REPAIR_ATTEMPTS,
    load_module_rejection_history,
    record_module_repair_attempt,
    resolve_rejection_history_root,
)


REPAIR_CONTEXT_SCHEMA_VERSION = "1.0"
DEFAULT_MAX_REPAIR_CONTEXT_BYTES = 131_072
MAX_MAX_REPAIR_CONTEXT_BYTES = 262_144
_CONTRACT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "module_contract_v1.schema.json"
_STABLE_SDK_SURFACE = (
    "ModuleExecutionContext",
    "ModuleSDKError",
)
_STANDARD_REPAIR_FILES = {"module.yaml", "handler.py", "README.md"}


def _usable_signing_key(signing_key: Optional[str]) -> str:
    if signing_key is None:
        raise ValueError("repair operations require SEED_MODULE_EVIDENCE_SIGNING_KEY")
    if len(signing_key.encode("utf-8")) < 32:
        raise ValueError("repair signing key must contain at least 32 UTF-8 bytes")
    return signing_key


def _select_rejection(
    module_id: str,
    *,
    rejection_id: Optional[str],
    rejections_root: Path,
    signing_key: str,
) -> Dict[str, Any]:
    history = load_module_rejection_history(
        module_id,
        rejections_root=rejections_root,
        signing_key=signing_key,
    )
    if history["invalid"]:
        raise ValueError("repair source history contains invalid rejection records")
    matches = [
        record
        for record in history["rejections"]
        if rejection_id is None or record.get("rejection_id") == rejection_id
    ]
    if not matches:
        raise FileNotFoundError(f"rejection not found for module {module_id}: {rejection_id or 'latest'}")
    selected = matches[-1]
    if selected.get("signature_status") != "valid":
        raise ValueError("repair source rejection must be signed by the configured authority")
    return selected


def _select_rejection_by_id(
    rejection_id: str,
    *,
    rejections_root: Path,
    signing_key: str,
) -> Dict[str, Any]:
    matches = [
        path
        for path in rejections_root.glob("*/*/*/*")
        if path.is_dir() and path.name == rejection_id
    ]
    if not matches:
        raise FileNotFoundError(f"rejection not found: {rejection_id}")
    if len(matches) > 1:
        raise ValueError(f"rejection ID is not unique: {rejection_id}")
    return _select_rejection(
        matches[0].parents[2].name,
        rejection_id=rejection_id,
        rejections_root=rejections_root,
        signing_key=signing_key,
    )


def _allowed_repair_files(rejection: Dict[str, Any]) -> list[str]:
    existing_files = {str(item["path"]) for item in rejection["files"]}
    return sorted(existing_files | _STANDARD_REPAIR_FILES)


def _expected_candidate_identity(rejection: Dict[str, Any]) -> tuple[str, str]:
    source = rejection["module"]
    attempts = rejection["repair_attempts"]
    first_candidate = attempts[0]["candidate"] if attempts else {}
    module_id = str(source["mode_id"])
    module_version = str(source["module_version"])
    if module_id == "unknown_module":
        module_id = str(first_candidate.get("mode_id") or module_id)
    if module_version == "unknown":
        module_version = str(first_candidate.get("module_version") or module_version)
    return module_id, module_version


def build_module_repair_plan(
    module_id: str,
    *,
    rejection_id: Optional[str] = None,
    rejections_root: Optional[Path] = None,
    signing_key: Optional[str] = None,
    max_context_bytes: int = DEFAULT_MAX_REPAIR_CONTEXT_BYTES,
) -> Dict[str, Any]:
    key = _usable_signing_key(signing_key)
    if not 4096 <= max_context_bytes <= MAX_MAX_REPAIR_CONTEXT_BYTES:
        raise ValueError(
            f"max repair context bytes must be between 4096 and {MAX_MAX_REPAIR_CONTEXT_BYTES}"
        )
    resolved_rejections_root = resolve_rejection_history_root(rejections_root=rejections_root)
    rejection = _select_rejection(
        module_id,
        rejection_id=rejection_id,
        rejections_root=resolved_rejections_root,
        signing_key=key,
    )
    files = []
    package_root = Path(rejection["package_path"])
    for item in rejection["files"]:
        relative = str(item["path"])
        try:
            content = (package_root / Path(relative)).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"repair context only supports UTF-8 text files: {relative}") from exc
        files.append({"path": relative, "content": content, "sha256": item["sha256"]})
    previous_attempts = [
        {
            "attempt": attempt["attempt"],
            "attempt_id": attempt["attempt_id"],
            "candidate": attempt["candidate"],
            "provenance": attempt["provenance"],
            "ok": bool((attempt.get("report") or {}).get("ok")),
            "diagnostics": (attempt.get("report") or {}).get("diagnostics") or [],
        }
        for attempt in rejection["repair_attempts"]
    ]
    existing_files = {str(item["path"]) for item in rejection["files"]}
    allowed_files = _allowed_repair_files(rejection)
    plan = {
        "ok": True,
        "diagnostics": [],
        "schema_version": REPAIR_CONTEXT_SCHEMA_VERSION,
        "module_id": rejection["module"]["mode_id"],
        "source_rejection": {
            "rejection_id": rejection["rejection_id"],
            "record_sha256": rejection["record_sha256"],
            "rejected_at": rejection["rejected_at"],
            "actor": rejection["decision"]["actor"],
            "reason": rejection["decision"]["reason"],
            "module": rejection["module"],
        },
        "budget": {
            "max_attempts": MAX_REPAIR_ATTEMPTS,
            "attempts_used": rejection["attempt_count"],
            "attempts_remaining": rejection["attempts_remaining"],
            "max_context_bytes": max_context_bytes,
        },
        "constraints": {
            "allowed_files": allowed_files,
            "creatable_files": sorted(_STANDARD_REPAIR_FILES - existing_files),
            "paths_outside_allowed_files": "forbidden",
            "allowed_sdk_import": "app.module_sdk",
            "stable_sdk_surface": list(_STABLE_SDK_SURFACE),
            "forbidden_lifecycle": ["published", "deprecated"],
            "publish_allowed": False,
        },
        "contract": {
            "schema_path": "app/contracts/module_contract_v1.schema.json",
            "schema": json.loads(_CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8")),
        },
        "candidate_files": files,
        "repair_context": rejection["repair_context"],
        "previous_attempts": previous_attempts,
        "expected_output": {
            "type": "object",
            "required": ["files", "summary"],
            "files": "complete replacement contents for allowed_files only",
            "summary": "short explanation of changes",
        },
    }
    plan["context_sha256"] = "sha256:" + ("0" * 64)
    context_bytes = 0
    while plan.get("context_bytes") != context_bytes:
        plan["context_bytes"] = context_bytes
        context_bytes = len(
            json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
    plan["context_bytes"] = context_bytes
    plan["context_sha256"] = _sha256(
        {key: value for key, value in plan.items() if key != "context_sha256"}
    )
    if context_bytes > max_context_bytes:
        raise ValueError(f"repair context exceeds byte budget: {context_bytes} > {max_context_bytes}")
    return plan


def check_module_repair(
    package: ModulePackage,
    *,
    rejection_id: str,
    actor: str,
    generator: str,
    inputs: Optional[Dict[str, Any]] = None,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    rejections_root: Optional[Path] = None,
    signing_key: Optional[str] = None,
    sandbox_runtime: str = "subprocess",
    sandbox_image: Optional[str] = None,
    docker_executable: str = "docker",
    timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    key = _usable_signing_key(signing_key)
    actor = actor.strip()
    generator = generator.strip()
    if not actor:
        raise ValueError("repair actor is required")
    if not generator:
        raise ValueError("repair generator is required")
    module_id, module_version = _module_identity(package)
    resolved_rejections_root = resolve_rejection_history_root(
        evidence_root=evidence_root,
        rejections_root=rejections_root,
    )
    rejection = _select_rejection_by_id(
        rejection_id,
        rejections_root=resolved_rejections_root,
        signing_key=key,
    )
    blockers = []
    source_module = rejection["module"]
    expected_module_id, expected_module_version = _expected_candidate_identity(rejection)
    fingerprint = fingerprint_module_package(package)
    candidate_paths = {relative for relative, _path in module_package_files(package)}
    allowed_paths = set(_allowed_repair_files(rejection))
    if rejection["attempts_remaining"] <= 0:
        blockers.append(
            {
                "code": "repair.attempt_budget_exhausted",
                "path": "$.budget.attempts_remaining",
                "message": f"repair attempt budget exhausted ({MAX_REPAIR_ATTEMPTS})",
            }
        )
    if any(
        bool((attempt.get("report") or {}).get("ok"))
        for attempt in rejection["repair_attempts"]
    ):
        blockers.append(
            {
                "code": "repair.already_succeeded",
                "path": "$.repair_attempts",
                "message": "the rejection already has a successful repair attempt",
            }
        )
    if (
        (expected_module_id != "unknown_module" and module_id != expected_module_id)
        or (
            expected_module_version != "unknown"
            and module_version != expected_module_version
        )
    ):
        blockers.append(
            {
                "code": "repair.identity_changed",
                "path": "$.candidate",
                "message": "repair candidate must preserve module ID and semantic version",
            }
        )
    unexpected_paths = sorted(candidate_paths - allowed_paths)
    if unexpected_paths:
        blockers.append(
            {
                "code": "repair.path_not_allowed",
                "path": "$.candidate.files",
                "message": f"repair candidate contains paths outside the plan: {unexpected_paths}",
            }
        )
    if fingerprint == source_module["fingerprint"]:
        blockers.append(
            {
                "code": "repair.candidate_unchanged",
                "path": "$.candidate.fingerprint",
                "message": "repair candidate must differ from the rejected fingerprint",
            }
        )
    if any(
        attempt.get("candidate", {}).get("fingerprint") == fingerprint
        for attempt in rejection["repair_attempts"]
    ):
        blockers.append(
            {
                "code": "repair.candidate_already_attempted",
                "path": "$.candidate.fingerprint",
                "message": "repair candidate fingerprint was already attempted",
            }
        )
    readiness = assess_module_readiness(package, evidence_root=evidence_root, signing_key=key)
    if (
        readiness["lifecycle"] in {"published", "deprecated"}
        or readiness["evidence_backed_lifecycle"] in {"published", "deprecated"}
    ):
        blockers.append(
            {
                "code": "repair.unpublished_candidate_required",
                "path": "$.lifecycle",
                "message": "repair check cannot operate on a published or deprecated release",
            }
        )
    if blockers:
        return {
            "ok": False,
            "status": "failed",
            "module_id": module_id,
            "module_version": module_version,
            "fingerprint": fingerprint,
            "source_rejection_id": rejection_id,
            "diagnostics": blockers,
            "repair_attempt": None,
        }

    qualification = qualify_module_package(
        package,
        inputs=inputs,
        timeout_seconds=timeout_seconds,
        evidence_root=evidence_root,
        sandbox_runtime=sandbox_runtime,
        sandbox_image=sandbox_image,
        docker_executable=docker_executable,
        signing_key=key,
    )
    source_codes = {
        str(item.get("code") or "")
        for item in rejection["repair_context"]["diagnostics"]
        if isinstance(item, dict)
    }
    current_codes = {
        str(item.get("code") or "")
        for item in qualification["diagnostics"]
        if isinstance(item, dict)
    }
    report = {
        "ok": bool(qualification["approval_ready"]),
        "status": "succeeded" if qualification["approval_ready"] else "failed",
        "module_id": module_id,
        "module_version": module_version,
        "fingerprint": qualification["fingerprint"],
        "source_rejection": {
            "rejection_id": rejection["rejection_id"],
            "record_sha256": rejection["record_sha256"],
            "fingerprint": source_module["fingerprint"],
        },
        "resolved_diagnostic_codes": sorted(source_codes - current_codes),
        "remaining_diagnostic_codes": sorted(source_codes & current_codes),
        "introduced_diagnostic_codes": sorted(current_codes - source_codes),
        "diagnostics": qualification["diagnostics"],
        "qualification": qualification,
    }
    repair_evidence = record_module_evidence(
        package,
        kind="repair",
        report=report,
        evidence_root=evidence_root,
        signing_key=key,
    )
    attempt = record_module_repair_attempt(
        rejection,
        package,
        provenance={
            "actor": actor,
            "generator": generator,
            "repair_evidence": {
                "evidence_id": repair_evidence["evidence_id"],
                "record_sha256": repair_evidence["record_sha256"],
            },
        },
        report=report,
        signing_key=key,
    )
    return {
        **report,
        "repair_evidence": {
            "evidence_id": repair_evidence["evidence_id"],
            "path": repair_evidence["path"],
            "record_sha256": repair_evidence["record_sha256"],
            "signature": repair_evidence.get("signature"),
        },
        "repair_attempt": attempt,
    }
