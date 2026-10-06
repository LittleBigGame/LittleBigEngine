"""Explicit persistent identity linking and disposable runtime handles."""
from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Handle:
    slot: int
    generation: int
    scope: UUID


class Linker:
    def __init__(self, runtime):
        self.runtime = runtime
        self.scope = uuid4()
        self.objects = {}
        self.owners = {}
        self.dependencies = {}
        self._dependents = {}
        self._slots = []
        self._generations = []
        self._free = []
        self._handles = {}

    def register(self, item, *, owner=None):
        identity = item.id
        if identity not in self.objects:
            slot = self._free.pop() if self._free else len(self._slots)
            if slot == len(self._slots):
                self._slots.append(None)
                self._generations.append(0)
            self._slots[slot] = identity
            self._handles[identity] = Handle(slot, self._generations[slot], self.scope)
        self.objects[identity] = item
        if owner is not None:
            self.owners[identity] = owner
        self._forget_dependencies(identity)
        from .items import InheritedComponent
        if isinstance(item, InheritedComponent):
            self.dependencies[identity] = {item.source}
        elif hasattr(item, "definition") and item.definition.references:
            self.dependencies[identity] = {reference.id for reference in item.definition.references}
        else:
            self.dependencies.pop(identity, None)
        for source in self.dependencies.get(identity, ()):
            self._dependents.setdefault(source, set()).add(identity)

    def _forget_dependencies(self, identity):
        for source in self.dependencies.pop(identity, ()):
            dependents = self._dependents.get(source)
            if dependents is not None:
                dependents.discard(identity)
                if not dependents:
                    self._dependents.pop(source, None)

    def unregister(self, identity):
        self.objects.pop(identity, None)
        self.owners.pop(identity, None)
        self._forget_dependencies(identity)
        handle = self._handles.pop(identity, None)
        if handle is not None:
            self._slots[handle.slot] = None
            self._generations[handle.slot] += 1
            self._free.append(handle.slot)

    def resolve(self, identity, expected=None):
        identity = identity if isinstance(identity, UUID) else UUID(str(identity))
        item = self.objects[identity]
        if expected is not None and not isinstance(item, expected):
            label = '/'.join(t.__name__ for t in expected) if isinstance(expected, tuple) else expected.__name__
            raise TypeError(f"{identity} is {type(item).__name__}, not {label}")
        return item

    def handle(self, identity):
        return self._handles[identity if isinstance(identity, UUID) else UUID(str(identity))]

    def resolve_handle(self, handle):
        if (not isinstance(handle, Handle) or handle.scope != self.scope or handle.slot < 0 or handle.slot >= len(self._slots)
                or self._generations[handle.slot] != handle.generation
                or self._slots[handle.slot] is None):
            raise ReferenceError("Stale or invalid runtime handle")
        return self.objects[self._slots[handle.slot]]

    def component_value(self, identity, seen=None):
        from .items import Component, InheritedComponent, compose
        item = self.resolve(identity)
        if isinstance(item, Component):
            return item.value
        seen = set() if seen is None else seen
        if identity in seen:
            raise ValueError(f"Composition cycle at {identity}")
        seen.add(identity)
        if not isinstance(item, InheritedComponent):
            raise TypeError(f"Composition source {identity} is not a component")
        return compose(self.component_value(item.source, seen), item.patch)

    def dependents(self, identity):
        """Transitive derived dependency query; source records stay authoritative."""
        identity = identity if isinstance(identity, UUID) else UUID(str(identity))
        if identity not in self._dependents:
            return frozenset()
        found, frontier = set(), {identity}
        while frontier:
            next_items = set().union(*(self._dependents.get(uid, set()) for uid in frontier)) - found
            found.update(next_items)
            frontier = next_items
        return frozenset(found)
