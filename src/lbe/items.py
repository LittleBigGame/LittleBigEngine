"""UUID-keyed typed records and their authoritative mutation boundary."""
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
        self._by_category = {}

    def __getitem__(self, identity):
        self.entity._check()
        return self._records[identity if isinstance(identity, UUID) else UUID(str(identity))]

    def __iter__(self):
        self.entity._check()
        return iter(tuple(self._records))

    def __len__(self):
        self.entity._check()
        return len(self._records)

    @staticmethod
    def category(item):
        if isinstance(item, (Component, InheritedComponent)):
            return Component
        if isinstance(item, (Tag, Relation, Parent)):
            return type(item)
        from .scripts import ScriptInstance
        from .systems import SystemInstance
        if isinstance(item, ScriptInstance):
            return ScriptInstance
        if isinstance(item, SystemInstance):
            return SystemInstance
        return type(item)

    def named(self, category, name):
        return self._records[self._names[category, name]]

    def _put(self, item):
        old = self._records.get(item.id)
        if (old is not None and type(old) is type(item) and old.name == item.name
                and isinstance(item, (Component, InheritedComponent, Tag, Relation, Parent))
                and (not isinstance(item, InheritedComponent) or old.source == item.source)):
            # Value/patch edits do not need to rebuild unchanged identity indexes.
            self._records[item.id] = item
            self.entity.runtime.linker.objects[item.id] = item
            return
        category = self.category(item)
        key = category, item.name
        previous_id = self._names.get(key)
        existing = self.entity.runtime.linker.objects.get(item.id)
        if existing is not None and item.id not in self._records:
            raise ValueError(f"Duplicate object UUID: {item.id}")
        if previous_id is not None and previous_id != item.id:
            self._drop(previous_id)
        old = self._records.get(item.id)
        if old is not None and old.name != item.name:
            self._names.pop((category, old.name), None)
            self._by_category.get(category, {}).pop(old.name, None)
        self.entity.runtime.linker.register(item, owner=self.entity.id)
        self._records[item.id] = item
        self._names[key] = item.id
        self._by_category.setdefault(category, {})[item.name] = item.id

    def _drop(self, identity):
        item = self._records.pop(identity)
        self._names.pop((self.category(item), item.name), None)
        self._by_category.get(self.category(item), {}).pop(item.name, None)
        self.entity.runtime.linker.unregister(identity)
        return item

    def add(self, item, *, activate=True):
        """Insert an actual typed record, not a named collection projection.

        Application-defined record types are supported. Runtime behaviours are
        records in this same collection; initialization follows registration so
        their own identity is already linkable when their source executes.
        """
        self.entity._check()
        if self.entity._destroying:
            raise RuntimeError("Cannot add items during entity destruction")
        if not isinstance(item.id, UUID):
            raise TypeError("Item identity must be a UUID")
        if not isinstance(item.name, str) or not item.name:
            raise ValueError("Item names must be nonempty strings")
        category = self.category(item)
        if (category, item.name) in self._names or item.id in self.entity.runtime.linker.objects:
            raise ValueError("Item identity/name already exists")
        if isinstance(item, (Component, InheritedComponent)):
            if isinstance(item, InheritedComponent):
                compose(self.entity.runtime.linker.component_value(item.source), item.patch)
            self._put(item)
            self.entity._changed("component.set", item.name, new=self.value(item.id))
            self.entity.runtime._composition_changed(item.id)
        elif isinstance(item, Tag):
            self._put(item)
            self.entity._changed("tag.add", item.name, old=False, new=True)
        elif isinstance(item, Relation):
            target = self.entity.runtime.resolve(item.target)
            self.entity.runtime._validate(target)
            if target._destroying:
                raise RuntimeError("Cannot link to an entity during destruction")
            self._put(item)
            self.entity.runtime._incoming.setdefault(target, set()).add((self.entity, item.name))
            self.entity._changed("relation.set", item.name, old=None, new=target)
        elif isinstance(item, Parent):
            self.entity.parent = self.entity.runtime.resolve(item.target)
            self._replace_identity(Parent, "parent", item.id)
        else:
            from .systems import SystemInstance
            from .scripts import ScriptInstance
            if isinstance(item, SystemInstance):
                if item.entity is not self.entity:
                    raise ValueError("Behaviour belongs to another entity")
                if item._initialized or item._started or item._stopped:
                    raise ValueError("Insert a fresh behaviour declaration")
                self._put(item)
                kind = "script" if isinstance(item, ScriptInstance) else "system"
                self.entity._changed(kind + ".attach", item.name)
                if activate and item.initialize() and self.entity.alive and self._records.get(item.id) is item:
                    item.start()
            else:
                # A custom typed item is ordinary data. Core does not need to
                # know what a TransformComponent or application record means.
                self._put(item)
                self.entity._changed("item.add", item.name, new=item)
        return item

    def remove(self, identity):
        """Remove by persistent UUID with lifetime/index/observation cleanup."""
        item = self[identity]
        category = self.category(item)
        if category is Component:
            try:
                previous = self.value(item.id)
            except (KeyError, TypeError, ValueError):
                from .events import ABSENT
                previous = ABSENT
            self._drop(item.id)
            self.entity._changed("component.remove", item.name, old=previous)
            self.entity.runtime._composition_changed(item.id)
        elif category is Tag:
            self._drop(item.id)
            self.entity._changed("tag.remove", item.name, old=True, new=False)
        elif category is Relation:
            target = self.entity.runtime.resolve(item.target)
            incoming = self.entity.runtime._incoming.get(target)
            if incoming is not None:
                incoming.discard((self.entity, item.name))
                if not incoming:
                    self.entity.runtime._incoming.pop(target, None)
            self._drop(item.id)
            self.entity._changed("relation.remove", item.name, old=target)
        elif category is Parent:
            self.entity.parent = None
        else:
            from .systems import SystemInstance
            from .scripts import ScriptInstance
            if isinstance(item, SystemInstance):
                self._drop(item.id)
                item.stop()
                kind = "script" if isinstance(item, ScriptInstance) else "system"
                self.entity._changed(kind + ".detach", item.name)
            else:
                self._drop(item.id)
                self.entity._changed("item.remove", item.name, old=item)
        return item

    def value(self, identity):
        """Resolve component data by UUID, including inherited composition."""
        item = self[identity]
        if not isinstance(item, (Component, InheritedComponent)):
            raise TypeError("Item is not a value component")
        return self.entity.runtime.linker.component_value(item.id)

    def replace(self, identity, replacement):
        """Edit a data record without replacing its persistent identity."""
        current = self[identity]
        from .systems import SystemInstance
        if isinstance(current, (SystemInstance, Parent, Relation)):
            raise TypeError("Use lifecycle/link operations to replace this item")
        if type(replacement) is not type(current) or replacement.id != current.id:
            raise ValueError("Replacement must preserve item UUID and type")
        if replacement.name != current.name:
            raise ValueError("Rename the item explicitly")
        if isinstance(replacement, InheritedComponent):
            compose(self.entity.runtime.linker.component_value(replacement.source), replacement.patch)
        previous = self.value(current.id) if isinstance(current, (Component, InheritedComponent)) else current
        self._put(replacement)
        if isinstance(replacement, (Component, InheritedComponent)):
            self.entity._changed("component.set", replacement.name, old=previous, new=self.value(replacement.id))
            self.entity.runtime._composition_changed(replacement.id)
        else:
            self.entity._changed("item.set", replacement.name, old=previous, new=replacement)
        return replacement

    def rename(self, identity, name):
        """Change a display name; UUID references and runtime handles survive."""
        item = self[identity]
        if not isinstance(name, str) or not name:
            raise ValueError("Item names must be nonempty strings")
        if isinstance(item, Parent):
            raise TypeError("Parent labels are structural")
        if name == item.name:
            return item
        category = self.category(item)
        if (category, name) in self._names:
            raise ValueError("Item name already exists for this type")
        old_name = item.name
        from .systems import SystemInstance
        if isinstance(item, SystemInstance):
            self._names.pop((category, old_name))
            self._by_category[category].pop(old_name)
            item.name = name
            renamed = item
        else:
            renamed = replace(item, name=name)
        self._put(renamed)
        if isinstance(item, Relation):
            target = self.entity.runtime.resolve(item.target)
            incoming = self.entity.runtime._incoming[target]
            incoming.discard((self.entity, old_name))
            incoming.add((self.entity, name))
        kind = "component.rename" if category is Component else "item.rename"
        self.entity._changed(kind, old_name, new=name)
        return renamed

    def reload(self, identity, definition):
        """Reload a behaviour selected by item UUID, preserving live references."""
        from .systems import SystemDefinition, SystemInstance
        from .events import Diagnostic
        import traceback
        current = self[identity]
        if not isinstance(current, SystemInstance):
            raise TypeError("Only behaviour items can be reloaded")
        try:
            if isinstance(definition, str):
                definition = SystemDefinition(definition, current.definition.path, current.definition.asset_id)
            if not isinstance(definition, SystemDefinition):
                raise TypeError("Expected a definition or source text")
        except Exception as error:
            current.errors.append(Diagnostic(f"{current.name}.compile", str(error), traceback.format_exc()))
            self.entity._changed("system.error", current.name)
            return current
        candidate = type(current)(self.entity, current.name, definition, identity=current.id)
        if not candidate.initialize():
            current.errors.extend(candidate.errors)
            return current
        if not self.entity.alive or self._records.get(current.id) is not current:
            candidate.stop()
            return current
        current.stop()
        if not self.entity.alive or self._records.get(current.id) is not current:
            candidate.stop()
            return current
        self._put(candidate)
        candidate.start()
        from .scripts import ScriptInstance
        kind = "script" if isinstance(candidate, ScriptInstance) else "system"
        self.entity._changed(kind + ".reload", candidate.name)
        return candidate

    def move(self, identity, index):
        """Reorder the actual UUID dictionary, not a separate attachment list."""
        item = self[identity]
        if not isinstance(index, int) or not 0 <= index < len(self._records):
            raise IndexError(index)
        order = list(self._records)
        order.remove(item.id)
        order.insert(index, item.id)
        self._records = {uid: self._records[uid] for uid in order}
        self._by_category = {}
        for record in self._records.values():
            self._by_category.setdefault(self.category(record), {})[record.name] = record.id
        self.entity._changed("item.reorder", item.name)

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
            if isinstance(item, Component):
                return item.value
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
        return iter(tuple(self.entity.items._by_category.get(self.category, {})))

    def __len__(self):
        return len(self.entity.items._by_category.get(self.category, {}))

    def __contains__(self, name):
        return (self.category, name) in self.entity.items._names

    def reorder(self, pairs):
        ids = [value.id for _, value in pairs]
        records = self.entity.items._records
        slots = iter(ids)
        order = [next(slots) if identity in ids else identity for identity in records]
        self.entity.items._records = {identity: records[identity] for identity in order}
        self.entity.items._by_category[self.category] = {records[uid].name: uid for uid in ids}


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
