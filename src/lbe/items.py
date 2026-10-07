"""UUID-keyed typed records and their authoritative mutation boundary."""
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from copy import deepcopy
from contextlib import contextmanager
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
        self._by_type = {}

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
        self.entity._check()
        return self._records[self._names[category, name]]

    def has(self, category, name):
        self.entity._check()
        return (category, name) in self._names

    def has_value(self, name):
        return self.has(Component, name)

    def component(self, name):
        return self.named(Component, name)

    def get_value(self, name, default=None):
        """Read conventional named data; the stored key remains the item UUID."""
        try:
            item = self.named(Component, name)
        except KeyError:
            return default
        return self.value(item.id)

    def require_value(self, name):
        return self.value(self.named(Component, name).id)

    def set_value(self, name, value):
        """Create or edit a value, keeping its concrete type and identity."""
        try:
            current = self.named(Component, name)
        except KeyError:
            return self.add(Component(name, value))
        if isinstance(current, InheritedComponent):
            edited = replace(current, patch=({"op": "replace", "value": value},))
        else:
            edited = replace(current, value=value)
        return self.replace(current.id, edited)

    def update_values(self, values=None, **kwargs):
        for name, value in dict(values or {}, **kwargs).items():
            self.set_value(name, value)

    def ensure_value(self, name, default=None):
        if not self.has(Component, name):
            self.add(Component(name, default))
        return self.require_value(name)

    def remove_value(self, name, *default):
        try:
            item = self.named(Component, name)
        except KeyError:
            if default:
                return default[0]
            raise
        value = self.value(item.id)
        self.remove(item.id)
        return value

    def value_dict(self):
        """Disposable resolved snapshot, never an authoritative collection."""
        return {name: self.value(uid) for name, uid in tuple(self._by_category.get(Component, {}).items())}

    def value_names(self):
        self.entity._check()
        return tuple(self._by_category.get(Component, {}))

    def clear_values(self):
        for name in self.value_names():
            self.remove(self.named(Component, name).id)

    def touch_value(self, name):
        item = self.named(Component, name)
        self.entity._changed("component.mutate", name, new=self.value(item.id))
        self.entity.runtime._composition_changed(item.id)

    @contextmanager
    def edit_value(self, name):
        value = deepcopy(self.require_value(name))
        yield value
        self.set_value(name, value)

    def inherit_value(self, name, source, patch=()):
        source = source.id if isinstance(source, (Component, InheritedComponent)) else UUID(str(source))
        return self.add(InheritedComponent(name, source, tuple(deepcopy(patch))))

    def patch_value(self, identity, operations):
        current = self[identity]
        if not isinstance(current, InheritedComponent):
            raise TypeError("Only inherited components have patches")
        return self.replace(current.id, replace(current, patch=tuple(deepcopy(operations))))

    def tag_names(self):
        return tuple(item.name for item in self.all(Tag))

    def has_tag(self, name):
        return self.has(Tag, name)

    def add_tags(self, names):
        for name in names:
            self.add_tag(name)

    def clear_tags(self):
        for item in self.all(Tag):
            self.remove(item.id)

    def add_tag(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError("Item names must be non-empty strings")
        if self.has(Tag, name):
            return self.named(Tag, name)
        return self.add(Tag(name))

    def remove_tag(self, name):
        if self.has(Tag, name):
            return self.remove(self.named(Tag, name).id)

    def target(self, name, default=None):
        try:
            item = self.named(Relation, name)
        except KeyError:
            return default
        return self.entity.runtime.resolve(item.target)

    def require_target(self, name):
        return self.entity.runtime.resolve(self.named(Relation, name).target)

    def has_link(self, name):
        return self.has(Relation, name)

    def clear_links(self):
        for item in self.all(Relation):
            self.remove(item.id)

    def update_links(self, values):
        for name, target in dict(values).items():
            self.connect(name, target)

    def connect(self, name, target):
        if not isinstance(name, str) or not name:
            raise ValueError("Item names must be non-empty strings")
        self.entity.runtime._validate(target)
        if target._destroying:
            raise RuntimeError("Cannot link to an entity during destruction")
        if not self.has(Relation, name):
            return self.add(Relation(name, target.id))
        current = self.named(Relation, name)
        previous = self.entity.runtime.resolve(current.target)
        incoming = self.entity.runtime._incoming.get(previous)
        if incoming is not None:
            incoming.discard((self.entity, name))
            if not incoming:
                self.entity.runtime._incoming.pop(previous, None)
        edited = replace(current, target=target.id)
        self._put(edited)
        self.entity.runtime._incoming.setdefault(target, set()).add((self.entity, name))
        self.entity._changed("relation.set", name, old=previous, new=target)
        return edited

    def disconnect(self, name, *default):
        if not self.has(Relation, name):
            if default:
                return default[0]
            raise KeyError(name)
        item = self.named(Relation, name)
        target = self.entity.runtime.resolve(item.target)
        self.remove(item.id)
        return target

    def link_dict(self):
        return {item.name: self.entity.runtime.resolve(item.target) for item in self.all(Relation)}

    def behaviour_dict(self, kind='system'):
        """Disposable named query snapshot over actual behaviour records."""
        self.entity._check()
        from .systems import SystemInstance
        from .scripts import ScriptInstance
        category = {'system': SystemInstance, 'script': ScriptInstance}[kind]
        return {name: self._records[uid] for name, uid in self._by_category.get(category, {}).items()}

    def behaviour(self, reference, kind='system'):
        self.entity._check()
        from .systems import SystemInstance
        from .scripts import ScriptInstance, identity
        category = {'system': SystemInstance, 'script': ScriptInstance}[kind]
        if isinstance(reference, str) and (category, reference) in self._names:
            return self.named(category, reference)
        try:
            uid = reference if isinstance(reference, UUID) else UUID(str(reference))
        except (ValueError, TypeError):
            uid = None
        record = self._records.get(uid)
        if record is not None and self.category(record) is category:
            return record
        if kind == 'system':
            return self.named(category, reference)
        source_id = identity(self.entity, reference)
        matches = tuple(record for record in self.behaviour_dict('script').values()
                        if record.definition.asset_id == source_id or record.name == str(source_id))
        if len(matches) > 1:
            raise ValueError('Multiple script items use this asset; select an item UUID')
        if not matches:
            raise KeyError(reference)
        return matches[0]

    def get_behaviour(self, reference, default=None, kind='system'):
        try:
            return self.behaviour(reference, kind)
        except (KeyError, ValueError, TypeError):
            return default

    def has_behaviour(self, reference, kind='system'):
        return self.get_behaviour(reference, kind=kind) is not None

    def attach_system(self, name, definition=None, *, identity=None, activate=True):
        from .systems import SystemDefinition, SystemInstance
        if definition is None:
            definition = name if isinstance(name, SystemDefinition) else self.entity.runtime.assets.resolve(name)
            asset_id = definition.asset_id
            if asset_id is None and self.entity.runtime.assets.registry is not None:
                asset_id = self.entity.runtime.assets.registry.get_id(definition.path)
            if asset_id is None:
                raise ValueError('A source-only attachment requires a registered asset UUID')
            name = str(asset_id)
        if not isinstance(definition, SystemDefinition):
            raise TypeError('Expected a SystemDefinition')
        return self.add(SystemInstance(self.entity, name, definition, identity=identity), activate=activate)

    def attach_script(self, reference, *, item_identity=None, activate=True):
        from .systems import SystemDefinition
        from .scripts import ScriptInstance, identity
        definition = reference if isinstance(reference, SystemDefinition) else self.entity.runtime.assets.resolve(reference)
        asset_id = identity(self.entity, definition)
        if asset_id is None:
            raise ValueError('Script must have a registered asset UUID')
        return self.add(ScriptInstance(self.entity, str(asset_id), definition, identity=item_identity), activate=activate)

    def clear_behaviours(self, kind='system'):
        for record in tuple(self.behaviour_dict(kind).values()):
            if record.id in self._records:
                self.remove(record.id)

    def run_script(self, reference, *args, **kwargs):
        try:
            return self.behaviour(reference, 'script').run(*args, **kwargs)
        except Exception as error:
            self.entity._changed('script.error', str(reference), new=str(error))
            return None

    def relocate(self, identity, path, *, new_name=None):
        """Edit source location by item UUID without restarting execution."""
        from .systems import SystemDefinition, SystemInstance
        from .scripts import ScriptInstance
        current = self[identity]
        if not isinstance(current, SystemInstance):
            raise TypeError('Only behaviour items have source locations')
        definition = SystemDefinition(current.definition.source, str(path), current.definition.asset_id)
        if new_name is not None and not isinstance(current, ScriptInstance):
            current = self.rename(current.id, new_name)
        current.definition = definition
        current.namespace['__file__'] = str(path)
        kind = 'script' if isinstance(current, ScriptInstance) else 'system'
        self.entity._changed(kind + '.relocate', current.name)
        return current

    def move_behaviour(self, identity, index):
        """Reorder typed behaviour slots within the canonical item dictionary."""
        current = self[identity]
        from .systems import SystemInstance
        if not isinstance(current, SystemInstance):
            raise TypeError('Expected a behaviour item')
        category = self.category(current)
        identities = list(self._by_category.get(category, {}).values())
        if not isinstance(index, int) or not 0 <= index < len(identities):
            raise IndexError(index)
        identities.remove(current.id)
        identities.insert(index, current.id)
        slots = iter(identities)
        order = [next(slots) if self.category(record) is category else uid
                 for uid, record in self._records.items()]
        self._records = {uid: self._records[uid] for uid in order}
        self._reindex_order()
        self.entity._changed('system.reorder', current.name)

    def _put(self, item):
        old = self._records.get(item.id)
        if (old is not None and type(old) is type(item) and old.name == item.name
                and isinstance(item, (Component, InheritedComponent, Tag, Relation, Parent))
                and (not isinstance(item, InheritedComponent) or old.source == item.source)):
            # Value/patch edits do not need to rebuild unchanged identity indexes.
            self._records[item.id] = item
            self.entity.runtime.linker.objects[item.id] = item
            for item_type in type(item).__mro__[:-1]:
                self._by_type[item_type][item.id] = item
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
        if old is not None and type(old) is not type(item):
            for item_type in type(old).__mro__[:-1]:
                index = self._by_type[item_type]
                index.pop(old.id)
                if not index:
                    self._by_type.pop(item_type)
        if old is not None and old.name != item.name:
            self._names.pop((category, old.name), None)
            self._by_category.get(category, {}).pop(old.name, None)
        self.entity.runtime.linker.register(item, owner=self.entity.id)
        self._records[item.id] = item
        self._names[key] = item.id
        self._by_category.setdefault(category, {})[item.name] = item.id
        for item_type in type(item).__mro__[:-1]:
            self._by_type.setdefault(item_type, {})[item.id] = item

    def _drop(self, identity):
        item = self._records.pop(identity)
        for item_type in type(item).__mro__[:-1]:
            index = self._by_type[item_type]
            index.pop(identity)
            if not index:
                self._by_type.pop(item_type)
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
        self._reindex_order()
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
        from .scripts import ScriptInstance
        from .events import Diagnostic
        import traceback
        current = self[identity]
        if not isinstance(current, SystemInstance):
            raise TypeError("Only behaviour items can be reloaded")
        kind = "script" if isinstance(current, ScriptInstance) else "system"
        try:
            if isinstance(definition, str):
                definition = SystemDefinition(definition, current.definition.path, current.definition.asset_id)
            if not isinstance(definition, SystemDefinition):
                raise TypeError("Expected a definition or source text")
        except Exception as error:
            current.errors.append(Diagnostic(f"{current.name}.compile", str(error), traceback.format_exc()))
            self.entity._changed(kind + ".error", current.name)
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
        self._reindex_order()
        self.entity._changed("item.reorder", item.name)

    def _reindex_order(self):
        """Rebuild disposable ordering indexes from the UUID dictionary."""
        self._by_category = {}
        self._by_type = {}
        for record in self._records.values():
            self._by_category.setdefault(self.category(record), {})[record.name] = record.id
            for item_type in type(record).__mro__[:-1]:
                self._by_type.setdefault(item_type, {})[record.id] = record

    def _replace_identity(self, category, name, identity):
        from .systems import SystemInstance
        item = self.named(category, name)
        self._drop(item.id)
        if isinstance(item, SystemInstance):
            item.id = identity
        else:
            item = replace(item, id=identity)
        self._put(item)

    def all(self, item_type):
        self.entity._check()
        if item_type is object:
            return tuple(self._records.values())
        if isinstance(item_type, type) and not hasattr(item_type, '__abstractmethods__'):
            return tuple(self._by_type.get(item_type, {}).values())
        return tuple(item for item in self._records.values() if isinstance(item, item_type))
