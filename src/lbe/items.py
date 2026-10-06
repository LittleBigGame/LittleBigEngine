"""Persistent typed items; legacy named collections are projections of this store."""
from collections.abc import Mapping, MutableMapping, MutableSet
from dataclasses import dataclass, field, replace
from copy import deepcopy
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Component:
    name: str
    value: object
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class InheritedComponent:
    name: str
    source: UUID
    patch: tuple = ()
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class Tag:
    name: str
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class Relation:
    name: str
    target: UUID
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class Parent:
    target: UUID
    id: UUID = field(default_factory=uuid4)
    name: str = field(default="parent", init=False)


def compose(value, patch):
    """Apply explicit operations to a private copy, never to the source value.

    Each operation has op, optional path (mapping keys/list indices), and value.
    Supported ops: set/replace, remove, add (numeric or list), multiply.
    """
    value = deepcopy(value)
    for operation in patch:
        path = tuple(operation.get("path", ()))
        op = operation["op"]
        parent = value
        for key in path[:-1]:
            parent = parent[key]
        current = parent[path[-1]] if path else value
        argument = deepcopy(operation.get("value"))
        if op in ("set", "replace"):
            result = argument
        elif op == "add":
            result = current + argument
        elif op == "multiply":
            result = current * argument
        elif op == "remove":
            if not path:
                raise ValueError("Cannot remove the composition root")
            del parent[path[-1]]
            continue
        else:
            raise ValueError(f"Unknown patch operation: {op}")
        if path:
            parent[path[-1]] = result
        else:
            value = result
    return value


class Items(Mapping):
    """UUID-keyed source of truth. Mutations use add/remove and existing APIs.

    Read-only mapping prevents bypassing lifecycle, hierarchy and change events.
    Indexes are derived and disposable; item identities survive value edits.
    """
    def __init__(self, entity):
        self.entity = entity
        self._records = {}
        self._names = {}

    def __getitem__(self, identity):
        self.entity._check()
        return self._records[UUID(str(identity))]

    def __iter__(self):
        self.entity._check()
        return iter(tuple(self._records))

    def __len__(self):
        self.entity._check()
        return len(self._records)

    @staticmethod
    def category(item):
        from .scripts import ScriptInstance
        from .systems import SystemInstance
        if isinstance(item, (Component, InheritedComponent)):
            return Component
        if isinstance(item, ScriptInstance):
            return ScriptInstance
        if isinstance(item, SystemInstance):
            return SystemInstance
        return type(item)

    def named(self, category, name):
        return self._records[self._names[category, name]]

    def _put(self, item):
        category = self.category(item)
        key = category, item.name
        previous_id = self._names.get(key)
        if previous_id is not None and previous_id != item.id:
            self._drop(previous_id)
        existing = self.entity.runtime.linker.objects.get(item.id)
        if existing is not None and item.id not in self._records:
            raise ValueError(f"Duplicate object UUID: {item.id}")
        self.entity.runtime.linker.register(item, owner=self.entity.id)
        self._records[item.id] = item
        self._names[key] = item.id

    def _drop(self, identity):
        item = self._records.pop(identity)
        self._names.pop((self.category(item), item.name), None)
        self.entity.runtime.linker.unregister(identity)
        return item

    def add(self, item):
        """Add a typed declaration with its own UUID, using normal change hooks."""
        self.entity._check()
        if not isinstance(item.id, UUID):
            raise TypeError("Item identity must be a UUID")
        category = self.category(item)
        if (category, item.name) in self._names or item.id in self.entity.runtime.linker.objects:
            raise ValueError("Item identity/name already exists")
        if isinstance(item, (Component, InheritedComponent)):
            if not isinstance(item.name, str) or not item.name:
                raise ValueError("Component names must be nonempty strings")
            self._put(item)
            self.entity._changed("component.set", item.name, new=self.entity.components[item.name])
        elif isinstance(item, Tag):
            self.entity.tags.add(item.name)
            self._replace_identity(Tag, item.name, item.id)
        elif isinstance(item, Relation):
            self.entity.relations[item.name] = self.entity.runtime.resolve(item.target)
            self._replace_identity(Relation, item.name, item.id)
        elif isinstance(item, Parent):
            self.entity.parent = self.entity.runtime.resolve(item.target)
            self._replace_identity(Parent, "parent", item.id)
        else:
            raise TypeError("Attach behavior through systems/scripts lifecycle APIs")
        return item

    def remove(self, identity):
        item = self[identity]
        category = self.category(item)
        if category is Component:
            del self.entity.components[item.name]
        elif category is Tag:
            self.entity.tags.discard(item.name)
        elif category is Relation:
            del self.entity.relations[item.name]
        elif category is Parent:
            self.entity.parent = None
        else:
            from .scripts import ScriptInstance
            collection = self.entity.scripts if category is ScriptInstance else self.entity.systems
            del collection[item.name]

    def _replace_identity(self, category, name, identity):
        item = self.named(category, name)
        self._drop(item.id)
        if hasattr(item, "definition"):
            item.id = identity
        else:
            item = replace(item, id=identity)
        self._put(item)

    def all(self, item_type):
        self.entity._check()
        return tuple(item for item in self._records.values() if isinstance(item, item_type))


class NamedValues(MutableMapping):
    """Internal compatibility projection; no independent value dictionary."""
    def __init__(self, entity, category):
        self.entity, self.category = entity, category

    def record(self, name):
        return self.entity.items.named(self.category, name)

    def __getitem__(self, name):
        item = self.record(name)
        if self.category is Component:
            return self.entity.runtime.linker.component_value(item.id)
        if self.category is Relation:
            return self.entity.runtime.resolve(item.target)
        return item

    def __setitem__(self, name, value):
        try:
            current = self.record(name)
        except KeyError:
            current = None
        identity = current.id if current else uuid4()
        if self.category is Component:
            if isinstance(current, InheritedComponent):
                item = replace(current, patch=({"op": "replace", "value": value},))
            else:
                item = Component(name, value, identity)
        elif self.category is Relation:
            item = Relation(name, value.id, identity)
        else:
            item = value
        self.entity.items._put(item)

    def __delitem__(self, name):
        self.entity.items._drop(self.record(name).id)

    def __iter__(self):
        return iter(tuple(item.name for item in self.entity.items._records.values()
                          if Items.category(item) is self.category))

    def __len__(self):
        return sum(1 for _ in self)

    def reorder(self, pairs):
        ids = [value.id for _, value in pairs]
        records = self.entity.items._records
        slots = iter(ids)
        order = [next(slots) if identity in ids else identity for identity in records]
        self.entity.items._records = {identity: records[identity] for identity in order}


class TagValues(MutableSet):
    def __init__(self, entity):
        self.entity = entity

    def __contains__(self, name):
        return (Tag, name) in self.entity.items._names

    def __iter__(self):
        return iter(tuple(item.name for item in self.entity.items.all(Tag)))

    def __len__(self):
        return len(self.entity.items.all(Tag))

    def add(self, name):
        if name not in self:
            self.entity.items._put(Tag(name))

    def discard(self, name):
        if name in self:
            self.entity.items._drop(self.entity.items.named(Tag, name).id)

    def update(self, names):
        for name in names:
            self.add(name)
