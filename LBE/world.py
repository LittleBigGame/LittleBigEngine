"""Entity components, hierarchy and queries.

These functions operate on the Kernel's authoritative state.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
import copy

from .logger import logger
from .integrity import Validate
from .ui import ValidateUI
from .proxy import ComponentProxy, EntityProxy, ReadOnlySequence, _unwrap
from .views import _make_readonly_view
from .types import (
    StorageID,
    RuntimeID,
    Error,
    RuntimeIDNotFoundOnMemoryError,
    InvalidResourceDataError,
    EntityTypeMismatchError,
    ComponentNotFoundOnEntityError,
    Entity,
)

def create_entity(
    self,
    components: dict[str, dict] | None = None,
    resources: list[str | bytes] | None = None,
    name: str | None = None,
    storage_id: StorageID | None = None,
    immediate_save: bool = False,
    scripts: list[str] | None = None,
    parent_id: RuntimeID | None = None,
) -> RuntimeID | Error:
    """Create a new Entity. In ECS, an entity is purely a RuntimeID pointing to components and resources."""
    if parent_id is not None:
        pid = parent_id.id if hasattr(parent_id, "id") else parent_id
        if not self.is_valid_runtime_id(pid):
            err = Error(
                message="Parent entity not found",
                description=f"Parent entity with runtime ID {pid} not found in memory!",
                data={"parent_id": pid},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("create_entity failed: parent not found", channel="entities", error=err)
            return err
        resolved_pid = self._resolve_handle(pid)
        if not self.is_entity(resolved_pid):
            err = Error(
                message="Resource is not an entity",
                description=f"Runtime ID {pid} has type {self.resources.get(resolved_pid, {}).get('type')}, expected Entity ({Entity})!",
                data={"parent_id": pid},
                code=EntityTypeMismatchError,
            )
            logger.trace("create_entity failed: parent not an entity", channel="entities", error=err)
            return err

    entity_data = {
        "components": copy.deepcopy(components) if components is not None else {},
        "resources": list(resources) if resources is not None else [],
        "scripts": list(scripts) if scripts is not None else [],
        "children": [],
        "parent": None,
    }

    res_id = self.create_resource(
        resource_type=Entity,
        resource_data=entity_data,
        name=name,
        children=[],
        storage_id=storage_id,
        immediate_save=immediate_save,
    )
    if isinstance(res_id, Error):
        return res_id

    if parent_id is not None:
        pid = parent_id.id if hasattr(parent_id, "id") else parent_id
        err = self.add_entity_child(pid, res_id)
        if isinstance(err, Error):
            self.delete_resource(res_id)
            return err
        if immediate_save:
            save_err = self.save_resource(res_id)
            if isinstance(save_err, Error):
                return save_err
            save_parent_err = self.save_resource(pid)
            if isinstance(save_parent_err, Error):
                return save_parent_err

    logger.trace(
        f"Created Entity {res_id}",
        channel="entities",
        entity_id=res_id,
        action="created_entity",
        data={
            "component_count": len(entity_data["components"]),
            "resource_count": len(entity_data["resources"]),
        },
    )
    return res_id


def load_entity(
    self,
    storage_id: StorageID,
    load_depth: int = -1,
) -> RuntimeID | Error:
    """Load an Entity by its StorageID and return its RuntimeID."""
    runtime_id = self.load_resource(storage_id=storage_id, load_children=load_depth)
    if isinstance(runtime_id, Error):
        return runtime_id

    res = self.resources.get(runtime_id)
    if not res or res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"Resource with StorageID {storage_id.hex()} (RuntimeID {runtime_id}) has type {res.get('type') if res else None}, expected Entity ({Entity})!",
            data={"storage_id": storage_id.hex(), "runtime_id": runtime_id, "actual_type": res.get("type") if res else None},
            code=EntityTypeMismatchError,
        )
        logger.trace("Entity load failed: type mismatch", channel="entities", error=err, entity_id=runtime_id)
        return err

    logger.trace(
        f"Loaded Entity {runtime_id} (StorageID: 0x{storage_id.hex()[:8]}...)",
        channel="entities",
        entity_id=runtime_id,
        action="loaded_entity",
    )
    return runtime_id


def is_entity(self, entity_id: RuntimeID) -> bool:
    """Check whether a loaded RuntimeID is an Entity."""
    if not self.is_valid_runtime_id(entity_id):
        return False
    resolved_id = self._resolve_handle(entity_id)
    res = self.resources.get(resolved_id)
    return bool(res and res.get("type") == Entity)


def get_entity_proxy(self, entity: RuntimeID) -> EntityProxy | Error:
    """Get an EntityProxy for an entity in memory."""
    if not self.is_valid_runtime_id(entity):
        err = Error(
            message="Entity not found",
            description=f"Runtime ID {entity} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get entity proxy: invalid or stale", channel="entities", error=err, entity_id=entity)
        return err

    resolved_id = self._resolve_handle(entity)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity} was not found in memory!",
            data={"entity_id": entity},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get entity proxy: entity not found", channel="entities", error=err, entity_id=entity)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to get entity proxy: not an entity", channel="entities", error=err, entity_id=entity)
        return err

    return EntityProxy(self, resolved_id)


def get_component(self, entity_id: RuntimeID, component_name: str) -> ComponentProxy | Error:
    """Retrieve a component dictionary proxy from an Entity by ID."""
    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"Runtime ID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to get component: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    components = res.get("data", {}).get("components", {})
    if component_name not in components:
        err = Error(
            message="Component not found on entity",
            description=f"Component '{component_name}' does not exist on Entity {entity_id}!",
            data={"entity_id": entity_id, "component_name": component_name},
            code=ComponentNotFoundOnEntityError,
        )
        logger.trace(f"Component '{component_name}' not found on Entity {entity_id}", channel="entities", error=err, entity_id=entity_id)
        return err

    logger.trace(
        f"Retrieved component '{component_name}' from Entity {entity_id}",
        channel="entities",
        entity_id=entity_id,
        action="get_component",
        data={"component_name": component_name},
    )
    return ComponentProxy(self, entity_id, component_name, components[component_name])


def set_component(self, entity_id: RuntimeID, component_name: str, component_data: dict[str, Any]) -> None | Error:
    """Attach or update a component dictionary on an Entity by ID."""
    if hasattr(component_data, "to_dict"):
        component_data = component_data.to_dict()

    if not isinstance(component_name, str):
        err = Error(
            message="Invalid component name",
            description=f"Component name must be a string, got {type(component_name).__name__} instead!",
            data={"entity_id": entity_id, "component_name": component_name},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to set component: invalid component name", channel="entities", error=err, entity_id=entity_id)
        return err

    if isinstance(component_data, (Mapping, ComponentProxy)):
        component_data = _unwrap(component_data)
    elif hasattr(component_data, "to_dict"):
        component_data = component_data.to_dict()

    if not isinstance(component_data, dict):
        err = Error(
            message="Invalid component data",
            description=f"Component data must be a dictionary, got {type(component_data).__name__} instead!",
            data={"entity_id": entity_id, "component_name": component_name, "component_data": component_data},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to set component: invalid component data", channel="entities", error=err, entity_id=entity_id)
        return err

    ui_err = ValidateUI.validate_ui_component(component_name, component_data)
    if isinstance(ui_err, Error):
        logger.trace("Failed to set component: UI component validation failed", channel="entities", error=ui_err, entity_id=entity_id)
        return ui_err

    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to set component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to set component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to set component: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    components = res.setdefault("data", {}).setdefault("components", {})
    before = copy.deepcopy(components.get(component_name))
    after = copy.deepcopy(component_data)
    components[component_name] = after

    self.dirty_runtime_ids.add(resolved_id)
    self._script_cache.pop(resolved_id, None)
    self._script_module_cache.pop(resolved_id, None)
    self._script_mtime_cache.pop(resolved_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != resolved_id}

    logger.trace(
        f"Set component '{component_name}' on Entity {entity_id}",
        channel="entities",
        entity_id=entity_id,
        action="set_component",
        before=before,
        after=after,
        data={"component_name": component_name},
    )
    return None


def mutate_component(self, entity_id: RuntimeID, component_name: str, new_data: dict[str, Any]) -> None | Error:
    """Update or merge a component's payload with validation, script cache invalidation, and tracing."""
    if isinstance(new_data, (Mapping, ComponentProxy)):
        new_data = _unwrap(new_data)
    elif hasattr(new_data, "to_dict"):
        new_data = new_data.to_dict()

    if not isinstance(component_name, str):
        err = Error(
            message="Invalid component name",
            description=f"Component name must be a string, got {type(component_name).__name__} instead!",
            data={"entity_id": entity_id, "component_name": component_name},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to mutate component: invalid component name", channel="entities", error=err, entity_id=entity_id)
        return err

    if not isinstance(new_data, dict):
        err = Error(
            message="Invalid component data",
            description=f"Component data must be a dictionary, got {type(new_data).__name__} instead!",
            data={"entity_id": entity_id, "component_name": component_name, "new_data": new_data},
            code=InvalidResourceDataError,
        )
        logger.trace("Failed to mutate component: invalid component data", channel="entities", error=err, entity_id=entity_id)
        return err

    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to mutate component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to mutate component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to mutate component: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    components = res.setdefault("data", {}).setdefault("components", {})
    existing = components.get(component_name)
    if isinstance(existing, dict):
        merged = copy.deepcopy(existing)
        merged.update(new_data)
    else:
        merged = copy.deepcopy(new_data)

    ui_err = ValidateUI.validate_ui_component(component_name, merged)
    if isinstance(ui_err, Error):
        logger.trace("Failed to mutate component: UI component validation failed", channel="entities", error=ui_err, entity_id=entity_id)
        return ui_err

    before = copy.deepcopy(existing)
    after = merged
    components[component_name] = after

    self.dirty_runtime_ids.add(resolved_id)
    self._script_cache.pop(resolved_id, None)
    self._script_module_cache.pop(resolved_id, None)
    self._script_mtime_cache.pop(resolved_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != resolved_id}

    logger.trace(
        f"Mutated component '{component_name}' on Entity {entity_id}",
        channel="entities",
        entity_id=entity_id,
        action="mutate_component",
        before=before,
        after=after,
        data={"component_name": component_name},
    )
    return None


def has_component(self, entity_id: RuntimeID, component_name: str) -> bool:
    """Check if an Entity by ID has a specific component."""
    if not self.is_valid_runtime_id(entity_id):
        return False
    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        return False
    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        return False
    return component_name in res.get("data", {}).get("components", {})


def remove_component(self, entity_id: RuntimeID, component_name: str) -> dict | Error:
    """Remove a component from an Entity by ID and return its previous value."""
    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to remove component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to remove component: entity not found", channel="entities", error=err, entity_id=entity_id)
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        logger.trace("Failed to remove component: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    components = res.get("data", {}).get("components", {})
    if component_name not in components:
        err = Error(
            message="Component not found on entity",
            description=f"Component '{component_name}' does not exist on Entity {entity_id}!",
            data={"entity_id": entity_id, "component_name": component_name},
            code=ComponentNotFoundOnEntityError,
        )
        logger.trace(f"Failed to remove component: '{component_name}' not on Entity {entity_id}", channel="entities", error=err, entity_id=entity_id)
        return err

    before = components.pop(component_name)
    self.dirty_runtime_ids.add(resolved_id)
    self._script_cache.pop(resolved_id, None)
    self._script_module_cache.pop(resolved_id, None)
    self._script_mtime_cache.pop(resolved_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != resolved_id}

    logger.trace(
        f"Removed component '{component_name}' from Entity {entity_id}",
        channel="entities",
        entity_id=entity_id,
        action="remove_component",
        before=before,
        after=None,
        data={"component_name": component_name},
    )
    return before


def get_components(self, entity_id: RuntimeID) -> MappingProxyType | Error:
    """Get all components of an Entity by ID as a nested read-only view."""
    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        return err

    components = res.get("data", {}).get("components", {})
    return _make_readonly_view(components)


def get_entity_resources(self, entity_id: RuntimeID) -> ReadOnlySequence | Error:
    """Get the referenced resources list of an Entity by ID as a read-only view."""
    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Entity not found",
            description=f"Runtime ID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        return err

    resolved_id = self._resolve_handle(entity_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        return err

    res = self.resources[resolved_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        return err

    return _make_readonly_view(res.get("data", {}).get("resources", []))


def add_entity_resource(self, entity_id: RuntimeID, resource_ref: str | bytes) -> None | Error:
    """Add a resource reference to an Entity by ID."""
    if entity_id not in self.resources:
        err = Error(
            message="Entity not found",
            description=f"RuntimeID {entity_id} was not found in memory!",
            data={"entity_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        return err

    res = self.resources[entity_id]
    if res.get("type") != Entity:
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
            data={"entity_id": entity_id, "type": res.get("type")},
            code=EntityTypeMismatchError,
        )
        return err

    ref_str = resource_ref.hex() if isinstance(resource_ref, bytes) else str(resource_ref)
    res_list = res.setdefault("data", {}).setdefault("resources", [])
    if ref_str not in res_list:
        before = copy.deepcopy(res_list)
        res_list.append(ref_str)
        self.dirty_runtime_ids.add(entity_id)
        logger.trace(
            f"Added resource reference to Entity {entity_id}",
            channel="entities",
            entity_id=entity_id,
            action="add_entity_resource",
            before=before,
            after=copy.deepcopy(res_list),
            data={"resource_ref": ref_str},
        )
    return None


def save_entity(self, entity_id: RuntimeID) -> None | Error:
    """Persist an Entity by ID to disk."""
    if not self.is_entity(entity_id):
        err = Error(
            message="Resource is not an entity",
            description=f"RuntimeID {entity_id} is not an entity!",
            data={"entity_id": entity_id},
            code=EntityTypeMismatchError,
        )
        return err
    return self.save_resource(entity_id)


def add_entity_child(self, parent_id: RuntimeID, child_id: RuntimeID) -> None | Error:
    """Appends child's canonical hex StorageID to parent's data['children'] and envelope ['children'], sets child's data['parent'], and marks both dirty."""
    if hasattr(parent_id, "id"):
        parent_id = parent_id.id
    if hasattr(child_id, "id"):
        child_id = child_id.id

    if not self.is_valid_runtime_id(parent_id):
        err = Error(
            message="Parent entity not found",
            description=f"Parent entity with runtime ID {parent_id} not found in memory!",
            data={"parent_id": parent_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("add_entity_child failed: parent not found", channel="entities", error=err)
        return err

    resolved_parent_id = self._resolve_handle(parent_id)
    if not self.is_entity(resolved_parent_id):
        err = Error(
            message="Resource is not an entity",
            description=f"Runtime ID {parent_id} has type {self.resources.get(resolved_parent_id, {}).get('type')}, expected Entity ({Entity})!",
            data={"parent_id": parent_id},
            code=EntityTypeMismatchError,
        )
        logger.trace("add_entity_child failed: parent not an entity", channel="entities", error=err)
        return err

    if not self.is_valid_runtime_id(child_id):
        err = Error(
            message="Child entity not found",
            description=f"Child entity with runtime ID {child_id} not found in memory!",
            data={"child_id": child_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("add_entity_child failed: child not found", channel="entities", error=err)
        return err

    resolved_child_id = self._resolve_handle(child_id)
    if not self.is_entity(resolved_child_id):
        err = Error(
            message="Resource is not an entity",
            description=f"Runtime ID {child_id} has type {self.resources.get(resolved_child_id, {}).get('type')}, expected Entity ({Entity})!",
            data={"child_id": child_id},
            code=EntityTypeMismatchError,
        )
        logger.trace("add_entity_child failed: child not an entity", channel="entities", error=err)
        return err

    curr = resolved_parent_id
    visited_ancestors: set[RuntimeID] = set()
    while curr is not None:
        if curr == resolved_child_id:
            err = Error(
                message="Cannot add entity: cyclic hierarchy detected",
                description=f"Entity {child_id} is already an ancestor of {parent_id}!",
                data={"parent_id": parent_id, "child_id": child_id},
                code=InvalidResourceDataError,
            )
            logger.trace("add_entity_child failed: cyclic hierarchy", channel="entities", error=err)
            return err
        if curr in visited_ancestors:
            break
        visited_ancestors.add(curr)
        curr = self.get_entity_parent(curr)

    parent_sid = self.get_storage_id(resolved_parent_id)
    if isinstance(parent_sid, Error):
        return parent_sid
    child_sid = self.get_storage_id(resolved_child_id)
    if isinstance(child_sid, Error):
        return child_sid

    parent_hex = parent_sid.hex()
    child_hex = child_sid.hex()

    child_envelope = self.resources[resolved_child_id]
    child_data = child_envelope.setdefault("data", {})
    old_parent_hex = child_data.get("parent")

    if old_parent_hex == parent_hex:
        return None

    parent_envelope = self.resources[resolved_parent_id]
    parent_snapshot = copy.deepcopy(parent_envelope)
    child_snapshot = copy.deepcopy(child_envelope)

    old_p_snapshot = None
    old_p_rid = None

    if old_parent_hex:
        try:
            old_p_sid = bytes.fromhex(old_parent_hex)
            if old_p_sid in self.resource_runtime_ids:
                old_p_rid = self.resource_runtime_ids[old_p_sid]
            else:
                old_p_rid = self.load_resource(old_p_sid, load_dependencies=0, load_children=0)
            if isinstance(old_p_rid, int) and old_p_rid in self.resources:
                old_p_snapshot = copy.deepcopy(self.resources[old_p_rid])
        except Exception:
            pass

    try:
        if old_p_snapshot is not None and old_p_rid is not None:
            old_p_env = self.resources[old_p_rid]
            old_p_data = old_p_env.setdefault("data", {})
            if "children" in old_p_data and isinstance(old_p_data["children"], list):
                if child_hex in old_p_data["children"]:
                    old_p_data["children"].remove(child_hex)
            if "children" in old_p_env and isinstance(old_p_env["children"], list):
                if child_hex in old_p_env["children"]:
                    old_p_env["children"].remove(child_hex)
            self.mark_dirty(old_p_rid)

        parent_data = parent_envelope.setdefault("data", {})
        if "children" not in parent_data or not isinstance(parent_data["children"], list):
            parent_data["children"] = []
        if "children" not in parent_envelope or not isinstance(parent_envelope["children"], list):
            parent_envelope["children"] = []

        if child_hex not in parent_data["children"]:
            parent_data["children"].append(child_hex)
        if child_hex not in parent_envelope["children"]:
            parent_envelope["children"].append(child_hex)

        child_data["parent"] = parent_hex

        self.mark_dirty(resolved_parent_id)
        self.mark_dirty(resolved_child_id)

        logger.trace(
            f"Added child {resolved_child_id} (0x{child_hex[:8]}...) to parent {resolved_parent_id} (0x{parent_hex[:8]}...)",
            channel="entities",
            entity_id=resolved_parent_id,
            action="added_child",
            data={"parent_id": resolved_parent_id, "child_id": resolved_child_id},
        )
        return None
    except Exception as ex:
        self.resources[resolved_parent_id] = parent_snapshot
        self.resources[resolved_child_id] = child_snapshot
        if old_p_snapshot is not None and old_p_rid is not None:
            self.resources[old_p_rid] = old_p_snapshot
        err = Error(
            message="Failed to add entity child",
            description=str(ex),
            data={"parent_id": parent_id, "child_id": child_id, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.error("add_entity_child failed, rolled back", channel="entities", error=err)
        return err


def remove_entity_child(self, parent_id: RuntimeID, child_id: RuntimeID) -> None | Error:
    """Removes child's StorageID from parent's data['children'] and envelope ['children'], clears child's data['parent'] = None, and marks both dirty."""
    if hasattr(parent_id, "id"):
        parent_id = parent_id.id
    if hasattr(child_id, "id"):
        child_id = child_id.id

    if not self.is_valid_runtime_id(parent_id):
        err = Error(
            message="Parent entity not found",
            description=f"Parent entity with runtime ID {parent_id} not found in memory!",
            data={"parent_id": parent_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("remove_entity_child failed: parent not found", channel="entities", error=err)
        return err

    resolved_parent_id = self._resolve_handle(parent_id)
    if not self.is_entity(resolved_parent_id):
        err = Error(
            message="Resource is not an entity",
            description=f"Runtime ID {parent_id} has type {self.resources.get(resolved_parent_id, {}).get('type')}, expected Entity ({Entity})!",
            data={"parent_id": parent_id},
            code=EntityTypeMismatchError,
        )
        logger.trace("remove_entity_child failed: parent not an entity", channel="entities", error=err)
        return err

    if not self.is_valid_runtime_id(child_id):
        err = Error(
            message="Child entity not found",
            description=f"Child entity with runtime ID {child_id} not found in memory!",
            data={"child_id": child_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("remove_entity_child failed: child not found", channel="entities", error=err)
        return err

    resolved_child_id = self._resolve_handle(child_id)
    if not self.is_entity(resolved_child_id):
        err = Error(
            message="Resource is not an entity",
            description=f"Runtime ID {child_id} has type {self.resources.get(resolved_child_id, {}).get('type')}, expected Entity ({Entity})!",
            data={"child_id": child_id},
            code=EntityTypeMismatchError,
        )
        logger.trace("remove_entity_child failed: child not an entity", channel="entities", error=err)
        return err

    child_sid = self.get_storage_id(resolved_child_id)
    if isinstance(child_sid, Error):
        return child_sid

    parent_sid = self.get_storage_id(resolved_parent_id)
    if isinstance(parent_sid, Error):
        return parent_sid

    child_hex = child_sid.hex()
    parent_hex = parent_sid.hex()

    parent_envelope = self.resources[resolved_parent_id]
    child_envelope = self.resources[resolved_child_id]
    parent_data = parent_envelope.setdefault("data", {})
    child_data = child_envelope.setdefault("data", {})

    in_parent_data = isinstance(parent_data.get("children"), list) and child_hex in parent_data["children"]
    in_parent_env = isinstance(parent_envelope.get("children"), list) and child_hex in parent_envelope["children"]
    if not (in_parent_data or in_parent_env):
        return None

    parent_snapshot = copy.deepcopy(parent_envelope)
    child_snapshot = copy.deepcopy(child_envelope)

    try:
        if isinstance(parent_data.get("children"), list) and child_hex in parent_data["children"]:
            parent_data["children"].remove(child_hex)
        if isinstance(parent_envelope.get("children"), list) and child_hex in parent_envelope["children"]:
            parent_envelope["children"].remove(child_hex)

        if child_data.get("parent") == parent_hex:
            child_data["parent"] = None

        self.mark_dirty(resolved_parent_id)
        self.mark_dirty(resolved_child_id)

        logger.trace(
            f"Removed child {resolved_child_id} (0x{child_hex[:8]}...) from parent {resolved_parent_id}",
            channel="entities",
            entity_id=resolved_parent_id,
            action="removed_child",
            data={"parent_id": resolved_parent_id, "child_id": resolved_child_id},
        )
        return None
    except Exception as ex:
        self.resources[resolved_parent_id] = parent_snapshot
        self.resources[resolved_child_id] = child_snapshot
        err = Error(
            message="Failed to remove entity child",
            description=str(ex),
            data={"parent_id": parent_id, "child_id": child_id, "error": str(ex)},
            code=InvalidResourceDataError,
        )
        logger.error("remove_entity_child failed, rolled back", channel="entities", error=err)
        return err


def delete_entity(self, entity_id: RuntimeID) -> bool | Error:
    """Delete an entity and its subtree transactionally from memory, advancing slot generations to tombstone handles."""
    if hasattr(entity_id, "id"):
        entity_id = entity_id.id

    if not self.is_valid_runtime_id(entity_id):
        err = Error(
            message="Resource not found",
            description=f"Runtime ID {entity_id} is invalid or stale (referencing a deleted resource)!",
            data={"runtime_id": entity_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("delete_entity failed: invalid or stale", channel="entities", error=err, entity_id=entity_id)
        return err

    resolved_id = self._resolve_handle(entity_id)
    if not self.is_entity(resolved_id):
        err = Error(
            message="Resource is not an entity",
            description=f"Runtime ID {entity_id} has type {self.resources.get(resolved_id, {}).get('type')}, expected Entity!",
            data={"entity_id": entity_id},
            code=EntityTypeMismatchError,
        )
        logger.trace("delete_entity failed: not an entity", channel="entities", error=err, entity_id=entity_id)
        return err

    snapshot = self._snapshot_loaded_state()

    try:
        parent_id = self.get_entity_parent(resolved_id)
        if parent_id is not None:
            detach_err = self.remove_entity_child(parent_id, resolved_id)
            if isinstance(detach_err, Error):
                self._restore_loaded_state(snapshot)
                return detach_err

        subtree_to_delete: list[RuntimeID] = []

        def _collect_subtree(curr_id: RuntimeID) -> None:
            curr_res_id = self._resolve_handle(curr_id)
            children = list(self.get_entity_children(curr_res_id))
            for child_id in children:
                _collect_subtree(child_id)
            subtree_to_delete.append(curr_res_id)

        _collect_subtree(resolved_id)

        for target_id in subtree_to_delete:
            del_res = self.delete_resource(target_id)
            if isinstance(del_res, Error):
                self._restore_loaded_state(snapshot)
                return del_res

        logger.trace(
            f"Deleted entity {resolved_id} and subtree ({len(subtree_to_delete)} entities)",
            channel="entities",
            entity_id=resolved_id,
            action="deleted_entity_subtree",
            data={"deleted_count": len(subtree_to_delete)},
        )
        return True
    except Exception as ex:
        self._restore_loaded_state(snapshot)
        err = Error(
            message="Entity deletion failed",
            description=f"Exception during entity deletion: {ex}",
            data={"entity_id": entity_id, "error": str(ex)},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.error("Exception during delete_entity, rolled back", channel="entities", error=err)
        return err


def get_entity_children(self, parent_id: RuntimeID) -> list[RuntimeID]:
    """Return in-memory runtime IDs of children of parent entity."""
    if hasattr(parent_id, "id"):
        parent_id = parent_id.id

    if not self.is_valid_runtime_id(parent_id):
        return []

    resolved_parent_id = self._resolve_handle(parent_id)
    if not self.is_entity(resolved_parent_id):
        return []

    parent_envelope = self.resources.get(resolved_parent_id, {})
    parent_data = parent_envelope.get("data", {})
    children_hexes = parent_data.get("children", [])
    if not isinstance(children_hexes, list):
        children_hexes = parent_envelope.get("children", [])
    if not isinstance(children_hexes, list):
        return []

    children_rids: list[RuntimeID] = []
    for child_hex in children_hexes:
        if not isinstance(child_hex, str):
            continue
        try:
            child_sid = bytes.fromhex(child_hex)
            if child_sid in self.resource_runtime_ids:
                children_rids.append(self.resource_runtime_ids[child_sid])
        except (ValueError, TypeError):
            continue

    return children_rids


def get_entity_parent(self, child_id: RuntimeID) -> RuntimeID | None:
    """Return in-memory runtime ID of parent of child entity."""
    if hasattr(child_id, "id"):
        child_id = child_id.id

    if not self.is_valid_runtime_id(child_id):
        return None

    resolved_child_id = self._resolve_handle(child_id)
    if not self.is_entity(resolved_child_id):
        return None

    child_data = self.resources.get(resolved_child_id, {}).get("data", {})
    parent_hex = child_data.get("parent")
    if not parent_hex or not isinstance(parent_hex, str):
        return None

    try:
        parent_sid = bytes.fromhex(parent_hex)
        if parent_sid in self.resource_runtime_ids:
            return self.resource_runtime_ids[parent_sid]
    except (ValueError, TypeError):
        pass

    return None


def query(self, *component_names: str) -> list[RuntimeID]:
    """Iterate over all loaded entities in memory and return runtime IDs possessing all specified component names (case-insensitive)."""
    req_lower = [c.lower() for c in component_names]
    results: list[RuntimeID] = []
    for rid, res in self.resources.items():
        if not isinstance(res, dict) or res.get("type") != Entity:
            continue
        entity_comps = res.get("data", {}).get("components", {})
        if not isinstance(entity_comps, dict):
            continue
        comp_names_lower = {k.lower() for k in entity_comps}
        if all(req in comp_names_lower for req in req_lower):
            results.append(rid)
    return results


def query_proxies(self, *component_names: str) -> list[EntityProxy]:
    """Return list of EntityProxy objects matching the component query."""
    return [EntityProxy(self, rid) for rid in self.query(*component_names)]


def spawn(
    self,
    template: RuntimeID | StorageID | str | dict,
    parent_id: RuntimeID | None = None,
    name: str | None = None,
) -> RuntimeID | Error:
    """Spawn a new Entity cloned from a dictionary or existing entity template."""
    if hasattr(template, "id"):
        template = template.id

    components: dict[str, dict] = {}
    scripts: list[str] = []
    resources: list[str | bytes] = []

    if isinstance(template, dict):
        if "data" in template and isinstance(template["data"], dict):
            comp_source = template["data"].get("components", {})
            script_source = template["data"].get("scripts", [])
            resource_source = template["data"].get("resources", [])
            if name is None:
                name = template.get("name")
        elif "components" in template and isinstance(template["components"], dict):
            comp_source = template["components"]
            script_source = template.get("scripts", [])
            resource_source = template.get("resources", [])
            if name is None:
                name = template.get("name")
        else:
            comp_source = template
            script_source = []
            resource_source = []
        components = copy.deepcopy(comp_source)
        scripts = copy.deepcopy(script_source) if isinstance(script_source, list) else []
        resources = copy.deepcopy(resource_source) if isinstance(resource_source, list) else []
    elif isinstance(template, int):
        if template not in self.resources:
            err = Error(
                message="Template entity not found",
                description=f"Runtime ID {template} not found in memory!",
                data={"template": template},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Spawn failed: template not found", channel="entities", error=err)
            return err
        t_res = self.resources[template]
        if t_res.get("type") != Entity:
            err = Error(
                message="Template is not an entity",
                description=f"Runtime ID {template} has type {t_res.get('type')}, expected Entity ({Entity})!",
                data={"template": template},
                code=EntityTypeMismatchError,
            )
            logger.trace("Spawn failed: template not an entity", channel="entities", error=err)
            return err
        t_data = t_res.get("data", {})
        components = copy.deepcopy(t_data.get("components", {}))
        scripts = copy.deepcopy(t_data.get("scripts", []))
        resources = copy.deepcopy(t_data.get("resources", []))
        if name is None:
            name = t_res.get("name")
    elif isinstance(template, (bytes, str)):
        sid = self._normalize_storage_id(template)
        if isinstance(sid, Error):
            return sid
        if sid in self.resource_runtime_ids:
            t_rid = self.resource_runtime_ids[sid]
        else:
            t_rid = self.load_entity(sid)
            if isinstance(t_rid, Error):
                return t_rid
        t_res = self.resources[t_rid]
        t_data = t_res.get("data", {})
        components = copy.deepcopy(t_data.get("components", {}))
        scripts = copy.deepcopy(t_data.get("scripts", []))
        resources = copy.deepcopy(t_data.get("resources", []))
        if name is None:
            name = t_res.get("name")
    else:
        err = Error(
            message="Invalid template",
            description=f"Spawn template must be RuntimeID, StorageID, hex string, or dict, got {type(template).__name__}!",
            data={"template": template},
            code=InvalidResourceDataError,
        )
        logger.trace("Spawn failed: invalid template type", channel="entities", error=err)
        return err

    new_entity_id = self.create_entity(
        components=components,
        resources=resources,
        name=name,
        scripts=scripts,
        parent_id=parent_id,
    )
    return new_entity_id

