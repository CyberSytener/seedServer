"""BFS and A* pathfinding on the grocery store grid."""
from __future__ import annotations

import heapq
from collections import deque
from typing import Optional

from .grid import Grid


def bfs_shortest_path(
    grid: Grid,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: Optional[set[tuple[int, int]]] = None,
    prefer_left: bool = False,
) -> Optional[list[tuple[int, int]]]:
    """BFS shortest path.  Returns path from *start* to *goal* (inclusive) or None.

    When *prefer_left* is True, the neighbour exploration order is
    LEFT, UP, DOWN, RIGHT instead of the default UP, DOWN, LEFT, RIGHT.
    This causes BFS to prefer paths that exit narrow aisles leftward
    (toward the drop-off column) when equal-length alternatives exist.
    """
    if start == goal:
        return [start]
    blocked = blocked or set()
    visited: set[tuple[int, int]] = {start}
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    queue: deque[tuple[int, int]] = deque([start])

    if prefer_left:
        offsets = ((-1, 0), (0, -1), (0, 1), (1, 0))
    else:
        offsets = ((0, -1), (0, 1), (-1, 0), (1, 0))

    while queue:
        cx, cy = queue.popleft()
        for dx, dy in offsets:
            nx, ny = cx + dx, cy + dy
            if not grid.is_walkable(nx, ny):
                continue
            if (nx, ny) in visited or (nx, ny) in blocked:
                continue
            parent[(nx, ny)] = (cx, cy)
            if (nx, ny) == goal:
                # Reconstruct path
                path: list[tuple[int, int]] = [(nx, ny)]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            visited.add((nx, ny))
            queue.append((nx, ny))
    return None


def bfs_distance(
    grid: Grid,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: Optional[set[tuple[int, int]]] = None,
) -> int:
    """Return shortest-path distance, or a large sentinel (999999) if unreachable."""
    path = bfs_shortest_path(grid, start, goal, blocked)
    return len(path) - 1 if path else 999999


def bfs_distances_from(
    grid: Grid,
    start: tuple[int, int],
    blocked: Optional[set[tuple[int, int]]] = None,
) -> dict[tuple[int, int], int]:
    """BFS flood-fill: return distance from *start* to every reachable cell."""
    blocked = blocked or set()
    dist: dict[tuple[int, int], int] = {start: 0}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        d = dist[(cx, cy)]
        for nx, ny in grid.neighbors(cx, cy):
            if (nx, ny) in dist or (nx, ny) in blocked:
                continue
            dist[(nx, ny)] = d + 1
            queue.append((nx, ny))
    return dist


def astar_path(
    grid: Grid,
    start: tuple[int, int],
    goal: tuple[int, int],
    blocked: Optional[set[tuple[int, int]]] = None,
) -> Optional[list[tuple[int, int]]]:
    """A* with Manhattan heuristic.  Same interface as bfs_shortest_path."""
    if start == goal:
        return [start]
    blocked = blocked or set()
    gx, gy = goal

    def h(x: int, y: int) -> int:
        return abs(x - gx) + abs(y - gy)

    open_set: list[tuple[int, int, int, int]] = []  # (f, g, x, y)
    heapq.heappush(open_set, (h(start[0], start[1]), 0, start[0], start[1]))
    g_score: dict[tuple[int, int], int] = {start: 0}
    parent: dict[tuple[int, int], tuple[int, int]] = {}

    while open_set:
        _f, g, cx, cy = heapq.heappop(open_set)
        if (cx, cy) == goal:
            path: list[tuple[int, int]] = [(cx, cy)]
            while path[-1] != start:
                path.append(parent[path[-1]])
            path.reverse()
            return path
        if g > g_score.get((cx, cy), 999999):
            continue  # stale entry
        for nx, ny in grid.neighbors(cx, cy):
            if (nx, ny) in blocked:
                continue
            ng = g + 1
            if ng < g_score.get((nx, ny), 999999):
                g_score[(nx, ny)] = ng
                parent[(nx, ny)] = (cx, cy)
                heapq.heappush(open_set, (ng + h(nx, ny), ng, nx, ny))
    return None


def find_pickup_position(
    grid: Grid,
    item_pos: tuple[int, int],
) -> Optional[tuple[int, int]]:
    """Return the nearest walkable cell adjacent to *item_pos* (shelf cell).
    
    Items sit on shelves (walls). The bot must stand on a walkable neighbour
    to pick up.  Returns None only if there is no walkable cell adjacent
    (shouldn't happen with valid maps).
    """
    candidates = grid.walkable_neighbors_of(
        __import__("modules.bot.models", fromlist=["Pos"]).Pos(item_pos[0], item_pos[1])
    )
    return candidates[0] if candidates else None


def find_all_pickup_positions(
    grid: Grid,
    item_pos: tuple[int, int],
) -> list[tuple[int, int]]:
    """Return *all* walkable cells adjacent to *item_pos*."""
    from .models import Pos
    return grid.walkable_neighbors_of(Pos(item_pos[0], item_pos[1]))
