"""Explicit persistent identity linking and disposable runtime handles."""
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Handle:
    slot: int
    generation: int


class Linker:
    def __init__(self, runtime):
        self.runtime = runtime
        self.objects = {}
        self.owners = {}
        self.dependencies = {}
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
            self._handles[identity] = Handle(slot, self._generations[slot])
        self.objects[identity] = item
        if owner is not None:
            self.owners[identity] = owner
        from .items import InheritedComponent
        if isinstance(item, InheritedComponent):
            self.dependencies[identity] = {item.source}
        else:
            self.dependencies.pop(identity, None)

    def unregister(self, identity):
        self.objects.pop(identity, None)
        self.owners.pop(identity, None)
        self.dependencies.pop(identity, None)
        handle = self._handles.pop(identity, None)
        if handle is not None:
            self._slots[handle.slot] = None
            self._generations[handle.slot] += 1
            self._free.append(handle.slot)

    def resolve(self, identity, expected=None):
        identity = UUID(str(identity))
        item = self.objects[identity]
        if expected is not None and not isinstance(item, expected):
            raise TypeError(f"{identity} is {type(item).__name__}, not {expected.__name__}")
        return item

    def handle(self, identity):
        return self._handles[UUID(str(identity))]

    def resolve_handle(self, handle):
        if (not isinstance(handle, Handle) or handle.slot < 0 or handle.slot >= len(self._slots)
                or self._generations[handle.slot] != handle.generation
                or self._slots[handle.slot] is None):
            raise ReferenceError("Stale or invalid runtime handle")
        return self.objects[self._slots[handle.slot]]

    def component_value(self, identity, seen=None):
        from .items import Component, InheritedComponent, compose
        seen = set() if seen is None else seen
        if identity in seen:
            raise ValueError(f"Composition cycle at {identity}")
        seen.add(identity)
        item = self.resolve(identity)
        if isinstance(item, Component):
            return item.value
        if not isinstance(item, InheritedComponent):
            raise TypeError(f"Composition source {identity} is not a component")
        return compose(self.component_value(item.source, seen), item.patch)

    def dependents(self, identity):
        """Transitive derived dependency query; source records stay authoritative."""
        found, frontier = set(), {UUID(str(identity))}
        while frontier:
            next_items = {uid for uid, sources in self.dependencies.items() if sources & frontier} - found
            found.update(next_items)
            frontier = next_items
        return frozenset(found)
