from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.settings import get_settings


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _allowed_capabilities() -> List[str]:
    raw = os.getenv("SEED_DYNAMIC_BLOCK_ALLOWED_CAPABILITIES", "compute")
    capabilities = [item.strip().lower() for item in raw.replace(";", ",").split(",") if item.strip()]
    if not capabilities:
        capabilities = ["compute"]
    return sorted(set(capabilities))


def _dry_run_passed(dry_run_result: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(dry_run_result, dict):
        return False
    return str(dry_run_result.get("status") or "").lower() == "succeeded"


def _simulation_passed(simulation_result: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(simulation_result, dict):
        return False
    if isinstance(simulation_result.get("passed"), bool):
        return bool(simulation_result.get("passed"))
    status = str(simulation_result.get("status") or "").lower()
    return status in {"passed", "succeeded"}


def _capability_scan_check(capability_scan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    allowed = _allowed_capabilities()
    if not isinstance(capability_scan, dict):
        return {
            "required_capabilities": [],
            "disallowed_capabilities": [],
            "violations": ["capability_scan_missing"],
            "allowed_capabilities": allowed,
            "passed": False,
        }

    required_caps = [
        str(item).strip().lower()
        for item in (capability_scan.get("required_capabilities") or [])
        if str(item).strip()
    ]
    violations = [
        str(item).strip()
        for item in (capability_scan.get("violations") or [])
        if str(item).strip()
    ]
    disallowed = [cap for cap in required_caps if cap not in allowed]
    passed = len(violations) == 0 and len(disallowed) == 0
    return {
        "required_capabilities": sorted(set(required_caps)),
        "disallowed_capabilities": sorted(set(disallowed)),
        "violations": violations,
        "allowed_capabilities": allowed,
        "passed": passed,
    }


def evaluate_publish_gate(
    *,
    dry_run_result: Optional[Dict[str, Any]],
    capability_scan: Optional[Dict[str, Any]],
    simulation_result: Optional[Dict[str, Any]],
    approval_token: Optional[str],
) -> Dict[str, Any]:
    settings = get_settings()
    is_production = settings.is_production

    require_dry_run = _get_bool_env("SEED_DYNAMIC_BLOCK_REQUIRE_DRY_RUN", True)
    require_simulation = _get_bool_env("SEED_DYNAMIC_BLOCK_REQUIRE_SIMULATION", is_production)
    require_approval = _get_bool_env("SEED_DYNAMIC_BLOCK_REQUIRE_APPROVAL", is_production)
    registration_enabled = _get_bool_env("SEED_DYNAMIC_BLOCK_ENABLE_REGISTRATION", True)

    dry_run_ok = _dry_run_passed(dry_run_result)
    sim_ok = _simulation_passed(simulation_result)
    approval_ok = bool(str(approval_token or "").strip())
    capability = _capability_scan_check(capability_scan)

    checks = {
        "dry_run": {
            "required": require_dry_run,
            "passed": dry_run_ok,
            "status": str((dry_run_result or {}).get("status") or "missing"),
        },
        "capability_scan": {
            "required": True,
            "passed": bool(capability["passed"]),
            "required_capabilities": capability["required_capabilities"],
            "disallowed_capabilities": capability["disallowed_capabilities"],
            "violations": capability["violations"],
            "allowed_capabilities": capability["allowed_capabilities"],
        },
        "simulation": {
            "required": require_simulation,
            "passed": sim_ok,
            "status": str((simulation_result or {}).get("status") or "missing"),
            "artifact_ref": (simulation_result or {}).get("artifact_ref"),
            "source": (simulation_result or {}).get("source"),
        },
        "approval": {
            "required": require_approval,
            "passed": approval_ok,
            "provided": approval_ok,
        },
    }

    required_failures = [
        check_name
        for check_name, payload in checks.items()
        if bool(payload.get("required")) and not bool(payload.get("passed"))
    ]

    if not registration_enabled:
        decision = "block"
        reason = "registration_disabled"
        can_register = False
    elif required_failures:
        decision = "block"
        reason = f"required_check_failed:{required_failures[0]}"
        can_register = False
    else:
        decision = "allow"
        reason = "all_required_checks_passed"
        can_register = True

    return {
        "environment": settings.environment,
        "is_production": is_production,
        "registration_enabled": registration_enabled,
        "checks": checks,
        "decision": decision,
        "reason": reason,
        "can_register": can_register,
    }


def record_publish_decision(
    *,
    block_name: str,
    actor_id: str,
    gate_report: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    audit_path = Path(
        os.getenv(
            "SEED_DYNAMIC_PUBLISH_AUDIT_LOG",
            ".seed_artifacts/dynamic_publish/audit.jsonl",
        )
    )
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "block_name": block_name,
        "actor_id": actor_id,
        "decision": gate_report.get("decision"),
        "reason": gate_report.get("reason"),
        "can_register": bool(gate_report.get("can_register")),
        "gate": gate_report,
        "extra": extra or {},
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(audit_path)
