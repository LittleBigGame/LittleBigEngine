"""Cycle-safe operations over the resource graph.

Resources may reference each other in cycles and may reference themselves.
Every traversal here is iterative and keeps a visited set, so it terminates
on any graph.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from lbe.kernel.errors import ResourceNotFound
from lbe.kernel.ids import ResourceId
from lbe.kernel.resource import Resource
from lbe.kernel.types import ResourceLookup

Edges = Callable[[Resource], Iterable[ResourceId]]


def closure(
    store: ResourceLookup,
    roots: Iterable[ResourceId],
    *,
    edges: Edges = Resource.dependencies,
) -> dict[ResourceId, Resource]:
    """Every resource reachable from `roots` through `edges`, in discovery order.

    Raises ResourceNotFound if any reachable resource is missing.
    """
    found: dict[ResourceId, Resource] = {}
    pending = list(roots)
    while pending:
        resource_id = pending.pop()
        if resource_id in found:
            continue
        resource = store.get(resource_id)
        found[resource_id] = resource
        pending.extend(target for target in edges(resource) if target not in found)
    return found


def missing_dependencies(
    store: ResourceLookup,
    roots: Iterable[ResourceId],
    *,
    edges: Edges = Resource.dependencies,
) -> dict[ResourceId, list[ResourceId]]:
    """Map each missing resource id to the ids of the resources that need it."""
    missing: dict[ResourceId, list[ResourceId]] = {}
    found: set[ResourceId] = set()
    pending = [(root, None) for root in roots]
    while pending:
        resource_id, needed_by = pending.pop()
        if resource_id in found:
            continue
        try:
            resource = store.get(resource_id)
        except ResourceNotFound:
            if needed_by is not None:
                missing.setdefault(resource_id, []).append(needed_by)
            else:
                missing.setdefault(resource_id, [])
            continue
        found.add(resource_id)
        pending.extend((target, resource_id) for target in edges(resource) if target not in found)
    return missing


def strongly_connected_groups(
    resources: Mapping[ResourceId, Resource],
    *,
    edges: Edges = Resource.dependencies,
) -> list[frozenset[ResourceId]]:
    """Tarjan's algorithm, iteratively. Groups come out dependencies-first.

    Each group is a set of resources that (transitively) reference each other;
    a resource with no cycle is a group of one. Edges leaving `resources` are
    ignored. Publishing a group atomically is what makes circular references
    between immutable resources possible.
    """
    index: dict[ResourceId, int] = {}
    lowlink: dict[ResourceId, int] = {}
    on_stack: set[ResourceId] = set()
    stack: list[ResourceId] = []
    groups: list[frozenset[ResourceId]] = []
    counter = 0

    for start in resources:
        if start in index:
            continue
        work = [(start, iter([t for t in edges(resources[start]) if t in resources]))]
        index[start] = lowlink[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, successors = work[-1]
            advanced = False
            for target in successors:
                if target not in index:
                    index[target] = lowlink[target] = counter
                    counter += 1
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter([t for t in edges(resources[target]) if t in resources])))
                    advanced = True
                    break
                if target in on_stack:
                    lowlink[node] = min(lowlink[node], index[target])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                groups.append(frozenset(group))
    return groups
