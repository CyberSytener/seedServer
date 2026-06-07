from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from app.contracts import ContractIssue
from app.core.blocks import BlockRegistry, build_default_registry
from app.services.module_registry import ModuleRegistry


@dataclass(frozen=True)
class ResolvedFlowModule:
    module_id: str
    source: str
    executable_in_flow: bool
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    contract_issues: tuple[ContractIssue, ...] = ()


def _types(schema: Mapping[str, Any]) -> Set[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


class FlowContractValidator:
    def __init__(
        self,
        *,
        module_registry: Optional[ModuleRegistry] = None,
        block_registry: Optional[BlockRegistry] = None,
    ) -> None:
        self.module_registry = module_registry or ModuleRegistry()
        self.block_registry = block_registry or build_default_registry()

    def resolve_module(self, module_id: str) -> Optional[ResolvedFlowModule]:
        module_spec = self.module_registry.get_module(module_id)
        if module_spec is not None:
            execution_adapter = self.module_registry.execution_adapter(module_spec)
            return ResolvedFlowModule(
                module_id=module_id,
                source="module_contract_v1",
                executable_in_flow=(
                    execution_adapter == "block_registry"
                    and module_id in self.block_registry.list_blocks()
                ),
                input_schema=module_spec.get("input_schema")
                if isinstance(module_spec.get("input_schema"), dict)
                else {},
                output_schema=module_spec.get("output_schema")
                if isinstance(module_spec.get("output_schema"), dict)
                else {},
                contract_issues=tuple(self.module_registry.validate_contract(module_spec)),
            )

        if module_id in self.block_registry.list_blocks():
            metadata = self.block_registry.get_metadata(module_id)
            return ResolvedFlowModule(
                module_id=module_id,
                source="block_metadata",
                executable_in_flow=True,
                input_schema=metadata.input_schema,
                output_schema=metadata.output_schema,
            )
        return None

    def validate_graph(
        self,
        nodes: Iterable[Mapping[str, Any]],
        edges: Iterable[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        node_map: Dict[str, Mapping[str, Any]] = {}
        resolved: Dict[str, ResolvedFlowModule] = {}
        issues: List[ContractIssue] = []

        for index, node in enumerate(nodes):
            node_id = str(node.get("node_id") or "").strip()
            module_id = str(node.get("module_id") or "").strip()
            path = f"$.graph.nodes.{index}"
            if not node_id:
                issues.append(
                    ContractIssue(code="flow.node_id_required", path=path, message="flow node requires node_id")
                )
                continue
            if node_id in node_map:
                issues.append(
                    ContractIssue(
                        code="flow.duplicate_node_id",
                        path=f"{path}.node_id",
                        message=f"duplicate node_id '{node_id}'",
                    )
                )
                continue
            node_map[node_id] = node
            if not module_id:
                issues.append(
                    ContractIssue(
                        code="flow.module_id_required",
                        path=f"{path}.module_id",
                        message=f"node '{node_id}' requires module_id",
                    )
                )
                continue
            resolved_module = self.resolve_module(module_id)
            if resolved_module is None:
                issues.append(
                    ContractIssue(
                        code="flow.module_not_found",
                        path=f"{path}.module_id",
                        message=f"module '{module_id}' is not present in module or block registry",
                    )
                )
                continue
            resolved[node_id] = resolved_module
            for contract_issue in resolved_module.contract_issues:
                issues.append(
                    ContractIssue(
                        code="flow.module_contract_invalid",
                        path=f"{path}.module_id",
                        message=(
                            f"module '{module_id}' failed {contract_issue.code} at "
                            f"{contract_issue.path}: {contract_issue.message}"
                        ),
                    )
                )
            if not resolved_module.executable_in_flow:
                issues.append(
                    ContractIssue(
                        code="flow.module_not_executable",
                        path=f"{path}.module_id",
                        message=f"module '{module_id}' has no flow execution adapter",
                    )
                )

        checked_edges = 0
        for index, edge in enumerate(edges):
            source_id = str(edge.get("from") or "").strip()
            target_id = str(edge.get("to") or "").strip()
            path = f"$.graph.edges.{index}"
            if source_id not in node_map:
                issues.append(
                    ContractIssue(
                        code="flow.source_node_not_found",
                        path=f"{path}.from",
                        message=f"source node '{source_id}' was not found",
                    )
                )
                continue
            if target_id not in node_map:
                issues.append(
                    ContractIssue(
                        code="flow.target_node_not_found",
                        path=f"{path}.to",
                        message=f"target node '{target_id}' was not found",
                    )
                )
                continue
            producer = resolved.get(source_id)
            consumer = resolved.get(target_id)
            if producer is None or consumer is None:
                continue
            checked_edges += 1
            issues.extend(self._validate_edge(path=path, edge=edge, producer=producer, consumer=consumer))

        sorted_issues = sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
        return {
            "ok": len(sorted_issues) == 0,
            "checked_nodes": len(resolved),
            "checked_edges": checked_edges,
            "sources": {node_id: module.source for node_id, module in sorted(resolved.items())},
            "issues": [issue.model_dump() for issue in sorted_issues],
            "errors": [issue.as_message() for issue in sorted_issues],
        }

    @staticmethod
    def _validate_edge(
        *,
        path: str,
        edge: Mapping[str, Any],
        producer: ResolvedFlowModule,
        consumer: ResolvedFlowModule,
    ) -> List[ContractIssue]:
        mapping = edge.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            return [
                ContractIssue(
                    code="flow.edge_mapping_required",
                    path=f"{path}.mapping",
                    message="contract validation requires an explicit target-to-source field mapping",
                )
            ]

        issues: List[ContractIssue] = []
        producer_properties = (
            producer.output_schema.get("properties")
            if isinstance(producer.output_schema.get("properties"), dict)
            else {}
        )
        producer_required = (
            producer.output_schema.get("required")
            if isinstance(producer.output_schema.get("required"), list)
            else []
        )
        consumer_properties = (
            consumer.input_schema.get("properties")
            if isinstance(consumer.input_schema.get("properties"), dict)
            else {}
        )
        consumer_required = (
            consumer.input_schema.get("required")
            if isinstance(consumer.input_schema.get("required"), list)
            else []
        )

        for target_field_raw, source_field_raw in mapping.items():
            target_field = str(target_field_raw or "").strip()
            source_field = str(source_field_raw or "").strip()
            field_path = f"{path}.mapping.{target_field or 'unknown'}"
            source_schema = producer_properties.get(source_field)
            target_schema = consumer_properties.get(target_field)
            if not isinstance(source_schema, dict):
                issues.append(
                    ContractIssue(
                        code="flow.source_field_not_found",
                        path=field_path,
                        message=f"module '{producer.module_id}' does not declare output field '{source_field}'",
                    )
                )
                continue
            if not isinstance(target_schema, dict):
                issues.append(
                    ContractIssue(
                        code="flow.target_field_not_found",
                        path=field_path,
                        message=f"module '{consumer.module_id}' does not declare input field '{target_field}'",
                    )
                )
                continue
            if target_field in consumer_required and source_field not in producer_required:
                issues.append(
                    ContractIssue(
                        code="flow.required_output_not_guaranteed",
                        path=field_path,
                        message=(
                            f"module '{producer.module_id}' does not guarantee output '{source_field}' "
                            f"required by '{consumer.module_id}.{target_field}'"
                        ),
                    )
                )
            source_types = _types(source_schema)
            target_types = _types(target_schema)
            if source_types and target_types and not source_types.issubset(target_types):
                issues.append(
                    ContractIssue(
                        code="flow.field_type_mismatch",
                        path=field_path,
                        message=(
                            f"module '{producer.module_id}.{source_field}' types {sorted(source_types)} "
                            f"are not accepted by '{consumer.module_id}.{target_field}' types {sorted(target_types)}"
                        ),
                    )
                )
        return issues
