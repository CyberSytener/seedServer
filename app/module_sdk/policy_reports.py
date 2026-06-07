from __future__ import annotations

from typing import Any, Dict


def build_secret_report(manifest: Dict[str, Any]) -> Dict[str, Any]:
    security = manifest.get("security") if isinstance(manifest.get("security"), dict) else {}
    raw_refs = security.get("secret_refs")
    declared_refs = [str(item) for item in raw_refs] if isinstance(raw_refs, list) else []
    return {
        "enforcement": "no_secret_forwarding",
        "declared_refs": declared_refs,
        "forwarded_refs": [],
        "broker": "unavailable",
        "policy_satisfied": not declared_refs,
    }


def build_dependency_report(manifest: Dict[str, Any]) -> Dict[str, Any]:
    dependencies = manifest.get("dependencies") if isinstance(manifest.get("dependencies"), dict) else {}
    raw_python = dependencies.get("python")
    declared_python = [str(item) for item in raw_python] if isinstance(raw_python, list) else []
    return {
        "enforcement": "static_import_allowlist",
        "declared_python": declared_python,
        "installed_bundle": [],
        "installer": "disabled",
        "policy_satisfied": not declared_python,
    }


def build_policy_reports(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "secret_report": build_secret_report(manifest),
        "dependency_report": build_dependency_report(manifest),
    }
