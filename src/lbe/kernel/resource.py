"""The immutable resource record and the reference value embedded in data."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterator, Mapping

from lbe.kernel.ids import ResourceId, TypeId


@dataclass(frozen=True, slots=True)
class Ref:
    """A reference to another resource (or to the containing resource itself)."""

    target: ResourceId

    def __repr__(self) -> str:
        return f"Ref({self.target.hex[:12]}...)"


class State(str, Enum):
    """Local lifecycle state. Published resources are permanently immutable."""

    DRAFT = "draft"
    PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class Resource:
    """A persistent resource definition.

    `data` is JSON-compatible structured data in which Ref values express
    references to other resources. `blob` names binary content held in the
    store by its SHA-256 hash. `derived_from` records history only; it is not
    a dependency. `label` is for humans and is never used as identity.
    """

    id: ResourceId
    type_id: TypeId
    label: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    blob: str | None = None
    derived_from: ResourceId | None = None
    state: State = State.DRAFT

    @property
    def published(self) -> bool:
        return self.state is State.PUBLISHED

    def references(self) -> list[ResourceId]:
        """Every resource referenced from `data`, in encounter order, without duplicates."""
        seen: dict[ResourceId, None] = {}
        for ref in iter_refs(self.data):
            seen.setdefault(ref.target)
        return list(seen)

    def dependencies(self) -> list[ResourceId]:
        """What must exist to validate and load this resource: its type, then its references."""
        deps: dict[ResourceId, None] = {self.type_id: None}
        for target in self.references():
            deps.setdefault(target)
        return list(deps)

    def with_data(self, data: Mapping[str, Any]) -> Resource:
        return replace(self, data=copy.deepcopy(dict(data)))

    def successor(self, *, data: Mapping[str, Any] | None = None, label: str | None = None) -> Resource:
        """A new draft resource with a fresh id derived from this one.

        This is the only way to "change" a published resource: the original
        keeps its id and contents forever.
        """
        return Resource(
            id=ResourceId.generate(),
            type_id=self.type_id,
            label=self.label if label is None else label,
            data=copy.deepcopy(dict(self.data if data is None else data)),
            blob=self.blob,
            derived_from=self.id,
            state=State.DRAFT,
        )


def iter_refs(value: Any) -> Iterator[Ref]:
    """Yield every Ref nested anywhere inside a data value, depth first."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Ref):
            yield item
        elif isinstance(item, Mapping):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
