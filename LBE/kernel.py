"""Public LBE façade. All authoritative runtime state belongs to this Kernel."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from . import registry, storage, world, scripts, ui
from .logger import logger
from .proxy import ComponentProxy, EntityProxy, ScriptProxy, ReadOnlySequence
from .types import (
    StorageID,
    RuntimeID,
    Error,
    FolderNotFoundOnDiskError,
    ResourceType,
    BrokenReference,
    ProjectManifest,
)


class Kernel:
    def __init__(self, folder_location: Path):
        if not folder_location.exists():
            raise Error(
                "Folder not found",
                f"Folder {folder_location} does not exist!",
                {"folder_location": folder_location},
                FolderNotFoundOnDiskError,
            )
        self.folder_location = folder_location

        self.resource_runtime_ids: dict[StorageID, RuntimeID] = {}
        self.resource_storage_ids: dict[RuntimeID, StorageID] = {}
        self.resources: dict[RuntimeID, Any] = {}
        self.dirty_runtime_ids: set[RuntimeID] = set()
        self.stale_runtime_ids: list[int] = []
        self._slot_generations: dict[int, int] = {}
        self._issued_generations: dict[int, int] = {}
        self._active_slots: set[int] = set()
        self.runtime_idx = 0
        self.manifest: ProjectManifest | None = None
        self._unloaded_project_root_ids: set[StorageID] = set()
        self.broken_references: list[BrokenReference] = []
        self._script_cache: dict[RuntimeID, tuple[str, Any, set[tuple[int, str]]]] = {}
        self._script_module_cache: dict[RuntimeID, tuple[str, dict[str, Any]]] = {}
        self._last_good_script_modules: dict[RuntimeID, dict[str, Any]] = {}
        self._script_reload_errors: dict[RuntimeID, Error] = {}
        self._script_failed_sources: dict[RuntimeID, tuple] = {}
        self._scripts_activating: set[RuntimeID] = set()
        self._script_mtime_cache: dict[RuntimeID, int] = {}
        self._method_sig_cache: dict[tuple[RuntimeID, str], tuple[int, str | None]] = {}
        self.function_exports: dict[str, tuple[StorageID, str]] = {}
        self.input_state: dict[str, Any] = {"keys": set(), "mouse": (0.0, 0.0)}

        logger.trace(
            f"Initialized Kernel at '{folder_location}'",
            channel="lifecycle",
            data={"folder_location": str(folder_location)},
        )

    def get_resource_id(self, storage_id: StorageID) -> RuntimeID | Error:
        """Get the Resource ID corresponding to the given Storage ID only if it has been loaded."""
        return registry.get_resource_id(self, storage_id)

    def _unpack_handle(self, runtime_id: RuntimeID) -> tuple[int, int]:
        """Unpack a RuntimeID handle into (slot_index, generation)."""
        return registry._unpack_handle(self, runtime_id)

    def is_valid_runtime_id(self, runtime_id: RuntimeID) -> bool:
        """Check if a runtime handle is alive and matches the current slot generation."""
        return registry.is_valid_runtime_id(self, runtime_id)

    def _resolve_handle(self, runtime_id: RuntimeID) -> RuntimeID:
        """Resolve a potentially plain slot index to its active packed handle."""
        return registry._resolve_handle(self, runtime_id)

    def get_storage_id(self, runtime_id: RuntimeID) -> StorageID | Error:
        """Get the Storage ID corresponding to the given Resource ID only if it has been loaded."""
        return registry.get_storage_id(self, runtime_id)

    def get_resource(self, runtime_id: RuntimeID) -> MappingProxyType | Error:
        """Get the loaded resource data for a given Runtime ID as a read-only view."""
        return registry.get_resource(self, runtime_id)

    def mutate_resource(self, runtime_id: RuntimeID, new_data: dict[str, Any]) -> None | Error:
        """Update a resource's payload in memory and trace the before/after mutation."""
        return registry.mutate_resource(self, runtime_id, new_data)

    def get_fresh_runtime_id(self) -> RuntimeID:
        """Get the fresh runtime ID packed with generation counter."""
        return registry.get_fresh_runtime_id(self)

    def delete_resource(self, runtime_id: RuntimeID) -> bool | Error:
        """Delete a resource from memory, advancing its slot generation so existing handles become invalid."""
        return registry.delete_resource(self, runtime_id)

    def is_dirty(self, runtime_id: RuntimeID) -> bool:
        """Check if a runtime ID has unpersisted changes in memory."""
        return registry.is_dirty(self, runtime_id)

    def mark_dirty(self, runtime_id: RuntimeID) -> None | Error:
        """Mark a resource as dirty so it will be saved on next flush."""
        return registry.mark_dirty(self, runtime_id)

    def save_resource(self, runtime_id: RuntimeID) -> None | Error | list[Error]:
        """Flush a specific resource (or all dirty resources if runtime_id is None) to disk."""
        return storage.save_resource(self, runtime_id)

    def save_all_resources(self) -> None | list[Error]:
        """Flush all dirty resources to disk and persist project manifest."""
        return storage.save_all_resources(self)

    def save_dirty_resources(self) -> None | list[Error]:
        """Flush all dirty resources to disk."""
        return storage.save_dirty_resources(self)

    def save_project(self) -> None | Error:
        """Gather root entity storage IDs and persist project manifest to project.json atomically."""
        return storage.save_project(self)

    def load_project(self, root_storage_id: StorageID | str | None = None) -> dict[str, Any] | None | Error:
        """Load all project roots, or a specific manifest root when its persistent ID is supplied."""
        return storage.load_project(self, root_storage_id)

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic metrics including broken references, total loaded resources, and dirty count."""
        return storage.get_diagnostics(self)

    def _snapshot_loaded_state(self) -> dict[str, Any]:
        """Capture registry state so a failed graph load or transaction can be rolled back."""
        return storage._snapshot_loaded_state(self)

    def _restore_loaded_state(self, snapshot: dict[str, Any]) -> None:
        """Restore registry state captured by _snapshot_loaded_state."""
        return storage._restore_loaded_state(self, snapshot)

    def transaction(self):
        """Context manager providing transactional rollback for batch operations on failure."""
        return storage.transaction(self)

    def reload_resource(self, runtime_id: RuntimeID) -> None | Error:
        """Discard in-memory changes and reload the resource from disk."""
        return storage.reload_resource(self, runtime_id)

    def _normalize_storage_id(self, sid: Any) -> StorageID | Error:
        """Convert a hex string or bytes ID to a 16-byte StorageID."""
        return storage._normalize_storage_id(self, sid)

    def load_resource(
        self,
        storage_id: StorageID,
        load_dependencies: int = -1,
        load_children: int = -1,
        _visited: set[StorageID | tuple[StorageID, int, int]] | None = None,
        is_fatal: bool = False,
    ) -> RuntimeID | Error:
        """Load a resource graph, optionally rolling back all new registrations on failure."""
        return storage.load_resource(self, storage_id, load_dependencies, load_children, _visited, is_fatal)

    def _load_resource(
        self,
        storage_id: StorageID,
        load_dependencies: int = -1,
        load_children: int = -1,
        _visited: set[StorageID | tuple[StorageID, int, int]] | None = None,
        is_fatal: bool = False,
    ) -> RuntimeID | Error:
        return storage._load_resource(self, storage_id, load_dependencies, load_children, _visited, is_fatal)

    def create_resource(
        self,
        resource_type: ResourceType,
        resource_data: dict[str, Any],
        name: str | None = None,
        dependencies: list[str | bytes] | None = None,
        children: list[str | bytes] | None = None,
        metadata: dict | None = None,
        storage_id: StorageID | None = None,
        immediate_save: bool = False,
    ) -> RuntimeID | Error:
        """Create a new resource, store in memory, mark dirty, and optionally persist to disk."""
        return storage.create_resource(self, resource_type, resource_data, name, dependencies, children, metadata, storage_id, immediate_save)

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
        return world.create_entity(self, components, resources, name, storage_id, immediate_save, scripts, parent_id)

    def load_entity(
        self,
        storage_id: StorageID,
        load_depth: int = -1,
    ) -> RuntimeID | Error:
        """Load an Entity by its StorageID and return its RuntimeID."""
        return world.load_entity(self, storage_id, load_depth)

    def is_entity(self, entity_id: RuntimeID) -> bool:
        """Check whether a loaded RuntimeID is an Entity."""
        return world.is_entity(self, entity_id)

    def get_entity_proxy(self, entity: RuntimeID) -> EntityProxy | Error:
        """Get an EntityProxy for an entity in memory."""
        return world.get_entity_proxy(self, entity)

    def get_component(self, entity_id: RuntimeID, component_name: str) -> ComponentProxy | Error:
        """Retrieve a component dictionary proxy from an Entity by ID."""
        return world.get_component(self, entity_id, component_name)

    def set_component(self, entity_id: RuntimeID, component_name: str, component_data: dict[str, Any]) -> None | Error:
        """Attach or update a component dictionary on an Entity by ID."""
        return world.set_component(self, entity_id, component_name, component_data)

    def mutate_component(self, entity_id: RuntimeID, component_name: str, new_data: dict[str, Any]) -> None | Error:
        """Update or merge a component's payload with validation, script cache invalidation, and tracing."""
        return world.mutate_component(self, entity_id, component_name, new_data)

    def has_component(self, entity_id: RuntimeID, component_name: str) -> bool:
        """Check if an Entity by ID has a specific component."""
        return world.has_component(self, entity_id, component_name)

    def remove_component(self, entity_id: RuntimeID, component_name: str) -> dict | Error:
        """Remove a component from an Entity by ID and return its previous value."""
        return world.remove_component(self, entity_id, component_name)

    def get_components(self, entity_id: RuntimeID) -> MappingProxyType | Error:
        """Get all components of an Entity by ID as a nested read-only view."""
        return world.get_components(self, entity_id)

    def get_entity_resources(self, entity_id: RuntimeID) -> ReadOnlySequence | Error:
        """Get the referenced resources list of an Entity by ID as a read-only view."""
        return world.get_entity_resources(self, entity_id)

    def add_entity_resource(self, entity_id: RuntimeID, resource_ref: str | bytes) -> None | Error:
        """Add a resource reference to an Entity by ID."""
        return world.add_entity_resource(self, entity_id, resource_ref)

    def save_entity(self, entity_id: RuntimeID) -> None | Error:
        """Persist an Entity by ID to disk."""
        return world.save_entity(self, entity_id)

    def add_entity_child(self, parent_id: RuntimeID, child_id: RuntimeID) -> None | Error:
        """Appends child's canonical hex StorageID to parent's data['children'] and envelope ['children'], sets child's data['parent'], and marks both dirty."""
        return world.add_entity_child(self, parent_id, child_id)

    def remove_entity_child(self, parent_id: RuntimeID, child_id: RuntimeID) -> None | Error:
        """Removes child's StorageID from parent's data['children'] and envelope ['children'], clears child's data['parent'] = None, and marks both dirty."""
        return world.remove_entity_child(self, parent_id, child_id)

    def delete_entity(self, entity_id: RuntimeID) -> bool | Error:
        """Delete an entity and its subtree transactionally from memory, advancing slot generations to tombstone handles."""
        return world.delete_entity(self, entity_id)

    def get_entity_children(self, parent_id: RuntimeID) -> list[RuntimeID]:
        """Return in-memory runtime IDs of children of parent entity."""
        return world.get_entity_children(self, parent_id)

    def get_entity_parent(self, child_id: RuntimeID) -> RuntimeID | None:
        """Return in-memory runtime ID of parent of child entity."""
        return world.get_entity_parent(self, child_id)

    def query(self, *component_names: str) -> list[RuntimeID]:
        """Iterate over all loaded entities in memory and return runtime IDs possessing all specified component names (case-insensitive)."""
        return world.query(self, *component_names)

    def query_proxies(self, *component_names: str) -> list[EntityProxy]:
        """Return list of EntityProxy objects matching the component query."""
        return world.query_proxies(self, *component_names)

    def spawn(
        self,
        template: RuntimeID | StorageID | str | dict,
        parent_id: RuntimeID | None = None,
        name: str | None = None,
    ) -> RuntimeID | Error:
        """Spawn a new Entity cloned from a dictionary or existing entity template."""
        return world.spawn(self, template, parent_id, name)

    def resolve_proxy(self, resource_type: int, storage_id_hex: str) -> Any | Error:
        """Resolve a resource by type and hex StorageID into a proxy or loaded resource."""
        return scripts.resolve_proxy(self, resource_type, storage_id_hex)

    def resolve_reference(self, storage_id_hex: str) -> Any | Error:
        """Resolve a universal 128-bit persistent StorageID (hex string) into a callable, proxy, or resource."""
        return scripts.resolve_reference(self, storage_id_hex)

    def execute_script(
        self,
        source: str,
        filename: str = "<lbe_script>",
        extra_globals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a script with preprocessed reference binding and optional extra globals."""
        return scripts.execute_script(self, source, filename, extra_globals)

    def _resolve_script_id(self, script_id: RuntimeID | StorageID | str) -> tuple[StorageID, str, RuntimeID] | Error:
        return scripts._resolve_script_id(self, script_id)

    def create_script_resource(
        self,
        name: str = "Script",
        source_path: str = "",
        code: str = "",
        requires: list[str] | None = None,
        storage_id: StorageID | None = None,
        immediate_save: bool = False,
    ) -> RuntimeID | Error:
        """Create a new Script resource."""
        return scripts.create_script_resource(self, name, source_path, code, requires, storage_id, immediate_save)

    def get_script_proxy(self, script_id: RuntimeID) -> ScriptProxy | Error:
        """Get a ScriptProxy for a script resource in memory."""
        return scripts.get_script_proxy(self, script_id)

    def get_script_module(self, script_id: RuntimeID | StorageID | str) -> dict[str, Any] | Error:
        """Load, bind, and execute a script resource module, returning its namespace globals."""
        return scripts.get_script_module(self, script_id)

    def resolve_function_export(self, fn_uuid_hex: str | bytes) -> tuple[Callable, RuntimeID] | Error:
        """Resolve an exported function UUID into (callable, script_runtime_id)."""
        return scripts.resolve_function_export(self, fn_uuid_hex)

    def update_script_source(self, script_id: RuntimeID, source: str) -> None | Error:
        """Validate and replace editable script source without changing its source mode."""
        return scripts.update_script_source(self, script_id, source)

    def get_script_callable(self, script_id: RuntimeID, func_name: str) -> Callable | None | Error:
        """Retrieve a callable function from a script resource by function name."""
        return scripts.get_script_callable(self, script_id, func_name)

    def attach_script(self, entity_id: RuntimeID, script_id: RuntimeID | StorageID | str) -> None | Error:
        """Attach a script resource to an Entity, storing its canonical StorageID hex."""
        return scripts.attach_script(self, entity_id, script_id)

    def detach_script(self, entity_id: RuntimeID, script_id: RuntimeID | StorageID | str) -> None | Error:
        """Detach a script from an Entity."""
        return scripts.detach_script(self, entity_id, script_id)

    def get_entity_scripts(self, entity_id: RuntimeID) -> list[RuntimeID]:
        """Get RuntimeIDs of all scripts attached to an Entity."""
        return scripts.get_entity_scripts(self, entity_id)

    def run_entity_scripts(
        self,
        entity_id: RuntimeID,
        dt: float = 0.0,
        method_name: str = "update",
    ) -> None | Error:
        """Execute all scripts attached to an Entity with self context."""
        return scripts.run_entity_scripts(self, entity_id, dt, method_name)

    def tick(self, dt: float = 0.0) -> None | list[Error]:
        """Iterate over all active entities with attached scripts and run update(dt)."""
        return scripts.tick(self, dt)

    def create_ui_entity(
        self,
        name: str,
        component_type: str,
        component_props: dict | None = None,
        parent_id: RuntimeID | None = None,
        storage_id: StorageID | None = None,
        immediate_save: bool = False,
    ) -> RuntimeID | Error:
        """Create an entity with the specified UI component pre-populated with default values merged with component_props."""
        return ui.create_ui_entity(self, name, component_type, component_props, parent_id, storage_id, immediate_save)

    def trigger_ui_event(
        self,
        entity_id: RuntimeID | Any,
        event_name: str = "on_click",
        *args: Any,
        bubble: bool = True,
        **kwargs: Any,
    ) -> Any | Error:
        """Trigger a UI event handler on an Entity with optional bubbling."""
        return ui.trigger_ui_event(self, entity_id, event_name, *args, bubble=bubble, **kwargs)

