from __future__ import annotations

from typing import Any, Dict, List

from app.core.flow_graph import topological_order
from app.core.realtime.sagas.flows.flow_executor import (
    FlowExecutorSaga as _BaseFlowExecutorSaga,
)


class FlowExecutorSaga(_BaseFlowExecutorSaga):
    """Canonical flow executor with fail-closed structural validation.

    The historical executor remains the implementation base while the package
    export points to this guarded subclass. This keeps existing behavior stable
    and makes graph validation non-bypassable for production imports.
    """

    @staticmethod
    def _topological_order(
        node_map: Dict[str, Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> List[str]:
        return topological_order(node_map.keys(), edges)
