from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.blocks import BlockRegistry, build_default_registry
from app.core.expression_engine import resolve_inputs_with_expressions
from app.core.realtime.engine import BaseSaga, SagaStepDefinition, SagaStepResult
from app.core.realtime.sagas.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

_CONTEXT_ROOTS = {"payload", "request", "user_id", "persona", "scan_id"}

# Block types that emit ``_route`` in their output for conditional routing
_ROUTING_BLOCKS = {"if_block", "switch_block"}


class FlowExecutorSaga(BaseSaga):
    """Execute a compiled flow graph as a saga with per-node timeline + artifacts."""

    saga_type = "flow_executor"

    def __init__(self, engine: Any, *, registry: Optional[BlockRegistry] = None):
        super().__init__(engine)
        self._registry = registry or build_default_registry()

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        if not nodes:
            raise ValueError("flow_executor requires graph.nodes")

        node_map = {
            str(node.get("node_id") or ""): node
            for node in nodes
            if isinstance(node, dict) and str(node.get("node_id") or "").strip()
        }
        if not node_map:
            raise ValueError("flow_executor graph has no valid node_id values")

        execution_order = self._topological_order(node_map, edges)
        incoming_edges: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        outgoing_nodes: Dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("from") or "").strip()
            dst = str(edge.get("to") or "").strip()
            if not src or not dst:
                continue
            incoming_edges[dst].append(edge)
            outgoing_nodes[src].add(dst)

        request_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        user_id = str(request_input.get("user_id") or payload.get("user_id") or "flow_executor")
        persona = request_input.get("persona") if isinstance(request_input.get("persona"), dict) else {}
        scan_id = str(request_input.get("scan_id") or payload.get("scan_id") or str(uuid.uuid4()))
        context: Dict[str, Any] = {
            "payload": request_input,
            "request": request_input,
            "user_id": user_id,
            "persona": persona,
            "scan_id": scan_id,
        }

        artifact_store_enabled = bool(payload.get("artifact_store_enabled", True))
        artifact_store = ArtifactStore() if artifact_store_enabled else None
        node_outputs: Dict[str, Dict[str, Any]] = {}
        timeline: List[Dict[str, Any]] = []
        artifact_refs: List[Dict[str, Any]] = []

        def _store_artifact(step_name: str, kind: str, artifact_payload: Any) -> Optional[Dict[str, Any]]:
            if artifact_store is None:
                return None
            try:
                ref = artifact_store.store(
                    saga_id=saga_id,
                    step=step_name,
                    kind=kind,
                    payload=artifact_payload,
                )
            except Exception:
                return None
            artifact_refs.append(ref)
            return ref

        def _resolve_path(source: Any, path: str) -> Any:
            current = source
            for key in [item for item in str(path or "").split(".") if item]:
                if isinstance(current, dict):
                    current = current.get(key)
                    continue
                if isinstance(current, list):
                    try:
                        current = current[int(key)]
                    except Exception:
                        return None
                    continue
                return None
            return current

        def _resolve_source_value(source_node: str, source_key: str) -> Any:
            if source_node in _CONTEXT_ROOTS:
                source_root = context.get(source_node)
            else:
                source_root = node_outputs.get(source_node)
            if source_key:
                return _resolve_path(source_root, source_key)
            return source_root

        def _resolve_node_inputs(node_id: str, node_config: Dict[str, Any]) -> Dict[str, Any]:
            resolved: Dict[str, Any] = {}
            explicit_inputs = node_config.get("inputs")
            if isinstance(explicit_inputs, dict):
                resolved.update(explicit_inputs)

            for edge in incoming_edges.get(node_id, []):
                source_node = str(edge.get("from") or "").strip()
                mapping = edge.get("mapping")
                if not isinstance(mapping, dict) or not mapping:
                    resolved[source_node] = _resolve_source_value(source_node, "")
                    continue

                for target_key, source_key in mapping.items():
                    target_field = str(target_key or "").strip()
                    source_field = str(source_key or "").strip()
                    if not target_field:
                        continue
                    resolved[target_field] = _resolve_source_value(source_node, source_field)
            return resolved

        def _node_params(node_config: Dict[str, Any]) -> Dict[str, Any]:
            params = node_config.get("params")
            if isinstance(params, dict):
                return dict(params)
            reserved = {"inputs", "params", "retry", "timeout", "budget_slice"}
            return {key: value for key, value in node_config.items() if key not in reserved}

        def _retry_config(node: Dict[str, Any]) -> Tuple[int, float]:
            retry = node.get("retry")
            if not isinstance(retry, dict):
                return 1, 0.0
            max_attempts = int(retry.get("max_attempts") or retry.get("retries") or 1)
            max_attempts = max(1, min(max_attempts, 10))
            backoff_ms = float(retry.get("backoff_ms") or retry.get("jitter_ms") or 0.0)
            return max_attempts, max(0.0, min(backoff_ms, 10_000.0))

        # ── Routing helpers ───────────────────────────────────────
        # Track which nodes are *skipped* due to conditional routing
        skipped_nodes: Set[str] = set()

        # Build edge-branch index: edges may carry a ``branch`` label
        # so that IF/Switch nodes can activate only the matching branch.
        edge_branches: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            if isinstance(edge, dict):
                src = str(edge.get("from") or "").strip()
                if src:
                    edge_branches[src].append(edge)

        def _should_skip(node_id: str, node: Dict[str, Any]) -> bool:
            """Return True if the node should be skipped."""
            # Explicitly disabled by user
            if node.get("disabled"):
                return True
            # All upstream sources were skipped → propagate skip
            sources = {str(e.get("from") or "").strip() for e in incoming_edges.get(node_id, [])}
            sources.discard("")
            if sources and sources.issubset(skipped_nodes):
                return True
            return False

        def _apply_routing(node_id: str, output: Dict[str, Any]) -> None:
            """If a routing block, mark non-matching downstream edges for skip."""
            route_value = output.get("_route")
            if route_value is None:
                return
            module_id_local = str((node_map.get(node_id) or {}).get("module_id") or "")
            if module_id_local not in _ROUTING_BLOCKS:
                return
            for edge in edge_branches.get(node_id, []):
                branch_label = str(edge.get("branch") or "").strip()
                dst = str(edge.get("to") or "").strip()
                if not dst or not branch_label:
                    continue
                if branch_label != str(route_value):
                    skipped_nodes.add(dst)
                    logger.debug("Routing: skip %s (branch=%s, route=%s)", dst, branch_label, route_value)

        # ── Topological-level grouping for parallel execution ────
        def _group_by_level(order: List[str], edges_list: List[Dict[str, Any]]) -> List[List[str]]:
            """Group topologically-sorted nodes into levels for parallel exec."""
            level_of: Dict[str, int] = {}
            for nid in order:
                max_parent = -1
                for edge in incoming_edges.get(nid, []):
                    src = str(edge.get("from") or "").strip()
                    if src in level_of:
                        max_parent = max(max_parent, level_of[src])
                level_of[nid] = max_parent + 1

            levels: Dict[int, List[str]] = defaultdict(list)
            for nid in order:
                levels[level_of[nid]].append(nid)
            return [levels[i] for i in sorted(levels)]

        execution_levels = _group_by_level(execution_order, edges)

        # ── Node execution ────────────────────────────────────────
        async def _run_single_node(node_id: str) -> Optional[SagaStepResult]:
            node = node_map.get(node_id) or {}
            module_id = str(node.get("module_id") or "").strip()
            node_config = node.get("config") if isinstance(node.get("config"), dict) else {}
            if not module_id:
                raise ValueError(f"flow node '{node_id}' missing module_id")

            # Skip check
            if _should_skip(node_id, node):
                skipped_nodes.add(node_id)
                timeline.append({
                    "node_id": node_id,
                    "module_id": module_id,
                    "status": "skipped",
                    "attempts": 0,
                    "elapsed_sec": 0.0,
                    "started_at": None,
                    "ended_at": None,
                    "input_ref": None,
                    "output_ref": None,
                    "error": None,
                })
                return SagaStepResult(
                    result={},
                    meta={"node_id": node_id, "status": "skipped"},
                )

            max_attempts, backoff_ms = _retry_config(node)
            t0 = time.monotonic()
            attempts = 0
            last_error: Optional[Exception] = None
            resolved_inputs: Dict[str, Any] = {}

            # Determine previous node for $json shorthand
            prev_node_id: Optional[str] = None
            for edge in incoming_edges.get(node_id, []):
                src = str(edge.get("from") or "").strip()
                if src and src not in skipped_nodes:
                    prev_node_id = src
                    break

            while attempts < max_attempts:
                attempts += 1
                try:
                    resolved_inputs = _resolve_node_inputs(node_id, node_config)
                    # Apply expression engine on resolved inputs
                    resolved_inputs = resolve_inputs_with_expressions(
                        resolved_inputs, node_outputs, context, prev_node_id,
                    )
                    input_ref = _store_artifact(node_id, "node_input", resolved_inputs)
                    block = self._registry.create(
                        module_id,
                        engine=self,
                        params=_node_params(node_config),
                    )
                    block_output = await block.execute(context, resolved_inputs)
                    output_payload = (
                        block_output if isinstance(block_output, dict) else {"value": block_output}
                    )
                    node_outputs[node_id] = output_payload
                    context[node_id] = output_payload
                    output_ref = _store_artifact(node_id, "node_output", output_payload)
                    elapsed = round(time.monotonic() - t0, 4)

                    # Apply routing if this is a routing block
                    _apply_routing(node_id, output_payload)

                    timeline.append({
                        "node_id": node_id,
                        "module_id": module_id,
                        "status": "succeeded",
                        "attempts": attempts,
                        "elapsed_sec": elapsed,
                        "started_at": None,
                        "ended_at": None,
                        "input_ref": input_ref,
                        "output_ref": output_ref,
                        "error": None,
                    })
                    return SagaStepResult(
                        result={},
                        meta={
                            "node_id": node_id,
                            "module_id": module_id,
                            "attempts": attempts,
                            "elapsed_sec": elapsed,
                            "output_keys": sorted(output_payload.keys()),
                            "input_ref": input_ref,
                            "output_ref": output_ref,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempts < max_attempts and backoff_ms > 0:
                        await asyncio.sleep(backoff_ms / 1000.0)
                    continue

            elapsed = round(time.monotonic() - t0, 4)
            timeline.append({
                "node_id": node_id,
                "module_id": module_id,
                "status": "failed",
                "attempts": attempts,
                "elapsed_sec": elapsed,
                "started_at": None,
                "ended_at": None,
                "input_ref": _store_artifact(node_id, "node_input", resolved_inputs),
                "output_ref": None,
                "error": str(last_error) if last_error else "unknown_error",
            })
            raise RuntimeError(f"flow node '{node_id}' failed: {last_error}") from last_error

        # ── Build step plan with parallel level execution ─────────
        step_plan: List[SagaStepDefinition] = []
        for level_nodes in execution_levels:
            if len(level_nodes) == 1:
                nid = level_nodes[0]
                step_plan.append(SagaStepDefinition(
                    name=nid,
                    execute=lambda _nid=nid: _run_single_node(_nid),
                    adapter_type=str((node_map.get(nid) or {}).get("module_id") or ""),
                ))
            else:
                # Parallel execution for independent nodes at same level
                async def _run_parallel(nids: List[str] = level_nodes) -> SagaStepResult:
                    results = await asyncio.gather(
                        *[_run_single_node(nid) for nid in nids],
                        return_exceptions=True,
                    )
                    for i, res in enumerate(results):
                        if isinstance(res, Exception):
                            raise res
                    return SagaStepResult(
                        result={},
                        meta={"parallel_nodes": nids, "count": len(nids)},
                    )
                step_plan.append(SagaStepDefinition(
                    name=f"parallel_{'_'.join(level_nodes)}",
                    execute=_run_parallel,
                    adapter_type="parallel",
                ))

        async def _aggregate_step() -> SagaStepResult:
            sink_nodes = [
                node_id for node_id in execution_order if not outgoing_nodes.get(node_id)
            ]
            sink_outputs = {
                node_id: node_outputs.get(node_id, {})
                for node_id in sink_nodes
            }
            final_output: Any
            if len(sink_outputs) == 1:
                final_output = next(iter(sink_outputs.values()))
            elif sink_outputs:
                final_output = sink_outputs
            else:
                fallback_node = execution_order[-1]
                final_output = node_outputs.get(fallback_node, {})

            assertions = payload.get("assertions") if isinstance(payload.get("assertions"), dict) else {}
            assertion_report = self._evaluate_assertions(
                assertions=assertions,
                timeline=timeline,
                final_output=final_output if isinstance(final_output, dict) else {},
            )
            stop_reason = "ok" if assertion_report.get("passed") else "assertions_failed"

            return SagaStepResult(
                result={
                    "output": final_output,
                    "score": 1.0 if assertion_report.get("passed") else 0.0,
                    "stop_reason": stop_reason,
                    "timeline": timeline,
                    "artifacts": artifact_refs,
                    "assertions": assertion_report,
                },
                meta={
                    "step_contract": "aggregate",
                    "stop_reason": stop_reason,
                    "assertions": assertion_report,
                },
            )

        step_plan.append(
            SagaStepDefinition(
                name="aggregate",
                execute=_aggregate_step,
                adapter_type="flow_executor",
            )
        )

        outcome = await self.execute_step_plan(
            saga_id=saga_id,
            saga_type=self.saga_type,
            payload=payload,
            steps=steps,
            step_plan=step_plan,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        if isinstance(outcome, dict):
            result_payload = outcome.get("result")
            if not isinstance(result_payload, dict):
                result_payload = {}
                outcome["result"] = result_payload
            result_payload.setdefault("timeline", timeline)
            result_payload.setdefault("artifacts", artifact_refs)
            result_payload.setdefault("stop_reason", "ok" if outcome.get("status") == "succeeded" else "node_failed")
            outcome.setdefault("execution_trace", timeline)
            outcome.setdefault(
                "execution_mode",
                str(payload.get("execution_mode") or "LIVE").upper(),
            )
        return outcome

    @staticmethod
    def _topological_order(
        node_map: Dict[str, Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> List[str]:
        indegree: Dict[str, int] = {node_id: 0 for node_id in node_map}
        adjacency: Dict[str, List[str]] = {node_id: [] for node_id in node_map}
        insertion_order = list(node_map.keys())

        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("from") or "").strip()
            dst = str(edge.get("to") or "").strip()
            if src not in node_map or dst not in node_map:
                continue
            adjacency[src].append(dst)
            indegree[dst] += 1

        queue = deque([node_id for node_id in insertion_order if indegree[node_id] == 0])
        order: List[str] = []
        while queue:
            current = queue.popleft()
            order.append(current)
            for nxt in adjacency.get(current, []):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        if len(order) == len(node_map):
            return order
        return insertion_order

    @staticmethod
    def _evaluate_assertions(
        *,
        assertions: Dict[str, Any],
        timeline: List[Dict[str, Any]],
        final_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        failures: List[str] = []
        required_nodes = assertions.get("required_nodes")
        if isinstance(required_nodes, list):
            success_nodes = {
                str(item.get("node_id"))
                for item in timeline
                if str(item.get("status")) == "succeeded"
            }
            for node_id in required_nodes:
                normalized = str(node_id or "").strip()
                if normalized and normalized not in success_nodes:
                    failures.append(f"required_node_failed:{normalized}")

        required_fields = assertions.get("required_output_fields")
        if isinstance(required_fields, list):
            for field in required_fields:
                key = str(field or "").strip()
                if not key:
                    continue
                value = final_output.get(key) if isinstance(final_output, dict) else None
                if value is None or (isinstance(value, str) and not value.strip()):
                    failures.append(f"required_output_missing:{key}")

        forbid_errors = bool(assertions.get("forbid_errors", False))
        if forbid_errors and any(str(item.get("status")) == "failed" for item in timeline):
            failures.append("timeline_contains_failed_nodes")

        return {
            "passed": len(failures) == 0,
            "failures": failures,
        }
