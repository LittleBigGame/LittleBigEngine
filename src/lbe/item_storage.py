"""Canonical item records and compatibility projections at the storage boundary."""
from uuid import UUID, uuid5


def from_legacy(record):
    """Deterministic item identities let legacy documents migrate reproducibly."""
    owner = UUID(record["id"])
    items = {}

    def add(kind, name, **fields):
        identity = fields.pop("item_id", None) or str(uuid5(owner, kind + ":" + name))
        items[identity] = dict(type=kind, name=name, **fields)

    for name, value in record.get("components", {}).items():
        add("Component", name, value=value)
    for name in record.get("tags", ()):
        add("Tag", name)
    for name, target in record.get("relations", {}).items():
        add("Relation", name, target=target)
    if record.get("parent"):
        add("Parent", "parent", target=record["parent"])
    for kind, collection in (("System", "systems"), ("Script", "scripts")):
        for name, declaration in record.get(collection, {}).items():
            declaration = dict(declaration)
            add(kind, name, item_id=declaration.pop("item_id", None), definition=declaration)
    return items


def project_record(record):
    """Derive legacy loading fields. If items exist, redundant fields are ignored."""
    if "items" not in record:
        return dict(record, items=from_legacy(record))
    result = dict(record, components={}, tags=[], relations={}, systems={}, scripts={}, parent=None)
    seen = set()
    for identity, item in record["items"].items():
        UUID(identity)
        kind, name = item["type"], item["name"]
        if not isinstance(name, str) or not name:
            raise ValueError("Item names must be nonempty strings")
        category = "Component" if kind == "InheritedComponent" else kind
        if (category, name) in seen:
            raise ValueError(f"Duplicate {category} name: {name}")
        seen.add((category, name))
        if kind == "Component":
            result["components"][name] = item["value"]
        elif kind == "InheritedComponent":
            UUID(item["source"])
        elif kind == "Tag":
            result["tags"].append(name)
        elif kind == "Relation":
            UUID(item["target"])
            result["relations"][name] = item["target"]
        elif kind == "Parent":
            if name != "parent":
                raise ValueError("Parent item must be named parent")
            UUID(item["target"])
            result["parent"] = item["target"]
        elif kind in ("System", "Script"):
            collection = "systems" if kind == "System" else "scripts"
            result[collection][name] = dict(item["definition"], item_id=identity)
        else:
            raise ValueError(f"Unknown item type: {kind}")
    return result


def encode_items(entity, data, *, encode, pending_items=None):
    from .items import Component, InheritedComponent, Tag, Relation, Parent
    from .scripts import ScriptInstance
    from .systems import SystemInstance
    result = {}
    for item in entity.items.values():
        record = dict(type=type(item).__name__, name=item.name)
        if isinstance(item, Component):
            if item.name not in data["components"]:
                continue
            record["value"] = data["components"][item.name]
        elif isinstance(item, InheritedComponent):
            record.update(source=str(item.source), patch=encode(item.patch))
        elif isinstance(item, Tag):
            pass
        elif isinstance(item, Relation):
            if item.name not in data["relations"]:
                continue
            record["target"] = data["relations"][item.name]
        elif isinstance(item, Parent):
            if not data["parent"]:
                continue
            record["target"] = data["parent"]
        elif isinstance(item, SystemInstance):
            collection = "scripts" if isinstance(item, ScriptInstance) else "systems"
            record["type"] = "Script" if collection == "scripts" else "System"
            record["definition"] = data[collection][item.name]
        else:
            raise TypeError(f"Unsupported persistent item: {type(item).__name__}")
        result[str(item.id)] = record
    # Missing external sources retain their original identity/declaration.
    fallback = from_legacy(data)
    names = {(r["type"], r["name"]) for r in result.values()}
    for identity, record in fallback.items():
        if (record["type"], record["name"]) not in names:
            original = next(((uid, old) for uid, old in (pending_items or {}).items()
                             if old["type"] == record["type"] and old["name"] == record["name"]), None)
            uid = original[0] if original else identity
            result[uid] = record
    return result
