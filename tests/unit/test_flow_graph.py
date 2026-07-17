from __future__ import annotations

import pytest

from app.core.flow_graph import FlowGraphCycleError, topological_order


def test_topological_order_is_stable_for_independent_nodes() -> None:
    assert topological_order(
        ["first", "second", "third"],
        [{"from": "first", "to": "third"}],
    ) == ["first", "second", "third"]


def test_topological_order_collapses_duplicate_edges() -> None:
    assert topological_order(
        ["source", "sink"],
        [
            {"from": "source", "to": "sink"},
            {"from": "source", "to": "sink"},
        ],
    ) == ["source", "sink"]


def test_topological_order_rejects_self_loop_with_stable_code() -> None:
    with pytest.raises(FlowGraphCycleError) as exc_info:
        topological_order(["node"], [{"from": "node", "to": "node"}])

    error = exc_info.value
    assert error.code == "flow.cycle_detected"
    assert error.cycle_nodes == ("node",)
    assert str(error) == (
        "flow.cycle_detected: graph contains a cycle involving nodes: node"
    )


def test_topological_order_reports_only_cycle_participants() -> None:
    with pytest.raises(FlowGraphCycleError) as exc_info:
        topological_order(
            ["alpha", "beta", "downstream", "free"],
            [
                {"from": "alpha", "to": "beta"},
                {"from": "beta", "to": "alpha"},
                {"from": "beta", "to": "downstream"},
            ],
        )

    assert exc_info.value.cycle_nodes == ("alpha", "beta")
