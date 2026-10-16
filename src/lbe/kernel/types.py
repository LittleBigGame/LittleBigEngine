"""Type and requirement validation.

A type definition is a resource of type wellknown.TYPE_DEFINITION whose data
declares the fields of its typed data:

    {"fields": {"x": {"kind": "float", "default": 0.0},
                "target": {"kind": "ref", "type": "<64 hex>"}}}

Kinds: int, float, bool, string, ref. A ref field may constrain the target's
type. Fields without a default are required. Unknown fields are rejected.

The three bootstrap types (type definition, entity, blob) are validated in
code here; every other type is validated from its definition's fields.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from lbe.kernel import wellknown
from lbe.kernel.errors import ValidationError
from lbe.kernel.ids import ResourceId, TypeId
from lbe.kernel.resource import Ref, Resource


class ResourceLookup(Protocol):
    def get(self, resource_id: ResourceId) -> Resource: ...


def validate_resource(store: ResourceLookup, resource: Resource) -> None:
    """Validate a resource against its type. Raises ValidationError.

    Requires the type definition and every referenced resource that is
    checked for type compatibility to be present in `store`.
    """
    if not isinstance(resource.data, Mapping):
        raise ValidationError("resource data must be a mapping")
    definition = store.get(resource.type_id)
    if definition.type_id != wellknown.TYPE_DEFINITION:
        raise ValidationError(f"type {resource.type_id} is not a type definition")

    if resource.type_id == wellknown.TYPE_DEFINITION:
        _validate_type_definition(resource)
    elif resource.type_id == wellknown.ENTITY:
        _validate_entity(store, resource)
    elif resource.type_id == wellknown.BLOB:
        _validate_blob(resource)
    else:
        validate_fields(store, definition.data, resource.data)


def validate_fields(store: ResourceLookup, definition_data: Mapping[str, Any], data: Mapping[str, Any]) -> None:
    """Validate typed data against the `fields` declared by a type definition."""
    fields = definition_data.get("fields", {})
    unknown = set(data) - set(fields)
    if unknown:
        raise ValidationError(f"unknown fields: {sorted(unknown)}")
    for name, spec in fields.items():
        if name not in data:
            if "default" in spec:
                continue
            raise ValidationError(f"missing required field {name!r}")
        _check_kind(store, name, spec, data[name])


def apply_defaults(definition_data: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new mapping with declared defaults filled in for absent fields."""
    merged = dict(data)
    for name, spec in definition_data.get("fields", {}).items():
        if name not in merged and "default" in spec:
            merged[name] = spec["default"]
    return merged


def _check_kind(store: ResourceLookup, name: str, spec: Mapping[str, Any], value: Any) -> None:
    kind = spec.get("kind")
    ok = {
        "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "bool": lambda v: isinstance(v, bool),
        "string": lambda v: isinstance(v, str),
        "ref": lambda v: isinstance(v, Ref),
    }.get(kind)
    if ok is None:
        raise ValidationError(f"field {name!r} has unknown kind {kind!r}")
    if not ok(value):
        raise ValidationError(f"field {name!r} expects {kind}, got {type(value).__name__}")
    if kind == "ref" and "type" in spec:
        expected = TypeId(ResourceId.parse(spec["type"]))
        target = store.get(value.target)
        if target.type_id != expected:
            raise ValidationError(f"field {name!r} must reference a resource of type {expected}")


def _validate_type_definition(resource: Resource) -> None:
    if resource.id in (wellknown.TYPE_DEFINITION, wellknown.ENTITY, wellknown.BLOB):
        return  # bootstrap definitions carry a kernel marker, not fields
    fields = resource.data.get("fields")
    if not isinstance(fields, Mapping):
        raise ValidationError("a type definition needs a 'fields' mapping")
    for name, spec in fields.items():
        if not name.isidentifier():
            raise ValidationError(f"field name {name!r} is not an identifier")
        if not isinstance(spec, Mapping) or spec.get("kind") not in wellknown.FIELD_KINDS:
            raise ValidationError(f"field {name!r} must declare a kind in {sorted(wellknown.FIELD_KINDS)}")
        if spec.get("kind") == "ref" and "type" in spec:
            ResourceId.parse(spec["type"])  # raises ValueError if malformed
        if "default" in spec:
            _check_kind(_NoLookup(), name, {"kind": spec["kind"]}, spec["default"])


def _validate_entity(store: ResourceLookup, resource: Resource) -> None:
    components = resource.data.get("components")
    if not isinstance(components, list) or set(resource.data) != {"components"}:
        raise ValidationError("an entity's data is exactly {'components': [Ref, ...]}")
    seen: set[TypeId] = set()
    for item in components:
        if not isinstance(item, Ref):
            raise ValidationError("entity components must be references")
        component = store.get(item.target)
        if component.type_id in (wellknown.ENTITY, wellknown.TYPE_DEFINITION):
            raise ValidationError("entities and type definitions cannot be components")
        if component.type_id in seen:
            raise ValidationError(f"entity has more than one component of type {component.type_id}")
        seen.add(component.type_id)


def _validate_blob(resource: Resource) -> None:
    if resource.blob is None:
        raise ValidationError("a blob resource must carry binary content")
    if not isinstance(resource.data.get("media_type"), str):
        raise ValidationError("a blob resource needs a 'media_type' string")


class _NoLookup:
    def get(self, resource_id: ResourceId) -> Resource:
        raise ValidationError("defaults cannot be validated against the store")
