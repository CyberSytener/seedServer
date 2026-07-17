from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.blocks import BlockRegistry
from app.core.flow_graph import FlowGraphCycleError
from app.core.realtime.sagas.flows import FlowExecutorSaga
from app.core.realtime.sagas.orchestrator import SagaOrchestrator
from app.services.flow_contract_validator import FlowContractValidator


class _TrackingRegistry(BlockRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.create_calls = 0

    def create(self, *args, **kwargs):
        self.create_calls += 1
        return super().create(*args, **kwargs)


def _build_orchestrator() -> SagaOrchestrator:
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()
    return orchestrator


@pytest.mark.asyncio
async def test_cyclic_graph_is_rejected_before_runtime_execution() -> None:
    nodes = [
        {"node_id": "scan", "module_id": "market_scanner"},
        {"node_id": "score", "module_id": "job_scorer"},
    ]
    edges = [
        {"from": "scan", "to": "score", "mapping": {"jobs": "jobs", "scan_id": "scan_id"}},
        {"from": "score", "to": "scan", "mapping": {"query": "scored_jobs"}},
    ]

    report = FlowContractValidator().validate_graph(nodes, edges)
    assert report["ok"] is False
    assert any(issue["code"] == "flow.cycle_detected" for issue in report["issues"])

    registry = _TrackingRegistry()
    steps: list[dict] = []
    flow = FlowExecutorSaga(_build_orchestrator(), registry=registry)

    with pytest.raises(FlowGraphCycleError) as exc_info:
        await flow.run(
            "integration-cycle",
            {
                "graph": {"nodes": nodes, "edges": edges},
                "artifact_store_enabled": False,
            },
            steps,
        )

    assert exc_info.value.code == "flow.cycle_detected"
    assert registry.create_calls == 0
    assert steps == []
