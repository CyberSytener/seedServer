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


def _find_cycle_nodes(
    ordered_nodes: list[str],
    adjacency: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return only nodes that belong to a strongly connected cycle."""

    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str) -> None:
        nonlocal next_index
        indices[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)

        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return

        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break

        if len(component) > 1:
            cycle_nodes.update(component)
        elif component and component[0] in adjacency[component[0]]:
            cycle_nodes.add(component[0])

    for node in ordered_nodes:
        if node not in indices:
            visit(node)

    return [node for node in ordered_nodes if node in cycle_nodes]


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
        cycle_nodes = _find_cycle_nodes(ordered_nodes, adjacency)
        raise FlowGraphCycleError(cycle_nodes)

    return result
