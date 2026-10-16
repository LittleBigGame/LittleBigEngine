"""JSON document encoding for resources, plus the content hash.

Document shape (format version 1):

    {
      "lbe": 1,
      "id": "<64 hex>",
      "type": "<64 hex>",
      "label": "Player",
      "state": "draft" | "published",
      "derived_from": "<64 hex>" | null,
      "blob": "<sha256 hex>" | null,
      "data": { ... }          // Ref values appear as {"$ref": "<64 hex>"}
    }

Keys beginning with "$" are reserved inside `data`. Non-finite floats are
rejected because they have no JSON representation.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

from lbe.kernel.errors import ValidationError
from lbe.kernel.ids import ResourceId, TypeId
from lbe.kernel.resource import Ref, Resource, State

FORMAT_VERSION = 1
REF_KEY = "$ref"


def encode_value(value: Any) -> Any:
    """Convert a data value into a plain JSON-compatible structure."""
    if isinstance(value, Ref):
        return {REF_KEY: value.target.hex}
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("non-finite floats cannot be stored in resource data")
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("resource data keys must be strings")
            if key.startswith("$"):
                raise ValidationError(f"data key {key!r} is reserved")
            out[key] = encode_value(item)
        return out
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    raise ValidationError(f"unsupported value in resource data: {type(value).__name__}")


def decode_value(value: Any) -> Any:
    """Inverse of encode_value: {"$ref": hex} becomes Ref."""
    if isinstance(value, dict):
        if REF_KEY in value:
            if len(value) != 1 or not isinstance(value[REF_KEY], str):
                raise ValidationError("malformed reference object")
            return Ref(ResourceId.parse(value[REF_KEY]))
        return {key: decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    return value


def to_document(resource: Resource) -> dict[str, Any]:
    return {
        "lbe": FORMAT_VERSION,
        "id": resource.id.hex,
        "type": resource.type_id.hex,
        "label": resource.label,
        "state": resource.state.value,
        "derived_from": resource.derived_from.hex if resource.derived_from else None,
        "blob": resource.blob,
        "data": encode_value(resource.data),
    }


def from_document(document: Mapping[str, Any]) -> Resource:
    if document.get("lbe") != FORMAT_VERSION:
        raise ValidationError(f"unsupported resource format version: {document.get('lbe')!r}")
    try:
        derived = document.get("derived_from")
        blob = document.get("blob")
        if blob is not None and not isinstance(blob, str):
            raise ValidationError("blob must be a hex string or null")
        label = document.get("label", "")
        if not isinstance(label, str):
            raise ValidationError("label must be a string")
        return Resource(
            id=ResourceId.parse(document["id"]),
            type_id=TypeId(ResourceId.parse(document["type"])),
            label=label,
            data=decode_value(document.get("data", {})),
            blob=blob,
            derived_from=ResourceId.parse(derived) if derived is not None else None,
            state=State(document.get("state", State.DRAFT.value)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError(f"malformed resource document: {exc}") from exc


def dumps(resource: Resource) -> str:
    """Readable, diff-friendly encoding used for files on disk."""
    return json.dumps(to_document(resource), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def loads(text: str) -> Resource:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"resource file is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValidationError("resource document must be a JSON object")
    return from_document(document)


def content_hash(resource: Resource) -> str:
    """SHA-256 of the canonical encoding of everything except the lifecycle state.

    Used for integrity checks and deduplication. It never replaces the id.
    """
    document = to_document(resource)
    del document["state"]
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
