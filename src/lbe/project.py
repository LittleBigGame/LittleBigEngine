"""Load a directory of application scripts through the public runtime API and persist project state."""

import json
from math import isfinite
from pathlib import Path
import shutil
import tempfile
from uuid import UUID

from .core import Entity, Runtime
from .space import SpatialIndex

CURRENT_VERSION = 1


def serialize_value(value, *, project_dir=None, on_unsupported="error"):
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
    if isinstance(value, Entity):
        return {"__type__": "entity", "id": str(value.id)}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "values": [serialize_value(x, project_dir=project_dir, on_unsupported=on_unsupported) for x in value]}
    if isinstance(value, set):
        return {"__type__": "set", "values": [serialize_value(x, project_dir=project_dir, on_unsupported=on_unsupported) for x in sorted(value, key=str)]}
    if isinstance(value, list):
        return [serialize_value(x, project_dir=project_dir, on_unsupported=on_unsupported) for x in value]
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise TypeError(f"Dictionary keys must be strings, got {type(k).__name__}")
        return {k: serialize_value(v, project_dir=project_dir, on_unsupported=on_unsupported) for k, v in value.items()}
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
                    return runtime.resolve(entity_id)
                return entity_id
            elif type_tag == "tuple":
                return tuple(deserialize_value(x, runtime=runtime, id_map=id_map) for x in data["values"])
            elif type_tag == "set":
                return set(deserialize_value(x, runtime=runtime, id_map=id_map) for x in data["values"])
            else:
                raise ValueError(f"Unknown serialized type tag: {type_tag!r}")
        return {k: deserialize_value(v, runtime=runtime, id_map=id_map) for k, v in data.items()}
    raise TypeError(f"Unexpected serialized data structure: {type(data).__name__}")


def serialize_entity(entity, *, project_dir=None, on_unsupported="error", known_ids=None):
    """Serialize a single entity's identity, tags, components, relations, and systems."""
    parent_id = None
    if entity.parent is not None:
        if known_ids is None or entity.parent.id in known_ids:
            parent_id = str(entity.parent.id)
    data = {
        "id": str(entity.id),
        "tags": list(entity.tags),
        "parent": parent_id,
        "components": {},
        "relations": {},
        "systems": {},
    }
    for k, v in entity.components.items():
        try:
            val = serialize_value(v, project_dir=project_dir, on_unsupported=on_unsupported)
            if val is not None or on_unsupported != "skip":
                data["components"][k] = val
        except TypeError as err:
            raise TypeError(f"Component {k!r} on entity {entity.id} cannot be serialized: {err}") from None
    for k, target in entity.relations.items():
        if known_ids is None or target.id in known_ids:
            data["relations"][k] = str(target.id)
    for name, instance in entity.systems.items():
        sys_path = Path(instance.definition.path)
        if project_dir is not None:
            try:
                rel_path = str(sys_path.relative_to(project_dir))
            except ValueError:
                rel_path = sys_path.name
        else:
            rel_path = sys_path.name
        data["systems"][name] = {"path": rel_path}
    return data


def serialize_entities(entities, *, project_dir=None, on_unsupported="error"):
    """Serialize a collection of entities."""
    entities = tuple(entities)
    entity_ids = {e.id for e in entities}
    return [serialize_entity(e, project_dir=project_dir, on_unsupported=on_unsupported, known_ids=entity_ids) for e in entities]


def deserialize_entities(entity_data_list, runtime, *, default_parent=None, project_dir=None):
    """Reconstruct entities in the runtime preserving UUID identities, hierarchy, and systems."""
    created = {}
    # Pass 1: create all entities with explicit UUID identity and tags
    for edata in entity_data_list:
        eid = UUID(edata["id"])
        tags = tuple(edata.get("tags", ()))
        entity = runtime.create(identity=eid, tags=tags)
        created[eid] = entity

    # Pass 2: populate parents, components, relations, and systems
    for edata in entity_data_list:
        eid = UUID(edata["id"])
        entity = created[eid]

        # Parent hierarchy
        parent_id = edata.get("parent")
        if parent_id is not None:
            pid = UUID(parent_id)
            if pid in created:
                entity.parent = created[pid]
            else:
                try:
                    entity.parent = runtime.resolve(pid)
                except KeyError:
                    if default_parent is not None:
                        entity.parent = default_parent
        elif default_parent is not None and entity is not default_parent:
            entity.parent = default_parent

        # Components
        for k, v in edata.get("components", {}).items():
            entity.components[k] = deserialize_value(v, runtime=runtime, id_map=created)

        # Relations
        for k, target_id_str in edata.get("relations", {}).items():
            target_id = UUID(target_id_str)
            if target_id in created:
                entity.relations[k] = created[target_id]
            else:
                try:
                    entity.relations[k] = runtime.resolve(target_id)
                except KeyError:
                    pass

        # Systems (reconstructed safely)
        for name, sdata in edata.get("systems", {}).items():
            rel_path = sdata.get("path")
            if rel_path and project_dir:
                sys_path = (project_dir / rel_path).resolve()
                if sys_path.exists():
                    try:
                        definition = runtime.assets.system(sys_path)
                        entity.systems.attach(name, definition)
                    except Exception:
                        pass
    return created


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


MIGRATIONS = {
    0: migrate_v0_to_v1,
}


def migrate_project_data(data):
    """Validate and migrate project data to the latest format version."""
    if not isinstance(data, dict):
        raise ValueError("Invalid project file format: expected JSON object")
    version = data.get("version", 0)
    if not isinstance(version, int):
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


def save_project(directory, *, entities=None, layout=None, assets=None, filename="project.json", on_unsupported="error"):
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

    data = {
        "version": CURRENT_VERSION,
        "entities": serialize_entities(entities, project_dir=directory, on_unsupported=on_unsupported) if entities is not None else [],
        "layout": serialize_value(layout, project_dir=directory, on_unsupported=on_unsupported) if layout is not None else {},
        "assets": assets_data,
    }

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=directory, delete=False, suffix=".tmp") as f:
        json.dump(data, f, indent=2)
        temp_path = Path(f.name)
    temp_path.replace(project_file)
    return project_file


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
    if template is not None and not (directory / entry).exists():
        for source in Path(template).glob("*.py"):
            destination = directory / source.name
            if not destination.exists():
                shutil.copyfile(source, destination)
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
    runtime.services.update(window=window, graphics=graphics, input=input_state, project=directory, assets=registry)
    runtime.services["space"] = SpatialIndex(runtime)
    root = runtime.create(name="Application", tags=["root"])
    try:
        instance = root.systems.attach(path.stem, runtime.assets.system(path))
        if not instance.running:
            raise RuntimeError(instance.errors[-1].traceback)
    except Exception:
        runtime.close()
        runtime.services["space"].close()
        raise
    return runtime
