"""Load a directory of application scripts through the public runtime API and persist project state."""

import json
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
import tempfile
from uuid import UUID

from .core import Entity, Runtime
from .events import Diagnostic
from .space import SpatialIndex

CURRENT_VERSION = 4


@dataclass(frozen=True)
class EntityRef:
    """An unresolved persisted identity, retained until its target is available."""
    id: UUID

    def resolve(self, runtime):
        return runtime.resolve(self.id)


@dataclass
class Restoration:
    """Diagnostics only; persistent declarations live in Entity.items."""
    diagnostics: list[Diagnostic] = field(default_factory=list)


def restoration(runtime):
    return runtime.services.setdefault("restoration", Restoration())


class PersistentGraph:
    """Application-owned entities remain persistent even when their UI placement changes."""

    def __init__(self, runtime, entities, *, application=None):
        entities = tuple(entities)
        self.runtime = runtime
        self.application = application
        self._entities = {entity.id: entity for entity in entities}
        self.revision = 0
        self.schema_revision = 0
        self._types = {entity.id: {key: type(value) for key, value in entity.items.value_dict().items()} for entity in entities}
        self._unsubscribe = runtime.changes.subscribe(self._change)

    @property
    def entities(self):
        return tuple(self._entities.values())

    def include(self, entity):
        if entity.runtime is not self.runtime or not entity.alive:
            raise ValueError("Expected a live entity in this runtime")
        self._entities[entity.id] = entity
        self._types[entity.id] = {key: type(value) for key, value in entity.items.value_dict().items()}
        self.revision += 1
        self.schema_revision += 1

    def _change(self, change):
        entity = change.entity
        if change.kind == "entity.create" and not entity.items.has_tag("ui"):
            parent = entity.parent
            if parent is None or parent is self.application or parent.id in self._entities:
                self.include(entity)
        if entity.id in self._entities:
            self.revision += 1
            if change.kind == "entity.destroy":
                self._entities.pop(entity.id)
                self._types.pop(entity.id, None)
                self.schema_revision += 1
            elif change.kind.startswith("component."):
                types = self._types[entity.id]
                value_type = type(entity.items.require_value(change.key)) if entity.items.has_value(change.key) else None
                if change.key == "name" or types.get(change.key) is not value_type:
                    self.schema_revision += 1
                if value_type is None:
                    types.pop(change.key, None)
                else:
                    types[change.key] = value_type

    def close(self):
        self._unsubscribe()


def serialize_value(value, *, project_dir=None, on_unsupported="error", known_ids=None):
    """Serialize a supported value to JSON-compatible data structures."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"Cannot serialize non-finite float: {value}")
        return value
    if isinstance(value, UUID):
        return {"__type__": "uuid", "value": str(value)}
    from .assets import AssetRef
    if isinstance(value, AssetRef):
        return {"__type__": "asset_ref", "id": str(value.id), "type": value.type, "name": value.name}
    if isinstance(value, (Entity, EntityRef)):
        if isinstance(value, Entity) and (not value.alive or known_ids is not None and value.id not in known_ids):
            raise ValueError(f"Entity reference {value.id} is outside the saved project")
        return {"__type__": "entity", "id": str(value.id)}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "values": [serialize_value(x, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=known_ids) for x in value]}
    if isinstance(value, set):
        return {"__type__": "set", "values": [serialize_value(x, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=known_ids) for x in sorted(value, key=str)]}
    if isinstance(value, list):
        return [serialize_value(x, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=known_ids) for x in value]
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise TypeError(f"Dictionary keys must be strings, got {type(k).__name__}")
        values = {k: serialize_value(v, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=known_ids) for k, v in value.items()}
        return {"__type__": "dict", "values": values} if "__type__" in value else values
    if on_unsupported == "error":
        raise TypeError(f"Cannot serialize unsupported object of type {type(value).__name__}: {value!r}")
    elif on_unsupported == "skip":
        return None
    else:
        raise ValueError(f"Unknown on_unsupported mode: {on_unsupported!r}")


def deserialize_value(data, *, runtime=None, id_map=None):
    """Deserialize supported value from serialized data structure."""
    if data is None or isinstance(data, (int, float, str, bool)):
        return data
    if isinstance(data, list):
        return [deserialize_value(x, runtime=runtime, id_map=id_map) for x in data]
    if isinstance(data, dict):
        if "__type__" in data:
            type_tag = data["__type__"]
            if type_tag == "uuid":
                return UUID(data["value"])
            elif type_tag == "asset_ref":
                from .assets import AssetRef
                return AssetRef(UUID(data["id"]), data.get("type", "asset"), data.get("name", ""))
            elif type_tag == "entity":
                entity_id = UUID(data["id"])
                if id_map is not None and entity_id in id_map:
                    return id_map[entity_id]
                if runtime is not None:
                    try:
                        return runtime.resolve(entity_id)
                    except KeyError:
                        restoration(runtime).diagnostics.append(Diagnostic("project.reference", f"Missing entity {entity_id}"))
                        return EntityRef(entity_id)
                return entity_id
            elif type_tag == "dict":
                return {k: deserialize_value(v, runtime=runtime, id_map=id_map) for k, v in data["values"].items()}
            elif type_tag == "tuple":
                return tuple(deserialize_value(x, runtime=runtime, id_map=id_map) for x in data["values"])
            elif type_tag == "set":
                return set(deserialize_value(x, runtime=runtime, id_map=id_map) for x in data["values"])
            else:
                raise ValueError(f"Unknown serialized type tag: {type_tag!r}")
        return {k: deserialize_value(v, runtime=runtime, id_map=id_map) for k, v in data.items()}
    raise TypeError(f"Unexpected serialized data structure: {type(data).__name__}")


def serialize_entity(entity, *, project_dir=None, on_unsupported="error", known_ids=None, transient_relations=()):
    """Write only the canonical UUID dictionary, excluding explicit transient links."""
    from .item_storage import encode_items
    return {"id": str(entity.id), "items": encode_items(entity,
        encode=lambda value: serialize_value(value, project_dir=project_dir,
            on_unsupported=on_unsupported, known_ids=known_ids),
        project_dir=project_dir, known_ids=known_ids,
        transient_relations=transient_relations, on_unsupported=on_unsupported)}


def serialize_entities(entities, *, project_dir=None, on_unsupported="error", known_ids=None, transient_relations=None):
    """Serialize a collection of entities."""
    entities = tuple(entities)
    entity_ids = {e.id for e in entities}
    if known_ids:
        entity_ids.update(UUID(str(x)) if not isinstance(x, UUID) else x for x in known_ids if x is not None)
    transient_relations = transient_relations or {}
    return [serialize_entity(e, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=entity_ids,
                             transient_relations=transient_relations.get(e.id, ())) for e in entities]


def deserialize_entities(entity_data_list, runtime, *, project_dir=None, activate=True):
    """Register all native records before linking references and executing behaviour."""
    from .item_storage import validate_record, StoredSource, ITEM_TYPES
    from .items import Component, InheritedComponent, Tag, Relation, Parent
    from .systems import SystemInstance
    from .scripts import ScriptInstance
    records = [validate_record(record) for record in entity_data_list]
    ids = [UUID(record["id"]) for record in records]
    all_ids = ids + [UUID(uid) for record in records for uid in record["items"]]
    if len(set(all_ids)) != len(all_ids) or any(uid in runtime.linker.objects for uid in all_ids):
        raise ValueError("Duplicate object UUID in project")
    parents = {entity.id: entity.items.named(Parent, 'parent').target
               for entity in runtime.entities if entity.items.has(Parent, 'parent')}
    parents.update({eid: next((UUID(item["target"]) for item in record["items"].values()
                             if item["type"] == "Parent"), None) for eid, record in zip(ids, records)})
    for eid in parents:
        current, seen = eid, set()
        while current in parents:
            if current in seen:
                raise ValueError("Project hierarchy contains a cycle")
            seen.add(current)
            current = parents[current]
    created = {}
    diagnostics = restoration(runtime).diagnostics
    diagnostic_start = len(diagnostics)
    try:
        for eid in ids:
            created[eid] = runtime.create(identity=eid)
        for eid, record in zip(ids, records):
            target = created[eid]
            for identity, declaration in record["items"].items():
                uid, kind, name = UUID(identity), declaration["type"], declaration["name"]
                if kind == "Component":
                    item = Component(name, deserialize_value(declaration["value"], runtime=runtime, id_map=created), uid)
                elif kind == "InheritedComponent":
                    patch = deserialize_value(declaration["patch"], runtime=runtime, id_map=created)
                    item = InheritedComponent(name, UUID(declaration["source"]), tuple(patch), uid)
                elif kind == "Tag":
                    item = Tag(name, uid)
                elif kind == "Relation":
                    item = Relation(name, UUID(declaration["target"]), uid)
                elif kind == "Parent":
                    item = Parent(UUID(declaration["target"]), uid)
                elif kind in ('System', 'Script'):
                    source = declaration["definition"]
                    definition = StoredSource(source["path"],
                        UUID(source["asset_id"]) if source.get("asset_id") else None, source.get("source"))
                    item_type = ScriptInstance if kind == "Script" else SystemInstance
                    item = item_type(target, name, definition, identity=uid)
                else:
                    payload = deserialize_value(declaration['data'], runtime=runtime, id_map=created)
                    item = ITEM_TYPES[kind](name=name, id=uid, **payload)
                target.items._put(item)
            for item in target.all(Component):
                target._changed("component.set", item.name, new=item.value)
        for target in created.values():
            resolve_references(target, runtime)
        # Sibling ordering is encoded on the Parent item, not an Entity field.
        positions = {eid: next((item["position"] for item in record["items"].values()
                               if item["type"] == "Parent"), 0) for eid, record in zip(ids, records)}
        for parent in {entity.parent for entity in created.values() if entity.parent is not None}:
            children = [entity for entity in created.values() if entity.parent is parent]
            for index, child in enumerate(sorted(children, key=lambda entity: positions[entity.id])):
                parent.move_child(child, index)
    except Exception:
        for target in reversed(tuple(created.values())):
            if target.alive:
                target.destroy()
        del diagnostics[diagnostic_start:]
        raise
    if activate:
        activate_entities(created.values(), runtime, project_dir=project_dir)
    return created


def activate_entities(entities, runtime, *, project_dir=None):
    """Compile/link all declarations, initialize all, then start all."""
    from .item_storage import StoredSource, compile_source
    from .systems import SystemInstance
    ready = []
    diagnostics = restoration(runtime).diagnostics
    for entity in tuple(entities):
        if not entity.alive:
            continue
        resolve_references(entity, runtime)
        for instance in entity.all(SystemInstance):
            if instance._initialized or instance._stopped:
                continue
            if isinstance(instance.definition, StoredSource):
                try:
                    instance.definition = compile_source(instance.definition, runtime, project_dir)
                    entity.items._put(instance)
                except (OSError, ValueError, TypeError, SyntaxError) as error:
                    diagnostics.append(Diagnostic('project.behaviour', f'{instance.id}: {error}'))
                    continue
            ready.append(instance)
    initialized = []
    for instance in ready:
        if instance.entity.alive and runtime.linker.objects.get(instance.id) is instance:
            if instance.initialize():
                initialized.append(instance)
            else:
                diagnostics.extend(instance.errors)
    for instance in initialized:
        if instance.entity.alive and runtime.linker.objects.get(instance.id) is instance:
            instance.start()
            if not instance.running:
                diagnostics.extend(instance.errors)


def resolve_references(entity, runtime):
    """Recover retained identities without changing unrelated component objects."""
    from .items import Parent, Relation
    diagnostics = restoration(runtime).diagnostics
    for item in entity.all(Parent):
        try:
            parent = runtime.resolve(item.target)
        except KeyError:
            diagnostics.append(Diagnostic('project.parent', f'Missing parent {item.target} for {entity.id}'))
            continue
        if entity not in parent._children:
            parent._children.append(entity)
            entity._changed('hierarchy.parent', old=None, new=parent)
    for item in entity.all(Relation):
        try:
            target = runtime.resolve(item.target)
        except KeyError:
            diagnostics.append(Diagnostic('project.relation', f'Missing target {item.target} for {item.id}'))
            continue
        runtime._incoming.setdefault(target, set()).add((entity, item.name))


    def resolve_value(value, seen):
        if isinstance(value, EntityRef):
            try:
                return runtime.resolve(value.id), True
            except KeyError:
                return value, False
        if type(value) not in (dict, list, tuple, set) or id(value) in seen:
            return value, False
        seen.add(id(value))
        if isinstance(value, dict):
            resolved = {key: resolve_value(item, seen) for key, item in value.items()}
            changed = any(flag for _, flag in resolved.values())
            return ({key: item for key, (item, _) in resolved.items()} if changed else value), changed
        resolved = [resolve_value(item, seen) for item in value]
        changed = any(flag for _, flag in resolved)
        return (type(value)(item for item, _ in resolved) if changed else value), changed

    from .items import Component
    for item in entity.all(Component):
        key, value = item.name, item.value
        resolved, changed = resolve_value(value, set())
        if changed:
            entity.items.set_value(key, resolved)


def validate_project_data(data):
    """Accept the native schema only; never convert or write an older document."""
    if not isinstance(data, dict):
        raise ValueError('Invalid project file format: expected JSON object')
    version = data.get('version')
    if type(version) is not int or version != CURRENT_VERSION:
        raise ValueError(f'Unsupported project format {version!r}; native version {CURRENT_VERSION} required. Existing files were not converted.')
    from .item_storage import validate_record
    if not isinstance(data.get('entities'), list):
        raise ValueError('Project entities must be a list')
    for record in data['entities']:
        validate_record(record)
    if data.get('application_id') is not None:
        UUID(data['application_id'])
    return data


def save_project(directory, *, entities=None, layout=None, assets=None, application_id=None, filename="project.json", on_unsupported="error", transient_relations=None):
    """Atomically save project entities and editor layout to a versioned project file."""
    directory = Path(directory).resolve()
    load_project_data(directory, filename=filename)
    directory.mkdir(parents=True, exist_ok=True)
    project_file = directory / filename

    if hasattr(assets, "to_dict"):
        assets_data = assets.to_dict()
    elif isinstance(assets, dict):
        assets_data = assets
    else:
        assets_data = {}

    known_extra = {application_id} if application_id is not None else None
    data = {
        "version": CURRENT_VERSION,
        "application_id": str(application_id) if application_id is not None else None,
        "entities": serialize_entities(entities, project_dir=directory, on_unsupported=on_unsupported, known_ids=known_extra, transient_relations=transient_relations) if entities is not None else [],
        "layout": serialize_value(layout, project_dir=directory, on_unsupported=on_unsupported) if layout is not None else {},
        "assets": assets_data,
    }

    write_json(project_file, data)
    return project_file


def write_json(path, data):
    """Replace JSON atomically and clean up a failed temporary write."""
    path = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False, suffix=".tmp") as file:
            temp_path = Path(file.name)
            json.dump(data, file, indent=2, allow_nan=False)
            file.flush()
            import os
            os.fsync(file.fileno())
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def load_project_data(directory, *, filename="project.json"):
    """Load native project JSON data if the file exists, otherwise None."""
    project_file = Path(directory) / filename
    if not project_file.exists():
        return None
    with open(project_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_project_data(data)


def template_path(name):
    root = Path(__file__).parent / "templates"
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_dir():
        raise ValueError("Unknown bundled application template")
    return path


def load_project(window, graphics, input_state, directory, *, template=None, entry="app.py"):
    directory = Path(directory).resolve()
    # Reject unsupported documents before template/recovery/user-state writes.
    project_data = load_project_data(directory)
    directory.mkdir(parents=True, exist_ok=True)
    from .user_state import save_last_project
    save_last_project(directory)
    from .project_files import recover_file_operation
    recover_file_operation(directory)
    from .project_templates import recover_template_upgrade
    recover_template_upgrade(directory)
    if template is not None:
        from .project_templates import initialize_template
        initialize_template(directory, template, entry=entry)
    path = (directory / entry).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("Entry point must be inside the project")
    runtime = Runtime()
    from .assets import AssetRegistry
    registry = AssetRegistry(directory)
    project_data = load_project_data(directory)
    if project_data and "assets" in project_data:
        registry.from_dict(project_data["assets"])
    registry.scan(directory)
    runtime.assets.registry = registry
    runtime.services.update(window=window, graphics=graphics, input=input_state, project=directory, project_data=project_data, restoring=bool(project_data and project_data.get("entities")))
    runtime.services["space"] = SpatialIndex(runtime)
    from .activity import ActivityLog
    runtime.services['log'] = ActivityLog(runtime)
    from .effects import SystemEffects
    runtime.services['effects'] = SystemEffects(runtime)
    app_id = None
    if project_data:
        if "application_id" in project_data and project_data["application_id"]:
            try:
                app_id = UUID(str(project_data["application_id"]))
            except ValueError:
                pass
    if app_id is None:
        import uuid as _uuid
        app_id = _uuid.uuid5(_uuid.NAMESPACE_URL, f"lbe://{directory.resolve().as_posix()}/application")
    root = runtime.create(identity=app_id, name="Application", tags=["root"])
    try:
        instance = root.items.attach_system(path.stem, runtime.assets.system(path))
        if not instance.running:
            raise RuntimeError(instance.errors[-1].traceback)
    except Exception:
        runtime.close()
        runtime.services["space"].close()
        raise
    return runtime
