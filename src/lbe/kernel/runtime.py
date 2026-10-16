"""Runtime handles and mutable instances.

Persistent resources are immutable definitions. A Runtime loads a resource
graph once, gives every loaded resource a small integer Handle, and owns the
mutable per-entity instance state that applications actually change.

Handles are valid only inside the Runtime that issued them and are never
persisted; durable references always use ResourceIds.
"""

from __future__ import annotations

import copy
from typing import Any, NewType

from lbe.kernel import wellknown
from lbe.kernel.errors import KernelError, ValidationError
from lbe.kernel.graph import closure
from lbe.kernel.ids import ResourceId, TypeId
from lbe.kernel.resource import Resource
from lbe.kernel.types import ResourceLookup, apply_defaults, validate_resource

Handle = NewType("Handle", int)


class Runtime:
    """Resolved resource graph with compact handles and per-entity instances."""

    def __init__(self, store: ResourceLookup) -> None:
        self._store = store
        self._resources: list[Resource] = []
        self._handles: dict[ResourceId, Handle] = {}
        self._components: dict[Handle, dict[TypeId, Handle]] = {}
        self._instances: dict[tuple[Handle, TypeId], dict[str, Any]] = {}

    def load(self, root: ResourceId) -> Handle:
        """Load `root` and everything it depends on; returns the root's handle.

        Loading is idempotent: already loaded resources keep their handles.
        Every newly loaded resource is validated against its type.
        """
        for resource_id, resource in closure(self._store, [root]).items():
            if resource_id in self._handles:
                continue
            validate_resource(self._store, resource)
            self._handles[resource_id] = Handle(len(self._resources))
            self._resources.append(resource)
        return self._handles[root]

    def __len__(self) -> int:
        return len(self._resources)

    def handle(self, resource_id: ResourceId) -> Handle:
        try:
            return self._handles[resource_id]
        except KeyError:
            raise KernelError(f"resource {resource_id} is not loaded") from None

    def resource(self, handle: Handle) -> Resource:
        try:
            return self._resources[handle]
        except IndexError:
            raise KernelError(f"invalid handle {handle}") from None

    def components(self, entity: Handle) -> dict[TypeId, Handle]:
        """The entity's components keyed by their type, resolved to handles."""
        if entity not in self._components:
            resource = self.resource(entity)
            if resource.type_id != wellknown.ENTITY:
                raise ValidationError(f"handle {entity} is not an entity")
            self._components[entity] = {
                self.resource(self._handles[ref.target]).type_id: self._handles[ref.target]
                for ref in resource.data["components"]
            }
        return self._components[entity]

    def instance(self, entity: Handle, type_id: TypeId) -> dict[str, Any]:
        """Mutable state of the entity's component of `type_id`.

        Created on first access by copying the component definition's data
        (with declared defaults applied). Two entities sharing one component
        definition get independent instances; mutating an instance never
        touches the definition or the store.
        """
        key = (entity, type_id)
        if key not in self._instances:
            component_handle = self.components(entity).get(type_id)
            if component_handle is None:
                raise KernelError(f"entity {entity} has no component of type {type_id}")
            definition = self.resource(self._handles[type_id])
            data = self.resource(component_handle).data
            self._instances[key] = copy.deepcopy(apply_defaults(definition.data, data))
        return self._instances[key]
