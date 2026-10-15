"""Project persistence and transactional graph loading.

These functions operate on the Kernel's authoritative state.
"""

from __future__ import annotations

from typing import Any
import contextlib
import copy
import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path

from .logger import logger
from .integrity import Validate
from .types import (
    StorageID,
    RuntimeID,
    Error,
    StorageIDNotFoundOnDiskError,
    RuntimeIDNotFoundOnMemoryError,
    InvalidResourceDataError,
    ResourceAlreadyExistsOnDiskError,
    FailedToSaveResourceOnDiskError,
    EntityTypeMismatchError,
    InvalidProjectManifestError,
    ProjectLoadError,
    ResourceType,
    Entity,
    BrokenReference,
    ProjectManifest,
)

PROJECT_FORMAT_VERSION = 1

def save_resource(self, runtime_id: RuntimeID) -> None | Error | list[Error]:
    """Flush a specific resource (or all dirty resources if runtime_id is None) to disk."""
    if runtime_id is not None:
        if not self.is_valid_runtime_id(runtime_id):
            err = Error(
                message="Resource not found",
                description=f"Runtime ID {runtime_id} is invalid or stale (referencing a deleted resource)!",
                data={"runtime_id": runtime_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Save failed: invalid or stale", channel="storage", error=err, entity_id=runtime_id)
            return err
        runtime_id = self._resolve_handle(runtime_id)
        if runtime_id not in self.resources or runtime_id not in self.resource_storage_ids:
            err = Error(
                message="Resource not found",
                description=f"Resource with runtime ID {runtime_id} not found on memory!",
                data={"runtime_id": runtime_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Save failed: not in memory", channel="storage", error=err, entity_id=runtime_id)
            return err

    storage_id = self.resource_storage_ids[runtime_id]
    resource_data = self.resources[runtime_id]
    resource_path = self.folder_location / f"{storage_id.hex()}.json"
    temp_path = self.folder_location / f"{storage_id.hex()}.tmp"
    was_dirty = runtime_id in self.dirty_runtime_ids

    logger.trace(
        f"Beginning save pipeline for Resource {runtime_id} (StorageID: 0x{storage_id.hex()})",
        channel="storage",
        entity_id=runtime_id,
        action="saving_initiated",
        data={
            "storage_id": storage_id.hex(),
            "file": str(resource_path),
            "is_dirty": was_dirty,
            "type": resource_data.get("type"),
        },
    )

    # 1. Serialization step
    try:
        serialized_payload = json.dumps(resource_data, indent=4)
        byte_size = len(serialized_payload.encode("utf-8"))
        logger.trace(
            f"Serialized Resource {runtime_id} JSON payload ({byte_size} bytes)",
            channel="storage",
            entity_id=runtime_id,
            action="serialized",
            data={"byte_size": byte_size, "payload_keys": list(resource_data.keys())},
        )
    except Exception as ex:
        err = Error(
            message="Serialization failed",
            description=f"Failed to serialize resource data to JSON: {ex}",
            data={"runtime_id": runtime_id, "error": str(ex)},
            code=FailedToSaveResourceOnDiskError,
        )
        logger.error("JSON serialization failed during save", channel="storage", error=err, entity_id=runtime_id)
        return err

    # 2. Write to temporary file
    logger.trace(
        f"Writing {byte_size} bytes to temp file '{temp_path.name}'",
        channel="storage",
        entity_id=runtime_id,
        action="temp_writing",
        data={"temp_file": str(temp_path)},
    )
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(serialized_payload)
            f.flush()
            os.fsync(f.fileno())
    except Exception as ex:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        err = Error(
            message="Disk write failed",
            description=f"Failed to write to temp file: {ex}",
            data={"temp_path": str(temp_path), "error": str(ex)},
            code=FailedToSaveResourceOnDiskError,
        )
        logger.error("Failed to write temporary file", channel="storage", error=err, entity_id=runtime_id)
        return err

    # 3. Atomic rename/replace
    file_existed_before = resource_path.exists()
    logger.trace(
        f"Atomically replacing '{temp_path.name}' -> '{resource_path.name}' (file existed before: {file_existed_before})",
        channel="storage",
        entity_id=runtime_id,
        action="atomic_replacing",
        data={"target_file": str(resource_path), "overwriting": file_existed_before},
    )
    try:
        os.replace(temp_path, resource_path)
    except Exception as ex:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        err = Error(
            message="Disk write failed",
            description=f"Failed to atomically replace temp file with target: {ex}",
            data={"storage_id": storage_id, "error": str(ex)},
            code=FailedToSaveResourceOnDiskError,
        )
        logger.error("Failed atomic swap during save", channel="storage", error=err, entity_id=runtime_id)
        return err

    # 4. Update dirty cache
    self.dirty_runtime_ids.discard(runtime_id)
    logger.trace(
        f"Resource {runtime_id} flushed to disk and cleared from dirty cache",
        channel="storage",
        entity_id=runtime_id,
        action="saved",
        after=copy.deepcopy(resource_data),
        data={
            "storage_id": storage_id.hex(),
            "file": str(resource_path),
            "bytes_written": byte_size,
            "remaining_dirty_count": len(self.dirty_runtime_ids),
        },
    )
    return None


def save_all_resources(self) -> None | list[Error]:
    """Stage resources and manifest together; roll back published files on write failure."""
    folder = self.folder_location
    dirty = set(self.dirty_runtime_ids)
    previous_manifest = self.manifest
    try:
        stage = Path(tempfile.mkdtemp(prefix=".lbe-save-", dir=folder))
    except OSError as ex:
        return [Error("Project save failed", str(ex), {}, FailedToSaveResourceOnDiskError)]
    committed = False
    retain_recovery = False
    published = []
    try:
        if self.manifest is None:
            self.manifest = ProjectManifest(name=folder.name)
        self.folder_location = stage
        errors = []
        for runtime_id in sorted(dirty):
            result = self.save_resource(runtime_id)
            if isinstance(result, Error):
                errors.append(result)
            elif isinstance(result, list):
                errors.extend(result)
        if errors:
            return errors
        result = self.save_project()
        if isinstance(result, Error):
            return [result]
        candidate_manifest = self.manifest
        self.folder_location = folder
        backup = stage / "previous"
        backup.mkdir()
        for source in sorted(stage.glob("*.json"), key=lambda path: (path.name == "project.json", path.name)):
            target = folder / source.name
            existed = target.exists()
            if existed:
                shutil.copy2(target, backup / source.name)
            os.replace(source, target)
            published.append((target, existed))
        self.manifest = candidate_manifest
        committed = True
        return None
    except OSError as ex:
        rollback_errors = []
        for target, existed in reversed(published):
            try:
                if existed:
                    os.replace(stage / "previous" / target.name, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as restore_error:
                rollback_errors.append(str(restore_error))
        retain_recovery = bool(rollback_errors)
        return [Error("Project save failed", str(ex),
                      {"rollback_errors": rollback_errors, "recovery_folder": str(stage)},
                      FailedToSaveResourceOnDiskError)]
    finally:
        self.folder_location = folder
        if not committed:
            self.dirty_runtime_ids = dirty
            self.manifest = previous_manifest
        if not retain_recovery:
            try:
                shutil.rmtree(stage)
            except OSError as ex:
                logger.warn("Could not remove project staging directory", channel="storage", data={"error": str(ex)})


def save_dirty_resources(self) -> None | list[Error]:
    """Flush all dirty resources to disk."""
    return self.save_all_resources()


def save_project(self) -> None | Error:
    """Gather root entity storage IDs and persist project manifest to project.json atomically."""
    root_sids: list[str] = []
    for rid in self.resources:
        if self.is_entity(rid):
            parent_val = self.resources[rid].get("data", {}).get("parent")
            parent_sid = self._normalize_storage_id(parent_val) if parent_val else None
            if isinstance(parent_sid, bytes) and parent_sid in self.resource_runtime_ids:
                continue
            storage_id = self.resource_storage_ids.get(rid)
            if storage_id is not None:
                root_sids.append(storage_id.hex())
    # A save must not erase references to roots that could not be loaded.
    if self.manifest is not None:
        missing_roots = {
            reference.target_storage_id.hex()
            for reference in self.broken_references
            if reference.reference_type == "root"
        }
        for root_id in self.manifest.root_entity_ids:
            normalized_id = self._normalize_storage_id(root_id)
            if (isinstance(normalized_id, Error)
                or normalized_id.hex() in missing_roots
                or normalized_id in self._unloaded_project_root_ids):
                root_sids.append(root_id)
        candidate_manifest = copy.deepcopy(self.manifest)
        candidate_manifest.root_entity_ids = sorted(set(root_sids))
    else:
        candidate_manifest = ProjectManifest(
            name=self.folder_location.name,
            format_version=PROJECT_FORMAT_VERSION,
            root_entity_ids=sorted(set(root_sids)),
        )

    if type(candidate_manifest.format_version) is not int or candidate_manifest.format_version != PROJECT_FORMAT_VERSION:
        return Error(
            message="Invalid project manifest",
            description=(
                f"Cannot save unsupported manifest format_version "
                f"{candidate_manifest.format_version}; supported version is {PROJECT_FORMAT_VERSION}"
            ),
            data={"format_version": candidate_manifest.format_version},
            code=InvalidProjectManifestError,
        )

    manifest_dict = {
        "name": candidate_manifest.name,
        "format_version": candidate_manifest.format_version,
        "root_entity_ids": candidate_manifest.root_entity_ids,
        "settings": candidate_manifest.settings,
    }

    project_path = self.folder_location / "project.json"
    temp_path = self.folder_location / "project.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(manifest_dict, indent=4))
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(project_path)
    except Exception as ex:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        err = Error(
            message="Failed to save project manifest",
            description=f"Failed to write project manifest: {ex}",
            data={"path": str(project_path), "error": str(ex)},
            code=FailedToSaveResourceOnDiskError,
        )
        logger.error("Failed to save project manifest", channel="storage", error=err)
        return err

    self.manifest = candidate_manifest
    return None


def load_project(self, root_storage_id: StorageID | str | None = None) -> dict[str, Any] | None | Error:
    """Load all project roots, or a specific manifest root when its persistent ID is supplied."""
    selected_root = None
    if root_storage_id is not None:
        selected_root = self._normalize_storage_id(root_storage_id)
        if isinstance(selected_root, Error):
            return selected_root
    manifest_path = self.folder_location / "project.json"
    if selected_root is not None and not manifest_path.exists():
        return Error(
            message="Project manifest required",
            description="Loading a specific project root requires project.json; no application was created",
            data={"manifest_path": str(manifest_path), "storage_id": selected_root.hex()},
            code=InvalidProjectManifestError,
        )
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as ex:
            err = Error(
                message="Invalid project manifest",
                description=f"Failed to read or parse project.json: {ex}",
                data={"manifest_path": str(manifest_path), "error": str(ex)},
                code=InvalidProjectManifestError,
            )
            logger.error("Project manifest parsing failed", channel="storage", error=err)
            return err

        if not isinstance(manifest_data, dict):
            err = Error(
                message="Invalid project manifest",
                description=f"Manifest must be a JSON object, got {type(manifest_data).__name__}",
                data={"manifest_path": str(manifest_path)},
                code=InvalidProjectManifestError,
            )
            logger.error("Project manifest structure invalid", channel="storage", error=err)
            return err

        if "format_version" not in manifest_data:
            err = Error(
                message="Invalid project manifest",
                description="Manifest format_version is required",
                data={"manifest_path": str(manifest_path)},
                code=InvalidProjectManifestError,
            )
            logger.error("Manifest format_version missing", channel="storage", error=err)
            return err

        format_version = manifest_data["format_version"]
        if type(format_version) is not int or format_version < 1:
            err = Error(
                message="Invalid project manifest",
                description=f"Manifest format_version must be an integer >= 1, got {format_version}",
                data={"manifest_path": str(manifest_path), "format_version": format_version},
                code=InvalidProjectManifestError,
            )
            logger.error("Manifest format_version invalid", channel="storage", error=err)
            return err

        if format_version != PROJECT_FORMAT_VERSION:
            err = Error(
                message="Invalid project manifest",
                description=(
                    f"Unsupported manifest format_version {format_version}; "
                    f"supported version is {PROJECT_FORMAT_VERSION}"
                ),
                data={"manifest_path": str(manifest_path), "format_version": format_version},
                code=InvalidProjectManifestError,
            )
            logger.error("Manifest format_version unsupported", channel="storage", error=err)
            return err

        raw_root_ids = manifest_data.get("root_entity_ids", [])
        if not isinstance(raw_root_ids, list):
            err = Error(
                message="Invalid project manifest",
                description="Manifest root_entity_ids must be a JSON array",
                data={"manifest_path": str(manifest_path)},
                code=InvalidProjectManifestError,
            )
            logger.error("Manifest root_entity_ids invalid", channel="storage", error=err)
            return err

        manifest_name = manifest_data.get("name", "Untitled Project")
        settings = manifest_data.get("settings", {})
        if not isinstance(manifest_name, str) or not isinstance(settings, dict):
            err = Error(
                message="Invalid project manifest",
                description="Manifest name must be a string and settings must be a JSON object",
                data={"manifest_path": str(manifest_path)},
                code=InvalidProjectManifestError,
            )
            logger.error("Manifest metadata invalid", channel="storage", error=err)
            return err

        candidate_manifest = ProjectManifest(
            name=manifest_name,
            format_version=format_version,
            root_entity_ids=[str(rid) for rid in raw_root_ids],
            settings=settings,
        )

        roots_to_load = candidate_manifest.root_entity_ids
        if selected_root is not None:
            declared_roots = set()
            for root_id in roots_to_load:
                normalized_id = self._normalize_storage_id(root_id)
                if isinstance(normalized_id, bytes):
                    declared_roots.add(normalized_id)
            if selected_root not in declared_roots:
                return Error(
                    message="Project root not found",
                    description=f"Storage ID {selected_root.hex()} is not a root in project.json",
                    data={"storage_id": selected_root.hex(), "manifest_path": str(manifest_path)},
                    code=ProjectLoadError,
                )
            roots_to_load = [selected_root.hex()]

        state_before_load = self._snapshot_loaded_state()
        previous_manifest = self.manifest
        previous_broken_references = self.broken_references
        self.manifest = candidate_manifest
        self.broken_references = []
        roots_loaded = 0
        loaded_root_ids: set[StorageID] = set()
        for raw_root_id in roots_to_load:
            norm_sid = self._normalize_storage_id(raw_root_id)
            if isinstance(norm_sid, Error):
                self.broken_references.append(
                    BrokenReference(
                        source_storage_id=b"\x00" * 16,
                        target_storage_id=b"\x00" * 16,
                        reference_type="root",
                        details=f"Invalid root ID: {raw_root_id}",
                    )
                )
                logger.trace(f"Broken reference detected: invalid root entity ID {raw_root_id}", channel="storage")
                continue
            if norm_sid in loaded_root_ids:
                continue
            res = self.load_resource(norm_sid, load_dependencies=-1, load_children=-1)
            if isinstance(res, Error):
                if res.code == StorageIDNotFoundOnDiskError and selected_root is None:
                    self.broken_references.append(
                        BrokenReference(
                            source_storage_id=b"\x00" * 16,
                            target_storage_id=norm_sid,
                            reference_type="root",
                            details="File not found on disk",
                        )
                    )
                    logger.trace(f"Broken reference detected: 0x{norm_sid.hex()} missing from disk", channel="storage")
                    continue
                self._restore_loaded_state(state_before_load)
                self.manifest = previous_manifest
                self.broken_references = previous_broken_references
                return res
            if selected_root is not None and not self.is_entity(res):
                self._restore_loaded_state(state_before_load)
                self.manifest = previous_manifest
                self.broken_references = previous_broken_references
                return Error(
                    message="Project root is not an entity",
                    description=f"Selected root {selected_root.hex()} must be an entity",
                    data={"storage_id": selected_root.hex()},
                    code=EntityTypeMismatchError,
                )
            loaded_root_ids.add(norm_sid)
            roots_loaded += 1

        self._unloaded_project_root_ids = declared_roots - loaded_root_ids if selected_root is not None else set()
        return {
            "manifest": self.manifest,
            "roots_loaded": roots_loaded,
            "broken_references": len(self.broken_references),
        }

    # If project.json does not exist, inspect resource envelopes without loading them.
    candidate_entity_sids: set[StorageID] = set()
    referenced_child_sids: set[StorageID] = set()

    for p in sorted(self.folder_location.glob("*.json")):
        if p.name == "project.json":
            continue
        try:
            sid = bytes.fromhex(p.stem)
            if len(sid) != 16:
                continue
        except ValueError:
            continue

        try:
            with open(p, "r", encoding="utf-8") as f:
                envelope = json.load(f)
        except (OSError, UnicodeError, json.JSONDecodeError) as ex:
            return Error(
                message="Project root discovery failed",
                description=f"Failed to inspect resource {p.name}: {ex}",
                data={"resource_path": p, "error": str(ex)},
                code=ProjectLoadError,
            )

        if not isinstance(envelope, dict):
            return Error(
                message="Project root discovery failed",
                description=f"Resource {p.name} must contain a JSON object",
                data={"resource_path": p},
                code=ProjectLoadError,
            )

        if envelope.get("type") == Entity:
            candidate_entity_sids.add(sid)
            entity_data = envelope.get("data", {})
            if isinstance(entity_data, dict):
                data_children = entity_data.get("children", [])
                if isinstance(data_children, list):
                    for ch in data_children:
                        ch_sid = self._normalize_storage_id(ch)
                        if isinstance(ch_sid, bytes):
                            referenced_child_sids.add(ch_sid)

            children_list = envelope.get("children", [])
            if isinstance(children_list, list):
                for ch in children_list:
                    ch_sid = self._normalize_storage_id(ch)
                    if isinstance(ch_sid, bytes):
                        referenced_child_sids.add(ch_sid)

    if not candidate_entity_sids:
        return None

    discovered_roots = [
        sid for sid in candidate_entity_sids
        if sid not in referenced_child_sids
    ]
    discovered_roots.sort(key=lambda s: s.hex())

    if not discovered_roots:
        return Error(
            message="Project root discovery failed",
            description="Entity resources were found, but no root entities could be discovered",
            data={"folder_location": self.folder_location, "entity_count": len(candidate_entity_sids)},
            code=ProjectLoadError,
        )

    state_before_load = self._snapshot_loaded_state()
    previous_manifest = self.manifest
    previous_broken_references = self.broken_references
    self.broken_references = []
    for sid in discovered_roots:
        res = self.load_resource(sid, load_dependencies=-1, load_children=-1)
        if isinstance(res, Error):
            if res.code == StorageIDNotFoundOnDiskError:
                self.broken_references.append(
                    BrokenReference(
                        source_storage_id=b"\x00" * 16,
                        target_storage_id=sid,
                        reference_type="root",
                        details="File not found on disk",
                    )
                )
                logger.trace(f"Broken reference detected: 0x{sid.hex()} missing from disk", channel="storage")
                continue
            self._restore_loaded_state(state_before_load)
            self.manifest = previous_manifest
            self.broken_references = previous_broken_references
            return res

    self.manifest = ProjectManifest(
        name=self.folder_location.name,
        format_version=PROJECT_FORMAT_VERSION,
        root_entity_ids=[s.hex() for s in discovered_roots],
    )
    if save_error := self.save_project():
        self._restore_loaded_state(state_before_load)
        self.manifest = previous_manifest
        self.broken_references = previous_broken_references
        return save_error

    self._unloaded_project_root_ids = set()
    return {
        "manifest": self.manifest,
        "roots_loaded": len(self.manifest.root_entity_ids),
        "broken_references": len(self.broken_references),
    }


def get_diagnostics(self) -> dict[str, Any]:
    """Return diagnostic metrics including broken references, total loaded resources, and dirty count."""
    return {
        "broken_references": self.broken_references,
        "total_resources": len(self.resources),
        "dirty_count": len(self.dirty_runtime_ids),
        "script_reload_errors": dict(self._script_reload_errors),
    }


def _snapshot_loaded_state(self) -> dict[str, Any]:
    """Capture registry state so a failed graph load or transaction can be rolled back."""
    containers = []
    pending = [self.resources]
    seen = set()
    while pending:
        value = pending.pop()
        if not isinstance(value, (dict, list)) or id(value) in seen:
            continue
        seen.add(id(value))
        containers.append((value, value.copy()))
        pending.extend(value.values() if isinstance(value, dict) else value)
    return {
        "resource_runtime_ids": self.resource_runtime_ids.copy(),
        "resource_storage_ids": self.resource_storage_ids.copy(),
        "resources": self.resources,
        "_container_snapshots": containers,
        "dirty_runtime_ids": self.dirty_runtime_ids.copy(),
        "stale_runtime_ids": self.stale_runtime_ids.copy(),
        "_slot_generations": self._slot_generations.copy(),
        "_active_slots": self._active_slots.copy(),
        "runtime_idx": self.runtime_idx,
        "manifest": copy.deepcopy(self.manifest),
        "broken_references": list(self.broken_references),
        "_unloaded_project_root_ids": set(self._unloaded_project_root_ids),
        "_script_cache": self._script_cache.copy(),
        "_script_module_cache": self._script_module_cache.copy(),
        "_last_good_script_modules": self._last_good_script_modules.copy(),
        "_script_reload_errors": self._script_reload_errors.copy(),
        "_script_failed_sources": self._script_failed_sources.copy(),
        "_script_mtime_cache": self._script_mtime_cache.copy(),
        "_method_sig_cache": self._method_sig_cache.copy(),
        "function_exports": getattr(self, "function_exports", {}).copy(),
        "input_state": {
            "keys": set(getattr(self, "input_state", {}).get("keys", set())),
            "mouse": getattr(self, "input_state", {}).get("mouse", (0.0, 0.0)),
        },
    }


def _restore_loaded_state(self, snapshot: dict[str, Any]) -> None:
    """Restore registry state captured by _snapshot_loaded_state."""
    for container, original in snapshot.get("_container_snapshots", []):
        if isinstance(container, dict):
            container.clear()
            container.update(original)
        else:
            container[:] = original
    self.resource_runtime_ids = snapshot["resource_runtime_ids"]
    self.resource_storage_ids = snapshot["resource_storage_ids"]
    self.resources = snapshot["resources"]
    self.dirty_runtime_ids = snapshot["dirty_runtime_ids"]
    self.stale_runtime_ids = snapshot["stale_runtime_ids"]
    self._slot_generations = snapshot.get("_slot_generations", self._slot_generations).copy()
    self._active_slots = snapshot.get("_active_slots", self._active_slots).copy()
    self.runtime_idx = snapshot["runtime_idx"]
    self.manifest = snapshot.get("manifest", self.manifest)
    self._unloaded_project_root_ids = snapshot.get("_unloaded_project_root_ids", self._unloaded_project_root_ids)
    self._script_cache = snapshot.get("_script_cache", self._script_cache).copy()
    self._script_module_cache = snapshot.get("_script_module_cache", self._script_module_cache).copy()
    self._last_good_script_modules = snapshot.get("_last_good_script_modules", self._last_good_script_modules).copy()
    self._script_reload_errors = snapshot.get("_script_reload_errors", self._script_reload_errors).copy()
    self._script_failed_sources = snapshot.get("_script_failed_sources", self._script_failed_sources).copy()
    self._script_mtime_cache = snapshot.get("_script_mtime_cache", self._script_mtime_cache).copy()
    self._method_sig_cache = snapshot.get("_method_sig_cache", self._method_sig_cache).copy()
    self.broken_references = snapshot.get("broken_references", self.broken_references).copy()
    if hasattr(self, "function_exports") and "function_exports" in snapshot:
        self.function_exports = snapshot["function_exports"].copy()
    if "input_state" in snapshot:
        self.input_state = {
            "keys": set(snapshot["input_state"].get("keys", set())),
            "mouse": snapshot["input_state"].get("mouse", (0.0, 0.0)),
        }


@contextlib.contextmanager
def transaction(self):
    """Context manager providing transactional rollback for batch operations on failure."""
    snapshot = self._snapshot_loaded_state()
    try:
        yield self
    except Exception:
        self._restore_loaded_state(snapshot)
        raise


def reload_resource(self, runtime_id: RuntimeID) -> None | Error:
    """Discard in-memory changes and reload the resource from disk."""
    if runtime_id not in self.resource_storage_ids:
        err = Error(
            message="Resource not found",
            description=f"Resource with runtime ID {runtime_id} not found on memory!",
            data={"runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Reload failed: not in memory", channel="storage", error=err, entity_id=runtime_id)
        return err

    storage_id = self.resource_storage_ids[runtime_id]
    resource_path = self.folder_location / f"{storage_id.hex()}.json"
    if not resource_path.exists():
        err = Error(
            message="Resource not found on disk",
            description=f"Cannot reload: resource with storage ID {storage_id.hex()} does not exist on disk!",
            data={"storage_id": storage_id, "resource_path": resource_path},
            code=StorageIDNotFoundOnDiskError,
        )
        logger.trace("Reload failed: file not on disk", channel="storage", error=err, entity_id=runtime_id)
        return err

    try:
        with open(resource_path, "r", encoding="utf-8") as file:
            disk_data = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        return Error("Resource reload failed", str(ex), {"resource_path": str(resource_path)}, ProjectLoadError)

    if isinstance(e := Validate.resource_data(disk_data), Error):
        logger.trace("Reload failed: disk data failed validation", channel="storage", error=e, entity_id=runtime_id)
        return e

    before_state = copy.deepcopy(self.resources[runtime_id])
    self.resources[runtime_id] = disk_data
    self.dirty_runtime_ids.discard(runtime_id)
    self._script_cache.pop(runtime_id, None)
    self._script_module_cache.pop(runtime_id, None)
    self._script_mtime_cache.pop(runtime_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != runtime_id}

    logger.trace(
        f"Resource {runtime_id} reloaded from disk (dirty changes reverted)",
        channel="storage",
        entity_id=runtime_id,
        action="reloaded",
        before=before_state,
        after=copy.deepcopy(disk_data),
    )
    return None


def _normalize_storage_id(self, sid: Any) -> StorageID | Error:
    """Convert a hex string or bytes ID to a 16-byte StorageID."""
    if isinstance(sid, bytes):
        if len(sid) == 16:
            return sid
        return Error(
            message="Invalid storage ID",
            description=f"Storage ID bytes must be exactly 16 bytes, got {len(sid)} bytes!",
            data={"storage_id": sid},
            code=InvalidResourceDataError,
        )
    elif isinstance(sid, str):
        try:
            raw_bytes = bytes.fromhex(sid)
            if len(raw_bytes) == 16:
                return raw_bytes
        except ValueError:
            pass
        return Error(
            message="Invalid storage ID",
            description=f"Storage ID string must be a valid 32-character hex string (16 bytes), got '{sid}'!",
            data={"storage_id": sid},
            code=InvalidResourceDataError,
        )
    return Error(
        message="Invalid storage ID",
        description=f"Storage ID must be 16 bytes or 32-char hex string, got {type(sid).__name__} instead!",
        data={"storage_id": sid},
        code=InvalidResourceDataError,
    )


def load_resource(
    self,
    storage_id: StorageID,
    load_dependencies: int = -1,
    load_children: int = -1,
    _visited: set[StorageID | tuple[StorageID, int, int]] | None = None,
    is_fatal: bool = False,
) -> RuntimeID | Error:
    """Load a resource graph, optionally rolling back all new registrations on failure."""
    if not is_fatal or _visited is not None:
        return self._load_resource(
            storage_id,
            load_dependencies=load_dependencies,
            load_children=load_children,
            _visited=_visited,
            is_fatal=is_fatal,
        )

    snapshot = self._snapshot_loaded_state()
    try:
        result = self._load_resource(
            storage_id,
            load_dependencies=load_dependencies,
            load_children=load_children,
            _visited=set(),
            is_fatal=True,
        )
        if isinstance(result, Error):
            self._restore_loaded_state(snapshot)
        return result
    except Exception:
        self._restore_loaded_state(snapshot)
        raise


def _load_resource(
    self,
    storage_id: StorageID,
    load_dependencies: int = -1,
    load_children: int = -1,
    _visited: set[StorageID | tuple[StorageID, int, int]] | None = None,
    is_fatal: bool = False,
) -> RuntimeID | Error:
    if _visited is None:
        _visited = set()

    # A resource reached through a dependency may later need deeper child traversal.
    visit_key = (storage_id, max(load_dependencies, -1), max(load_children, -1))
    if storage_id in _visited or visit_key in _visited:
        existing_id = self.resource_runtime_ids.get(storage_id)
        if existing_id is not None:
            return existing_id
        return Error(
            message="Project load failed",
            description=f"Resource cycle reached unregistered storage ID {storage_id.hex()}",
            data={"storage_id": storage_id},
            code=ProjectLoadError,
        )

    if storage_id in self.resource_runtime_ids:
        runtime_id = self.resource_runtime_ids[storage_id]
    else:
        resource_path = self.folder_location / f"{storage_id.hex()}.json"
        if not resource_path.exists():
            err = Error(
                message="Resource not found",
                description=f"Resource with storage ID {storage_id.hex()} not found on disk!",
                data={"folder_location": self.folder_location, "storage_id": storage_id},
                code=StorageIDNotFoundOnDiskError,
            )
            logger.trace("Load failed: file not on disk", channel="storage", error=err, entity_id=storage_id.hex())
            return err

        try:
            with open(resource_path, "r", encoding="utf-8") as file:
                resource_data = json.load(file)
        except (OSError, UnicodeError, json.JSONDecodeError) as ex:
            err = Error(
                message="Project load failed",
                description=f"Failed to read resource {storage_id.hex()}: {ex}",
                data={"resource_path": resource_path, "storage_id": storage_id, "error": str(ex)},
                code=ProjectLoadError,
            )
            logger.error("Resource file could not be read", channel="storage", error=err)
            return err

        if isinstance(e := Validate.resource_data(resource_data), Error):
            logger.trace("Load failed: resource validation failed", channel="storage", error=e, entity_id=storage_id.hex())
            return e

        # Synchronize envelope children and data["children"] for Entity resources
        if resource_data.get("type") == Entity:
            inner_data = resource_data.setdefault("data", {})
            if isinstance(inner_data, dict):
                inner_children = inner_data.get("children")
                env_children = resource_data.get("children")
                if env_children is None and inner_children is not None:
                    resource_data["children"] = list(inner_children)
                elif inner_children is None and env_children is not None:
                    inner_data["children"] = list(env_children)
                elif env_children is not None and inner_children is not None:
                    synced = list(dict.fromkeys(list(inner_children) + list(env_children)))
                    inner_data["children"] = synced
                    resource_data["children"] = synced
                else:
                    inner_data["children"] = []
                    resource_data["children"] = []

        # get a fresh Runtime ID
        runtime_id = self.get_fresh_runtime_id()

        self.resource_runtime_ids[storage_id] = runtime_id
        self.resource_storage_ids[runtime_id] = storage_id
        self.resources[runtime_id] = resource_data

        logger.trace(
            f"Loaded resource {runtime_id} from disk (0x{storage_id.hex()[:8]}...)",
            channel="storage",
            entity_id=runtime_id,
            action="loaded",
            after=copy.deepcopy(resource_data),
        )

    _visited.add(visit_key)

    # Recursively load dependencies if requested depth > 0 or infinite (< 0)
    if load_dependencies != 0:
        next_dep_depth = load_dependencies if load_dependencies < 0 else load_dependencies - 1
        resource_data = self.resources[runtime_id]
        dependency_ids = list(resource_data.get("dependencies", []))
        if resource_data.get("type") == Entity:
            entity_data = resource_data.get("data", {})
            if isinstance(entity_data, dict):
                for field_name in ("resources", "scripts"):
                    field_references = entity_data.get(field_name, [])
                    if isinstance(field_references, list):
                        for reference in field_references:
                            if reference not in dependency_ids:
                                dependency_ids.append(reference)

        for raw_dep_id in dependency_ids:
            norm_sid = self._normalize_storage_id(raw_dep_id)
            if isinstance(norm_sid, Error):
                self.broken_references.append(
                    BrokenReference(
                        source_storage_id=storage_id,
                        target_storage_id=b"\x00" * 16,
                        reference_type="dependency",
                        details=f"Invalid dependency ID: {raw_dep_id}",
                    )
                )
                logger.trace(f"Broken reference detected: invalid dependency ID {raw_dep_id}", channel="storage")
                if is_fatal:
                    return norm_sid
                continue
            dep_res = self._load_resource(
                norm_sid,
                load_dependencies=next_dep_depth,
                load_children=0,
                _visited=_visited,
                is_fatal=is_fatal,
            )
            if isinstance(dep_res, Error):
                if dep_res.code == StorageIDNotFoundOnDiskError:
                    self.broken_references.append(
                        BrokenReference(
                            source_storage_id=storage_id,
                            target_storage_id=norm_sid,
                            reference_type="dependency",
                            details="File not found on disk",
                        )
                    )
                    logger.trace(f"Broken reference detected: 0x{norm_sid.hex()} missing from disk", channel="storage")
                    if is_fatal:
                        return dep_res
                    continue
                return dep_res

    # Recursively load children if requested depth > 0 or infinite (< 0)
    if load_children != 0:
        next_child_depth = load_children if load_children < 0 else load_children - 1
        resource_envelope = self.resources[runtime_id]
        children_to_load = list(resource_envelope.get("children", []))
        if resource_envelope.get("type") == Entity:
            entity_children = resource_envelope.get("data", {}).get("children", [])
            if isinstance(entity_children, list):
                for c in entity_children:
                    if c not in children_to_load:
                        children_to_load.append(c)
        for raw_child_id in children_to_load:
            norm_sid = self._normalize_storage_id(raw_child_id)
            if isinstance(norm_sid, Error):
                self.broken_references.append(
                    BrokenReference(
                        source_storage_id=storage_id,
                        target_storage_id=b"\x00" * 16,
                        reference_type="child",
                        details=f"Invalid child ID: {raw_child_id}",
                    )
                )
                logger.trace(f"Broken reference detected: invalid child ID {raw_child_id}", channel="storage")
                if is_fatal:
                    return norm_sid
                continue
            child_res = self._load_resource(
                norm_sid,
                load_dependencies=load_dependencies,
                load_children=next_child_depth,
                _visited=_visited,
                is_fatal=is_fatal,
            )
            if isinstance(child_res, Error):
                if child_res.code == StorageIDNotFoundOnDiskError:
                    self.broken_references.append(
                        BrokenReference(
                            source_storage_id=storage_id,
                            target_storage_id=norm_sid,
                            reference_type="child",
                            details="File not found on disk",
                        )
                    )
                    logger.trace(f"Broken reference detected: 0x{norm_sid.hex()} missing from disk", channel="storage")
                    if is_fatal:
                        return child_res
                    continue
                return child_res

    return runtime_id


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
    if not isinstance(resource_type, int):
        err = Error(
            message="Invalid resource type",
            description=f"Resource type must be an integer ResourceType, got {type(resource_type).__name__} instead!",
            data={"resource_type": resource_type},
            code=InvalidResourceDataError,
        )
        logger.trace("Resource creation failed: invalid resource_type", channel="resources", error=err)
        return err

    if not isinstance(resource_data, dict):
        err = Error(
            message="Invalid resource data",
            description=f"Resource data must be a dictionary, got {type(resource_data).__name__} instead!",
            data={"resource_data": resource_data},
            code=InvalidResourceDataError,
        )
        logger.trace("Resource creation failed: resource_data not a dict", channel="resources", error=err)
        return err

    resource_data = copy.deepcopy(resource_data)
    envelope: dict[str, Any] = {
        "type": resource_type,
        "data": resource_data,
    }
    if name is not None:
        envelope["name"] = name
    if dependencies is not None:
        envelope["dependencies"] = dependencies
    if children is not None:
        envelope["children"] = children
    if metadata is not None:
        envelope["metadata"] = metadata

    reference_lists = [(envelope, "dependencies"), (envelope, "children")]
    if resource_type == Entity:
        reference_lists.extend((resource_data, field) for field in ("children", "resources", "scripts"))
    for owner, field in reference_lists:
        if field not in owner:
            continue
        if not isinstance(owner[field], list):
            return Error("Invalid resource references", f"{field} must be a list", {"field": field},
                         InvalidResourceDataError)
        normalized = []
        for reference in owner[field]:
            storage_reference = self._normalize_storage_id(reference)
            if isinstance(storage_reference, Error):
                return storage_reference
            normalized.append(storage_reference.hex())
        owner[field] = normalized

    if resource_type == Entity:
        if "children" not in envelope:
            envelope["children"] = list(resource_data.get("children", []))
        elif "children" in envelope and "children" not in resource_data:
            resource_data["children"] = list(envelope["children"])
        elif "children" in envelope and "children" in resource_data:
            synced = list(dict.fromkeys(list(resource_data["children"]) + list(envelope["children"])))
            resource_data["children"] = synced
            envelope["children"] = synced

    if isinstance(e := Validate.resource_data(envelope), Error):
        logger.trace("Resource creation failed: envelope validation failed", channel="resources", error=e)
        return e

    if storage_id is None:
        storage_id = secrets.token_bytes(16)
    else:
        storage_id = self._normalize_storage_id(storage_id)
        if isinstance(storage_id, Error):
            return storage_id

    if storage_id in self.resource_runtime_ids:
        err = Error(
            message="Resource already exists",
            description=f"Resource with storage ID {storage_id.hex()} is already loaded in memory!",
            data={"storage_id": storage_id},
            code=ResourceAlreadyExistsOnDiskError,
        )
        logger.trace("Resource creation failed: collision in memory", channel="resources", error=err, entity_id=storage_id.hex())
        return err

    resource_path = self.folder_location / f"{storage_id.hex()}.json"
    if resource_path.exists():
        err = Error(
            message="Resource already exists",
            description=f"Resource with storage ID {storage_id.hex()} already exists on disk!",
            data={"storage_id": storage_id, "resource_path": resource_path},
            code=ResourceAlreadyExistsOnDiskError,
        )
        logger.trace("Resource creation failed: collision on disk", channel="resources", error=err, entity_id=storage_id.hex())
        return err

    runtime_id = self.get_fresh_runtime_id()

    self.resource_runtime_ids[storage_id] = runtime_id
    self.resource_storage_ids[runtime_id] = storage_id
    self.resources[runtime_id] = envelope
    self.dirty_runtime_ids.add(runtime_id)

    logger.trace(
        f"Created resource {runtime_id} (StorageID: 0x{storage_id.hex()[:8]}...)",
        channel="resources",
        entity_id=runtime_id,
        action="created",
        after=copy.deepcopy(envelope),
        data={"storage_id": storage_id.hex(), "immediate_save": immediate_save},
    )

    if immediate_save:
        if err := self.save_resource(runtime_id):
            return err

    return runtime_id

