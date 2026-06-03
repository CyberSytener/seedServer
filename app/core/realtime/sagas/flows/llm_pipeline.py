from __future__ import annotations
import logging

import asyncio
import hashlib
import json
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.core.realtime.engine import BaseSaga, SagaStepDefinition, SagaStepResult
from app.core.realtime.sagas.artifact_store import ArtifactStore
from app.core.realtime.sagas.llm_budget import LLMBudget
from app.core.realtime.sagas.llm_policy import build_policy_snapshot, resolve_llm_policy
from app.services.evals import build_judge_trace, resolve_judge_cascade_policy

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover
    Draft202012Validator = None


class LLMPipelineFlow(BaseSaga):
    """Production-oriented pipeline: plan -> execute -> validate -> repair -> format -> finalize."""

    saga_type = "llm_pipeline"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_request = str(payload.get("user_request") or payload.get("prompt") or "").strip()
        task_type = str(payload.get("task_type") or "general")
        policy = resolve_llm_policy(
            payload=payload,
            task_type=task_type,
            requested_mode=str(payload.get("mode") or "").strip().lower() or None,
        )
        mode = str(policy.get("mode") or "fast")
        base_policy_snapshot = build_policy_snapshot(policy, mode=mode, task_type=task_type)
        max_repairs = int(policy.get("max_repairs") or 1)
        repair_strategy = str(payload.get("repair_strategy") or "llm").strip().lower()
        output_schema = payload.get("output_schema") if isinstance(payload.get("output_schema"), dict) else {}
        output_schema_strict = bool(payload.get("output_schema_strict", False))
        format_hint = str(payload.get("format_hint") or "json_object")
        required_fields = [
            str(field).strip()
            for field in (payload.get("required_fields") or [])
            if str(field).strip()
        ]

        effective_payload = {**payload, "budget": policy.get("budget") or payload.get("budget")}
        budget = LLMBudget.from_payload(effective_payload, mode)
        mock_usage = payload.get("mock_usage") if isinstance(payload.get("mock_usage"), dict) else {}

        state: Dict[str, Any] = {
            "plan": None,
            "draft_output": None,
            "candidates": [],
            "validation_report": None,
            "best_output": None,
            "formatted_output": None,
            "stop_reason": "ok",
            "repair_attempts": 0,
            "terminal_stop": False,
            "policy": policy,
            "artifacts": {
                "candidates": [],
                "validator_report": None,
                "judge_trace": None,
                "repair_diffs": [],
                "raw_model_responses": [],
                "policy_snapshot": base_policy_snapshot,
            },
        }
        artifacts_cfg = policy.get("artifacts") if isinstance(policy.get("artifacts"), dict) else {}
        artifact_store_enabled = bool(payload.get("artifact_store_enabled", artifacts_cfg.get("enabled", True)))
        artifact_store = ArtifactStore() if artifact_store_enabled else None
        store_raw_responses = bool(payload.get("store_raw_responses", artifacts_cfg.get("store_raw_responses", False)))
        raw_response_max_chars = int(payload.get("raw_response_max_chars") or artifacts_cfg.get("raw_max_chars") or 4096)
        raw_response_hash_only = bool(payload.get("raw_response_hash_only", artifacts_cfg.get("raw_hash_only", False)))

        def _artifact_ref(step_name: str, kind: str, content: Any) -> Dict[str, Any]:
            if not artifact_store_enabled or artifact_store is None:
                return {}
            try:
                return artifact_store.store(saga_id=saga_id, step=step_name, kind=kind, payload=content)
            except Exception:
                return {}

        def _step_policy(step_name: str) -> Dict[str, Any]:
            steps_cfg = policy.get("steps") if isinstance(policy.get("steps"), dict) else {}
            step_cfg = steps_cfg.get(step_name)
            return step_cfg if isinstance(step_cfg, dict) else {}

        def _tier_info(step_name: str) -> Dict[str, Any]:
            step_cfg = _step_policy(step_name)
            tier_name = str(step_cfg.get("tier") or "cheap").strip().lower()
            model_tiers = policy.get("model_tiers") if isinstance(policy.get("model_tiers"), dict) else {}
            tier_cfg = model_tiers.get(tier_name) if isinstance(model_tiers.get(tier_name), dict) else {}
            return {
                "tier": tier_name,
                "provider": str(tier_cfg.get("provider") or "mock"),
                "model": str(tier_cfg.get("model") or "mock-model"),
                "unit_cost": float(tier_cfg.get("unit_cost") or 1.0),
            }

        def _safe_json(value: Any) -> str:
            try:
                return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
            except Exception:
                return str(value)

        def _fingerprint(value: Any) -> str:
            return hashlib.sha256(_safe_json(value).encode("utf-8")).hexdigest()

        def _fingerprinted_inputs(step_name: str, step_inputs: Dict[str, Any]) -> Dict[str, Any]:
            compact: Dict[str, Any] = {}
            for key, value in step_inputs.items():
                if isinstance(value, (str, bytes)):
                    as_str = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
                    compact[f"{key}_hash"] = _fingerprint(as_str)
                    compact[f"{key}_len"] = len(as_str)
                elif isinstance(value, (dict, list, tuple)):
                    compact[f"{key}_hash"] = _fingerprint(value)
                else:
                    compact[key] = value
            compact["policy_version"] = policy.get("policy_version")
            compact["step_policy"] = _step_policy(step_name)
            return compact

        def _build_step_key(step_name: str, step_inputs: Dict[str, Any]) -> str:
            normalized = {
                "step": step_name,
                "task_type": task_type,
                "mode": mode,
                "inputs": _fingerprinted_inputs(step_name, step_inputs),
            }
            return _fingerprint(normalized)

        def _decode_cached_step(cached: Any) -> Dict[str, Any]:
            if isinstance(cached, dict):
                return cached
            if isinstance(cached, str):
                try:
                    parsed = json.loads(cached)
                except json.JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
            return {}

        def _extract_output_fields(raw_output: Any) -> Dict[str, Any]:
            if isinstance(raw_output, dict):
                return raw_output
            if isinstance(raw_output, str):
                text = raw_output.strip()
                if not text:
                    return {}
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return {"answer": text}
                return parsed if isinstance(parsed, dict) else {"answer": parsed}
            return {"answer": raw_output}

        def _coerce_json_text(raw: Any) -> Optional[Dict[str, Any]]:
            if isinstance(raw, dict):
                return raw
            if not isinstance(raw, str):
                return None
            text = raw.strip()
            if not text:
                return None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None

        def _capture_raw_response(step_name: str, raw_value: Any, extra: Optional[Dict[str, Any]] = None) -> None:
            if raw_value is None or not store_raw_responses:
                return
            text = raw_value if isinstance(raw_value, str) else _safe_json(raw_value)
            text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
            text = re.sub(r"\b\+?\d[\d\s().-]{7,}\b", "[REDACTED_PHONE]", text)
            if raw_response_hash_only:
                payload_raw: Dict[str, Any] = {"hash": _fingerprint(text), "length": len(text)}
            else:
                payload_raw = {"text": text[:raw_response_max_chars], "length": len(text), "truncated": len(text) > raw_response_max_chars}
            if extra:
                payload_raw.update(extra)
            state["artifacts"]["raw_model_responses"].append({"step": step_name, "raw": payload_raw})

        def _derive_schema_stop_reason(violations: List[Dict[str, Any]]) -> str:
            if any(v.get("type") == "schema_invalid_json" for v in violations):
                return "schema_invalid_json"
            if any(v.get("type") == "schema_required_missing" for v in violations):
                return "schema_required_missing"
            if any(v.get("type") == "schema_type_mismatch" for v in violations):
                return "schema_type_mismatch"
            if violations:
                return "schema_contract_violation"
            return "schema_ok"

        def _schema_validate(raw_output: Any) -> Dict[str, Any]:
            requires_json_contract = bool(output_schema) or format_hint == "json_object"
            json_candidate = _coerce_json_text(raw_output)

            if requires_json_contract and isinstance(raw_output, str) and json_candidate is None:
                violations = [
                    {
                        "type": "schema_invalid_json",
                        "severity": "high",
                        "message": "Output is not valid JSON object text.",
                    }
                ]
                return {
                    "is_pass": False,
                    "violations": violations,
                    "stop_reason": "schema_invalid_json",
                    "normalized_output": {},
                }

            output = json_candidate if json_candidate is not None else _extract_output_fields(raw_output)
            violations: List[Dict[str, Any]] = []

            if not output:
                violations.append({"type": "schema_required_missing", "severity": "high", "field": "*", "message": "Output is empty."})

            if output_schema and Draft202012Validator is not None:
                validator = Draft202012Validator(output_schema)
                for err in validator.iter_errors(output):
                    pointer = ".".join(str(item) for item in err.path) if list(err.path) else "$"
                    if err.validator == "required":
                        missing = None
                        if isinstance(err.message, str) and "'" in err.message:
                            parts = err.message.split("'")
                            if len(parts) >= 2:
                                missing = parts[1]
                        violations.append(
                            {
                                "type": "schema_required_missing",
                                "severity": "high",
                                "field": str(missing or pointer),
                                "message": err.message,
                                "location": pointer,
                            }
                        )
                    elif err.validator == "type":
                        violations.append(
                            {
                                "type": "schema_type_mismatch",
                                "severity": "high",
                                "field": pointer,
                                "expected": err.validator_value,
                                "message": err.message,
                                "location": pointer,
                            }
                        )
                    else:
                        violations.append(
                            {
                                "type": "schema_contract_violation",
                                "severity": "high",
                                "field": pointer,
                                "validator": err.validator,
                                "message": err.message,
                                "location": pointer,
                            }
                        )

            schema_required = output_schema.get("required") if isinstance(output_schema.get("required"), list) else []
            effective_required = schema_required or required_fields
            for field in effective_required:
                value = output.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    violations.append(
                        {
                            "type": "schema_required_missing",
                            "severity": "high",
                            "field": str(field),
                            "message": f"Missing required field: {field}",
                        }
                    )

            properties = output_schema.get("properties") if isinstance(output_schema.get("properties"), dict) else {}
            type_map = {
                "string": str,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict,
            }
            for field, cfg in properties.items():
                if field not in output:
                    continue
                expected = cfg.get("type") if isinstance(cfg, dict) else None
                if expected not in type_map:
                    continue
                if output_schema_strict and not isinstance(output.get(field), type_map[expected]):
                    violations.append(
                        {
                            "type": "schema_type_mismatch",
                            "severity": "high",
                            "field": field,
                            "expected": expected,
                            "message": f"Field '{field}' should be {expected}",
                        }
                    )

            stop_reason = _derive_schema_stop_reason(violations)

            return {
                "is_pass": len(violations) == 0,
                "violations": violations,
                "stop_reason": stop_reason,
                "normalized_output": output,
            }

        def _quality_validate(raw_output: Any, schema_report: Dict[str, Any]) -> Dict[str, Any]:
            output = schema_report.get("normalized_output") if isinstance(schema_report.get("normalized_output"), dict) else _extract_output_fields(raw_output)
            violations: List[Dict[str, Any]] = []

            if not output:
                violations.append({"type": "quality_empty", "severity": "high", "message": "No semantic content."})

            if any(str(v).lower().strip() in {"refused", "unsafe", "blocked"} for v in output.values() if isinstance(v, str)):
                violations.append({"type": "unsafe_or_refused", "severity": "high", "message": "Model refused or marked unsafe."})

            score = max(0, 100 - (20 * len(violations)))
            pass_score = int((policy.get("thresholds") or {}).get("pass_score") or 85)
            is_pass = len(violations) == 0 and score >= pass_score
            return {
                "score": score,
                "is_pass": is_pass,
                "violations": violations,
                "stop_reason": "validation_passed" if is_pass else "quality_failed",
            }

        def _fallback_repair_patch(current: Dict[str, Any], report: Dict[str, Any], attempt: int) -> Dict[str, Any]:
            patched = dict(current)
            schema_gate = report.get("schema_gate") if isinstance(report.get("schema_gate"), dict) else {}
            violations = schema_gate.get("violations") if isinstance(schema_gate.get("violations"), list) else []
            for violation in violations:
                if violation.get("type") == "schema_required_missing":
                    field = str(violation.get("field") or "").strip()
                    if field and field not in patched:
                        patched[field] = f"auto_repaired_attempt_{attempt}"
                if violation.get("type") == "schema_type_mismatch":
                    field = str(violation.get("field") or "").strip()
                    expected = str(violation.get("expected") or "").strip()
                    if field and field in patched and expected in {"number", "integer"}:
                        try:
                            patched[field] = int(patched[field]) if expected == "integer" else float(patched[field])
                        except Exception:
                            logging.debug("Suppressed exception", exc_info=True)
            return patched

        async def _call_llm_adapter(step_name: str, step_inputs: Dict[str, Any], fallback_output: Any) -> Dict[str, Any]:
            adapters = getattr(self, "adapters", {}) if self else {}
            adapter = adapters.get("llm_pipeline") or adapters.get("llm") or adapters.get("llm_engine")
            tier = _tier_info(step_name)

            if adapter:
                for method_name in (step_name, "generate", "run_step"):
                    method = getattr(adapter, method_name, None)
                    if callable(method):
                        response = await self._call_adapter_method(
                            adapter,
                            method_name,
                            {
                                "step": step_name,
                                "inputs": step_inputs,
                                "policy": _step_policy(step_name),
                                "task_type": task_type,
                                "mode": mode,
                                "output_schema": output_schema,
                                "format_hint": format_hint,
                            },
                            adapter_name="llm_pipeline",
                            operation_name=f"llm_pipeline.{step_name}",
                        )
                        if isinstance(response, dict):
                            return {
                                "output": response.get("output") if response.get("output") is not None else fallback_output,
                                "usage": response.get("usage") if isinstance(response.get("usage"), dict) else None,
                                "cost": response.get("cost") if isinstance(response.get("cost"), dict) else None,
                                "model": response.get("model") if isinstance(response.get("model"), dict) else {
                                    "provider": tier["provider"],
                                    "model": tier["model"],
                                    "tier": tier["tier"],
                                },
                                "artifacts": response.get("artifacts") if isinstance(response.get("artifacts"), dict) else {},
                                "raw_response": response.get("raw_response"),
                                "candidates": response.get("candidates") if isinstance(response.get("candidates"), list) else [],
                            }

            default_usage, default_cost = _estimated_usage(step_name)
            default_cost = {
                **default_cost,
                "provider": tier["provider"],
                "model": tier["model"],
            }
            return {
                "output": fallback_output,
                "usage": default_usage,
                "cost": default_cost,
                "model": {
                    "provider": tier["provider"],
                    "model": tier["model"],
                    "tier": tier["tier"],
                },
                "artifacts": {},
                "raw_response": None,
                "candidates": [],
            }

        def _estimated_usage(step_name: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
            cfg = mock_usage.get(step_name) if isinstance(mock_usage.get(step_name), dict) else {}
            if cfg:
                usage = {
                    "input_tokens": int(cfg.get("input_tokens") or 0),
                    "output_tokens": int(cfg.get("output_tokens") or 0),
                }
                usage["total_tokens"] = int(cfg.get("total_tokens") or (usage["input_tokens"] + usage["output_tokens"]))
                cost = {
                    "units": float(cfg.get("cost_units") or 0.0),
                    "provider": str(cfg.get("provider") or "mock"),
                    "model": str(cfg.get("model") or "mock-model"),
                }
                return usage, cost

            tier = _tier_info(step_name)
            base = {
                "plan": 300,
                "execute": 1200,
                "validate": 500,
                "repair_loop": 700,
                "format": 250,
                "finalize": 30,
            }.get(step_name, 200)
            return (
                {"total_tokens": base, "input_tokens": int(base * 0.6), "output_tokens": int(base * 0.4)},
                {
                    "units": round((base / 1000.0) * max(0.1, float(tier["unit_cost"])), 3),
                    "provider": tier["provider"],
                    "model": tier["model"],
                },
            )

        def _set_soft_stop(stop_reason: str) -> None:
            state["stop_reason"] = stop_reason
            state["terminal_stop"] = True

        def _classify_stop_reason(stop_reason: Optional[str]) -> Dict[str, str]:
            reason = str(stop_reason or "ok")
            if reason in {"ok", "validation_passed"}:
                return {"stop_category": "success", "stop_severity": "info"}
            if reason.startswith("schema_"):
                return {"stop_category": "schema", "stop_severity": "error"}
            if reason.startswith("quality_"):
                return {"stop_category": "quality", "stop_severity": "error"}
            if reason.startswith("budget_"):
                return {"stop_category": "budget", "stop_severity": "error"}
            if reason.startswith("provider_"):
                return {"stop_category": "provider", "stop_severity": "error"}
            if reason.startswith("security_") or reason == "unsafe_or_refused":
                return {"stop_category": "security", "stop_severity": "critical"}
            if reason.startswith("recovery_") or reason == "max_repairs_reached":
                return {"stop_category": "recovery", "stop_severity": "warning"}
            return {"stop_category": "unknown", "stop_severity": "error"}

        async def _run_idempotent_step(
            step_name: str,
            step_inputs: Dict[str, Any],
            runner: Callable[[], Awaitable[SagaStepResult]],
        ) -> Tuple[SagaStepResult, bool]:
            step_key = _build_step_key(step_name, step_inputs)
            operation = f"llm:{step_name}:{step_key}"
            cached = await self._check_idempotency(saga_id, operation)
            parsed_cached = _decode_cached_step(cached)
            step_cfg = _step_policy(step_name)
            tier = _tier_info(step_name)
            step_policy_snapshot = build_policy_snapshot(
                policy,
                mode=mode,
                task_type=task_type,
                step_name=step_name,
                step_policy=step_cfg,
            )

            if parsed_cached:
                cached_result = parsed_cached.get("result") if isinstance(parsed_cached.get("result"), dict) else {}
                cached_meta = parsed_cached.get("meta") if isinstance(parsed_cached.get("meta"), dict) else {}
                cached_meta = {
                    **cached_meta,
                    "idempotency": {"operation": operation, "key": step_key, "cache_hit": True},
                    "policy": {
                        "version": policy.get("policy_version"),
                        "pricing_version": policy.get("pricing_version"),
                        "mode": mode,
                        "step": step_cfg,
                        "snapshot": step_policy_snapshot,
                    },
                    "model": cached_meta.get("model") if isinstance(cached_meta.get("model"), dict) else {
                        "provider": tier["provider"], "model": tier["model"], "tier": tier["tier"]
                    },
                }
                return SagaStepResult(result=cached_result, meta=cached_meta, pause=bool(parsed_cached.get("pause"))), True

            step_result = await runner()
            step_meta = step_result.meta if isinstance(step_result.meta, dict) else {}
            wrapped = SagaStepResult(
                result=step_result.result,
                meta={
                    **step_meta,
                    "idempotency": {"operation": operation, "key": step_key, "cache_hit": False},
                    "policy": {
                        "version": policy.get("policy_version"),
                        "pricing_version": policy.get("pricing_version"),
                        "mode": mode,
                        "step": step_cfg,
                        "snapshot": step_policy_snapshot,
                    },
                    "model": step_meta.get("model") if isinstance(step_meta.get("model"), dict) else {
                        "provider": tier["provider"], "model": tier["model"], "tier": tier["tier"]
                    },
                },
                pause=step_result.pause,
            )
            await self._record_idempotency(
                saga_id,
                operation,
                {"result": wrapped.result, "meta": wrapped.meta, "pause": wrapped.pause},
            )
            return wrapped, False

        async def _run_budgeted_step(
            step_name: str,
            step_inputs: Dict[str, Any],
            runner: Callable[[], Awaitable[SagaStepResult]],
        ) -> SagaStepResult:
            if state.get("terminal_stop") and step_name != "finalize":
                return SagaStepResult(
                    result={},
                    meta={
                        "stop_reason": state.get("stop_reason"),
                        "step_contract": step_name,
                        "skipped_due_to_terminal_stop": True,
                        "budget": budget.snapshot(),
                    },
                )

            pre_reason = budget.pre_check()
            if pre_reason:
                _set_soft_stop(pre_reason)
                return SagaStepResult(
                    result={"stop_reason": pre_reason},
                    meta={"stop_reason": pre_reason, "step_contract": step_name, "budget": budget.snapshot()},
                )

            if step_name in {"execute", "repair_loop"}:
                usage_estimate, cost_estimate = _estimated_usage(step_name)
                predicted_reason = budget.would_exceed(usage_estimate, cost_estimate)
                if predicted_reason:
                    _set_soft_stop(predicted_reason)
                    return SagaStepResult(
                        result={"stop_reason": predicted_reason},
                        meta={
                            "stop_reason": predicted_reason,
                            "step_contract": step_name,
                            "budget": budget.snapshot(),
                            "predicted_budget_stop": True,
                            "usage_estimate": usage_estimate,
                            "cost_estimate": cost_estimate,
                        },
                    )

            step_result, cache_hit = await _run_idempotent_step(step_name, step_inputs, runner)
            meta = step_result.meta if isinstance(step_result.meta, dict) else {}

            if cache_hit:
                return SagaStepResult(
                    result=step_result.result,
                    pause=step_result.pause,
                    meta={**meta, "budget": budget.snapshot()},
                )

            usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else None
            cost = meta.get("cost") if isinstance(meta.get("cost"), dict) else None
            if usage is None or cost is None:
                usage, cost = _estimated_usage(step_name)

            budget.consume(usage, cost)
            post_reason = budget.post_check()
            if post_reason:
                _set_soft_stop(post_reason)

            return SagaStepResult(
                result=step_result.result,
                pause=step_result.pause,
                meta={
                    **meta,
                    "usage": usage,
                    "cost": cost,
                    "budget": budget.snapshot(),
                    "stop_reason": state.get("stop_reason") if state.get("terminal_stop") else meta.get("stop_reason", "ok"),
                },
            )

        def _build_plan(request_text: str) -> Dict[str, Any]:
            return {
                "task_type": task_type,
                "mode": mode,
                "request": request_text,
                "success_criteria": ["schema_gate_pass", "quality_gate_pass"],
                "format_hint": format_hint,
                "output_schema": output_schema,
                "constraints": payload.get("constraints") or {},
            }

        async def plan_step_impl() -> SagaStepResult:
            if not user_request:
                _set_soft_stop("schema_parse_error_unrepairable")
                return SagaStepResult(
                    result={"stop_reason": state["stop_reason"]},
                    meta={"stop_reason": state["stop_reason"], "step_contract": "plan"},
                )

            adapter_out = await _call_llm_adapter("plan", {"user_request": user_request}, _build_plan(user_request))
            plan = _extract_output_fields(adapter_out.get("output")) or _build_plan(user_request)
            state["plan"] = plan
            _capture_raw_response("plan", adapter_out.get("raw_response"))

            return SagaStepResult(
                result={"plan": plan},
                meta={
                    "stop_reason": "ok",
                    "step_contract": "plan",
                    "usage": adapter_out.get("usage"),
                    "cost": adapter_out.get("cost"),
                    "model": adapter_out.get("model"),
                    "artifacts": adapter_out.get("artifacts") or {},
                },
            )

        async def execute_step_impl() -> SagaStepResult:
            quorum_cfg = policy.get("quorum") if isinstance(policy.get("quorum"), dict) else {}
            quorum_caps = policy.get("quorum_caps") if isinstance(policy.get("quorum_caps"), dict) else {}
            quorum_enabled = bool(quorum_cfg.get("enabled"))
            candidate_count = int(quorum_cfg.get("candidates") or (2 if quorum_enabled else 1))
            max_candidates_cap = int(quorum_caps.get("max_candidates") or 5)
            candidate_count = max(1, min(candidate_count, max(1, max_candidates_cap)))
            candidate_concurrency = int(quorum_cfg.get("concurrency") or min(3, candidate_count))
            max_concurrency_cap = int(quorum_caps.get("max_concurrency") or 3)
            candidate_concurrency = max(1, min(candidate_concurrency, candidate_count, max(1, max_concurrency_cap)))
            per_candidate_timeout_sec = float(
                quorum_cfg.get("per_candidate_timeout_seconds")
                or quorum_caps.get("per_candidate_timeout_seconds")
                or 30.0
            )

            candidates: List[Dict[str, Any]] = []
            total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            total_cost_units = 0.0
            provider = None
            model = None
            timed_out_candidates = 0

            semaphore = asyncio.Semaphore(candidate_concurrency)

            async def _generate_candidate(index: int) -> Dict[str, Any]:
                fallback = {
                    "answer": f"Draft response {index + 1} for: {user_request}",
                    "task_type": task_type,
                }
                async with semaphore:
                    started_at = time.perf_counter()
                    timed_out = False
                    try:
                        adapter_out = await asyncio.wait_for(
                            _call_llm_adapter(
                                "execute",
                                {"plan": state.get("plan"), "user_request": user_request, "candidate_index": index},
                                fallback,
                            ),
                            timeout=max(0.1, per_candidate_timeout_sec),
                        )
                    except asyncio.TimeoutError:
                        timed_out = True
                        adapter_out = {
                            "output": fallback,
                            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                            "cost": {"units": 0.0, "provider": "timeout", "model": "timeout"},
                            "model": {"provider": "timeout", "model": "timeout"},
                            "raw_response": None,
                        }
                    latency_ms = int((time.perf_counter() - started_at) * 1000)
                candidate_output = _extract_output_fields(adapter_out.get("output"))
                return {
                    "index": index,
                    "output": candidate_output,
                    "usage": adapter_out.get("usage") or {},
                    "cost": adapter_out.get("cost") or {},
                    "model": adapter_out.get("model") or {},
                    "raw_response": adapter_out.get("raw_response"),
                    "latency_ms": latency_ms,
                    "timed_out": timed_out,
                }

            generated_candidates = await asyncio.gather(*[_generate_candidate(index) for index in range(candidate_count)])

            for candidate in generated_candidates:
                candidates.append(candidate)
                if bool(candidate.get("timed_out")):
                    timed_out_candidates += 1

                candidate_payload = {
                    "index": candidate.get("index"),
                    "output": candidate.get("output"),
                    "usage": candidate.get("usage"),
                    "cost": candidate.get("cost"),
                    "model": candidate.get("model"),
                    "latency_ms": candidate.get("latency_ms"),
                    "timed_out": candidate.get("timed_out"),
                }
                candidate_ref = _artifact_ref("execute", "candidate", candidate_payload)
                if candidate_ref:
                    candidate["artifact_ref"] = candidate_ref
                state["artifacts"]["candidates"].append(candidate)
                _capture_raw_response("execute", candidate.get("raw_response"), extra={"candidate": candidate.get("index", 0)})

                usage = candidate["usage"]
                total_usage["input_tokens"] += int(usage.get("input_tokens") or 0)
                total_usage["output_tokens"] += int(usage.get("output_tokens") or 0)
                total_usage["total_tokens"] += int(usage.get("total_tokens") or 0)
                total_cost_units += float((candidate["cost"] or {}).get("units") or 0.0)
                provider = provider or (candidate["cost"] or {}).get("provider") or (candidate["model"] or {}).get("provider")
                model = model or (candidate["cost"] or {}).get("model") or (candidate["model"] or {}).get("model")

            state["candidates"] = candidates
            state["draft_output"] = candidates[0]["output"] if candidates else {}

            return SagaStepResult(
                result={"draft_output": state["draft_output"], "candidates": candidates},
                meta={
                    "stop_reason": "ok",
                    "step_contract": "execute",
                    "usage": total_usage,
                    "cost": {"units": round(total_cost_units, 6), "provider": provider or "mock", "model": model or "mock-model"},
                    "model": {"provider": provider or "mock", "model": model or "mock-model"},
                    "artifacts": {
                        "candidates_count": len(candidates),
                        "candidate_concurrency": candidate_concurrency,
                        "per_candidate_timeout_seconds": per_candidate_timeout_sec,
                        "candidate_latencies_ms": [int(c.get("latency_ms") or 0) for c in candidates],
                        "timed_out_candidates": timed_out_candidates,
                    },
                },
            )

        async def validate_step_impl() -> SagaStepResult:
            candidates = state.get("candidates") or [{"index": 0, "output": state.get("draft_output")}]
            best_candidate: Optional[Dict[str, Any]] = None
            best_report: Optional[Dict[str, Any]] = None
            best_rank: Optional[Tuple[int, int, int, float, int]] = None
            candidate_reports: List[Dict[str, Any]] = []

            for candidate in candidates:
                raw_output = candidate.get("output")
                schema_gate = _schema_validate(raw_output)
                quality_gate = _quality_validate(raw_output, schema_gate)
                combined = {
                    "candidate_index": candidate.get("index", 0),
                    "schema_gate": schema_gate,
                    "quality_gate": quality_gate,
                }
                candidate_reports.append(combined)

                schema_ok = bool(schema_gate.get("is_pass"))
                quality_ok = bool(quality_gate.get("is_pass"))
                score = int(quality_gate.get("score") or 0)
                cost_units = float((candidate.get("cost") or {}).get("units") or 0.0)
                output_len = len(_safe_json(schema_gate.get("normalized_output") or {}))
                rank = (1 if schema_ok else 0, 1 if quality_ok else 0, score, -cost_units, -output_len)
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    best_candidate = candidate
                    best_report = combined

            best_output = _extract_output_fields((best_candidate or {}).get("output"))
            state["draft_output"] = best_output

            schema_gate = (best_report or {}).get("schema_gate") or {"is_pass": False, "violations": []}
            quality_gate = (best_report or {}).get("quality_gate") or {"is_pass": False, "score": 0, "violations": []}
            is_pass = bool(schema_gate.get("is_pass")) and bool(quality_gate.get("is_pass"))
            stop_reason = "validation_passed" if is_pass else (
                str(schema_gate.get("stop_reason") or "schema_contract_violation") if not schema_gate.get("is_pass") else "quality_failed"
            )
            pass_score = int((policy.get("thresholds") or {}).get("pass_score") or 85)
            judge_trace = build_judge_trace(
                schema_gate=schema_gate,
                quality_gate=quality_gate,
                candidate_reports=candidate_reports,
                pass_score=pass_score,
                policy=resolve_judge_cascade_policy(policy),
            )

            report = {
                "is_pass": is_pass,
                "score": quality_gate.get("score") or 0,
                "schema_gate": schema_gate,
                "quality_gate": quality_gate,
                "candidate_reports": candidate_reports,
                "stop_reason": stop_reason,
                "judge_trace": judge_trace,
            }
            state["validation_report"] = report
            validator_ref = _artifact_ref("validate", "validator_report", report)
            state["artifacts"]["validator_report"] = validator_ref or report
            judge_ref = _artifact_ref("validate", "judge_trace", judge_trace)
            state["artifacts"]["judge_trace"] = judge_ref or judge_trace
            state["stop_reason"] = stop_reason

            if not is_pass and max_repairs <= 0:
                _set_soft_stop(stop_reason)

            return SagaStepResult(
                result={"validation_report": report, "draft_output": best_output},
                meta={
                    "step_contract": "validate",
                    "stop_reason": stop_reason,
                    "quality": {"score": report["score"], "is_pass": is_pass, "violations": quality_gate.get("violations")},
                    "schema": {"is_pass": schema_gate.get("is_pass"), "violations": schema_gate.get("violations")},
                    "judge": judge_trace,
                    "artifacts": {"validator_report": report, "judge_trace": judge_trace},
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                    "cost": {"units": 0.0, "provider": "internal", "model": "validator"},
                },
            )

        async def repair_loop_step_impl() -> SagaStepResult:
            report = state.get("validation_report") or {}
            if report.get("is_pass"):
                state["best_output"] = _extract_output_fields(state.get("draft_output"))
                state["stop_reason"] = "validation_passed"
                return SagaStepResult(
                    result={"best_output": state["best_output"], "repair_attempts": 0},
                    meta={"step_contract": "repair_loop", "stop_reason": "validation_passed", "repair_attempts": 0},
                )

            if repair_strategy == "none":
                state["best_output"] = _extract_output_fields(state.get("draft_output"))
                _set_soft_stop("max_repairs_reached")
                return SagaStepResult(
                    result={"best_output": state["best_output"], "validation_report": report},
                    meta={
                        "step_contract": "repair_loop",
                        "stop_reason": state["stop_reason"],
                        "repair_attempts": 0,
                        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                        "cost": {"units": 0.0, "provider": "internal", "model": "repair:none"},
                    },
                )

            original = _extract_output_fields(state.get("draft_output"))
            current = original
            cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            cumulative_cost = 0.0
            provider = None
            model = None

            for attempt in range(1, max_repairs + 1):
                if repair_strategy == "patch":
                    adapter_out = {
                        "output": _fallback_repair_patch(current, report, attempt),
                        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                        "cost": {"units": 0.0, "provider": "internal", "model": "repair:patch"},
                        "model": {"provider": "internal", "model": "repair:patch"},
                        "raw_response": None,
                    }
                else:
                    adapter_out = await _call_llm_adapter(
                        "repair_loop",
                        {
                            "original_output": current,
                            "validator_report": report,
                            "plan": state.get("plan"),
                            "constraints": payload.get("constraints") or {},
                            "attempt": attempt,
                        },
                        current,
                    )

                repaired = _extract_output_fields(adapter_out.get("output"))
                if repaired == current and repair_strategy == "llm":
                    repaired = _fallback_repair_patch(current, report, attempt)
                schema_gate = _schema_validate(repaired)
                quality_gate = _quality_validate(repaired, schema_gate)
                repaired_pass = bool(schema_gate.get("is_pass")) and bool(quality_gate.get("is_pass"))

                usage = adapter_out.get("usage") if isinstance(adapter_out.get("usage"), dict) else {}
                cost = adapter_out.get("cost") if isinstance(adapter_out.get("cost"), dict) else {}
                cumulative_usage["input_tokens"] += int(usage.get("input_tokens") or 0)
                cumulative_usage["output_tokens"] += int(usage.get("output_tokens") or 0)
                cumulative_usage["total_tokens"] += int(usage.get("total_tokens") or 0)
                cumulative_cost += float(cost.get("units") or 0.0)
                provider = provider or cost.get("provider") or (adapter_out.get("model") or {}).get("provider")
                model = model or cost.get("model") or (adapter_out.get("model") or {}).get("model")

                repair_diff = {
                    "attempt": attempt,
                    "before_hash": _fingerprint(current),
                    "after_hash": _fingerprint(repaired),
                    "schema_ok": schema_gate.get("is_pass"),
                    "quality_ok": quality_gate.get("is_pass"),
                    "score": quality_gate.get("score"),
                }
                repair_ref = _artifact_ref("repair_loop", "repair_diff", repair_diff)
                if repair_ref:
                    repair_diff = {**repair_diff, "artifact_ref": repair_ref}
                state["artifacts"]["repair_diffs"].append(repair_diff)
                _capture_raw_response("repair_loop", adapter_out.get("raw_response"), extra={"attempt": attempt})

                state["repair_attempts"] = attempt
                current = repaired
                report = {
                    "is_pass": repaired_pass,
                    "score": quality_gate.get("score") or 0,
                    "schema_gate": schema_gate,
                    "quality_gate": quality_gate,
                    "stop_reason": "validation_passed" if repaired_pass else (
                        str(schema_gate.get("stop_reason") or "schema_contract_violation") if not schema_gate.get("is_pass") else "quality_failed"
                    ),
                }
                state["validation_report"] = report

                if repaired_pass:
                    state["best_output"] = repaired
                    state["stop_reason"] = "validation_passed"
                    return SagaStepResult(
                        result={"best_output": repaired, "validation_report": report, "repair_attempts": attempt},
                        meta={
                            "step_contract": "repair_loop",
                            "stop_reason": "validation_passed",
                            "repair_attempts": attempt,
                            "usage": cumulative_usage,
                            "cost": {"units": round(cumulative_cost, 6), "provider": provider or "mock", "model": model or "mock-model"},
                            "model": {"provider": provider or "mock", "model": model or "mock-model"},
                            "artifacts": {"repair_diffs": list(state["artifacts"].get("repair_diffs") or [])},
                        },
                    )

            state["best_output"] = current
            _set_soft_stop("max_repairs_reached")
            return SagaStepResult(
                result={"best_output": current, "validation_report": state.get("validation_report")},
                meta={
                    "step_contract": "repair_loop",
                    "stop_reason": state["stop_reason"],
                    "repair_attempts": state.get("repair_attempts") or max_repairs,
                    "usage": cumulative_usage,
                    "cost": {"units": round(cumulative_cost, 6), "provider": provider or "mock", "model": model or "mock-model"},
                    "model": {"provider": provider or "mock", "model": model or "mock-model"},
                    "artifacts": {"repair_diffs": list(state["artifacts"].get("repair_diffs") or [])},
                },
            )

        def _apply_format_contract(best_output: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
            if format_hint == "markdown":
                lines = ["# Result", ""]
                for key, value in best_output.items():
                    lines.append(f"- **{key}**: {value}")
                formatted = "\n".join(lines)
                return formatted, {"is_pass": isinstance(formatted, str), "kind": "markdown"}

            if format_hint == "shopping_list":
                items = best_output.get("items") if isinstance(best_output.get("items"), list) else []
                if not items:
                    items = [str(value) for value in best_output.values()]
                formatted = {"shopping_list": [str(item) for item in items if str(item).strip()]}
                return formatted, {"is_pass": isinstance(formatted, dict) and "shopping_list" in formatted, "kind": "shopping_list"}

            formatted = {
                "schema_version": "v1",
                "task_type": task_type,
                "output": best_output,
            }
            return formatted, {"is_pass": isinstance(formatted, dict) and "output" in formatted, "kind": "json_object"}

        async def format_step_impl() -> SagaStepResult:
            best_output = state.get("best_output") or _extract_output_fields(state.get("draft_output"))
            formatted_output, format_validation = _apply_format_contract(best_output)
            if not format_validation.get("is_pass"):
                _set_soft_stop("schema_contract_violation")

            state["formatted_output"] = formatted_output
            return SagaStepResult(
                result={"formatted_output": formatted_output},
                meta={
                    "step_contract": "format",
                    "stop_reason": state.get("stop_reason") if state.get("terminal_stop") else "ok",
                    "format_validation": format_validation,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                    "cost": {"units": 0.0, "provider": "internal", "model": "formatter"},
                },
            )

        async def _record_phase4_metrics(final_response: Dict[str, Any]) -> None:
            try:
                pass_at_1 = bool(final_response.get("stop_reason") == "validation_passed" and int(final_response.get("repair_attempts") or 0) == 0)
                pass_at_final = bool(final_response.get("stop_reason") == "validation_passed")
                repair_attempts = int(final_response.get("repair_attempts") or 0)
                stop_reason = str(final_response.get("stop_reason") or "unknown")

                prom = getattr(self, "prom_metrics", None)
                if prom and hasattr(prom, "record_adapter_call"):
                    prom.record_adapter_call("llm_pipeline", "pass_at_1", "success" if pass_at_1 else "failure")
                    prom.record_adapter_call("llm_pipeline", "pass_at_final", "success" if pass_at_final else "failure")
                    prom.record_adapter_call("llm_pipeline", "repair_rate", "repair" if repair_attempts > 0 else "no_repair")
                    prom.record_adapter_call("llm_pipeline", "stop_reason", stop_reason)

                collector = getattr(self, "metrics_collector", None)
                if collector and hasattr(collector, "record_saga_succeeded") and pass_at_final:
                    collector.record_saga_succeeded()
                if collector and hasattr(collector, "record_saga_failed") and not pass_at_final:
                    collector.record_saga_failed()
            except Exception:
                return

        async def finalize_step_impl() -> SagaStepResult:
            stop_reason = state.get("stop_reason") or "ok"
            stop_meta = _classify_stop_reason(stop_reason)
            final_policy_snapshot = build_policy_snapshot(policy, mode=mode, task_type=task_type)
            final_response = {
                "saga_id": saga_id,
                "pipeline": "llm_pipeline@v1",
                "task_type": task_type,
                "mode": mode,
                "stop_reason": stop_reason,
                "stop_category": stop_meta["stop_category"],
                "stop_severity": stop_meta["stop_severity"],
                "repair_attempts": state.get("repair_attempts") or 0,
                "pricing_version": policy.get("pricing_version"),
                "policy": {
                    "version": policy.get("policy_version"),
                    "pricing_version": policy.get("pricing_version"),
                    "mode": mode,
                    "quorum": policy.get("quorum") or {"enabled": False},
                    "thresholds": policy.get("thresholds") or {},
                    "snapshot_fingerprint": final_policy_snapshot.get("fingerprint"),
                },
                "policy_snapshot": final_policy_snapshot,
                "budget": budget.snapshot(),
                "artifacts": state.get("artifacts") or {},
                "result": state.get("formatted_output") or {},
            }

            if artifact_store_enabled and isinstance(final_response.get("artifacts"), dict):
                policy_snapshot_ref = _artifact_ref("finalize", "policy_snapshot", final_policy_snapshot)
                if policy_snapshot_ref:
                    final_response["artifacts"]["policy_snapshot_ref"] = policy_snapshot_ref
                final_artifact_ref = _artifact_ref("finalize", "final_response", final_response)
                if final_artifact_ref:
                    final_response["artifacts"]["final_response_ref"] = final_artifact_ref

            await _record_phase4_metrics(final_response)
            return SagaStepResult(
                result={"final_response": final_response, "stop_reason": final_response["stop_reason"]},
                meta={"stop_reason": final_response["stop_reason"], "step_contract": "finalize", "budget": budget.snapshot()},
            )

        async def plan_step() -> SagaStepResult:
            return await _run_budgeted_step("plan", {"user_request": user_request, "task_type": task_type, "mode": mode}, plan_step_impl)

        async def execute_step() -> SagaStepResult:
            return await _run_budgeted_step("execute", {"plan": state.get("plan"), "task_type": task_type}, execute_step_impl)

        async def validate_step() -> SagaStepResult:
            return await _run_budgeted_step(
                "validate",
                {"draft_output": state.get("draft_output"), "required_fields": required_fields, "output_schema": output_schema},
                validate_step_impl,
            )

        async def repair_loop_step() -> SagaStepResult:
            return await _run_budgeted_step(
                "repair_loop",
                {"validation_report": state.get("validation_report"), "max_repairs": max_repairs, "constraints": payload.get("constraints") or {}},
                repair_loop_step_impl,
            )

        async def format_step() -> SagaStepResult:
            return await _run_budgeted_step("format", {"best_output": state.get("best_output"), "format_hint": format_hint}, format_step_impl)

        async def finalize_step() -> SagaStepResult:
            step_result, _cache_hit = await _run_idempotent_step(
                "finalize",
                {"formatted_output": state.get("formatted_output"), "stop_reason": state.get("stop_reason")},
                finalize_step_impl,
            )
            return step_result

        step_plan = [
            SagaStepDefinition(name="plan", execute=plan_step, adapter_type="llm"),
            SagaStepDefinition(name="execute", execute=execute_step, adapter_type="llm"),
            SagaStepDefinition(name="validate", execute=validate_step, adapter_type="validator"),
            SagaStepDefinition(name="repair_loop", execute=repair_loop_step, adapter_type="llm"),
            SagaStepDefinition(name="format", execute=format_step, adapter_type="formatter"),
            SagaStepDefinition(name="finalize", execute=finalize_step, adapter_type=None),
        ]

        return await self.execute_step_plan(
            saga_id=saga_id,
            saga_type=self.saga_type,
            payload=payload,
            steps=steps,
            step_plan=step_plan,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
