"""Dependencies between the work packages of a project: a directed graph without cycles.

An edge predecessor → successor means "the successor starts when the predecessor is
done" (finish to start). A new edge closes a cycle exactly when the predecessor is
already reachable from the successor; `cycle_path` returns that path, so the refusal
can name every work package of the cycle, also of an indirect one (A → B → C → A).
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Edge:
    predecessor: str
    successor: str


def _successors(edges: Iterable[Edge]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge.predecessor].append(edge.successor)
    for targets in graph.values():
        targets.sort()          # deterministic paths in messages
    return graph


def path_between(edges: Iterable[Edge], start: str, goal: str) -> list[str] | None:
    """A shortest path start → … → goal along the edges, or None (iterative BFS, no recursion limit)."""
    graph = _successors(edges)
    previous: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            path = [node]
            while previous[path[-1]] is not None:
                path.append(previous[path[-1]])  # type: ignore[arg-type]
            return path[::-1]
        for target in graph.get(node, ()):
            if target not in previous:
                previous[target] = node
                queue.append(target)
    return None


def cycle_path(edges: Iterable[Edge], new: Edge) -> list[str] | None:
    """The cycle the new edge would close, as [predecessor, successor, …, predecessor], or None."""
    if new.predecessor == new.successor:
        return [new.predecessor, new.predecessor]
    back = path_between(edges, new.successor, new.predecessor)
    return None if back is None else [new.predecessor, *back]


def find_cycle(edges: Iterable[Edge]) -> list[str] | None:
    """Any cycle of an existing graph (a damaged import, say), or None."""
    edges = list(edges)
    for edge in sorted(edges, key=lambda e: (e.predecessor, e.successor)):
        back = path_between(edges, edge.successor, edge.predecessor)
        if back is not None:
            return [edge.predecessor, *back]
    return None


def topological_order(nodes: Iterable[str], edges: Iterable[Edge],
                      rank: Mapping[str, tuple] | None = None) -> list[str] | None:
    """Kahn's algorithm; ties broken by `rank` (then id). None if the graph has a cycle."""
    nodes = set(nodes)
    edges = [e for e in edges if e.predecessor in nodes and e.successor in nodes]
    incoming: dict[str, int] = {node: 0 for node in nodes}
    graph = _successors(edges)
    for edge in edges:
        incoming[edge.successor] += 1

    def key(node: str) -> tuple:
        return ((rank or {}).get(node, ()), node)

    ready = sorted((node for node, count in incoming.items() if count == 0), key=key)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in graph.get(node, ()):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort(key=key)
    return order if len(order) == len(nodes) else None


@dataclass(frozen=True)
class ScheduleConflict:
    predecessor: str
    successor: str
    predecessor_end: date
    successor_start: date


def schedule_conflicts(edges: Iterable[Edge], starts: Mapping[str, date | None],
                       ends: Mapping[str, date | None]) -> list[ScheduleConflict]:
    """Planned dates that contradict a dependency: the successor starts before the predecessor ends."""
    found = []
    for edge in edges:
        end, start = ends.get(edge.predecessor), starts.get(edge.successor)
        if end is not None and start is not None and start < end:
            found.append(ScheduleConflict(edge.predecessor, edge.successor, end, start))
    return found
