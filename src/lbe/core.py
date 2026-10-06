"""Generic entity storage, hierarchy and live queries."""

from collections.abc import MutableMapping, MutableSet
from contextlib import contextmanager
from copy import deepcopy
from uuid import UUID, uuid4
from math import isfinite

from .events import Changes, Events, ABSENT
from .items import Component, InheritedComponent, Items, NamedValues, Tag, TagValues, Relation, Parent

_MISSING = object()


class Components(MutableMapping):
    def __init__(self, entity):
        self._entity = entity
        self._values = NamedValues(entity, Component)

    def item(self, key):
        """Persistent declaration behind a named component value."""
        self._entity._check()
        return self._values.record(key)

    def rename(self, key, new_name):
        from dataclasses import replace
        if not isinstance(new_name, str) or not new_name:
            raise ValueError("Component names must be nonempty strings")
        item = self.item(key)
        if key == new_name:
            return item
        if new_name in self:
            raise ValueError(f"Component {new_name!r} already exists")
        self._entity.items._names.pop((Component, key))
        renamed = replace(item, name=new_name)
        self._entity.items._put(renamed)
        self._entity._changed("component.rename", key, new=new_name)
        return renamed

    def inherit(self, key, source, patch=()):
        """Attach a source UUID and local patch without copying authoritative data."""
        source = source.id if isinstance(source, (Component, InheritedComponent)) else UUID(str(source))
        candidate = InheritedComponent(key, source, tuple(deepcopy(patch)))
        # Validate before altering the entity. Missing/cyclic sources are errors.
        self._entity.runtime.linker.component_value(source)
        if key in self:
            raise ValueError(f"Component {key!r} already exists")
        return self._entity.items.add(candidate)

    def patch(self, key, operations):
        from dataclasses import replace
        from .items import compose
        current = self.item(key)
        if not isinstance(current, InheritedComponent):
            raise TypeError("Only inherited components have patches")
        operations = tuple(deepcopy(operations))
        value = compose(self._entity.runtime.linker.component_value(current.source), operations)
        previous = self[key]
        self._entity.items._put(replace(current, patch=operations))
        self._entity._changed("component.set", key, old=previous, new=value)

    def __getitem__(self, key):
        self._entity._check()
        return self._values[key]

    def __setitem__(self, key, value):
        self._entity._check()
        if not isinstance(key, str) or not key:
            raise ValueError("Component names must be nonempty strings")
        previous = self._values.get(key, ABSENT)
        self._values[key] = value
        self._entity._changed("component.set", key, old=previous, new=value)

    def __delitem__(self, key):
        self._entity._check()
        previous = self._values.pop(key)
        self._entity._changed("component.remove", key, old=previous)

    def __iter__(self):
        self._entity._check()
        return iter(tuple(self._values))

    def __len__(self):
        self._entity._check()
        return len(self._values)

    def touch(self, key):
        """Notify observers after externally mutating an arbitrary object."""
        self._entity._changed("component.mutate", key, new=self[key])

    @contextmanager
    def edit(self, key):
        """Edit a deep copy and commit once, only on successful exit."""
        value = deepcopy(self[key])
        yield value
        self[key] = value


class Tags(MutableSet):
    def __init__(self, entity):
        self._entity = entity
        self._values = TagValues(entity)

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
            self._entity._changed("tag.add", value, old=False, new=True)

    def discard(self, value):
        self._entity._check()
        if value in self._values:
            self._values.remove(value)
            self._entity._changed("tag.remove", value, old=True, new=False)


class Relations(MutableMapping):
    """Named directed links to live entities in the same runtime."""

    def __init__(self, entity):
        self._entity = entity
        self._values = NamedValues(entity, Relation)

    def __getitem__(self, key):
        self._entity._check()
        return self._values[key]

    def __setitem__(self, key, target):
        self._entity._check()
        if not isinstance(key, str) or not key:
            raise ValueError("Relation names must be nonempty strings")
        self._entity.runtime._validate(target)
        if target._destroying:
            raise RuntimeError("Cannot link to an entity during destruction")
        runtime = self._entity.runtime
        previous = self._values.get(key)
        if previous is not None:
            incoming = runtime._incoming.get(previous)
            if incoming is not None:
                incoming.discard((self._entity, key))
                if not incoming:
                    runtime._incoming.pop(previous, None)
        self._values[key] = target
        runtime._incoming.setdefault(target, set()).add((self._entity, key))
        self._entity._changed("relation.set", key, old=previous, new=target)

    def __delitem__(self, key):
        self._entity._check()
        target = self._values.pop(key)
        incoming = self._entity.runtime._incoming.get(target)
        if incoming is not None:
            incoming.discard((self._entity, key))
            if not incoming:
                self._entity.runtime._incoming.pop(target, None)
        self._entity._changed("relation.remove", key, old=target)

    def __iter__(self):
        self._entity._check()
        return iter(tuple(self._values))

    def __len__(self):
        self._entity._check()
        return len(self._values)


class Entity:
    __slots__ = (
        "_runtime", "_id", "_alive", "_destroying", "_items",
        "_components", "_tags", "_relations", "_systems", "_scripts",
    )

    def __init__(self, runtime, identity):
        from .systems import Systems
        from .scripts import Scripts

        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_id", identity)
        object.__setattr__(self, "_alive", True)
        object.__setattr__(self, "_destroying", False)
        object.__setattr__(self, "_items", Items(self))
        object.__setattr__(self, "_components", Components(self))
        object.__setattr__(self, "_tags", Tags(self))
        object.__setattr__(self, "_relations", Relations(self))
        object.__setattr__(self, "_systems", Systems(self))
        object.__setattr__(self, "_scripts", Scripts(self))

    id = property(lambda self: self._id)
    alive = property(lambda self: self._alive)
    runtime = property(lambda self: self._runtime)
    components = property(lambda self: self._components)
    tags = property(lambda self: self._tags)
    relations = property(lambda self: self._relations)
    systems = property(lambda self: self._systems)
    scripts = property(lambda self: self._scripts)
    items = property(lambda self: self._items)
    handle = property(lambda self: self.runtime.linker.handle(self.id))

    def __getitem__(self, identity):
        return self.items[identity]

    def all(self, item_type):
        return self.items.all(item_type)

    @property
    def _parent(self):
        try:
            return self.runtime.resolve(self.items.named(Parent, "parent").target)
        except KeyError:
            return None

    @_parent.setter
    def _parent(self, target):
        try:
            item = self.items.named(Parent, "parent")
        except KeyError:
            item = None
        if target is None:
            if item is not None:
                self.items._drop(item.id)
        else:
            self.items._put(Parent(target.id, item.id if item else uuid4()))

    @property
    def _children(self):
        # Derived adjacency/sibling order, never recursively owned entity records.
        return self.runtime._children.setdefault(self.id, [])

    def run(self, reference, *args, **kwargs):
        return self.scripts.run(reference,*args,**kwargs)

    def _check(self):
        if not self._alive:
            raise ReferenceError(f"Entity {self.id} has been destroyed")

    def _changed(self, kind, key=None, **details):
        self.runtime.changes.publish(kind, self, key, **details)

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

    def __deepcopy__(self, memo):
        # An identity handle must never clone its owning runtime.
        return self

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
        previous = self._parent
        if self._parent is not None:
            self._parent._children.remove(self)
        object.__setattr__(self, "_parent", parent)
        if parent is not None:
            parent._children.append(self)
        self._changed("hierarchy.parent", old=previous, new=parent)

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


def _matches_requirement(entity, requirement):
    if isinstance(requirement,str):
        return requirement in entity.components
    from .systems import SystemDefinition
    from .assets import AssetRef
    if isinstance(requirement,(tuple,list)):
        return all(_matches_requirement(entity,k) for k in requirement)
    if isinstance(requirement, Entity):
        return requirement in entity.children
    if isinstance(requirement,(SystemDefinition,AssetRef,UUID)):
        from .scripts import identity
        uid=identity(entity,requirement)
        if uid is None:
            return False
        if str(uid) in entity.scripts or str(uid) in entity.systems:
            return True
        registry=entity.runtime.assets.registry
        for instance in entity.systems.values():
            if instance.definition.asset_id == uid:
                return True
            try:
                if registry is not None and instance.definition.path and registry.get_id(instance.definition.path)==uid:
                    return True
            except ValueError:
                pass
        return False
    return requirement in entity.components


def _matches(entity, components, tags):
    tags = (tags,) if isinstance(tags, str) else tags
    return entity.alive and all(_matches_requirement(entity,k) for k in components) and all(t in entity.tags for t in tags)


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
        results = tuple(e for e in candidates if _matches(e, self._components, self._tags))
        self._runtime.events._observe('query.result', (results,), {})
        return iter(results)


class Runtime:
    def __init__(self):
        from .systems import Assets

        self._entities = {}
        self._children = {}
        from .linker import Linker
        self.linker = Linker(self)
        self._incoming = {}
        self.changes = Changes()
        self.events = Events()
        self.assets = Assets()
        self.services = {}
        self._stepping = False
        self._incoming_relations = {}

    def _track_relation(self, source, key, target):
        if target not in self._incoming_relations:
            self._incoming_relations[target] = set()
        self._incoming_relations[target].add((source, key))

    def _untrack_relation(self, source, key, target):
        incoming = self._incoming_relations.get(target)
        if incoming:
            incoming.discard((source, key))
            if not incoming:
                del self._incoming_relations[target]

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
            if identity in self.linker.objects:
                raise ValueError(f"Entity with id {identity} already exists")
        else:
            identity = uuid4()
        entity = Entity(self, identity)
        self.linker.register(entity)
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
            node.scripts.clear()
            for other, key in tuple(self._incoming.pop(node, ())):
                if other.alive and other.relations.get(key) is node:
                    del other.relations[key]
            node.relations.clear()
            if node._parent is not None:
                node._parent._children.remove(node)
            object.__setattr__(node, "_parent", None)
            del self._entities[node.id]
            for identity in tuple(node.items):
                node.items._drop(identity)
            self.linker.unregister(node.id)
            self._children.pop(node.id, None)
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
            pause_cache = {}
            for phase in ("update", "draw"):
                for instance in instances:
                    if instance.running:
                        if phase == "update":
                            ent = instance.entity
                            if ent not in pause_cache:
                                is_p = False
                                curr = ent
                                while curr is not None:
                                    if "paused" in curr.tags or (curr.components.get("paused") is True):
                                        is_p = True
                                        break
                                    if curr in pause_cache:
                                        is_p = pause_cache[curr]
                                        break
                                    curr = curr._parent
                                c_fill = ent
                                while c_fill is not None and c_fill not in pause_cache:
                                    pause_cache[c_fill] = is_p
                                    c_fill = c_fill._parent
                            if pause_cache[ent]:
                                continue
                        instance.call(phase, dt) if phase == "update" else instance.call(phase)
        finally:
            self._stepping = False

    def close(self):
        for entity in self.entities:
            if entity.alive:
                self.destroy(entity)
        self.events.emit('runtime.close')
