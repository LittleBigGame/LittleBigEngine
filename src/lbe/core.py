"""Generic entity storage, hierarchy and live queries."""

from uuid import UUID, uuid4
from math import isfinite

from .events import Changes, Events, ABSENT
from .items import Component, InheritedComponent, Items, Tag, Relation, Parent

_MISSING = object()


class Entity:
    __slots__ = (
        "_runtime", "_id", "_alive", "_destroying", "_items",
    )

    def __init__(self, runtime, identity):
        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_id", identity)
        object.__setattr__(self, "_alive", True)
        object.__setattr__(self, "_destroying", False)
        object.__setattr__(self, "_items", Items(self))

    id = property(lambda self: self._id)
    alive = property(lambda self: self._alive)
    runtime = property(lambda self: self._runtime)
    items = property(lambda self: self._items)
    handle = property(lambda self: self.runtime.linker.handle(self.id))

    def __getitem__(self, identity):
        return self.items[identity]

    def all(self, item_type):
        return self.items.all(item_type)

    @property
    def _parent(self):
        if not self._alive:
            return None
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
        return self.items.run_script(reference, *args, **kwargs)

    def _check(self):
        if not self._alive:
            raise ReferenceError(f"Entity {self.id} has been destroyed")

    def _changed(self, kind, key=None, **details):
        self.runtime.changes.publish(kind, self, key, **details)

    def __getattr__(self, name):
        try:
            return self.items.require_value(name)
        except KeyError:
            if self.items.has_value(name):
                raise
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name == "parent":
            type(self).parent.fset(self, value)
        elif name.startswith("_") or hasattr(type(self), name):
            raise AttributeError(f"{name} is reserved; use items.set_value({name!r}, value)")
        else:
            self.items.set_value(name, value)

    def __delattr__(self, name):
        if name.startswith("_") or hasattr(type(self), name):
            raise AttributeError(f"{name} is reserved")
        try:
            self.items.remove_value(name)
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
        return next((e for e in chain if e.items.has_tag("root")), chain[-1])

    def inherit(self, key, default=_MISSING):
        for entity in (self,) + self.ancestors:
            if entity.items.has_value(key):
                return entity.items.require_value(key)
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
        return entity.items.has_value(requirement)
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
        if entity.items.has_behaviour(str(uid), kind='script') or entity.items.has_behaviour(str(uid), kind='system'):
            return True
        registry=entity.runtime.assets.registry
        for instance in entity.items.behaviour_dict('system').values():
            if instance.definition.asset_id == uid:
                return True
            try:
                if registry is not None and instance.definition.path and registry.get_id(instance.definition.path)==uid:
                    return True
            except ValueError:
                pass
        return False
    return entity.items.has_value(requirement)


def _matches(entity, components, tags):
    tags = (tags,) if isinstance(tags, str) else tags
    return entity.alive and all(_matches_requirement(entity,k) for k in components) and all(entity.items.has_tag(t) for t in tags)


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

    @property
    def entities(self):
        return tuple(self._entities.values())

    def _validate(self, entity):
        if not isinstance(entity, Entity) or entity.runtime is not self:
            raise ValueError("Entity must belong to this runtime")
        entity._check()

    def _composition_changed(self, identity):
        """Invalidate derived consumers through normal change observations."""
        if identity not in self.linker._dependents:
            return
        for uid in self.linker.dependents(identity):
            item = self.linker.objects.get(uid)
            if not isinstance(item, InheritedComponent):
                continue
            owner = self._entities.get(self.linker.owners.get(uid))
            if owner is None or not owner.alive or owner._destroying:
                continue
            try:
                value = self.linker.component_value(uid)
            except (KeyError, ValueError, TypeError):
                value = ABSENT
            self.changes.publish("component.mutate", owner, item.name, new=value)

    def create(self, *, identity=None, parent=None, tags=(), items=(), **values):
        if 'components' in values:
            raise TypeError('create no longer accepts components; supply typed items')
        if parent is not None:
            self._validate(parent)
            if parent._destroying:
                raise RuntimeError("Cannot create children during parent destruction")
        data = dict(values)
        if hasattr(items, 'items'):
            pairs = tuple(items.items())
            if any(UUID(str(key)) != item.id for key, item in pairs):
                raise ValueError('Item dictionary keys must match record UUIDs')
            declarations = tuple(item for _, item in pairs)
        else:
            declarations = tuple(items)
        ids = [item.id for item in declarations]
        if any(not isinstance(uid, UUID) for uid in ids):
            raise TypeError('Item identities must be UUIDs')
        if len(set(ids)) != len(ids) or any(uid in self.linker.objects for uid in ids):
            raise ValueError('Duplicate item UUID in entity creation')
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
        if identity in ids:
            raise ValueError('An entity and its items must have distinct UUIDs')
        entity = Entity(self, identity)
        self.linker.register(entity)
        for name, value in data.items():
            entity.items._put(Component(name, value))
        for name in dict.fromkeys(tags):
            entity.items._put(Tag(name))
        object.__setattr__(entity, "_parent", parent)
        if parent is not None:
            parent._children.append(entity)
        self._entities[entity.id] = entity
        try:
            # Sources are registered before inherited declarations are linked.
            ordered = sorted(declarations, key=lambda item: isinstance(item, InheritedComponent))
            for item in ordered:
                entity.items.add(item)
            if declarations:
                prefix = [uid for uid in entity.items._records if uid not in ids]
                entity.items._records = {uid: entity.items._records[uid] for uid in prefix + ids}
                entity.items._reindex_order()
        except Exception:
            self.destroy(entity)
            raise
        entity._changed("entity.create")
        return entity

    def resolve(self, identity):
        """Resolve exact persistent identity, never an editable display name."""
        try:
            uid = identity if isinstance(identity, UUID) else UUID(str(identity))
        except (ValueError, TypeError, AttributeError):
            raise KeyError(f'Expected an entity UUID, not {identity!r}') from None
        return self._entities[uid]

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
            node.items.clear_behaviours('system')
            node.items.clear_behaviours('script')
            for other, key in tuple(self._incoming.pop(node, ())):
                if other.alive and other.items.target(key) is node:
                    other.items.disconnect(key)
            node.items.clear_links()
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
            instances = tuple(instance for entity in self.entities for instance in entity.items.behaviour_dict('system').values())
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
                                    if curr.items.has_tag("paused") or (curr.items.get_value("paused") is True):
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
