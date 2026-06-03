from __future__ import annotations

import enum
import logging
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from app.core.blocks import BlockRegistry, build_default_registry
from app.core.realtime.engine import BaseSaga, SagaStepDefinition, SagaStepResult

logger = logging.getLogger(__name__)


class ExecutionMode(str, enum.Enum):
    LIVE = "LIVE"
    DRY_RUN = "DRY_RUN"


class DynamicSaga(BaseSaga):
    saga_type = "dynamic_saga"

    def __init__(
        self,
        engine: Any,
        *,
        blueprint: List[Dict[str, Any]],
        registry: Optional[BlockRegistry] = None,
        execution_mode: ExecutionMode = ExecutionMode.LIVE,
    ):
        super().__init__(engine)
        self._blueprint = blueprint
        self._registry = registry or build_default_registry()
        self._execution_mode = execution_mode

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        request_payload = self._normalize_payload(payload)
        user_id = self._resolve_user_id(payload, request_payload)
        persona = self._resolve_persona(request_payload)
        scan_id = self._resolve_scan_id(request_payload)

        context: Dict[str, Any] = {
            "payload": payload,
            "request": request_payload,
            "user_id": user_id,
            "persona": persona,
            "scan_id": scan_id,
        }

        execution_trace: List[Dict[str, Any]] = []
        is_dry_run = self._execution_mode == ExecutionMode.DRY_RUN

        class SagaStepExecutionError(RuntimeError):
            def __init__(self, step_name: str, block_type: str, error: Exception):
                super().__init__(str(error))
                self.step_name = step_name
                self.block_type = block_type
                self.error = error

        step_plan: List[SagaStepDefinition] = []
        for step in self._blueprint:
            step_name = step.get("name") or step.get("id") or "step"
            block_type = step.get("block") or step.get("block_type")
            inputs = step.get("inputs") or {}
            params = dict(step.get("params") or {})

            if not block_type:
                raise ValueError(f"Blueprint step missing block type: {step_name}")

            # --- DRY_RUN overrides ---
            if is_dry_run:
                if block_type == "job_scorer":
                    params["_force_no_persist"] = True
                if block_type == "notification_block":
                    params["_suppress_webhook"] = True

            block = self._registry.create(block_type, engine=self, params=params)

            async def _run_block(
                block=block, inputs=inputs, step_name=step_name, block_type=block_type,
            ) -> SagaStepResult:
                t0 = time.monotonic()
                trace_entry: Dict[str, Any] = {
                    "step": step_name,
                    "block": block_type,
                    "elapsed_sec": 0.0,
                    "dry_run": is_dry_run,
                }
                try:
                    resolved = self._resolve_inputs(inputs, context)
                    output = await block.execute(context, resolved)
                    elapsed = round(time.monotonic() - t0, 4)
                    trace_entry["elapsed_sec"] = elapsed
                    trace_entry["status"] = "succeeded"

                    if output:
                        if isinstance(output, dict):
                            context[step_name] = output
                            context.update(output)
                            trace_entry["output_keys"] = sorted(output.keys())
                        else:
                            context[step_name] = output
                            trace_entry["output_keys"] = []
                    execution_trace.append(trace_entry)

                    if isinstance(output, dict):
                        return SagaStepResult(result=output)
                    return SagaStepResult(result={"step": step_name})
                except Exception as exc:  # noqa: BLE001
                    trace_entry["elapsed_sec"] = round(time.monotonic() - t0, 4)
                    trace_entry["status"] = "failed"
                    trace_entry["error"] = str(exc)
                    trace_entry["failed_step_id"] = step_name
                    trace_entry["failed_block"] = block_type
                    execution_trace.append(trace_entry)
                    raise SagaStepExecutionError(step_name, block_type, exc) from exc

            step_plan.append(SagaStepDefinition(name=step_name, execute=_run_block))

        try:
            raw = await self.execute_step_plan(
                saga_id=saga_id,
                saga_type=self.saga_type,
                payload=payload,
                steps=steps,
                step_plan=step_plan,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )
        except SagaStepExecutionError as exc:
            raw = {
                "status": "failed",
                "error": str(exc),
                "failed_step_id": exc.step_name,
                "failed_block": exc.block_type,
            }

        if isinstance(raw, dict):
            raw["execution_trace"] = execution_trace
            raw["execution_mode"] = self._execution_mode.value
        return raw

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload.get("request") or payload.get("params") or payload

    @staticmethod
    def _resolve_user_id(payload: Dict[str, Any], request_payload: Dict[str, Any]) -> str:
        user_id = request_payload.get("user_id") or payload.get("user_id")
        if not user_id:
            raise ValueError("dynamic_saga requires user_id")
        return user_id

    @staticmethod
    def _resolve_persona(request_payload: Dict[str, Any]) -> Dict[str, Any]:
        return request_payload.get("persona") or request_payload

    @staticmethod
    def _resolve_scan_id(request_payload: Dict[str, Any]) -> str:
        scan_id = request_payload.get("scan_id")
        return scan_id or str(uuid.uuid4())

    @staticmethod
    def _resolve_inputs(inputs: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for key, value in inputs.items():
            resolved[key] = DynamicSaga._resolve_value(value, context)
        return resolved

    @staticmethod
    def _resolve_value(value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            if "from" in value:
                return DynamicSaga._resolve_mapping(value, context)
            return {key: DynamicSaga._resolve_value(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [DynamicSaga._resolve_value(item, context) for item in value]
        return value

    @staticmethod
    def _resolve_mapping(mapping: Dict[str, Any], context: Dict[str, Any]) -> Any:
        source = mapping.get("from")
        default = mapping.get("default")
        transforms = mapping.get("transform")

        value = DynamicSaga._resolve_path(context, source) if source is not None else None
        if value is None and "default" in mapping:
            value = default

        if transforms:
            for transform in DynamicSaga._normalize_transforms(transforms):
                value = DynamicSaga._apply_transform(transform, value, mapping)

        return value

    @staticmethod
    def _resolve_path(context: Dict[str, Any], path: str | Iterable[str]) -> Any:
        if path is None:
            return None
        if isinstance(path, str):
            parts = [part for part in path.split(".") if part]
        else:
            parts = list(path)

        current: Any = context
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    index = int(part)
                    current = current[index]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    @staticmethod
    def _normalize_transforms(transforms: Any) -> list[Dict[str, Any]]:
        if isinstance(transforms, list):
            normalized: list[Dict[str, Any]] = []
            for item in transforms:
                if isinstance(item, str):
                    normalized.append({"name": item})
                elif isinstance(item, dict):
                    normalized.append(item)
            return normalized
        if isinstance(transforms, str):
            return [{"name": transforms}]
        if isinstance(transforms, dict):
            return [transforms]
        return []

    @staticmethod
    def _apply_transform(transform: Dict[str, Any], value: Any, mapping: Dict[str, Any]) -> Any:
        name = transform.get("name") or transform.get("type")
        if not name:
            return value

        if name == "lower" and isinstance(value, str):
            return value.lower()
        if name == "upper" and isinstance(value, str):
            return value.upper()
        if name == "strip" and isinstance(value, str):
            return value.strip()
        if name == "join":
            sep = transform.get("sep", " ")
            if isinstance(value, list):
                return sep.join(str(item) for item in value)
            return value
        if name == "split" and isinstance(value, str):
            sep = transform.get("sep", " ")
            return [item for item in value.split(sep) if item]
        if name == "to_bool":
            return bool(value)
        if name == "to_int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return mapping.get("default")
        if name == "to_float":
            try:
                return float(value)
            except (TypeError, ValueError):
                return mapping.get("default")
        if name == "coalesce":
            fallback = transform.get("fallback")
            return value if value is not None else fallback
        if name == "len":
            try:
                return len(value)
            except TypeError:
                return 0

        if name == "slice":
            start = transform.get("start", 0)
            end = transform.get("end")
            try:
                start_i = int(start) if start is not None else 0
            except (TypeError, ValueError):
                start_i = 0
            try:
                end_i = int(end) if end is not None else None
            except (TypeError, ValueError):
                end_i = None
            if isinstance(value, (list, tuple, str)):
                return value[start_i:end_i]
            return value

        return value
