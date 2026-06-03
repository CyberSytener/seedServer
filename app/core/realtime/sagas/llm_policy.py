from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

DEFAULT_PROMPT_REGISTRY: Dict[str, Dict[str, str]] = {
    "plan": {"version": "plan.v1"},
    "execute": {"version": "execute.v1"},
    "repair": {"version": "repair.v1"},
    "format": {"version": "format.v1"},
    "finalize": {"version": "finalize.v1"},
}

DEFAULT_RUBRIC_REGISTRY: Dict[str, Dict[str, str]] = {
    "semantic": {"version": "rubric.semantic.v1"},
    "json": {"version": "rubric.json.v1"},
}

_STEP_PROMPT_REF_DEFAULTS = {
    "plan": "plan",
    "execute": "execute",
    "repair_loop": "repair",
    "format": "format",
    "finalize": "finalize",
}

_STEP_RUBRIC_REF_DEFAULTS = {
    "validate": "json",
    "format": "json",
}


DEFAULT_LLM_ORCHESTRATION_POLICY: Dict[str, Any] = {
    "version": "v1",
    "pricing_version": "pricing.v1",
    "prompt_registry": DEFAULT_PROMPT_REGISTRY,
    "rubric_registry": DEFAULT_RUBRIC_REGISTRY,
    "quorum_caps": {
        "max_candidates": 5,
        "max_concurrency": 3,
        "per_candidate_timeout_seconds": 30,
    },
    "artifacts": {
        "enabled": True,
        "store_raw_responses": True,
        "raw_max_chars": 4096,
        "raw_hash_only": False,
    },
    "tool_security": {
        "enabled": True,
        "default_caps": ["llm.read", "llm.generate"],
        "deny_prompt_injection_markers": True,
    },
    "model_tiers": {
        "cheap": {"provider": "mock", "model": "fast-small", "unit_cost": 1},
        "balanced": {"provider": "mock", "model": "mid", "unit_cost": 3},
        "powerful": {"provider": "mock", "model": "pro", "unit_cost": 10},
    },
    "global_budgets": {
        "fast": {
            "max_total_tokens": 6000,
            "max_total_cost_units": 12,
            "max_wall_time_seconds": 25,
            "max_repairs": 1,
        },
        "best": {
            "max_total_tokens": 18000,
            "max_total_cost_units": 40,
            "max_wall_time_seconds": 90,
            "max_repairs": 2,
        },
    },
    "task_policies": {
        "default": {
            "default_mode": "fast",
            "steps": {
                "plan": {"tier": "cheap", "prompt_ref": "plan"},
                "execute": {"tier": "balanced", "prompt_ref": "execute"},
                "validate": {"tier": "cheap", "rubric_ref": "json"},
                "repair_loop": {"tier": "balanced", "prompt_ref": "repair"},
                "format": {"tier": "cheap", "prompt_ref": "format", "rubric_ref": "json"},
                "finalize": {"tier": "cheap", "prompt_ref": "finalize"},
            },
            "thresholds": {"pass_score": 85},
        },
        "high_stakes_text": {
            "default_mode": "best",
            "steps": {
                "plan": {"tier": "balanced"},
                "execute": {"tier": "powerful"},
                "validate": {"tier": "balanced"},
                "repair_loop": {"tier": "powerful"},
                "format": {"tier": "balanced"},
                "finalize": {"tier": "balanced"},
            },
            "quorum": {"enabled": True, "strategy": "dual_run_judge", "merge": "pick_best"},
            "thresholds": {"pass_score": 90},
            "max_repairs": 2,
        },
    },
}


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parent / "llm_orchestration_policy.yaml"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_version(value: Any, default: str) -> str:
    normalized = str(value or "").strip()
    return normalized or default


def _normalize_registry_entry(value: Any, *, default_version: str) -> Dict[str, str]:
    if isinstance(value, dict):
        version = _normalize_version(value.get("version"), default_version)
        sha256 = str(value.get("sha256") or "").strip()
    elif isinstance(value, str):
        version = _normalize_version(value, default_version)
        sha256 = ""
    else:
        version = default_version
        sha256 = ""

    result = {"version": version}
    if sha256:
        result["sha256"] = sha256
    return result


def _normalize_registry(raw: Any, defaults: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    source = raw if isinstance(raw, dict) else {}
    normalized: Dict[str, Dict[str, str]] = {}

    for key, default_entry in defaults.items():
        default_version = _normalize_version(default_entry.get("version"), f"{key}.v1")
        normalized[key] = _normalize_registry_entry(source.get(key), default_version=default_version)

    for key, value in source.items():
        key_norm = str(key).strip()
        if not key_norm:
            continue
        if key_norm in normalized:
            continue
        normalized[key_norm] = _normalize_registry_entry(value, default_version=f"{key_norm}.v1")

    return normalized


def _registry_fingerprint(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _build_base_policy_snapshot(
    *,
    policy_version: str,
    pricing_version: str,
    prompt_registry: Dict[str, Dict[str, str]],
    rubric_registry: Dict[str, Dict[str, str]],
    policy_source: str,
) -> Dict[str, Any]:
    snapshot = {
        "schema_version": "llm.policy.snapshot.v1",
        "policy_version": policy_version,
        "pricing_version": pricing_version,
        "policy_source": policy_source,
        "prompt_registry": prompt_registry,
        "rubric_registry": rubric_registry,
    }
    snapshot["fingerprint"] = _registry_fingerprint(snapshot)
    return snapshot


def build_policy_snapshot(
    policy: Dict[str, Any],
    *,
    mode: Optional[str] = None,
    task_type: Optional[str] = None,
    step_name: Optional[str] = None,
    step_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base = policy.get("policy_snapshot") if isinstance(policy.get("policy_snapshot"), dict) else {}
    prompt_registry = policy.get("prompt_registry") if isinstance(policy.get("prompt_registry"), dict) else {}
    rubric_registry = policy.get("rubric_registry") if isinstance(policy.get("rubric_registry"), dict) else {}
    step_cfg = step_policy if isinstance(step_policy, dict) else {}

    snapshot = dict(base) if base else {
        "schema_version": "llm.policy.snapshot.v1",
        "policy_version": _normalize_version(policy.get("policy_version"), "v1"),
        "pricing_version": _normalize_version(policy.get("pricing_version"), "pricing.v1"),
        "policy_source": _normalize_version(policy.get("policy_source"), str(_default_policy_path())),
        "prompt_registry": prompt_registry,
        "rubric_registry": rubric_registry,
    }

    if mode:
        snapshot["mode"] = mode
    if task_type:
        snapshot["task_type"] = task_type

    if step_name:
        snapshot["step"] = step_name
        prompt_ref = _normalize_version(
            step_cfg.get("prompt_ref"),
            _STEP_PROMPT_REF_DEFAULTS.get(step_name, ""),
        )
        rubric_ref = _normalize_version(
            step_cfg.get("rubric_ref"),
            _STEP_RUBRIC_REF_DEFAULTS.get(step_name, ""),
        )

        if prompt_ref:
            snapshot["step_prompt_ref"] = prompt_ref
            prompt_meta = prompt_registry.get(prompt_ref) if isinstance(prompt_registry.get(prompt_ref), dict) else {}
            if prompt_meta:
                snapshot["step_prompt_version"] = _normalize_version(prompt_meta.get("version"), f"{prompt_ref}.v1")
                if prompt_meta.get("sha256"):
                    snapshot["step_prompt_sha256"] = str(prompt_meta.get("sha256"))

        if rubric_ref:
            snapshot["step_rubric_ref"] = rubric_ref
            rubric_meta = rubric_registry.get(rubric_ref) if isinstance(rubric_registry.get(rubric_ref), dict) else {}
            if rubric_meta:
                snapshot["step_rubric_version"] = _normalize_version(rubric_meta.get("version"), f"{rubric_ref}.v1")
                if rubric_meta.get("sha256"):
                    snapshot["step_rubric_sha256"] = str(rubric_meta.get("sha256"))

    snapshot["fingerprint"] = _registry_fingerprint(
        {k: v for k, v in snapshot.items() if k != "fingerprint"}
    )
    return snapshot


@lru_cache(maxsize=8)
def load_llm_orchestration_policy(policy_path: Optional[str] = None) -> Dict[str, Any]:
    env_path = os.getenv("SEED_LLM_POLICY_PATH")
    target = Path(policy_path or env_path or _default_policy_path())
    policy = dict(DEFAULT_LLM_ORCHESTRATION_POLICY)

    if not target.exists():
        return policy

    raw = target.read_text(encoding="utf-8")
    parsed: Any
    if target.suffix.lower() in {".yaml", ".yml"}:
        parsed = yaml.safe_load(raw) or {}
    else:
        parsed = json.loads(raw)

    if not isinstance(parsed, dict):
        return policy
    return _deep_merge(policy, parsed)


def resolve_llm_policy(
    *,
    payload: Dict[str, Any],
    task_type: str,
    requested_mode: Optional[str] = None,
    policy_path: Optional[str] = None,
) -> Dict[str, Any]:
    policy = load_llm_orchestration_policy(policy_path=policy_path)
    registry = policy.get("registry") if isinstance(policy.get("registry"), dict) else {}

    policy_source = str(Path(policy_path or os.getenv("SEED_LLM_POLICY_PATH") or _default_policy_path()))
    policy_version = _normalize_version(
        registry.get("policy_version") if isinstance(registry, dict) else None,
        _normalize_version(policy.get("version"), "v1"),
    )
    pricing_version = _normalize_version(
        registry.get("pricing_version") if isinstance(registry, dict) else None,
        _normalize_version(policy.get("pricing_version"), "pricing.v1"),
    )
    prompt_registry = _normalize_registry(
        registry.get("prompt_registry") if isinstance(registry.get("prompt_registry"), dict) else policy.get("prompt_registry"),
        DEFAULT_PROMPT_REGISTRY,
    )
    rubric_registry = _normalize_registry(
        registry.get("rubric_registry") if isinstance(registry.get("rubric_registry"), dict) else policy.get("rubric_registry"),
        DEFAULT_RUBRIC_REGISTRY,
    )
    base_policy_snapshot = _build_base_policy_snapshot(
        policy_version=policy_version,
        pricing_version=pricing_version,
        prompt_registry=prompt_registry,
        rubric_registry=rubric_registry,
        policy_source=policy_source,
    )

    task_policies = policy.get("task_policies") if isinstance(policy.get("task_policies"), dict) else {}
    base_task_policy = task_policies.get("default") if isinstance(task_policies.get("default"), dict) else {}
    specific_task_policy = task_policies.get(task_type) if isinstance(task_policies.get(task_type), dict) else {}
    task_policy = _deep_merge(base_task_policy, specific_task_policy)

    preferred_mode = (requested_mode or str(payload.get("mode") or "")).strip().lower()
    if not preferred_mode:
        preferred_mode = str(task_policy.get("default_mode") or "fast").strip().lower()

    global_budgets = policy.get("global_budgets") if isinstance(policy.get("global_budgets"), dict) else {}
    mode_budget = global_budgets.get(preferred_mode) if isinstance(global_budgets.get(preferred_mode), dict) else {}
    task_budget = task_policy.get("budget") if isinstance(task_policy.get("budget"), dict) else {}
    payload_budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    resolved_budget = _deep_merge(_deep_merge(mode_budget, task_budget), payload_budget)

    resolved_max_repairs = payload.get("max_repairs")
    if resolved_max_repairs is None:
        resolved_max_repairs = task_policy.get("max_repairs", resolved_budget.get("max_repairs", 1))

    return {
        "policy_version": policy_version,
        "pricing_version": pricing_version,
        "mode": preferred_mode,
        "budget": resolved_budget,
        "max_repairs": int(resolved_max_repairs or 1),
        "steps": task_policy.get("steps") if isinstance(task_policy.get("steps"), dict) else {},
        "thresholds": task_policy.get("thresholds") if isinstance(task_policy.get("thresholds"), dict) else {},
        "quorum": task_policy.get("quorum") if isinstance(task_policy.get("quorum"), dict) else {"enabled": False},
        "quorum_caps": policy.get("quorum_caps") if isinstance(policy.get("quorum_caps"), dict) else {},
        "artifacts": _deep_merge(
            policy.get("artifacts") if isinstance(policy.get("artifacts"), dict) else {},
            task_policy.get("artifacts") if isinstance(task_policy.get("artifacts"), dict) else {},
        ),
        "tool_security": _deep_merge(
            policy.get("tool_security") if isinstance(policy.get("tool_security"), dict) else {},
            task_policy.get("tool_security") if isinstance(task_policy.get("tool_security"), dict) else {},
        ),
        "model_tiers": policy.get("model_tiers") if isinstance(policy.get("model_tiers"), dict) else {},
        "prompt_registry": prompt_registry,
        "rubric_registry": rubric_registry,
        "policy_source": policy_source,
        "policy_snapshot": base_policy_snapshot,
    }
