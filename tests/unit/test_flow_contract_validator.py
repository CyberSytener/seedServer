from __future__ import annotations

import pytest

from app.core.blocks import JobScorerBlock, build_default_registry
from app.services.flow_contract_validator import FlowContractValidator
from app.services.module_registry import ModuleRegistry


def _nodes() -> list[dict]:
    return [
        {"node_id": "scan", "module_id": "market_scanner"},
        {"node_id": "score", "module_id": "job_scorer"},
    ]


def test_flow_contract_validator_accepts_compatible_block_edge() -> None:
    report = FlowContractValidator().validate_graph(
        _nodes(),
        [{"from": "scan", "to": "score", "mapping": {"jobs": "jobs", "scan_id": "scan_id"}}],
    )

    assert report["ok"] is True
    assert report["checked_nodes"] == 2
    assert report["checked_edges"] == 1
    assert report["sources"] == {"scan": "block_metadata", "score": "block_metadata"}


def test_flow_contract_validator_rejects_field_type_mismatch() -> None:
    report = FlowContractValidator().validate_graph(
        _nodes(),
        [{"from": "scan", "to": "score", "mapping": {"jobs": "scan_id"}}],
    )

    assert report["ok"] is False
    assert any(issue["code"] == "flow.field_type_mismatch" for issue in report["issues"])


def test_flow_contract_validator_rejects_unknown_output_field() -> None:
    report = FlowContractValidator().validate_graph(
        _nodes(),
        [{"from": "scan", "to": "score", "mapping": {"jobs": "missing"}}],
    )

    assert any(issue["code"] == "flow.source_field_not_found" for issue in report["issues"])


def test_flow_contract_validator_requires_explicit_mapping() -> None:
    report = FlowContractValidator().validate_graph(
        _nodes(),
        [{"from": "scan", "to": "score"}],
    )

    assert any(issue["code"] == "flow.edge_mapping_required" for issue in report["issues"])


def test_flow_contract_validator_reports_module_without_flow_adapter() -> None:
    report = FlowContractValidator(block_registry=build_default_registry()).validate_graph(
        [{"node_id": "assistant", "module_id": "general_assistant"}],
        [],
    )

    assert any(issue["code"] == "flow.module_not_executable" for issue in report["issues"])


def test_flow_contract_validator_rejects_invalid_module_contract(tmp_path) -> None:
    (tmp_path / "invalid.yaml").write_text(
        """
contract_version: 1.0.0
mode_id: invalid_module
input_schema: {type: object}
output_schema: {type: object}
""".strip(),
        encoding="utf-8",
    )
    validator = FlowContractValidator(module_registry=ModuleRegistry(root=tmp_path))

    report = validator.validate_graph(
        [{"node_id": "invalid", "module_id": "invalid_module"}],
        [],
    )

    assert any(issue["code"] == "flow.module_contract_invalid" for issue in report["issues"])


@pytest.mark.asyncio
async def test_job_scorer_guarantees_empty_scored_jobs_output() -> None:
    block = JobScorerBlock(engine=None, params={})

    result = await block.execute({}, {"user_id": "demo-user", "jobs": []})

    assert result == {"scored_count": 0, "scored_jobs": []}
