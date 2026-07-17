from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.blocks import BlockRegistry
from app.core.flow_graph import FlowGraphCycleError
from app.core.realtime.sagas import orchestrator as orchestrator_module
from app.core.realtime.sagas.flows import FlowExecutorSaga
from app.core.realtime.sagas.orchestrator import SagaOrchestrator


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


def test_orchestrator_uses_canonical_validated_flow_executor() -> None:
    assert orchestrator_module.FlowExecutorSaga is FlowExecutorSaga
    assert FlowExecutorSaga.__module__.endswith("validated_flow_executor")


@pytest.mark.asyncio
async def test_flow_executor_rejects_cycle_before_block_creation() -> None:
    registry = _TrackingRegistry()
    flow = FlowExecutorSaga(_build_orchestrator(), registry=registry)
    steps: list[dict] = []
    payload = {
        "graph": {
            "nodes": [
                {"node_id": "alpha", "module_id": "unused", "config": {}},
                {"node_id": "beta", "module_id": "unused", "config": {}},
            ],
            "edges": [
                {"from": "alpha", "to": "beta", "mapping": {"value": "value"}},
                {"from": "beta", "to": "alpha", "mapping": {"value": "value"}},
            ],
        },
        "artifact_store_enabled": False,
    }

    with pytest.raises(FlowGraphCycleError, match="flow.cycle_detected"):
        await flow.run("saga-flow-cycle", payload, steps)

    assert registry.create_calls == 0
    assert steps == []
