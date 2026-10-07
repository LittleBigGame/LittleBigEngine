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

CURRENT_VERSION = 3


@dataclass(frozen=True)
class EntityRef:
    """An unresolved persisted identity, retained until its target is available."""
    id: UUID

    def resolve(self, runtime):
        return runtime.resolve(self.id)


@dataclass
class Restoration:
    item_records: dict = field(default_factory=dict)
    scripts: dict = field(default_factory=dict)
    systems: dict = field(default_factory=dict)
    system_order: dict = field(default_factory=dict)
    relations: dict = field(default_factory=dict)
    parents: dict = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    loading: int = 0


def restoration(runtime):
    if "restoration" not in runtime.services:
        state = runtime.services["restoration"] = Restoration()
        def changed(change):
            if state.loading:
                return
            eid = change.entity.id
            if change.kind == "entity.destroy":
                for mapping in (state.parents, state.relations, state.systems, state.system_order):
                    mapping.pop(eid, None)
            elif change.kind == "hierarchy.parent":
                state.parents.pop(eid, None)
            elif change.kind.startswith("relation."):
                state.relations.get(eid, {}).pop(change.key, None)
            elif change.kind in ("system.attach", "system.detach"):
                state.systems.get(eid, {}).pop(change.key, None)
                if change.kind == "system.detach":
                    state.system_order[eid] = [name for name in state.system_order.get(eid, ()) if name != change.key]
            elif change.kind == "system.reorder":
                state.system_order[eid] = list(change.entity.systems) + list(state.systems.get(eid, {}))
        runtime.changes.subscribe(changed)
    return runtime.services["restoration"]


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
    """Serialize persistent data; runtime-only services stay outside this graph."""
    pending = restoration(entity.runtime)
    parent = entity.parent
    while parent is not None and known_ids is not None and parent.id not in known_ids:
        parent = parent.parent
    parent_id = pending.parents.get(entity.id) or (str(parent.id) if parent is not None else None)
    data = {
        "id": str(entity.id), "tags": list(set(entity.items.tag_names())), "parent": parent_id,
        "parent_scope": "entity" if parent_id else "detached",
        "position": entity.parent.children.index(entity) if entity.parent else 0,
        "components": {}, "relations": dict(pending.relations.get(entity.id, {})), "systems": {},
    }
    from .items import Component
    for item in entity.all(Component):
        key, value = item.name, item.value
        try:
            encoded = serialize_value(value, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=known_ids)
            if value is None or encoded is not None or on_unsupported != "skip":
                data["components"][key] = encoded
        except (TypeError, ValueError) as error:
            raise type(error)(f"Component {key!r} on entity {entity.id} cannot be serialized: {error}") from None
    for key, target in entity.items.link_dict().items():
        if key in transient_relations:
            continue
        if known_ids is not None and target.id not in known_ids:
            raise ValueError(f"Relation {key!r} on {entity.id} targets an entity outside the saved project")
        data["relations"][key] = str(target.id)
    for name, instance in entity.systems.items():
        definition = instance.definition
        path = Path(definition.path)
        if project_dir is not None and not definition.path.startswith("<"):
            try:
                path = path.resolve().relative_to(Path(project_dir).resolve())
                declaration = {"path": path.as_posix()}
            except ValueError:
                declaration = {"source": definition.source, "path": definition.path}
        else:
            declaration = {"source": definition.source, "path": definition.path}
        data["systems"][name] = declaration
    data['scripts'] = {}
    for name,instance in entity.scripts.items():
        definition=instance.definition
        path=Path(definition.path)
        try:
            relative=path.resolve().relative_to(Path(project_dir).resolve())
            declaration={'path':relative.as_posix()}
        except (ValueError,TypeError):
            declaration={'source':definition.source,'path':definition.path}
        data['scripts'][name]=declaration
    for name,declaration in pending.scripts.get(entity.id,{}).items():
        data['scripts'].setdefault(name,dict(declaration))
    for name, declaration in pending.systems.get(entity.id, {}).items():
        data["systems"].setdefault(name, dict(declaration))
    order = pending.system_order.get(entity.id, ())
    data["systems"] = {name: data["systems"][name] for name in dict.fromkeys((*order, *data["systems"]))
                       if name in data["systems"]}
    from .item_storage import encode_items
    data["items"] = encode_items(entity, data,
        encode=lambda value: serialize_value(value, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=known_ids),
        pending_items=pending.item_records.get(entity.id))
    return data


def serialize_entities(entities, *, project_dir=None, on_unsupported="error", known_ids=None, transient_relations=None):
    """Serialize a collection of entities."""
    entities = tuple(entities)
    entity_ids = {e.id for e in entities}
    if known_ids:
        entity_ids.update(UUID(str(x)) if not isinstance(x, UUID) else x for x in known_ids if x is not None)
    transient_relations = transient_relations or {}
    return [serialize_entity(e, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=entity_ids,
                             transient_relations=transient_relations.get(e.id, ())) for e in entities]


def deserialize_entities(entity_data_list, runtime, *, default_parent=None, project_dir=None, activate=True):
    """Restore the whole graph before activating scripts; roll back structural failures."""
    from .item_storage import project_record
    records = [project_record(record) for record in entity_data_list]
    ids = [UUID(record["id"]) for record in records]
    item_ids = [UUID(identity) for record in records for identity in record["items"]]
    all_ids = ids + item_ids
    if len(set(all_ids)) != len(all_ids) or any(identity in runtime.linker.objects for identity in all_ids):
        raise ValueError("Duplicate object UUID in project")
    if len(set(ids)) != len(ids) or any(eid in {e.id for e in runtime.entities} for eid in ids):
        raise ValueError("Duplicate entity identity in project")
    parents = {eid: UUID(record["parent"]) if record.get("parent") else None for eid, record in zip(ids, records)}
    for eid in ids:
        seen = set()
        current = eid
        while current in parents:
            if current in seen:
                raise ValueError("Project hierarchy contains a cycle")
            seen.add(current)
            current = parents[current]
    created = {}
    pending = restoration(runtime)
    diagnostic_start = len(pending.diagnostics)
    pending.loading += 1
    try:
        for eid, record in zip(ids, records):
            created[eid] = runtime.create(identity=eid, tags=record.get("tags", ()))
        for eid, record in zip(ids, records):
            target = created[eid]
            pid = parents[eid]
            if pid is not None:
                try:
                    target.parent = runtime.resolve(pid)
                except KeyError:
                    pending.parents[eid] = str(pid)
                    pending.diagnostics.append(Diagnostic("project.parent", f"Missing parent {pid} for {eid}"))
                    target.parent = default_parent
            elif record.get("parent_scope") != "detached":
                target.parent = default_parent
            for key, value in record.get("components", {}).items():
                target.items.set_value(key, deserialize_value(value, runtime=runtime, id_map=created))
            for key, identity in record.get("relations", {}).items():
                try:
                    target.items.connect(key, runtime.resolve(UUID(identity)))
                except KeyError:
                    pending.relations.setdefault(eid, {})[key] = identity
                    pending.diagnostics.append(Diagnostic("project.relation", f"Missing target {identity} for {eid}.{key}"))
            pending.scripts[eid] = dict(record.get("scripts", {}))
            pending.systems[eid] = dict(record.get("systems", {}))
            pending.system_order[eid] = list(record.get("systems", {}))
            pending.item_records[eid] = record["items"]
            from .items import Component, InheritedComponent, Tag, Relation, Parent
            categories = {"Component": Component, "Tag": Tag, "Relation": Relation, "Parent": Parent}
            for identity, item in record["items"].items():
                uid = UUID(identity)
                if item["type"] == "InheritedComponent":
                    patch = deserialize_value(item.get("patch", []), runtime=runtime, id_map=created)
                    target.items._put(InheritedComponent(item["name"], UUID(item["source"]), tuple(patch), uid))
                elif item["type"] in categories:
                    category = categories[item["type"]]
                    if (category, item["name"]) in target.items._names:
                        target.items._replace_identity(category, item["name"], uid)
        # Rebuild sibling order independently of creation/scheduler order.
        for parent in {e.parent for e in created.values() if e.parent is not None}:
            siblings = [(record.get("position", index), index, created[eid])
                        for index, (eid, record) in enumerate(zip(ids, records)) if created[eid].parent is parent]
            for index, (_, _, child) in enumerate(sorted(siblings, key=lambda item: item[:2])):
                parent.move_child(child, index)
    except Exception:
        for entity in reversed(tuple(created.values())):
            if entity.alive:
                entity.destroy()
        for eid in created:
            pending.systems.pop(eid, None)
            pending.scripts.pop(eid, None)
            pending.system_order.pop(eid, None)
            pending.relations.pop(eid, None)
            pending.parents.pop(eid, None)
            pending.item_records.pop(eid, None)
        del pending.diagnostics[diagnostic_start:]
        raise
    finally:
        pending.loading -= 1
    if activate:
        activate_entities(created.values(), runtime, project_dir=project_dir)
    return created


def activate_entities(entities, runtime, *, project_dir=None):
    """Attach restored scripts after application dependencies are ready. Retry missing files safely."""
    from .systems import SystemDefinition
    pending = restoration(runtime)
    ready = []
    for entity in tuple(entities):
        if not entity.alive:
            continue
        resolve_references(entity, runtime)
        for name, declaration in tuple(pending.systems.get(entity.id, {}).items()):
            if name in entity.systems:
                pending.systems.get(entity.id, {}).pop(name, None)
                continue
            try:
                if "source" in declaration:
                    definition = SystemDefinition(declaration["source"], declaration.get("path", "<system>"))
                else:
                    if project_dir is None:
                        raise ValueError("A project directory is required for file-backed systems")
                    path = (Path(project_dir) / declaration["path"]).resolve()
                    if not path.is_relative_to(Path(project_dir).resolve()):
                        raise ValueError("System path must be inside the project")
                    definition = runtime.assets.system(path)
                instance = entity.systems.attach(name, definition, identity=declaration.get("item_id"), activate=False)
                ready.append(instance)
                pending.systems.get(entity.id, {}).pop(name, None)
            except (OSError, ValueError, TypeError, SyntaxError) as error:
                pending.diagnostics.append(Diagnostic("project.system", f"{entity.id}.{name}: {error}"))
        for identity,declaration in tuple(pending.scripts.get(entity.id,{}).items()):
            if identity in entity.scripts:
                pending.scripts[entity.id].pop(identity,None)
                continue
            try:
                from uuid import UUID
                if 'source' in declaration:
                    definition=SystemDefinition(declaration['source'],declaration.get('path','<script>'),UUID(identity))
                else:
                    path=(Path(project_dir)/declaration['path']).resolve()
                    if not path.is_relative_to(Path(project_dir).resolve()):
                        raise ValueError('Script path must stay inside the project')
                    definition=SystemDefinition.from_file(path)
                    from dataclasses import replace
                    definition=replace(definition,asset_id=UUID(identity))
                instance=entity.scripts.attach(definition, item_identity=declaration.get("item_id"), activate=False)
                ready.append(instance)
                pending.scripts[entity.id].pop(identity,None)
            except (OSError,ValueError,TypeError,SyntaxError) as error:
                pending.diagnostics.append(Diagnostic('project.script',f'{entity.id}.{identity}: {error}'))
        pending.loading += 1
        try:
            names = [name for name in pending.system_order.get(entity.id, ()) if name in entity.systems]
            for index, name in enumerate(names):
                entity.systems.move(name, index)
        finally:
            pending.loading -= 1
    # All attachments have identities before source linking/initialization.
    initialized = []
    for instance in ready:
        if instance.entity.alive and runtime.linker.objects.get(instance.id) is instance:
            if instance.initialize():
                initialized.append(instance)
            else:
                pending.diagnostics.extend(instance.errors)
    for instance in initialized:
        if instance.entity.alive and runtime.linker.objects.get(instance.id) is instance:
            instance.start()
            if not instance.running:
                pending.diagnostics.extend(instance.errors)


def resolve_references(entity, runtime):
    """Recover retained identities without changing unrelated component objects."""
    pending = restoration(runtime)
    parent = pending.parents.get(entity.id)
    if parent:
        try:
            entity.parent = runtime.resolve(UUID(parent))
        except KeyError:
            pass
    for key, identity in tuple(pending.relations.get(entity.id, {}).items()):
        try:
            entity.items.connect(key, runtime.resolve(UUID(identity)))
        except KeyError:
            pass

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


def migrate_v0_to_v1(data):
    """Migrate legacy unversioned/v0 project format to v1."""
    migrated = dict(data)
    migrated["version"] = 1
    if "entities" not in migrated:
        migrated["entities"] = []
    normalized_entities = []
    for entity in migrated.get("entities", []):
        e = dict(entity)
        if isinstance(e.get("components"), list):
            e["components"] = {item["name"]: item["value"] for item in e["components"] if "name" in item}
        if isinstance(e.get("tags"), str):
            e["tags"] = [t.strip() for t in e["tags"].split(",") if t.strip()]
        if "relations" not in e:
            e["relations"] = {}
        if "systems" not in e:
            e["systems"] = {}
        normalized_entities.append(e)
    migrated["entities"] = normalized_entities
    if "layout" not in migrated:
        migrated["layout"] = {}
    return migrated


def migrate_v1_to_v2(data):
    migrated = dict(data, version=2)
    migrated["entities"] = [dict(record, position=record.get("position", index))
                            for index, record in enumerate(data.get("entities", []))]
    return migrated


def migrate_v2_to_v3(data):
    from .item_storage import from_legacy
    return dict(data, version=3, entities=[dict(record, items=from_legacy(record))
                                         for record in data.get("entities", ())])


MIGRATIONS = {
    2: migrate_v2_to_v3,
    1: migrate_v1_to_v2,
    0: migrate_v0_to_v1,
}


def migrate_project_data(data):
    """Validate and migrate project data to the latest format version."""
    if not isinstance(data, dict):
        raise ValueError("Invalid project file format: expected JSON object")
    version = data.get("version", 0)
    if type(version) is not int or version < 0:
        raise ValueError(f"Invalid project version: {version!r}")
    if version > CURRENT_VERSION:
        raise ValueError(f"Project format version {version} is newer than supported version {CURRENT_VERSION}")
    while version < CURRENT_VERSION:
        migrator = MIGRATIONS.get(version)
        if migrator is None:
            raise ValueError(f"No migration path from project version {version} to {CURRENT_VERSION}")
        data = migrator(data)
        version = data.get("version", version + 1)
    return data


def save_project(directory, *, entities=None, layout=None, assets=None, application_id=None, filename="project.json", on_unsupported="error", transient_relations=None):
    """Atomically save project entities and editor layout to a versioned project file."""
    directory = Path(directory).resolve()
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
    """Load and migrate project JSON data if the file exists, otherwise None."""
    project_file = Path(directory) / filename
    if not project_file.exists():
        return None
    with open(project_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return migrate_project_data(data)


def template_path(name):
    root = Path(__file__).parent / "templates"
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_dir():
        raise ValueError("Unknown bundled application template")
    return path


def load_project(window, graphics, input_state, directory, *, template=None, entry="app.py"):
    directory = Path(directory).resolve()
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
            known_ids = {e["id"] for e in project_data.get("entities", [])}
            layout_sel = project_data.get("layout", {}).get("selection")
            if layout_sel and layout_sel not in known_ids:
                try:
                    app_id = UUID(str(layout_sel))
                except ValueError:
                    pass
    if app_id is None:
        import uuid as _uuid
        app_id = _uuid.uuid5(_uuid.NAMESPACE_URL, f"lbe://{directory.resolve().as_posix()}/application")
    root = runtime.create(identity=app_id, name="Application", tags=["root"])
    try:
        instance = root.systems.attach(path.stem, runtime.assets.system(path))
        if not instance.running:
            raise RuntimeError(instance.errors[-1].traceback)
    except Exception:
        runtime.close()
        runtime.services["space"].close()
        raise
    return runtime
