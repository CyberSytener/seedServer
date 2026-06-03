from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover
    Draft202012Validator = None


DEFAULT_INJECTION_MARKERS = [
    "ignore previous instructions",
    "system prompt",
    "developer instructions",
    "tool override",
    "bypass safety",
]


def _module_root() -> Path:
    configured = os.getenv("SEED_MODULE_REGISTRY_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "modules"


def _load_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _validate_payload(schema: Dict[str, Any], payload: Dict[str, Any]) -> List[str]:
    if not schema:
        return []

    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda error: str(list(error.path)))
        messages = []
        for err in errors:
            location = ".".join([str(part) for part in err.path]) if list(err.path) else "$"
            messages.append(f"{location}: {err.message}")
        return messages

    # fallback minimal validation
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    return [f"missing required field: {name}" for name in required if name not in payload]


def _contains_injection_marker(value: Any, markers: List[str]) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in markers)
    if isinstance(value, dict):
        return any(_contains_injection_marker(item, markers) for item in value.values())
    if isinstance(value, list):
        return any(_contains_injection_marker(item, markers) for item in value)
    return False


class ModuleRegistry:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or _module_root()

    def _iter_module_files(self) -> List[Path]:
        if not self.root.exists():
            return []
        files = list(self.root.glob("**/*.yaml")) + list(self.root.glob("**/*.yml"))
        return sorted(files)

    def list_modules(self) -> List[Dict[str, Any]]:
        modules: List[Dict[str, Any]] = []
        for path in self._iter_module_files():
            spec = _load_yaml(path)
            mode_id = str(spec.get("mode_id") or "").strip()
            if not mode_id:
                continue
            modules.append(
                {
                    "mode_id": mode_id,
                    "pipeline": str(spec.get("pipeline") or "llm_pipeline"),
                    "task_type": str(spec.get("task_type") or "general"),
                    "path": str(path),
                    "capabilities": [str(cap) for cap in (spec.get("capabilities") or []) if str(cap).strip()],
                    "output_schema": spec.get("output_schema") if isinstance(spec.get("output_schema"), dict) else {},
                }
            )
        return modules

    def get_module(self, mode_id: str) -> Optional[Dict[str, Any]]:
        target = mode_id.strip().lower()
        for path in self._iter_module_files():
            spec = _load_yaml(path)
            current = str(spec.get("mode_id") or "").strip().lower()
            if current == target:
                return {**spec, "_path": str(path)}
        return None

    def validate_run_request(
        self,
        *,
        spec: Dict[str, Any],
        control: Dict[str, Any],
        data: Dict[str, Any],
        policy: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        errors: List[str] = []

        input_schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {}
        errors.extend(_validate_payload(input_schema, data))

        allowed_caps = [str(cap) for cap in (spec.get("capabilities") or []) if str(cap).strip()]
        requested_caps = [str(cap) for cap in (control.get("requested_capabilities") or []) if str(cap).strip()]
        unauthorized = [cap for cap in requested_caps if cap not in allowed_caps]
        if unauthorized:
            errors.append(f"unauthorized_capabilities: {', '.join(unauthorized)}")

        security_policy = (policy or {}).get("tool_security") if isinstance((policy or {}).get("tool_security"), dict) else {}
        deny_markers = bool(security_policy.get("deny_prompt_injection_markers", True))
        marker_list = [str(marker).lower() for marker in (security_policy.get("injection_markers") or DEFAULT_INJECTION_MARKERS)]
        if deny_markers and _contains_injection_marker(data, marker_list):
            errors.append("prompt_injection_marker_detected")

        return errors

    def build_saga_payload(
        self,
        *,
        mode_id: str,
        spec: Dict[str, Any],
        control: Dict[str, Any],
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "task_type": str(spec.get("task_type") or mode_id),
            "mode": str(control.get("mode") or spec.get("default_mode") or "fast"),
            "user_request": str(data.get("user_request") or data.get("prompt") or json.dumps(data, ensure_ascii=False, default=str)),
            "constraints": data.get("constraints") if isinstance(data.get("constraints"), dict) else {},
            "output_schema": spec.get("output_schema") if isinstance(spec.get("output_schema"), dict) else {},
            "required_fields": spec.get("required_fields") if isinstance(spec.get("required_fields"), list) else [],
            "format_hint": str(spec.get("format_hint") or "json_object"),
            "module": {
                "mode_id": mode_id,
                "capabilities": [str(cap) for cap in (spec.get("capabilities") or []) if str(cap).strip()],
                "requested_capabilities": [str(cap) for cap in (control.get("requested_capabilities") or []) if str(cap).strip()],
                "policy_ref": spec.get("policy_ref"),
            },
            "module_input": data,
            "control": {
                "idempotency_key": control.get("idempotency_key"),
            },
        }

        policy_overrides = spec.get("policy_overrides") if isinstance(spec.get("policy_overrides"), dict) else {}
        if policy_overrides:
            payload["policy_overrides"] = policy_overrides

        return payload
