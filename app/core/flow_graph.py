from __future__ import annotations

from collections import deque
from typing import Any, Iterable, Mapping, Sequence


class FlowGraphCycleError(ValueError):
    """Raised when a flow graph cannot be topologically ordered."""

    code = "flow.cycle_detected"

    def __init__(self, cycle_nodes: Sequence[str]) -> None:
        self.cycle_nodes = tuple(cycle_nodes)
        rendered = ", ".join(self.cycle_nodes) or "unknown"
        super().__init__(
            f"{self.code}: graph contains a cycle involving nodes: {rendered}"
        )


def topological_order(
    node_ids: Iterable[str],
    edges: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Return a stable topological order or raise ``FlowGraphCycleError``.

    Node insertion order is preserved when several nodes are simultaneously
    eligible. Edges whose endpoints are not in ``node_ids`` are ignored here;
    callers remain responsible for reporting missing-node diagnostics.
    Duplicate edges are collapsed so they cannot create artificial indegrees.
    """

    ordered_nodes = list(dict.fromkeys(str(node_id) for node_id in node_ids))
    node_set = set(ordered_nodes)
    indegree = {node_id: 0 for node_id in ordered_nodes}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in ordered_nodes}
    seen_edges: set[tuple[str, str]] = set()

    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source not in node_set or target not in node_set:
            continue
        pair = (source, target)
        if pair in seen_edges:
            continue
        seen_edges.add(pair)
        adjacency[source].append(target)
        indegree[target] += 1

    queue = deque(node_id for node_id in ordered_nodes if indegree[node_id] == 0)
    result: list[str] = []

    while queue:
        current = queue.popleft()
        result.append(current)
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if len(result) != len(ordered_nodes):
        remaining = [node_id for node_id in ordered_nodes if indegree[node_id] > 0]
        raise FlowGraphCycleError(remaining)

    return result
