from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

from app.core.blocks import BlockBase, BlockRegistry
from app.core.realtime.sagas.flows.flow_executor import FlowExecutorSaga
from app.core.realtime.sagas.orchestrator import SagaOrchestrator


class _EchoBlock(BlockBase):
    async def execute(self, context, inputs):
        text = str(inputs.get("text") or "")
        return {
            "text": text,
            "upper": text.upper(),
            "user_id": context.get("user_id"),
        }


class _CombineBlock(BlockBase):
    async def execute(self, _context, inputs):
        prefix = str(inputs.get("prefix") or "")
        suffix = str(inputs.get("suffix") or "")
        return {"final": f"{prefix}-{suffix}"}


class _FailBlock(BlockBase):
    async def execute(self, _context, _inputs):
        raise RuntimeError("forced_failure")


def _build_orchestrator():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()
    return orchestrator


@pytest.mark.asyncio
async def test_flow_executor_saga_runs_graph_and_assertions(tmp_path):
    os.environ["SEED_ARTIFACT_STORE_DIR"] = str(tmp_path)

    registry = BlockRegistry()
    registry.register("echo", _EchoBlock)
    registry.register("combine", _CombineBlock)

    flow = FlowExecutorSaga(_build_orchestrator(), registry=registry)
    steps = []
    payload = {
        "graph": {
            "nodes": [
                {
                    "node_id": "source",
                    "module_id": "echo",
                    "config": {"inputs": {"text": "hello"}},
                },
                {
                    "node_id": "sink",
                    "module_id": "combine",
                    "config": {"inputs": {"suffix": "world"}},
                },
            ],
            "edges": [
                {
                    "from": "source",
                    "to": "sink",
                    "mapping": {"prefix": "upper"},
                }
            ],
        },
        "input": {"user_id": "u-flow"},
        "assertions": {
            "required_nodes": ["source", "sink"],
            "required_output_fields": ["final"],
            "forbid_errors": True,
        },
    }

    result = await flow.run("saga-flow-ok", payload, steps)

    assert result["status"] == "succeeded"
    output = result["result"]["output"]
    assert output["final"] == "HELLO-world"
    assert result["result"]["assertions"]["passed"] is True
    assert len(result["result"]["timeline"]) == 2
    assert any(
        str(ref.get("uri") or "").startswith("artifact://")
        for ref in (result["result"].get("artifacts") or [])
    )
    assert [step.get("name") for step in steps] == ["source", "sink", "aggregate"]


@pytest.mark.asyncio
async def test_flow_executor_saga_marks_failed_nodes_and_stop_reason():
    registry = BlockRegistry()
    registry.register("echo", _EchoBlock)
    registry.register("failing", _FailBlock)

    flow = FlowExecutorSaga(_build_orchestrator(), registry=registry)
    steps = []
    payload = {
        "graph": {
            "nodes": [
                {
                    "node_id": "source",
                    "module_id": "echo",
                    "config": {"inputs": {"text": "x"}},
                },
                {
                    "node_id": "broken",
                    "module_id": "failing",
                    "config": {},
                },
            ],
            "edges": [
                {
                    "from": "source",
                    "to": "broken",
                    "mapping": {"payload": "upper"},
                }
            ],
        },
        "input": {"user_id": "u-flow"},
        "assertions": {"forbid_errors": True},
    }

    result = await flow.run("saga-flow-fail", payload, steps)

    assert result["status"] == "failed"
    assert result["result"]["stop_reason"] == "node_failed"
    timeline = result["result"]["timeline"]
    assert any(item.get("status") == "failed" for item in timeline)
    assert steps[-1]["name"] == "broken"
    assert steps[-1]["status"] == "failed"
