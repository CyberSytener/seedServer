from __future__ import annotations
import logging

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.modes import RunControl, RunModeRequest, run_mode
from app.api.saga_blueprints import (
    _get_saga_db_from_request,
    _run_saga,
    _validate_blueprint,
)
from app.core.authz import (
    UnifiedAuthContext,
    audit_auth_event,
    require_any_scope,
    require_scope,
)
from app.core.blocks import build_default_registry
from app.core.realtime.sagas.artifact_store import ArtifactStore
from app.core.realtime.sagas.flows.dynamic_saga import ExecutionMode
from app.core.saga_blueprints import (
    BlueprintStatus,
    RunRecord,
    blueprint_store as default_blueprint_store,
    run_store as default_run_store,
)
from app.services.module_registry import ModuleRegistry
from app.services.flow_contract_validator import FlowContractValidator
from app.services.saga_architect import SagaArchitect
module_registry = ModuleRegistry()

_CONTEXT_ROOTS = {"payload", "request", "user_id", "persona", "scan_id"}
_TERMINAL_DONE_STATES = {"succeeded", "success", "completed", "done"}
_TERMINAL_FAILED_STATES = {"failed", "error", "compensated"}
_TERMINAL_STOPPED_STATES = {"stopped", "cancelled", "canceled", "archived"}
_DEFAULT_PROVIDER_PROFILE_ID = "default_real"
_DEFAULT_PROVIDER_PROFILES: Dict[str, Dict[str, Any]] = {
    "default_real": {
        "id": "default_real",
        "enabled": True,
        "allowed_models": [],
        "daily_budget_units": 500.0,
        "per_run_cap_units": 100.0,
        "timeout_caps": {"max_seconds": 120},
        "retry_caps": {"max_retries": 2},
        "redaction_policy": {"store_raw_response": False},
        "requires_scope": "providers:use:real",
    }
}


class ModuleValidateRequest(BaseModel):
    sample_input: Dict[str, Any] = Field(default_factory=dict)
    requested_capabilities: List[str] = Field(default_factory=list)


class ReleaseRequest(BaseModel):
    version: Optional[str] = None
    notes: Optional[str] = None


class RunTarget(BaseModel):
    type: Literal["module", "flow"]
    id: str


class RunCreateRequest(BaseModel):
    target: RunTarget
    mode: Literal["stub", "real"] = "stub"
    provider_profile: Optional[str] = None
    budget: Dict[str, Any] = Field(default_factory=dict)
    input: Dict[str, Any] = Field(default_factory=dict)
    control: Dict[str, Any] = Field(default_factory=dict)


class FlowCompileRequest(BaseModel):
    flow_id: Optional[str] = None
    version: Optional[str] = None
    graph: Dict[str, Any] = Field(default_factory=dict)
    blueprint: Dict[str, Any] = Field(default_factory=dict)
    entrypoint_schema: Dict[str, Any] = Field(default_factory=dict)
    assertions: Dict[str, Any] = Field(default_factory=dict)
    observability: Dict[str, Any] = Field(default_factory=dict)
    save: bool = True


class ProviderProfileUpsertRequest(BaseModel):
    enabled: Optional[bool] = None
    allowed_models: Optional[List[str]] = None
    daily_budget_units: Optional[float] = None
    per_run_cap_units: Optional[float] = None
    timeout_caps: Optional[Dict[str, Any]] = None
    retry_caps: Optional[Dict[str, Any]] = None
    redaction_policy: Optional[Dict[str, Any]] = None
    requires_scope: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _canonical_sha256(payload: Any) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _release_root() -> Path:
    root = Path(".seed_artifacts") / "console" / "releases"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_release_record(kind: str, target_id: str, payload: Dict[str, Any]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target_dir = _release_root() / kind / target_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _latest_release(kind: str, target_id: str) -> Optional[Dict[str, Any]]:
    target_dir = _release_root() / kind / target_id
    if not target_dir.exists():
        return None
    files = sorted(target_dir.glob("*.json"), reverse=True)
    for file in files:
        try:
            parsed = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                parsed.setdefault("artifact_path", str(file))
                return parsed
        except Exception:
            continue
    return None


def _status_from_release_and_flags(*, latest_release: Optional[Dict[str, Any]], deprecated: bool) -> str:
    if deprecated:
        return "deprecated"
    if latest_release:
        return "released"
    return "draft"


def _normalize_run_status(raw: str) -> str:
    state = str(raw or "").strip().lower()
    if state in _TERMINAL_DONE_STATES:
        return "done"
    if state in _TERMINAL_FAILED_STATES:
        return "failed"
    if state in _TERMINAL_STOPPED_STATES:
        return "stopped"
    if state in {"running", "started", "pending", "in_progress", "waiting_confirm", "created"}:
        return "running"
    if not state:
        return "running"
    return "running"


def _extract_artifact_refs(value: Any) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            uri = node.get("uri")
            if isinstance(uri, str) and uri.startswith("artifact://"):
                if uri not in seen:
                    seen.add(uri)
                    refs.append(
                        {
                            "uri": uri,
                            "sha256": node.get("sha256"),
                            "kind": node.get("kind"),
                            "step": node.get("step"),
                            "bytes": node.get("bytes"),
                            "created_at": node.get("created_at"),
                        }
                    )
            for item in node.values():
                walk(item)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return refs


def _build_timeline_from_saga_steps(steps: Any) -> List[Dict[str, Any]]:
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:
            steps = []
    if not isinstance(steps, list):
        return []

    timeline: List[Dict[str, Any]] = []
    for index, item in enumerate(steps):
        if not isinstance(item, dict):
            continue
        timeline.append(
            {
                "index": index,
                "node_id": item.get("name") or f"step_{index}",
                "module_id": item.get("adapter_type") or item.get("name"),
                "status": _normalize_run_status(str(item.get("status") or "")),
                "raw_status": item.get("status"),
                "started_at": item.get("started_at"),
                "ended_at": item.get("ended_at"),
                "elapsed_sec": item.get("elapsed_sec"),
                "error": item.get("error"),
                "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
            }
        )
    return timeline


def _build_timeline_from_trace(trace: Any) -> List[Dict[str, Any]]:
    if not isinstance(trace, list):
        return []
    timeline: List[Dict[str, Any]] = []
    for index, item in enumerate(trace):
        if not isinstance(item, dict):
            continue
        timeline.append(
            {
                "index": index,
                "node_id": item.get("step") or f"step_{index}",
                "module_id": item.get("block"),
                "status": _normalize_run_status(str(item.get("status") or "succeeded")),
                "raw_status": item.get("status"),
                "started_at": item.get("started_at"),
                "ended_at": item.get("ended_at"),
                "elapsed_sec": item.get("elapsed_sec"),
                "error": item.get("error"),
                "meta": item,
            }
        )
    return timeline


def _aggregate_usage(timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    retries = 0
    cost_units = 0.0
    for entry in timeline:
        meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        cost = meta.get("cost") if isinstance(meta.get("cost"), dict) else {}
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        retries += int(meta.get("retry_count") or 0)
        cost_units += float(cost.get("units") or 0.0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "retries": retries,
        "cost_units": round(cost_units, 6),
    }


def _blueprint_to_flow_graph(blueprint: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    steps = blueprint.get("steps")
    if not isinstance(steps, list):
        return [], []

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or f"step_{index}")
        module_id = str(step.get("block") or step.get("block_type") or "").strip()
        inputs = step.get("inputs")
        params = step.get("params")
        node_config: Dict[str, Any] = {}
        if isinstance(inputs, dict) and inputs:
            node_config["inputs"] = inputs
        if isinstance(params, dict) and params:
            node_config["params"] = params

        nodes.append(
            {
                "node_id": step_id,
                "module_id": module_id,
                "config": node_config,
                "retry": step.get("retry") if isinstance(step.get("retry"), dict) else {},
                "timeout": step.get("timeout"),
                "budget_slice": step.get("budget_slice"),
            }
        )

        if not isinstance(inputs, dict):
            continue
        for input_key, input_value in inputs.items():
            if not isinstance(input_value, dict):
                continue
            source_ref = input_value.get("from")
            if not isinstance(source_ref, str) or "." not in source_ref:
                continue
            src_step, src_field = source_ref.split(".", 1)
            if src_step in _CONTEXT_ROOTS:
                continue
            edges.append(
                {
                    "from": src_step,
                    "to": step_id,
                    "mapping": {str(input_key): src_field},
                }
            )

    return nodes, edges


def _graph_to_blueprint_steps(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    ordered_nodes = [
        node
        for node in nodes
        if isinstance(node, dict) and str(node.get("node_id") or "").strip()
    ]
    incoming: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        dst = str(edge.get("to") or "").strip()
        if not dst:
            continue
        incoming.setdefault(dst, []).append(edge)

    steps: List[Dict[str, Any]] = []
    for node in ordered_nodes:
        node_id = str(node.get("node_id") or "").strip()
        module_id = str(node.get("module_id") or "").strip()
        if not node_id or not module_id:
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        params = config.get("params") if isinstance(config.get("params"), dict) else {
            key: value
            for key, value in config.items()
            if key not in {"inputs", "params", "retry", "timeout", "budget_slice"}
        }
        inputs = config.get("inputs") if isinstance(config.get("inputs"), dict) else {}
        step_inputs: Dict[str, Any] = dict(inputs)

        for edge in incoming.get(node_id, []):
            src = str(edge.get("from") or "").strip()
            if not src:
                continue
            mapping = edge.get("mapping")
            if isinstance(mapping, dict) and mapping:
                for target_key, source_key in mapping.items():
                    target_field = str(target_key or "").strip()
                    source_field = str(source_key or "").strip()
                    if not target_field:
                        continue
                    source_ref = src if not source_field else f"{src}.{source_field}"
                    step_inputs[target_field] = {"from": source_ref}
                continue

            step_inputs[src] = {"from": src}

        step: Dict[str, Any] = {
            "id": node_id,
            "block": module_id,
            "inputs": step_inputs,
        }
        if params:
            step["params"] = params
        steps.append(step)
    return steps


def _validate_flow_contract_graph(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return FlowContractValidator(module_registry=module_registry).validate_graph(nodes, edges)


def _validate_flow_contract_blueprint(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    graph = blueprint.get("graph") if isinstance(blueprint.get("graph"), dict) else {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    if not nodes:
        nodes, edges = _blueprint_to_flow_graph(blueprint)
    return _validate_flow_contract_graph(nodes, edges)


def _module_document(spec: Dict[str, Any]) -> Dict[str, Any]:
    module_id = str(spec.get("mode_id") or "").strip()
    latest_release = _latest_release("modules", module_id) if module_id else None
    deprecated = bool(spec.get("deprecated")) or str(spec.get("status") or "").strip().lower() == "deprecated"
    status = _status_from_release_and_flags(latest_release=latest_release, deprecated=deprecated)
    cost_policy = spec.get("cost_policy") if isinstance(spec.get("cost_policy"), dict) else {}
    tests_cfg = spec.get("tests") if isinstance(spec.get("tests"), dict) else {}
    cost_regression = tests_cfg.get("cost_regression") if isinstance(tests_cfg.get("cost_regression"), dict) else {}
    if cost_regression and not cost_policy:
        cost_policy = {"cost_regression": cost_regression}

    return {
        "module_id": module_id,
        "title": str(spec.get("title") or module_id.replace("_", " ").title()),
        "description": str(spec.get("description") or ""),
        "tags": [str(tag) for tag in (spec.get("tags") or []) if str(tag).strip()],
        "status": status,
        "version": str(spec.get("module_version") or "0.0.0"),
        "contract_version": str(spec.get("contract_version") or ""),
        "lifecycle": str(spec.get("lifecycle") or "draft"),
        "contract_valid": len(module_registry.validate_contract(spec)) == 0,
        "pipeline": str(spec.get("pipeline") or "llm_pipeline"),
        "task_type": str(spec.get("task_type") or module_id),
        "input_schema": spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {},
        "output_schema": spec.get("output_schema") if isinstance(spec.get("output_schema"), dict) else {},
        "runtime": spec.get("runtime")
        if isinstance(spec.get("runtime"), dict)
        else {
            "pipeline": str(spec.get("pipeline") or "llm_pipeline"),
            "task_type": str(spec.get("task_type") or module_id),
        },
        "capabilities": [str(cap) for cap in (spec.get("capabilities") or []) if str(cap).strip()],
        "cost_policy": cost_policy,
        "ui": spec.get("ui") if isinstance(spec.get("ui"), dict) else {},
        "latest_release": latest_release,
    }


def _flow_document(record: Any) -> Dict[str, Any]:
    flow_id = str(getattr(record, "name", ""))
    payload = getattr(record, "data", {}) if isinstance(getattr(record, "data", {}), dict) else {}
    graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    if not nodes:
        nodes, edges = _blueprint_to_flow_graph(payload)
    latest_release = _latest_release("flows", flow_id) if flow_id else None

    record_status = getattr(record, "status", BlueprintStatus.DRAFT)
    deprecated = record_status == BlueprintStatus.ARCHIVED
    status = _status_from_release_and_flags(latest_release=latest_release, deprecated=deprecated)

    if record_status == BlueprintStatus.ACTIVE and status == "draft":
        status = "released"
    if record_status == BlueprintStatus.SANDBOXED and status == "draft":
        status = "sandboxed"

    return {
        "flow_id": flow_id,
        "version": str(payload.get("version") or "v1"),
        "status": status,
        "owner_id": str(getattr(record, "owner_id", "system")),
        "nodes": nodes,
        "edges": edges,
        "contract_validation": _validate_flow_contract_graph(nodes, edges),
        "entrypoint_schema": payload.get("entrypoint_schema")
        if isinstance(payload.get("entrypoint_schema"), dict)
        else {},
        "assertions": payload.get("assertions") if isinstance(payload.get("assertions"), dict) else {},
        "observability": payload.get("observability")
        if isinstance(payload.get("observability"), dict)
        else {},
        "raw_blueprint": payload,
        "created_at": getattr(record, "created_at", None).isoformat()
        if getattr(record, "created_at", None)
        else None,
        "updated_at": getattr(record, "updated_at", None).isoformat()
        if getattr(record, "updated_at", None)
        else None,
        "latest_release": latest_release,
    }


def _get_console_mode_runs(request: Request) -> Dict[str, Dict[str, Any]]:
    runs = getattr(request.app.state, "console_mode_runs", None)
    if isinstance(runs, dict):
        return runs
    runs = {}
    request.app.state.console_mode_runs = runs
    return runs


def _get_blueprint_store(request: Request) -> Any:
    return getattr(request.app.state, "console_blueprint_store", default_blueprint_store)


def _get_run_store(request: Request) -> Any:
    return getattr(request.app.state, "console_run_store", default_run_store)


def _sse_event(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return (f"event: {event}\n" f"data: {payload}\n\n").encode("utf-8")


def _module_mode_from_run_mode(mode: str) -> str:
    return "fast" if mode == "real" else "cheap"


def _require_scope(
    request: Request,
    scope: str,
) -> UnifiedAuthContext:
    return require_scope(request, request.app.state.seed.db, scope)


def _require_any_scope(
    request: Request,
    scopes: List[str],
) -> UnifiedAuthContext:
    return require_any_scope(request, request.app.state.seed.db, scopes)


def _runtime_db(request: Request) -> Any:
    seed = getattr(request.app.state, "seed", None)
    return getattr(seed, "db", None)


def _db_supports_console_runtime_persistence(request: Request) -> bool:
    db = _runtime_db(request)
    required_methods = ("execute", "fetchone", "fetchall")
    return all(hasattr(db, method) for method in required_methods)


def _ensure_console_runtime_tables(request: Request) -> None:
    if getattr(request.app.state, "_console_runtime_tables_ready", False):
        return
    if not _db_supports_console_runtime_persistence(request):
        return

    db = _runtime_db(request)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_profiles (
          profile_id TEXT PRIMARY KEY,
          enabled INTEGER NOT NULL DEFAULT 1,
          allowed_models_json TEXT NOT NULL DEFAULT '[]',
          daily_budget_units REAL NOT NULL DEFAULT 0,
          per_run_cap_units REAL NOT NULL DEFAULT 0,
          timeout_caps_json TEXT NOT NULL DEFAULT '{}',
          retry_caps_json TEXT NOT NULL DEFAULT '{}',
          redaction_policy_json TEXT NOT NULL DEFAULT '{}',
          requires_scope TEXT NOT NULL DEFAULT 'providers:use:real',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          created_by TEXT,
          updated_by TEXT
        );
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_budget_ledger (
          day_utc TEXT NOT NULL,
          user_id TEXT NOT NULL,
          profile_id TEXT NOT NULL,
          used_units REAL NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(day_utc, user_id, profile_id)
        );
        """
    )
    request.app.state._console_runtime_tables_ready = True


def _parse_json_map(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _parse_json_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except Exception:
            return []
    return []


def _normalize_provider_profile(profile_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    normalized_id = str(profile.get("id") or profile_id).strip() or profile_id
    allowed_models = profile.get("allowed_models") if isinstance(profile.get("allowed_models"), list) else []
    timeout_caps = profile.get("timeout_caps") if isinstance(profile.get("timeout_caps"), dict) else {}
    retry_caps = profile.get("retry_caps") if isinstance(profile.get("retry_caps"), dict) else {}
    redaction_policy = profile.get("redaction_policy") if isinstance(profile.get("redaction_policy"), dict) else {}

    daily_budget_units = profile.get("daily_budget_units")
    per_run_cap_units = profile.get("per_run_cap_units")
    try:
        daily_budget_units = max(0.0, float(daily_budget_units or 0.0))
    except Exception:
        daily_budget_units = 0.0
    try:
        per_run_cap_units = max(0.0, float(per_run_cap_units or 0.0))
    except Exception:
        per_run_cap_units = 0.0

    return {
        "id": normalized_id,
        "enabled": bool(profile.get("enabled", False)),
        "allowed_models": [str(item) for item in allowed_models if str(item).strip()],
        "daily_budget_units": daily_budget_units,
        "per_run_cap_units": per_run_cap_units,
        "timeout_caps": timeout_caps,
        "retry_caps": retry_caps,
        "redaction_policy": redaction_policy,
        "requires_scope": str(profile.get("requires_scope") or "providers:use:real"),
    }


def _provider_profile_from_row(row: Any) -> Dict[str, Any]:
    return _normalize_provider_profile(
        str(row["profile_id"]),
        {
            "id": str(row["profile_id"]),
            "enabled": bool(int(row["enabled"] or 0)),
            "allowed_models": _parse_json_list(row["allowed_models_json"]),
            "daily_budget_units": row["daily_budget_units"],
            "per_run_cap_units": row["per_run_cap_units"],
            "timeout_caps": _parse_json_map(row["timeout_caps_json"]),
            "retry_caps": _parse_json_map(row["retry_caps_json"]),
            "redaction_policy": _parse_json_map(row["redaction_policy_json"]),
            "requires_scope": row["requires_scope"],
        },
    )


def _seed_default_provider_profiles(request: Request) -> None:
    if not _db_supports_console_runtime_persistence(request):
        return
    _ensure_console_runtime_tables(request)
    db = _runtime_db(request)
    now = _now_iso()
    for profile_id, profile in _DEFAULT_PROVIDER_PROFILES.items():
        normalized = _normalize_provider_profile(profile_id, profile)
        db.execute(
            """
            INSERT OR IGNORE INTO provider_profiles(
              profile_id,
              enabled,
              allowed_models_json,
              daily_budget_units,
              per_run_cap_units,
              timeout_caps_json,
              retry_caps_json,
              redaction_policy_json,
              requires_scope,
              created_at,
              updated_at,
              created_by,
              updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                normalized["id"],
                1 if normalized["enabled"] else 0,
                json.dumps(normalized["allowed_models"], ensure_ascii=False),
                float(normalized["daily_budget_units"]),
                float(normalized["per_run_cap_units"]),
                json.dumps(normalized["timeout_caps"], ensure_ascii=False),
                json.dumps(normalized["retry_caps"], ensure_ascii=False),
                json.dumps(normalized["redaction_policy"], ensure_ascii=False),
                str(normalized["requires_scope"] or "providers:use:real"),
                now,
                now,
                "system",
                "system",
            ),
        )


def _provider_profiles_from_db(request: Request) -> Optional[Dict[str, Dict[str, Any]]]:
    if not _db_supports_console_runtime_persistence(request):
        return None
    _ensure_console_runtime_tables(request)
    db = _runtime_db(request)
    rows = db.fetchall("SELECT * FROM provider_profiles ORDER BY profile_id")
    if not rows:
        _seed_default_provider_profiles(request)
        rows = db.fetchall("SELECT * FROM provider_profiles ORDER BY profile_id")
    return {str(row["profile_id"]): _provider_profile_from_row(row) for row in rows}


def _provider_profiles(request: Request) -> Dict[str, Dict[str, Any]]:
    configured = getattr(request.app.state, "provider_profiles", None)
    if isinstance(configured, dict) and configured:
        normalized: Dict[str, Dict[str, Any]] = {}
        for key, value in configured.items():
            if isinstance(value, dict):
                normalized[str(key)] = _normalize_provider_profile(str(key), value)
        if normalized:
            return normalized
    db_profiles = _provider_profiles_from_db(request)
    if isinstance(db_profiles, dict) and db_profiles:
        return db_profiles
    return {
        str(key): _normalize_provider_profile(str(key), value)
        for key, value in _DEFAULT_PROVIDER_PROFILES.items()
        if isinstance(value, dict)
    }


def _upsert_provider_profile(
    request: Request,
    *,
    profile_id: str,
    payload: Dict[str, Any],
    actor_user_id: str,
) -> Tuple[str, Dict[str, Any]]:
    normalized = _normalize_provider_profile(profile_id, payload)
    configured = getattr(request.app.state, "provider_profiles", None)
    if isinstance(configured, dict):
        operation = "updated" if normalized["id"] in configured else "created"
        configured[normalized["id"]] = dict(normalized)
        request.app.state.provider_profiles = configured
        return operation, dict(normalized)

    if _db_supports_console_runtime_persistence(request):
        _ensure_console_runtime_tables(request)
        db = _runtime_db(request)
        existing = db.fetchone(
            "SELECT profile_id FROM provider_profiles WHERE profile_id = ?",
            (normalized["id"],),
        )
        operation = "updated" if existing else "created"
        now = _now_iso()
        db.execute(
            """
            INSERT INTO provider_profiles(
              profile_id,
              enabled,
              allowed_models_json,
              daily_budget_units,
              per_run_cap_units,
              timeout_caps_json,
              retry_caps_json,
              redaction_policy_json,
              requires_scope,
              created_at,
              updated_at,
              created_by,
              updated_by
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(profile_id) DO UPDATE SET
              enabled=excluded.enabled,
              allowed_models_json=excluded.allowed_models_json,
              daily_budget_units=excluded.daily_budget_units,
              per_run_cap_units=excluded.per_run_cap_units,
              timeout_caps_json=excluded.timeout_caps_json,
              retry_caps_json=excluded.retry_caps_json,
              redaction_policy_json=excluded.redaction_policy_json,
              requires_scope=excluded.requires_scope,
              updated_at=excluded.updated_at,
              updated_by=excluded.updated_by
            """,
            (
                normalized["id"],
                1 if normalized["enabled"] else 0,
                json.dumps(normalized["allowed_models"], ensure_ascii=False),
                float(normalized["daily_budget_units"]),
                float(normalized["per_run_cap_units"]),
                json.dumps(normalized["timeout_caps"], ensure_ascii=False),
                json.dumps(normalized["retry_caps"], ensure_ascii=False),
                json.dumps(normalized["redaction_policy"], ensure_ascii=False),
                str(normalized["requires_scope"] or "providers:use:real"),
                now,
                now,
                actor_user_id,
                actor_user_id,
            ),
        )
        return operation, normalized

    fallback = {
        str(key): dict(value)
        for key, value in _DEFAULT_PROVIDER_PROFILES.items()
        if isinstance(value, dict)
    }
    operation = "updated" if normalized["id"] in fallback else "created"
    fallback[normalized["id"]] = dict(normalized)
    request.app.state.provider_profiles = fallback
    return operation, dict(normalized)


def _delete_provider_profile(request: Request, profile_id: str) -> bool:
    configured = getattr(request.app.state, "provider_profiles", None)
    if isinstance(configured, dict):
        existed = profile_id in configured
        if existed:
            configured.pop(profile_id, None)
            request.app.state.provider_profiles = configured
        return existed
    if _db_supports_console_runtime_persistence(request):
        _ensure_console_runtime_tables(request)
        db = _runtime_db(request)
        row = db.fetchone("SELECT profile_id FROM provider_profiles WHERE profile_id = ?", (profile_id,))
        if not row:
            return False
        db.execute("DELETE FROM provider_profiles WHERE profile_id = ?", (profile_id,))
        return True
    return False


def _consume_daily_budget_units(
    request: Request,
    *,
    user_id: str,
    profile_id: str,
    requested_units: float,
    daily_cap: float,
) -> None:
    if daily_cap <= 0 or requested_units <= 0:
        return

    day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _db_supports_console_runtime_persistence(request):
        _ensure_console_runtime_tables(request)
        db = _runtime_db(request)
        now = _now_iso()

        if hasattr(db, "transaction"):
            with db.transaction() as conn:
                row = conn.execute(
                    """
                    SELECT used_units
                    FROM provider_budget_ledger
                    WHERE day_utc = ? AND user_id = ? AND profile_id = ?
                    """,
                    (day_key, user_id, profile_id),
                ).fetchone()
                already_used = float(row["used_units"] if row else 0.0)
                if already_used + requested_units > daily_cap:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "daily_budget_exceeded",
                            "daily_budget_units": daily_cap,
                            "already_used_units": already_used,
                            "requested_units": requested_units,
                        },
                    )
                next_used = already_used + requested_units
                conn.execute(
                    """
                    INSERT INTO provider_budget_ledger(
                      day_utc, user_id, profile_id, used_units, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(day_utc, user_id, profile_id) DO UPDATE SET
                      used_units=excluded.used_units,
                      updated_at=excluded.updated_at
                    """,
                    (day_key, user_id, profile_id, next_used, now, now),
                )
            return

        row = db.fetchone(
            """
            SELECT used_units
            FROM provider_budget_ledger
            WHERE day_utc = ? AND user_id = ? AND profile_id = ?
            """,
            (day_key, user_id, profile_id),
        )
        already_used = float(row["used_units"] if row else 0.0)
        if already_used + requested_units > daily_cap:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "daily_budget_exceeded",
                    "daily_budget_units": daily_cap,
                    "already_used_units": already_used,
                    "requested_units": requested_units,
                },
            )
        next_used = already_used + requested_units
        db.execute(
            """
            INSERT INTO provider_budget_ledger(
              day_utc, user_id, profile_id, used_units, created_at, updated_at
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(day_utc, user_id, profile_id) DO UPDATE SET
              used_units=excluded.used_units,
              updated_at=excluded.updated_at
            """,
            (day_key, user_id, profile_id, next_used, now, now),
        )
        return

    ledger = getattr(request.app.state, "provider_budget_ledger", None)
    if not isinstance(ledger, dict):
        ledger = {}
        request.app.state.provider_budget_ledger = ledger
    ledger_key = f"{day_key}:{user_id}:{profile_id}"
    already_used = float(ledger.get(ledger_key) or 0.0)
    if already_used + requested_units > daily_cap:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_budget_exceeded",
                "daily_budget_units": daily_cap,
                "already_used_units": already_used,
                "requested_units": requested_units,
            },
        )
    ledger[ledger_key] = already_used + requested_units


def _extract_requested_units(budget: Dict[str, Any]) -> float:
    for key in ("requested_units", "units", "max_units", "estimated_units"):
        value = budget.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            if value is not None and str(value).strip():
                return float(value)
        except Exception:
            continue
    return 0.0


def _enforce_real_run_gate(
    request: Request,
    *,
    ctx: UnifiedAuthContext,
    run_req: RunCreateRequest,
) -> str:
    profile_id = str(run_req.provider_profile or _DEFAULT_PROVIDER_PROFILE_ID).strip() or _DEFAULT_PROVIDER_PROFILE_ID
    profile = _provider_profiles(request).get(profile_id)
    if not isinstance(profile, dict):
        audit_auth_event(
            action="runs.real.denied",
            request=request,
            context=ctx,
            allowed=False,
            details={"reason": "provider_profile_not_found", "provider_profile": profile_id},
        )
        raise HTTPException(status_code=400, detail="provider_profile_not_found")
    if not bool(profile.get("enabled", False)):
        audit_auth_event(
            action="runs.real.denied",
            request=request,
            context=ctx,
            allowed=False,
            details={"reason": "provider_profile_disabled", "provider_profile": profile_id},
        )
        raise HTTPException(status_code=403, detail="provider_profile_disabled")

    required_scope = str(profile.get("requires_scope") or "providers:use:real").strip()
    if required_scope and not ctx.has_scope(required_scope):
        audit_auth_event(
            action="runs.real.denied",
            request=request,
            context=ctx,
            allowed=False,
            details={
                "reason": "missing_scope",
                "required_scope": required_scope,
                "provider_profile": profile_id,
            },
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "missing_scope",
                "required_scope": required_scope,
            },
        )

    per_run_cap = float(profile.get("per_run_cap_units") or 0.0)
    requested_units = _extract_requested_units(run_req.budget)
    if per_run_cap > 0 and requested_units > per_run_cap:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "per_run_budget_exceeded",
                "requested_units": requested_units,
                "per_run_cap_units": per_run_cap,
            },
        )

    daily_cap = float(profile.get("daily_budget_units") or 0.0)
    if daily_cap > 0:
        _consume_daily_budget_units(
            request,
            user_id=ctx.user_id,
            profile_id=profile_id,
            requested_units=requested_units,
            daily_cap=daily_cap,
        )

    audit_auth_event(
        action="runs.real.allowed",
        request=request,
        context=ctx,
        allowed=True,
        details={
            "provider_profile": profile_id,
            "requested_units": requested_units,
            "target_type": run_req.target.type,
            "target_id": run_req.target.id,
        },
    )
    return profile_id

async def _create_module_run(run_req: RunCreateRequest, request: Request) -> Dict[str, Any]:
    control_payload = {
        **run_req.control,
        "mode": _module_mode_from_run_mode(run_req.mode),
    }
    if run_req.mode == "stub":
        control_payload.setdefault("requested_capabilities", ["llm.generate"])

    mode_request = RunModeRequest(
        control=RunControl(
            mode=str(control_payload.get("mode") or _module_mode_from_run_mode(run_req.mode)),
            requested_capabilities=[
                str(item) for item in (control_payload.get("requested_capabilities") or []) if str(item).strip()
            ],
            idempotency_key=str(control_payload.get("idempotency_key") or "").strip() or None,
        ),
        data=run_req.input,
    )
    try:
        response = await run_mode(run_req.target.id, mode_request, request)
    except HTTPException as exc:
        if exc.status_code != 503 or run_req.mode != "stub":
            raise

        spec = module_registry.get_module(run_req.target.id)
        if not spec:
            raise HTTPException(status_code=404, detail="module_not_found") from exc
        control = mode_request.control.model_dump()
        errors = module_registry.validate_run_request(
            spec=spec,
            control=control,
            data=run_req.input,
            policy={"tool_security": spec.get("tool_security") if isinstance(spec.get("tool_security"), dict) else {}},
        )
        if errors:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_mode_request", "violations": errors},
            ) from exc

        created_at = _now_iso()
        run_id = f"stub-module-{uuid.uuid4().hex}"
        timeline = [
            {
                "index": 0,
                "node_id": "execute",
                "module_id": run_req.target.id,
                "status": "done",
                "raw_status": "succeeded",
                "elapsed_sec": 0.0,
                "error": None,
                "meta": {"output_keys": ["answer", "confidence"], "fallback": "local_stub"},
            }
        ]
        run_meta = {
            "run_id": run_id,
            "target_type": "module",
            "target_id": run_req.target.id,
            "mode": run_req.mode,
            "provider_profile": run_req.provider_profile or "stub",
            "budget": run_req.budget,
            "input": run_req.input,
            "control": control_payload,
            "saga_id": run_id,
            "raw_status": "succeeded",
            "status": "done",
            "result": {
                "answer": "Local stub module run completed.",
                "confidence": 1.0,
                "input": run_req.input,
                "module_id": run_req.target.id,
            },
            "timeline": timeline,
            "created_at": created_at,
            "updated_at": created_at,
        }
        _get_console_mode_runs(request)[run_id] = run_meta
        return run_meta

    created_at = _now_iso()
    run_meta = {
        "run_id": response.saga_id,
        "target_type": "module",
        "target_id": response.mode_id,
        "mode": run_req.mode,
        "provider_profile": run_req.provider_profile or ("stub" if run_req.mode == "stub" else "real"),
        "budget": run_req.budget,
        "input": run_req.input,
        "control": control_payload,
        "saga_id": response.saga_id,
        "raw_status": response.status,
        "status": _normalize_run_status(response.status),
        "created_at": created_at,
        "updated_at": created_at,
    }
    _get_console_mode_runs(request)[response.saga_id] = run_meta
    return run_meta


async def _create_flow_run(
    run_req: RunCreateRequest,
    request: Request,
    *,
    auth_ctx: UnifiedAuthContext,
) -> Dict[str, Any]:
    store = _get_blueprint_store(request)
    record = await store.get_record(run_req.target.id)
    if not record:
        raise HTTPException(status_code=404, detail="flow_not_found")

    blueprint_payload = record.data if isinstance(record.data, dict) else {}
    ctx = auth_ctx
    graph = blueprint_payload.get("graph") if isinstance(blueprint_payload.get("graph"), dict) else {}
    graph_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    graph_edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    if not graph_nodes:
        graph_nodes, graph_edges = _blueprint_to_flow_graph(blueprint_payload)
    contract_validation = _validate_flow_contract_blueprint(blueprint_payload)
    if not contract_validation.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "incompatible_flow_contract",
                "issues": contract_validation.get("issues", []),
                "errors": contract_validation.get("errors", []),
            },
        )

    runtime_payload = {
        "graph": {
            "flow_id": run_req.target.id,
            "version": str(blueprint_payload.get("version") or "v1"),
            "nodes": graph_nodes,
            "edges": graph_edges,
        },
        "input": run_req.input,
        "assertions": blueprint_payload.get("assertions")
        if isinstance(blueprint_payload.get("assertions"), dict)
        else {},
        "entrypoint_schema": blueprint_payload.get("entrypoint_schema")
        if isinstance(blueprint_payload.get("entrypoint_schema"), dict)
        else {},
        "observability": blueprint_payload.get("observability")
        if isinstance(blueprint_payload.get("observability"), dict)
        else {},
        "execution_mode": "DRY_RUN" if run_req.mode == "stub" else "LIVE",
        "provider_profile": run_req.provider_profile or ("stub" if run_req.mode == "stub" else "real"),
        "budget": run_req.budget,
    }

    run_id: str
    raw_status: str
    run_created_at: str
    run_updated_at: str
    execution_trace: List[Dict[str, Any]]
    result_payload: Dict[str, Any]
    request_payload: Dict[str, Any]
    duration_ms = 0

    orchestrator = getattr(request.app.state, "saga_orchestrator", None)
    if orchestrator is not None and hasattr(orchestrator, "start_saga"):
        started_at = datetime.now(timezone.utc)
        action_id = str(
            run_req.control.get("idempotency_key")
            or f"flow:{run_req.target.id}:{uuid.uuid4().hex}"
        )
        run_id = await orchestrator.start_saga(
            action_id=action_id,
            saga_type="flow_executor",
            payload=runtime_payload,
            user_id=ctx.user_id,
        )
        saga_state = await orchestrator.get_saga_state(run_id)
        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        raw_status = str((saga_state or {}).get("state") or "unknown")
        run_created_at = str((saga_state or {}).get("created_at") or _now_iso())
        run_updated_at = str((saga_state or {}).get("updated_at") or run_created_at)
        flow_result = (saga_state or {}).get("result")
        if isinstance(flow_result, str):
            try:
                flow_result = json.loads(flow_result)
            except Exception:
                flow_result = {"raw": flow_result}
        result_payload = flow_result if isinstance(flow_result, dict) else {}
        timeline = result_payload.get("timeline") if isinstance(result_payload.get("timeline"), list) else _build_timeline_from_saga_steps((saga_state or {}).get("steps"))
        execution_trace = [
            {
                "step": item.get("node_id"),
                "block": item.get("module_id"),
                "elapsed_sec": item.get("elapsed_sec"),
                "status": "failed" if str(item.get("status")) == "failed" else "succeeded",
                "error": item.get("error"),
            }
            for item in timeline
            if isinstance(item, dict)
        ]
        request_payload = run_req.input
    else:
        registry = build_default_registry()
        try:
            _validate_blueprint(blueprint_payload, registry)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid_flow: {exc}") from exc

        fallback_input = dict(run_req.input or {})
        ctx_user_id = str(ctx.user_id or "").strip()
        if ctx_user_id.lower() in {"", "unknown", "anonymous", "none"}:
            ctx_user_id = ""
        if "user_id" not in fallback_input and not (
            isinstance(fallback_input.get("request"), dict) and fallback_input["request"].get("user_id")
        ):
            fallback_input["user_id"] = ctx_user_id or "anonymous"

        started_at = datetime.now(timezone.utc)
        fallback_result = await _run_saga(
            blueprint_payload,
            fallback_input,
            registry,
            execution_mode=ExecutionMode.DRY_RUN if run_req.mode == "stub" else ExecutionMode.LIVE,
            db=_get_saga_db_from_request(request),
            actor_user_id=ctx_user_id or None,
        )
        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        run_id = str(uuid.uuid4())
        raw_status = str(fallback_result.get("status") or "unknown") if isinstance(fallback_result, dict) else "unknown"
        run_created_at = started_at.isoformat()
        run_updated_at = ended_at.isoformat()
        result_payload = fallback_result.get("result", {}) if isinstance(fallback_result, dict) and isinstance(fallback_result.get("result"), dict) else {}
        execution_trace = fallback_result.get("execution_trace", []) if isinstance(fallback_result, dict) and isinstance(fallback_result.get("execution_trace"), list) else []
        request_payload = fallback_input

    run_record = RunRecord(
        run_id=run_id,
        blueprint_name=run_req.target.id,
        owner_id=ctx.user_id,
        status=raw_status,
        execution_mode="DRY_RUN" if run_req.mode == "stub" else "LIVE",
        request_payload=request_payload,
        result=result_payload,
        execution_trace=execution_trace,
        performance={
            "duration_ms": duration_ms,
            "cost_estimate": float((result_payload.get("score") or 0.0)),
            "provider_profile": run_req.provider_profile or ("stub" if run_req.mode == "stub" else "real"),
        },
        ai_summary=None,
        created_at=_coerce_dt(run_created_at),
        updated_at=_coerce_dt(run_updated_at),
    )
    run_store = _get_run_store(request)
    await run_store.save(run_record)

    created_at = run_record.created_at.isoformat() if run_record.created_at else run_created_at
    updated_at = run_record.updated_at.isoformat() if run_record.updated_at else run_updated_at
    return {
        "run_id": run_id,
        "target_type": "flow",
        "target_id": run_req.target.id,
        "mode": run_req.mode,
        "provider_profile": run_req.provider_profile or ("stub" if run_req.mode == "stub" else "real"),
        "status": _normalize_run_status(raw_status),
        "raw_status": raw_status,
        "created_at": created_at,
        "updated_at": updated_at,
    }

async def _module_run_summary(entry: Dict[str, Any], orchestrator: Any) -> Dict[str, Any]:
    saga_id = str(entry.get("saga_id") or entry.get("run_id") or "")
    raw_state = str(entry.get("raw_status") or "started")
    updated_at = entry.get("updated_at")
    if orchestrator and saga_id:
        saga = await orchestrator.get_saga_state(saga_id)
        if isinstance(saga, dict):
            raw_state = str(saga.get("state") or raw_state)
            updated_at = saga.get("updated_at") or updated_at

    return {
        "run_id": str(entry.get("run_id") or saga_id),
        "target_type": "module",
        "target_id": str(entry.get("target_id") or ""),
        "status": _normalize_run_status(raw_state),
        "raw_status": raw_state,
        "mode": str(entry.get("mode") or "real"),
        "provider_profile": entry.get("provider_profile"),
        "created_at": entry.get("created_at"),
        "updated_at": updated_at,
    }


def _flow_run_summary(record: Any) -> Dict[str, Any]:
    raw_status = str(getattr(record, "status", "unknown"))
    execution_mode = str(getattr(record, "execution_mode", "LIVE")).upper()
    return {
        "run_id": str(getattr(record, "run_id", "")),
        "target_type": "flow",
        "target_id": str(getattr(record, "blueprint_name", "")),
        "status": _normalize_run_status(raw_status),
        "raw_status": raw_status,
        "mode": "stub" if execution_mode == "DRY_RUN" else "real",
        "provider_profile": "stub" if execution_mode == "DRY_RUN" else "real",
        "created_at": getattr(record, "created_at", None).isoformat()
        if getattr(record, "created_at", None)
        else None,
        "updated_at": getattr(record, "updated_at", None).isoformat()
        if getattr(record, "updated_at", None)
        else None,
    }

async def _module_run_detail(run_id: str, request: Request) -> Dict[str, Any]:
    entry = _get_console_mode_runs(request).get(run_id)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="run_not_found")

    orchestrator = getattr(request.app.state, "saga_orchestrator", None)
    saga_payload: Dict[str, Any] = {}
    if orchestrator and entry.get("saga_id"):
        fetched = await orchestrator.get_saga_state(str(entry.get("saga_id")))
        if isinstance(fetched, dict):
            saga_payload = fetched

    raw_status = str(saga_payload.get("state") or entry.get("raw_status") or "started")
    timeline = _build_timeline_from_saga_steps(saga_payload.get("steps"))
    if not timeline and isinstance(entry.get("timeline"), list):
        timeline = entry.get("timeline") or []
    result_payload = saga_payload.get("result")
    if isinstance(result_payload, str):
        try:
            result_payload = json.loads(result_payload)
        except Exception:
            result_payload = {"raw": result_payload}
    if not isinstance(result_payload, dict) and isinstance(entry.get("result"), dict):
        result_payload = entry.get("result")
    if not isinstance(result_payload, dict):
        result_payload = {}

    artifacts = _extract_artifact_refs(result_payload)
    usage = _aggregate_usage(timeline)

    created_at = saga_payload.get("created_at") or entry.get("created_at")
    updated_at = saga_payload.get("updated_at") or entry.get("updated_at")
    created_dt = _coerce_dt(created_at)
    updated_dt = _coerce_dt(updated_at)
    latency_ms = None
    if created_dt and updated_dt:
        latency_ms = int((updated_dt - created_dt).total_seconds() * 1000)

    return {
        "run_id": run_id,
        "target_type": "module",
        "target_id": entry.get("target_id"),
        "status": _normalize_run_status(raw_status),
        "raw_status": raw_status,
        "mode": entry.get("mode"),
        "provider_profile": entry.get("provider_profile"),
        "budget": entry.get("budget") if isinstance(entry.get("budget"), dict) else {},
        "timeline": timeline,
        "result": result_payload,
        "artifacts": artifacts,
        "metrics": {
            "latency_ms": latency_ms,
            "tokens": usage.get("total_tokens"),
            "cost_units": usage.get("cost_units"),
            "retries": usage.get("retries"),
        },
        "created_at": created_at,
        "updated_at": updated_at,
        "saga_id": entry.get("saga_id"),
    }


async def _flow_run_detail(run_id: str, request: Request) -> Dict[str, Any]:
    run_store = _get_run_store(request)
    record = await run_store.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run_not_found")

    execution_mode = str(record.execution_mode or "LIVE").upper()
    timeline = _build_timeline_from_trace(record.execution_trace)
    artifacts = _extract_artifact_refs(record.result)
    raw_status = str(record.status or "unknown")
    performance = record.performance if isinstance(record.performance, dict) else {}

    return {
        "run_id": run_id,
        "target_type": "flow",
        "target_id": record.blueprint_name,
        "status": _normalize_run_status(raw_status),
        "raw_status": raw_status,
        "mode": "stub" if execution_mode == "DRY_RUN" else "real",
        "provider_profile": performance.get("provider_profile")
        or ("stub" if execution_mode == "DRY_RUN" else "real"),
        "budget": {},
        "timeline": timeline,
        "result": record.result if isinstance(record.result, dict) else {},
        "artifacts": artifacts,
        "metrics": {
            "latency_ms": performance.get("duration_ms"),
            "tokens": None,
            "cost_units": performance.get("cost_estimate"),
            "retries": 0,
        },
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
