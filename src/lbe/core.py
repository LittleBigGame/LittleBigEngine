"""Generic entity storage, hierarchy and live queries."""

from collections.abc import MutableMapping, MutableSet
from contextlib import contextmanager
from copy import deepcopy
from uuid import UUID, uuid4
from math import isfinite

from .events import Changes, Events

_MISSING = object()


class Components(MutableMapping):
    def __init__(self, entity):
        self._entity = entity
        self._values = {}

    def __getitem__(self, key):
        self._entity._check()
        return self._values[key]

    def __setitem__(self, key, value):
        self._entity._check()
        if not isinstance(key, str) or not key:
            raise ValueError("Component names must be nonempty strings")
        self._values[key] = value
        self._entity._changed("component.set", key)

    def __delitem__(self, key):
        self._entity._check()
        del self._values[key]
        self._entity._changed("component.remove", key)

    def __iter__(self):
        self._entity._check()
        return iter(tuple(self._values))

    def __len__(self):
        self._entity._check()
        return len(self._values)

    def touch(self, key):
        """Notify observers after externally mutating an arbitrary object."""
        self[key]
        self._entity._changed("component.mutate", key)

    @contextmanager
    def edit(self, key):
        """Edit a deep copy and commit once, only on successful exit."""
        value = deepcopy(self[key])
        yield value
        self[key] = value


class Tags(MutableSet):
    def __init__(self, entity):
        self._entity = entity
        self._values = set()

    def __contains__(self, value):
        self._entity._check()
        return value in self._values

    def __iter__(self):
        self._entity._check()
        return iter(sorted(self._values))

    def __len__(self):
        self._entity._check()
        return len(self._values)

    def add(self, value):
        self._entity._check()
        if not isinstance(value, str) or not value:
            raise ValueError("Tags must be nonempty strings")
        if value not in self._values:
            self._values.add(value)
            self._entity._changed("tag.add", value)

    def discard(self, value):
        self._entity._check()
        if value in self._values:
            self._values.remove(value)
            self._entity._changed("tag.remove", value)


class Relations(MutableMapping):
    """Named directed links to live entities in the same runtime."""

    def __init__(self, entity):
        self._entity = entity
        self._values = {}

    def __getitem__(self, key):
        self._entity._check()
        return self._values[key]

    def __setitem__(self, key, target):
        self._entity._check()
        if not isinstance(key, str) or not key:
            raise ValueError("Relation names must be nonempty strings")
        self._entity.runtime._validate(target)
        self._values[key] = target
        self._entity._changed("relation.set", key)

    def __delitem__(self, key):
        self._entity._check()
        del self._values[key]
        self._entity._changed("relation.remove", key)

    def __iter__(self):
        self._entity._check()
        return iter(tuple(self._values))

    def __len__(self):
        self._entity._check()
        return len(self._values)


class Entity:
    __slots__ = (
        "_runtime", "_id", "_alive", "_destroying", "_parent", "_children",
        "_components", "_tags", "_relations", "_systems",
    )

    def __init__(self, runtime, identity):
        from .systems import Systems

        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_id", identity)
        object.__setattr__(self, "_alive", True)
        object.__setattr__(self, "_destroying", False)
        object.__setattr__(self, "_parent", None)
        object.__setattr__(self, "_children", [])
        object.__setattr__(self, "_components", Components(self))
        object.__setattr__(self, "_tags", Tags(self))
        object.__setattr__(self, "_relations", Relations(self))
        object.__setattr__(self, "_systems", Systems(self))

    id = property(lambda self: self._id)
    alive = property(lambda self: self._alive)
    runtime = property(lambda self: self._runtime)
    components = property(lambda self: self._components)
    tags = property(lambda self: self._tags)
    relations = property(lambda self: self._relations)
    systems = property(lambda self: self._systems)

    def _check(self):
        if not self._alive:
            raise ReferenceError(f"Entity {self.id} has been destroyed")

    def _changed(self, kind, key=None):
        self.runtime.changes.publish(kind, self, key)

    def __getattr__(self, name):
        try:
            return self.components[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name == "parent":
            type(self).parent.fset(self, value)
        elif name.startswith("_") or hasattr(type(self), name):
            raise AttributeError(f"{name} is reserved; use components[{name!r}]")
        else:
            self.components[name] = value

    def __delattr__(self, name):
        if name.startswith("_") or hasattr(type(self), name):
            raise AttributeError(f"{name} is reserved")
        try:
            del self.components[name]
        except KeyError:
            raise AttributeError(name) from None

    def __repr__(self):
        return f"Entity({self.id}, alive={self.alive})"

    @property
    def parent(self):
        self._check()
        return self._parent

    @parent.setter
    def parent(self, parent):
        self._check()
        if self._destroying:
            raise RuntimeError("Cannot reparent an entity during destruction")
        if parent is not None:
            self.runtime._validate(parent)
            if parent._destroying:
                raise RuntimeError("Cannot parent to a destroying entity")
            current = parent
            while current is not None:
                if current is self:
                    raise ValueError("Hierarchy cannot contain cycles")
                current = current._parent
        if parent is self._parent:
            return
        if self._parent is not None:
            self._parent._children.remove(self)
        object.__setattr__(self, "_parent", parent)
        if parent is not None:
            parent._children.append(self)
        self._changed("hierarchy.parent")

    @property
    def children(self):
        self._check()
        return tuple(self._children)

    @property
    def ancestors(self):
        self._check()
        result = []
        current = self._parent
        while current is not None:
            result.append(current)
            current = current._parent
        return tuple(result)

    @property
    def descendants(self):
        self._check()
        result = []
        stack = list(reversed(self._children))
        while stack:
            entity = stack.pop()
            result.append(entity)
            stack.extend(reversed(entity._children))
        return tuple(result)

    @property
    def siblings(self):
        return tuple(e for e in self.parent.children if e is not self) if self.parent else ()

    @property
    def depth(self):
        return len(self.ancestors)

    @property
    def root(self):
        chain = (self,) + self.ancestors
        return next((e for e in chain if "root" in e.tags), chain[-1])

    def inherit(self, key, default=_MISSING):
        for entity in (self,) + self.ancestors:
            if key in entity.components:
                return entity.components[key]
        if default is _MISSING:
            raise KeyError(key)
        return default

    def closest(self, *components, tags=()):
        return next((e for e in (self,) + self.ancestors if _matches(e, components, tags)), None)

    def find(self, *components, tags=()):
        return next(iter(self.query(*components, tags=tags, recursive=True)), None)

    def query(self, *components, tags=(), recursive=False):
        self._check()
        return Query(self.runtime, self, components, tags, recursive)

    def move_child(self, child, index):
        self._check()
        self.runtime._validate(child)
        if child.parent is not self:
            raise ValueError("Entity is not a direct child")
        if not isinstance(index, int) or not 0 <= index < len(self._children):
            raise IndexError(index)
        self._children.remove(child)
        self._children.insert(index, child)
        self._changed("hierarchy.reorder")

    def destroy(self):
        self.runtime.destroy(self)


def _matches(entity, components, tags):
    tags = (tags,) if isinstance(tags, str) else tags
    return entity.alive and all(k in entity.components for k in components) and all(t in entity.tags for t in tags)


class Query:
    """Reusable query; each iteration snapshots membership at that moment."""

    def __init__(self, runtime, owner, components, tags, recursive):
        self._runtime = runtime
        self._owner = owner
        self._components = tuple(components)
        self._tags = (tags,) if isinstance(tags, str) else tuple(tags)
        self._recursive = recursive

    def __iter__(self):
        if self._owner is None:
            candidates = self._runtime.entities
        else:
            candidates = self._owner.descendants if self._recursive else self._owner.children
        return iter(tuple(e for e in candidates if _matches(e, self._components, self._tags)))


class Runtime:
    def __init__(self):
        from .systems import Assets

        self._entities = {}
        self.changes = Changes()
        self.events = Events()
        self.assets = Assets()
        self.services = {}
        self._stepping = False

    @property
    def entities(self):
        return tuple(self._entities.values())

    def _validate(self, entity):
        if not isinstance(entity, Entity) or entity.runtime is not self:
            raise ValueError("Entity must belong to this runtime")
        entity._check()

    def create(self, *, identity=None, parent=None, tags=(), components=None, **values):
        if parent is not None:
            self._validate(parent)
            if parent._destroying:
                raise RuntimeError("Cannot create children during parent destruction")
        data = dict(components or {})
        data.update(values)
        tags = (tags,) if isinstance(tags, str) else tuple(tags)
        if any(not isinstance(k, str) or not k for k in data):
            raise ValueError("Component names must be nonempty strings")
        if any(not isinstance(t, str) or not t for t in tags):
            raise ValueError("Tags must be nonempty strings")
        if identity is not None:
            identity = UUID(str(identity))
            if identity in self._entities:
                raise ValueError(f"Entity with id {identity} already exists")
        else:
            identity = uuid4()
        entity = Entity(self, identity)
        entity._components._values.update(data)
        entity._tags._values.update(tags)
        object.__setattr__(entity, "_parent", parent)
        if parent is not None:
            parent._children.append(entity)
        self._entities[entity.id] = entity
        entity._changed("entity.create")
        return entity

    def resolve(self, identity):
        if isinstance(identity, UUID):
            return self._entities[identity]
        if isinstance(identity, str):
            try:
                return self._entities[UUID(identity)]
            except ValueError:
                for entity in self._entities.values():
                    if entity.components.get("name") == identity:
                        return entity
                raise KeyError(identity) from None
        return self._entities[UUID(str(identity))]

    def query(self, *components, tags=()):
        return Query(self, None, components, tags, True)

    def destroy(self, entity):
        self._validate(entity)
        if entity._destroying:
            return
        subtree = (entity,) + entity.descendants
        for node in subtree:
            object.__setattr__(node, "_destroying", True)
        for node in reversed(subtree):
            if not node.alive:
                continue
            node.systems.clear()
            for other in self.entities:
                for key, target in tuple(other.relations.items()):
                    if target is node:
                        del other.relations[key]
            if node._parent is not None:
                node._parent._children.remove(node)
            object.__setattr__(node, "_parent", None)
            del self._entities[node.id]
            object.__setattr__(node, "_alive", False)
            node._changed("entity.destroy")

    def step(self, dt):
        if self._stepping:
            raise RuntimeError("Runtime.step cannot be called recursively")
        if not isinstance(dt, (int, float)) or not isfinite(dt) or dt < 0:
            raise ValueError("dt must be a nonnegative number of seconds")
        self._stepping = True
        try:
            instances = tuple(instance for entity in self.entities for instance in entity.systems.values())
            for phase in ("update", "draw"):
                for instance in instances:
                    if instance.running:
                        if phase == "update":
                            paused = instance.entity.closest("paused")
                            if paused is not None and paused.components.get("paused"):
                                continue
                            if instance.entity.closest(tags=("paused",)) is not None:
                                continue
                        instance.call(phase, dt) if phase == "update" else instance.call(phase)
        finally:
            self._stepping = False

    def close(self):
        for entity in self.entities:
            if entity.alive:
                self.destroy(entity)
