"""Session management, selection tracking, and event dispatch for the LittleBigEngine Editor."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from LBE.kernel import Kernel
from LBE.proxy import EntityProxy
from LBE.types import Error, RuntimeID, StorageID, InvalidResourceDataError
from LBE.logger import logger


class EditorSession:
    """Manages state, selection, mutation, and event dispatch for the LittleBigEngine editor."""

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel
        self._selected_entity_id: RuntimeID | None = None
        self._selected_script_id: RuntimeID | None = None
        self.active_code_editor: Any | None = None
        self._selection_listeners: list[Callable[[RuntimeID | None], None]] = []
        self._change_listeners: list[Callable[[], None]] = []
        self._tick_listeners: list[Callable[[float], None]] = []
        self._play_listeners: list[Callable[[bool], None]] = []

        self.is_playing: bool = False
        self.sim_time: float = 0.0
        self.sim_speed: float = 1.0

        # Bootstrapped Root Scoping
        self.view_root_id: RuntimeID | None = None

        # Multi-Inspector Active Focus and Locking
        self._inspectors: list[Any] = []
        self.active_inspector: Any | None = None
        self.errors: list[Error] = []
        self._reported_script_errors: set[tuple] = set()

    def report_errors(self, result, notify: bool = True) -> None:
        """Keep actionable failures available to the UI without aborting other listeners."""
        failures = [result] if isinstance(result, Error) else result if isinstance(result, list) else []
        for error in failures:
            if isinstance(error, Error):
                self.errors.append(error)
                logger.error(error.message, channel="editor", error=error)
        del self.errors[:-100]
        if failures and notify:
            self._notify_state_changed()

    def _report_listener_failure(self, error: Exception) -> None:
        self.report_errors(Error("Editor listener failed", str(error), {}, InvalidResourceDataError), notify=False)

    @property
    def selected_entity_id(self) -> RuntimeID | None:
        return self._selected_entity_id

    @selected_entity_id.setter
    def selected_entity_id(self, entity_id: RuntimeID | None) -> None:
        self.select_entity(entity_id)

    def select_entity(self, entity_id: RuntimeID | None) -> None:
        """Set the active entity selection and route to the active unlocked inspector."""
        if entity_id is not None and not self.kernel.is_entity(entity_id):
            entity_id = None

        self._selected_entity_id = entity_id
        self._route_selection_to_inspectors(entity_id)
        self._notify_selection_changed(entity_id)
        self._notify_state_changed()

    @property
    def selected_script_id(self) -> RuntimeID | None:
        return self._selected_script_id

    def select_script(self, script_id: RuntimeID | None) -> None:
        """Select a script resource and open it in the active code editor."""
        self._selected_script_id = script_id
        if self.active_code_editor is not None and script_id is not None:
            self.active_code_editor.open_script(script_id)
        self._notify_state_changed()

    def set_view_root(self, entity_id: RuntimeID | None) -> None:
        """Scope the visible hierarchy tree to entity_id or all roots if None."""
        if entity_id is not None and not self.kernel.is_entity(entity_id):
            entity_id = None
        if self.view_root_id != entity_id:
            self.view_root_id = entity_id
            self._notify_state_changed()

    def get_visible_root_ids(self) -> list[RuntimeID]:
        """Return the root entity IDs to display based on current view scope."""
        if self.view_root_id is not None and self.kernel.is_entity(self.view_root_id):
            return [self.view_root_id]
        return [
            rid for rid in self.kernel.resources
            if self.kernel.is_entity(rid) and self.kernel.get_entity_parent(rid) is None
        ]

    def register_inspector(self, inspector: Any) -> None:
        """Register an inspector panel instance."""
        if inspector not in self._inspectors:
            self._inspectors.append(inspector)
            if self.active_inspector is None:
                self.active_inspector = inspector

    def unregister_inspector(self, inspector: Any) -> None:
        """Unregister an inspector panel instance."""
        if inspector in self._inspectors:
            self._inspectors.remove(inspector)
            if self.active_inspector is inspector:
                self.active_inspector = self._inspectors[0] if self._inspectors else None

    def set_active_inspector(self, inspector: Any) -> None:
        """Set the currently focused inspector instance."""
        self.active_inspector = inspector

    def _route_selection_to_inspectors(self, entity_id: RuntimeID | None) -> None:
        """Route entity selection to the active unlocked inspector, or first unlocked."""
        target_inspector = None
        if self.active_inspector is not None and not getattr(self.active_inspector, "is_locked", False):
            target_inspector = self.active_inspector
        else:
            for insp in self._inspectors:
                if not getattr(insp, "is_locked", False):
                    target_inspector = insp
                    break

        if target_inspector is not None and hasattr(target_inspector, "set_target"):
            target_inspector.set_target(entity_id)

    def subscribe_selection_changed(
        self, callback: Callable[[RuntimeID | None], None]
    ) -> Callable[[], None]:
        """Subscribe to selection updates. Returns an unsubscribe function."""
        self._selection_listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._selection_listeners:
                self._selection_listeners.remove(callback)

        return unsubscribe

    def subscribe_state_changed(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to general engine/editor state changes. Returns an unsubscribe function."""
        self._change_listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._change_listeners:
                self._change_listeners.remove(callback)

        return unsubscribe

    def subscribe_tick(self, callback: Callable[[float], None]) -> Callable[[], None]:
        """Subscribe to simulation tick updates. Returns an unsubscribe function."""
        self._tick_listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._tick_listeners:
                self._tick_listeners.remove(callback)

        return unsubscribe

    def subscribe_play_changed(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Subscribe to play/pause state toggles. Returns an unsubscribe function."""
        self._play_listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._play_listeners:
                self._play_listeners.remove(callback)

        return unsubscribe

    def _notify_selection_changed(self, entity_id: RuntimeID | None) -> None:
        for callback in list(self._selection_listeners):
            try:
                callback(entity_id)
            except Exception as error:
                self._report_listener_failure(error)

    def _notify_state_changed(self) -> None:
        for callback in list(self._change_listeners):
            try:
                callback()
            except Exception as error:
                self._report_listener_failure(error)

    def _notify_tick(self, dt: float) -> None:
        for callback in list(self._tick_listeners):
            try:
                callback(dt)
            except Exception as error:
                self._report_listener_failure(error)

    def _notify_play_changed(self, is_playing: bool) -> None:
        for callback in list(self._play_listeners):
            try:
                callback(is_playing)
            except Exception as error:
                self._report_listener_failure(error)

    def toggle_play(self) -> bool:
        """Toggle simulation playback on or off."""
        self.is_playing = not self.is_playing
        self._notify_play_changed(self.is_playing)
        return self.is_playing

    def step_simulation(self, dt: float = 1.0 / 60.0) -> None:
        """Advance the simulation by dt and notify tick listeners."""
        effective_dt = dt * self.sim_speed
        self.sim_time += effective_dt
        self.report_errors(self.kernel.tick(effective_dt))
        for script_id, error in self.kernel.get_diagnostics().get("script_reload_errors", {}).items():
            key = (script_id, error.description)
            if key not in self._reported_script_errors:
                self._reported_script_errors.add(key)
                self.report_errors(error)
        self._notify_tick(effective_dt)

    def refresh(self) -> None:
        """Notify all listeners that editor state has been refreshed."""
        self._notify_state_changed()

    # -------------------------------------------------------------------------
    # Entity Operations
    # -------------------------------------------------------------------------

    def create_entity(
        self,
        name: str | None = None,
        parent_id: RuntimeID | None = None,
        components: dict[str, dict] | None = None,
    ) -> RuntimeID | Error:
        """Create a new entity, select it, and notify listeners."""
        res_id = self.kernel.create_entity(
            components=components,
            name=name,
            parent_id=parent_id,
        )
        if isinstance(res_id, Error):
            return res_id

        self.select_entity(res_id)
        self._notify_state_changed()
        return res_id

    def create_child_entity(
        self,
        parent_id: RuntimeID,
        name: str | None = None,
        components: dict[str, dict] | None = None,
    ) -> RuntimeID | Error:
        """Create an entity parented to the given entity ID."""
        return self.create_entity(name=name, parent_id=parent_id, components=components)

    def create_ui_entity(
        self,
        name: str,
        component_type: str,
        component_props: dict | None = None,
        parent_id: RuntimeID | None = None,
    ) -> RuntimeID | Error:
        """Create a UI entity, select it, and notify listeners."""
        res_id = self.kernel.create_ui_entity(
            name=name,
            component_type=component_type,
            component_props=component_props,
            parent_id=parent_id,
        )
        if isinstance(res_id, Error):
            return res_id

        self.select_entity(res_id)
        self._notify_state_changed()
        return res_id

    def delete_entity(self, entity_id: RuntimeID, delete_from_disk: bool = False) -> bool | Error:
        """Delete an entity and its subtree from memory (and optionally disk)."""
        if hasattr(entity_id, "id"):
            entity_id = entity_id.id
        if not self.kernel.is_entity(entity_id):
            return False

        # Collect storage IDs for disk cleanup if requested before in-memory deletion
        disk_files: list[Path] = []
        if delete_from_disk and hasattr(self.kernel, "folder_location"):
            def _collect_sids(curr_id: RuntimeID) -> None:
                resolved = self.kernel._resolve_handle(curr_id) if hasattr(self.kernel, "_resolve_handle") else curr_id
                sid = self.kernel.resource_storage_ids.get(resolved)
                if sid is not None:
                    disk_files.append(self.kernel.folder_location / f"{sid.hex()}.json")
                for child_id in self.kernel.get_entity_children(curr_id):
                    _collect_sids(child_id)
            _collect_sids(entity_id)

        del_res = self.kernel.delete_entity(entity_id)
        if isinstance(del_res, Error):
            return del_res
        if not del_res:
            return False

        if delete_from_disk:
            for f in disk_files:
                f.unlink(missing_ok=True)

        if self._selected_entity_id is not None and (
            self._selected_entity_id == entity_id or not self.kernel.is_valid_runtime_id(self._selected_entity_id)
        ):
            self._selected_entity_id = None
            self._notify_selection_changed(None)

        self._notify_state_changed()
        return True

    def get_entity_proxy(self, entity_id: RuntimeID) -> EntityProxy | None:
        """Get an EntityProxy for the given entity ID if valid."""
        proxy = self.kernel.get_entity_proxy(entity_id)
        if isinstance(proxy, Error):
            return None
        return proxy

    def get_root_entities(self) -> list[RuntimeID]:
        """Return all entities that have no loaded parent in the kernel."""
        roots: list[RuntimeID] = []
        for rid in sorted(self.kernel.resources.keys()):
            if self.kernel.is_entity(rid):
                parent = self.kernel.get_entity_parent(rid)
                if parent is None or parent not in self.kernel.resources:
                    roots.append(rid)
        return roots

    def get_children(self, entity_id: RuntimeID) -> list[RuntimeID]:
        """Return child entity IDs for a given entity."""
        return self.kernel.get_entity_children(entity_id)

    def get_entity_name(self, entity_id: RuntimeID) -> str:
        """Return the friendly name of an entity or a fallback label."""
        res = self.kernel.get_resource(entity_id)
        if isinstance(res, (dict, MappingProxyType)) and res.get("name"):
            return str(res["name"])
        return f"Entity_{entity_id}"

    def set_entity_name(self, entity_id: RuntimeID, name: str) -> None:
        """Update an entity's name and mark dirty if changed."""
        proxy = self.kernel.get_entity_proxy(entity_id)
        if not isinstance(proxy, Error):
            new_name = name.strip() if name else f"Entity_{entity_id}"
            if proxy.name != new_name:
                proxy.name = new_name
                self._notify_state_changed()

    # -------------------------------------------------------------------------
    # Component Operations
    # -------------------------------------------------------------------------

    def get_components(self, entity_id: RuntimeID) -> MappingProxyType | dict[str, dict]:
        """Get all components for an entity as a dictionary."""
        comps = self.kernel.get_components(entity_id)
        if isinstance(comps, (dict, MappingProxyType)):
            return comps
        return {}

    def mutate_component(
        self,
        entity_id: RuntimeID,
        component_name: str,
        new_data: dict[str, Any],
    ) -> None | Error:
        """Update or replace a component's payload and mark dirty."""
        err = self.kernel.mutate_component(entity_id, component_name, new_data)
        if not isinstance(err, Error):
            self._notify_state_changed()
        self.report_errors(err)
        return err

    def add_component(
        self,
        entity_id: RuntimeID,
        component_name: str,
        initial_data: dict[str, Any] | None = None,
    ) -> None | Error:
        """Add a new component to an entity."""
        err = self.kernel.set_component(entity_id, component_name, initial_data or {})
        if not isinstance(err, Error):
            self._notify_state_changed()
        self.report_errors(err)
        return err

    def remove_component(
        self,
        entity_id: RuntimeID,
        component_name: str,
    ) -> dict | Error:
        """Remove a component from an entity."""
        err = self.kernel.remove_component(entity_id, component_name)
        if not isinstance(err, Error):
            self._notify_state_changed()
        self.report_errors(err)
        return err

    # -------------------------------------------------------------------------
    # Script Operations
    # -------------------------------------------------------------------------

    def get_entity_scripts(self, entity_id: RuntimeID) -> list[RuntimeID]:
        """Return the list of script runtime IDs attached to an entity."""
        res = self.kernel.get_entity_scripts(entity_id)
        if isinstance(res, list):
            return res
        return []

    def attach_script(
        self,
        entity_id: RuntimeID,
        script_id: RuntimeID | StorageID | str,
    ) -> None | Error:
        """Attach a script to an entity."""
        err = self.kernel.attach_script(entity_id, script_id)
        if not isinstance(err, Error):
            self._notify_state_changed()
        self.report_errors(err)
        return err

    def detach_script(
        self,
        entity_id: RuntimeID,
        script_id: RuntimeID | StorageID | str,
    ) -> None | Error:
        """Detach a script from an entity."""
        err = self.kernel.detach_script(entity_id, script_id)
        if not isinstance(err, Error):
            self._notify_state_changed()
        self.report_errors(err)
        return err

    # -------------------------------------------------------------------------
    # Storage & Persistence Operations
    # -------------------------------------------------------------------------

    def save_resource(self, runtime_id: RuntimeID) -> None | Error | list[Error]:
        """Save a specific resource to disk."""
        res = self.kernel.save_resource(runtime_id)
        self.report_errors(res, notify=False)
        self._notify_state_changed()
        return res

    def save_dirty_resources(self) -> None | list[Error]:
        """Save all currently dirty resources to disk."""
        res = self.kernel.save_dirty_resources()
        self.report_errors(res, notify=False)
        self._notify_state_changed()
        return res

    def save_all_resources(self) -> None | list[Error]:
        """Save all loaded resources to disk."""
        res = self.kernel.save_all_resources()
        self.report_errors(res, notify=False)
        self._notify_state_changed()
        return res

    def reload_resource(self, runtime_id: RuntimeID) -> None | Error:
        """Reload a resource from disk."""
        res = self.kernel.reload_resource(runtime_id)
        self.report_errors(res, notify=False)
        self._notify_state_changed()
        return res

    def reload_all_resources(self) -> list[Error]:
        """Reload all resources together, preserving the previous state if any read fails."""
        errors: list[Error] = []
        try:
            with self.kernel.transaction():
                for rid in list(self.kernel.resources.keys()):
                    err = self.kernel.reload_resource(rid)
                    if isinstance(err, Error):
                        raise err
        except Error as error:
            errors.append(error)
        self.report_errors(errors, notify=False)
        self._notify_state_changed()
        return errors

    def is_dirty(self, runtime_id: RuntimeID) -> bool:
        """Check if a resource has unsaved modifications."""
        return self.kernel.is_dirty(runtime_id)

    def get_dirty_count(self) -> int:
        """Return the count of dirty resources."""
        return len(self.kernel.dirty_runtime_ids)

    def get_storage_id_hex(self, runtime_id: RuntimeID) -> str:
        """Get the 32-character hexadecimal storage ID for a runtime ID."""
        sid = self.kernel.get_storage_id(runtime_id)
        if isinstance(sid, (bytes, bytearray)):
            return sid.hex()
        return "N/A"

    def get_all_resources(self) -> list[dict[str, Any]]:
        """Return summary metadata for all currently loaded resources."""
        results: list[dict[str, Any]] = []
        for rid in sorted(self.kernel.resources.keys()):
            res = self.kernel.resources[rid]
            sid = self.kernel.get_storage_id(rid)
            sid_hex = sid.hex() if isinstance(sid, (bytes, bytearray)) else "N/A"
            is_dirty = self.kernel.is_dirty(rid)
            is_entity = self.kernel.is_entity(rid)
            name = res.get("name") if isinstance(res, dict) else None
            res_type = res.get("type") if isinstance(res, dict) else -1
            results.append({
                "runtime_id": rid,
                "storage_id": sid,
                "storage_id_hex": sid_hex,
                "type": res_type,
                "name": name or (f"Entity_{rid}" if is_entity else f"Resource_{rid}"),
                "is_dirty": is_dirty,
                "is_entity": is_entity,
            })
        return results
