from pathlib import Path
from typing import Any, Callable
import copy
import inspect
import json
import secrets

from .types import *
from .logger import logger
from .integrity import (
    Validate,
    UI_SCHEMAS,
    UI_COMPONENT_NAMES,
    UI_COMPONENT_ALIASES,
    UI_EVENT_HANDLER_REGEX,
)
from .proxy import ComponentProxy, EntityProxy, ScriptProxy


class Kernel(object):
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
        self.stale_runtime_ids: list[RuntimeID] = []
        self.runtime_idx = 0
        self.manifest: ProjectManifest | None = None
        self.broken_references: list[BrokenReference] = []
        self._script_cache: dict[RuntimeID, tuple[str, Any, set[tuple[int, str]]]] = {}
        self._script_module_cache: dict[RuntimeID, tuple[str, dict[str, Any]]] = {}
        self._script_mtime_cache: dict[RuntimeID, int] = {}
        self._method_sig_cache: dict[tuple[RuntimeID, str], tuple[int, str | None]] = {}

        logger.trace(
            f"Initialized Kernel at '{folder_location}'",
            channel="lifecycle",
            data={"folder_location": str(folder_location)},
        )

    def get_resource_id(self, storage_id: StorageID) -> RuntimeID | Error:
        """Get the Resource ID corresponding to the given Storage ID only if it has been loaded."""
        if storage_id not in self.resource_runtime_ids:
            err = Error(
                message="Resource not found",
                description=f"Resource with storage ID {storage_id.hex()} not found on memory!",
                data={"resource_runtime_ids": self.resource_runtime_ids, "storage_id": storage_id},
                code=StorageIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to resolve StorageID to RuntimeID", channel="storage", error=err, entity_id=storage_id.hex())
            return err
        rid = self.resource_runtime_ids[storage_id]
        logger.trace(
            f"Resolved StorageID 0x{storage_id.hex()[:8]}... to RuntimeID {rid}",
            channel="storage",
            entity_id=rid,
            data={"storage_id": storage_id.hex(), "runtime_id": rid},
        )
        return rid

    def get_storage_id(self, runtime_id: RuntimeID) -> StorageID | Error:
        """Get the Storage ID corresponding to the given Resource ID only if it has been loaded."""
        if runtime_id not in self.resource_storage_ids:
            err = Error(
                message="Resource not found",
                description=f"Resource with runtime ID {runtime_id} not found on memory!",
                data={"resource_storage_ids": self.resource_storage_ids, "runtime_id": runtime_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to resolve RuntimeID to StorageID", channel="storage", error=err, entity_id=runtime_id)
            return err
        sid = self.resource_storage_ids[runtime_id]
        logger.trace(
            f"Resolved RuntimeID {runtime_id} to StorageID 0x{sid.hex()[:8]}...",
            channel="storage",
            entity_id=runtime_id,
            data={"runtime_id": runtime_id, "storage_id": sid.hex()},
        )
        return sid

    def get_resource(self, runtime_id: RuntimeID) -> Any | Error:
        """Get the loaded resource data for a given Runtime ID."""
        if runtime_id not in self.resources:
            err = Error(
                message="Resource not found",
                description=f"Resource with runtime ID {runtime_id} not found on memory!",
                data={"resources": self.resources, "runtime_id": runtime_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to get resource from memory", channel="resources", error=err, entity_id=runtime_id)
            return err
        return self.resources[runtime_id]

    def mutate_resource(self, runtime_id: RuntimeID, new_data: dict[str, Any]) -> None | Error:
        """Update a resource's payload in memory and trace the before/after mutation."""
        if runtime_id not in self.resources:
            err = Error(
                message="Resource not found",
                description=f"Cannot mutate: Runtime ID {runtime_id} not found in memory!",
                data={"runtime_id": runtime_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Resource mutation failed: not in memory", channel="resources", error=err, entity_id=runtime_id)
            return err

        before_state = copy.deepcopy(self.resources[runtime_id].get("data"))
        self.resources[runtime_id]["data"] = new_data
        self.dirty_runtime_ids.add(runtime_id)
        self._script_cache.pop(runtime_id, None)
        self._script_module_cache.pop(runtime_id, None)
        self._script_mtime_cache.pop(runtime_id, None)
        self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != runtime_id}

        logger.trace(
            f"Resource {runtime_id} mutated in memory",
            channel="resources",
            entity_id=runtime_id,
            action="mutated",
            before=before_state,
            after=copy.deepcopy(new_data),
        )
        return None

    def get_fresh_runtime_id(self) -> RuntimeID:
        """Get the fresh runtime ID."""
        if len(self.stale_runtime_ids) > 0:
            runtime_id = self.stale_runtime_ids.pop()
            logger.trace(f"Recycled stale RuntimeID {runtime_id}", channel="allocation", entity_id=runtime_id)
        else:
            runtime_id = self.runtime_idx
            self.runtime_idx += 1
            logger.trace(f"Allocated fresh RuntimeID {runtime_id}", channel="allocation", entity_id=runtime_id)
        return runtime_id

    def is_dirty(self, runtime_id: RuntimeID) -> bool:
        """Check if a runtime ID has unpersisted changes in memory."""
        return runtime_id in self.dirty_runtime_ids

    def mark_dirty(self, runtime_id: RuntimeID) -> None | Error:
        """Mark a resource as dirty so it will be saved on next flush."""
        if runtime_id not in self.resources:
            err = Error(
                message="Resource not found",
                description=f"Resource with runtime ID {runtime_id} not found on memory!",
                data={"runtime_id": runtime_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to mark resource dirty: not in memory", channel="storage", error=err, entity_id=runtime_id)
            return err
        self.dirty_runtime_ids.add(runtime_id)
        logger.trace(f"Resource {runtime_id} marked dirty", channel="storage", entity_id=runtime_id, action="marked_dirty")
        return None

    def save_resource(self, runtime_id: RuntimeID) -> None | Error | list[Error]:
        """Flush a specific resource (or all dirty resources if runtime_id is None) to disk."""

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
            temp_path.replace(resource_path)
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
        """Flush all dirty resources to disk and persist project manifest."""
        dirty_count = len(self.dirty_runtime_ids)
        logger.trace(f"Flushing all {dirty_count} dirty resources to disk", channel="storage", data={"count": dirty_count})
        errors: list[Error] = []
        for runtime_id in list(self.dirty_runtime_ids):
            if err := self.save_resource(runtime_id):
                if isinstance(err, list):
                    errors.extend(err)
                else:
                    errors.append(err)
        if proj_err := self.save_project():
            if isinstance(proj_err, Error):
                errors.append(proj_err)
        return errors if errors else None

    def save_dirty_resources(self) -> None | list[Error]:
        """Flush all dirty resources to disk."""
        return self.save_all_resources()

    def save_project(self) -> None | Error:
        """Gather root entity storage IDs and persist project manifest to project.json atomically."""
        root_rids: list[RuntimeID] = []
        for rid in self.resources:
            if self.is_entity(rid):
                parent_val = self.resources[rid].get("data", {}).get("parent")
                if not parent_val:
                    root_rids.append(rid)

        root_sids: list[str] = [
            self.get_storage_id(r).hex()
            for r in root_rids
            if isinstance(self.get_storage_id(r), bytes)
        ]
        root_sids.sort()

        if self.manifest is not None:
            self.manifest.root_entity_ids = root_sids
        else:
            self.manifest = ProjectManifest(
                name=self.folder_location.name,
                format_version=1,
                root_entity_ids=root_sids,
            )

        manifest_dict = {
            "name": self.manifest.name,
            "format_version": self.manifest.format_version,
            "root_entity_ids": self.manifest.root_entity_ids,
            "settings": self.manifest.settings,
        }

        project_path = self.folder_location / "project.json"
        temp_path = self.folder_location / "project.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(manifest_dict, indent=4))
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

        return None

    def load_project(self) -> dict[str, Any] | None | Error:
        """Load a project either from project.json or via deterministic root discovery."""
        self.broken_references.clear()
        manifest_path = self.folder_location / "project.json"
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

            format_version = manifest_data.get("format_version", 1)
            if not isinstance(format_version, int) or format_version < 1:
                err = Error(
                    message="Invalid project manifest",
                    description=f"Manifest format_version must be an integer >= 1, got {format_version}",
                    data={"manifest_path": str(manifest_path), "format_version": format_version},
                    code=InvalidProjectManifestError,
                )
                logger.error("Manifest format_version invalid", channel="storage", error=err)
                return err

            raw_root_ids = manifest_data.get("root_entity_ids", [])
            if not isinstance(raw_root_ids, list):
                raw_root_ids = []

            self.manifest = ProjectManifest(
                name=manifest_data.get("name", "Untitled Project"),
                format_version=format_version,
                root_entity_ids=[str(rid) for rid in raw_root_ids],
                settings=manifest_data.get("settings", {}) if isinstance(manifest_data.get("settings"), dict) else {},
            )

            for raw_root_id in self.manifest.root_entity_ids:
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
                res = self.load_resource(norm_sid, load_dependencies=-1, load_children=-1)
                if isinstance(res, Error):
                    if res.code == StorageIDNotFoundOnDiskError:
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
                    return res

            return {
                "manifest": self.manifest,
                "roots_loaded": len(self.manifest.root_entity_ids),
                "broken_references": len(self.broken_references),
            }

        # If project.json does NOT exist:
        candidate_entity_sids: set[StorageID] = set()
        referenced_child_sids: set[StorageID] = set()
        has_parent_sids: set[StorageID] = set()

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
            except Exception:
                continue

            if not isinstance(envelope, dict):
                continue

            if envelope.get("type") == Entity:
                candidate_entity_sids.add(sid)
                entity_data = envelope.get("data", {})
                if isinstance(entity_data, dict):
                    parent_hex = entity_data.get("parent")
                    if parent_hex and isinstance(parent_hex, str):
                        has_parent_sids.add(sid)

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
            if sid not in referenced_child_sids and sid not in has_parent_sids
        ]
        discovered_roots.sort(key=lambda s: s.hex())

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
                return res

        self.manifest = ProjectManifest(
            name=self.folder_location.name,
            format_version=1,
            root_entity_ids=[s.hex() for s in discovered_roots],
        )
        self.save_project()

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
        }


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

        with open(resource_path, "r", encoding="utf-8") as file:
            disk_data = json.load(file)

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
        _visited: set[StorageID] | None = None,
        is_fatal: bool = False,
    ) -> RuntimeID | Error:
        if _visited is None:
            _visited = set()

        if storage_id in _visited:
            return self.resource_runtime_ids[storage_id]
        _visited.add(storage_id)

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

            with open(resource_path, "r", encoding="utf-8") as file:
                resource_data = json.load(file)

            if isinstance(e := Validate.resource_data(resource_data), Error):
                logger.trace("Load failed: resource validation failed", channel="storage", error=e, entity_id=storage_id.hex())
                return e

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

        # Recursively load dependencies if requested depth > 0 or infinite (< 0)
        if load_dependencies != 0:
            next_dep_depth = load_dependencies if load_dependencies < 0 else load_dependencies - 1
            resource_data = self.resources[runtime_id]
            for raw_dep_id in resource_data.get("dependencies", []):
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
                dep_res = self.load_resource(
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
                child_res = self.load_resource(
                    norm_sid,
                    load_dependencies=0,
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

        if isinstance(e := Validate.resource_data(envelope), Error):
            logger.trace("Resource creation failed: envelope validation failed", channel="resources", error=e)
            return e

        if storage_id is None:
            storage_id = secrets.token_bytes(16)
        elif len(storage_id) != 16:
            err = Error(
                message="Invalid storage ID",
                description="Storage ID must be exactly 16 bytes (128 bits)!",
                data={"storage_id": storage_id},
                code=InvalidResourceDataError,
            )
            logger.trace("Resource creation failed: storage ID length invalid", channel="resources", error=err)
            return err

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

    # -------------------------------------------------------------------------
    # Entity System (ECS: Entities exist strictly as IDs)
    # -------------------------------------------------------------------------

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
            storage_id=storage_id,
            immediate_save=immediate_save,
        )
        if isinstance(res_id, Error):
            return res_id

        if parent_id is not None:
            pid = parent_id.id if hasattr(parent_id, "id") else parent_id
            err = self.add_entity_child(pid, res_id)
            if isinstance(err, Error):
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
        res = self.resources.get(entity_id)
        return bool(res and res.get("type") == Entity)

    def get_entity_proxy(self, entity: RuntimeID) -> EntityProxy | Error:
        """Get an EntityProxy for an entity in memory."""
        if entity not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity} was not found in memory!",
                data={"entity_id": entity},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to get entity proxy: entity not found", channel="entities", error=err, entity_id=entity)
            return err

        res = self.resources[entity]
        if res.get("type") != Entity:
            err = Error(
                message="Resource is not an entity",
                description=f"RuntimeID {entity} has type {res.get('type')}, expected Entity ({Entity})!",
                data={"entity_id": entity, "type": res.get("type")},
                code=EntityTypeMismatchError,
            )
            logger.trace("Failed to get entity proxy: not an entity", channel="entities", error=err, entity_id=entity)
            return err

        return EntityProxy(self, entity)

    def get_component(self, entity_id: RuntimeID, component_name: str) -> ComponentProxy | Error:
        """Retrieve a component dictionary proxy from an Entity by ID."""
        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to get component: entity not found", channel="entities", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
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

    def set_component(self, entity_id: RuntimeID, component_name: str, component_data: dict) -> None | Error:
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

        if not isinstance(component_data, dict):
            err = Error(
                message="Invalid component data",
                description=f"Component data must be a dictionary, got {type(component_data).__name__} instead!",
                data={"entity_id": entity_id, "component_name": component_name, "component_data": component_data},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to set component: invalid component data", channel="entities", error=err, entity_id=entity_id)
            return err

        ui_err = Validate.ui_component(component_name, component_data)
        if isinstance(ui_err, Error):
            logger.trace("Failed to set component: UI component validation failed", channel="entities", error=ui_err, entity_id=entity_id)
            return ui_err

        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to set component: entity not found", channel="entities", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
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

        self.dirty_runtime_ids.add(entity_id)

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

    def has_component(self, entity_id: RuntimeID, component_name: str) -> bool:
        """Check if an Entity by ID has a specific component."""
        if entity_id not in self.resources:
            return False
        res = self.resources[entity_id]
        if res.get("type") != Entity:
            return False
        return component_name in res.get("data", {}).get("components", {})

    def remove_component(self, entity_id: RuntimeID, component_name: str) -> dict | Error:
        """Remove a component from an Entity by ID and return its previous value."""
        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to remove component: entity not found", channel="entities", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
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
        self.dirty_runtime_ids.add(entity_id)

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

    def get_components(self, entity_id: RuntimeID) -> dict[str, dict] | Error:
        """Get all components of an Entity by ID."""
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

        return res.get("data", {}).get("components", {})

    def get_entity_resources(self, entity_id: RuntimeID) -> list[str | bytes] | Error:
        """Get the referenced resources list of an Entity by ID."""
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

        return res.get("data", {}).get("resources", [])

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

    # -------------------------------------------------------------------------
    # Entity Hierarchy & World Queries
    # -------------------------------------------------------------------------

    def add_entity_child(self, parent_id: RuntimeID, child_id: RuntimeID) -> None | Error:
        """Appends child's canonical hex StorageID to parent's data['children'], sets child's data['parent'], and marks both dirty."""
        if hasattr(parent_id, "id"):
            parent_id = parent_id.id
        if hasattr(child_id, "id"):
            child_id = child_id.id

        if parent_id not in self.resources:
            err = Error(
                message="Parent entity not found",
                description=f"Parent entity with runtime ID {parent_id} not found in memory!",
                data={"parent_id": parent_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("add_entity_child failed: parent not found", channel="entities", error=err)
            return err

        if not self.is_entity(parent_id):
            err = Error(
                message="Resource is not an entity",
                description=f"Runtime ID {parent_id} has type {self.resources[parent_id].get('type')}, expected Entity ({Entity})!",
                data={"parent_id": parent_id},
                code=EntityTypeMismatchError,
            )
            logger.trace("add_entity_child failed: parent not an entity", channel="entities", error=err)
            return err

        if child_id not in self.resources:
            err = Error(
                message="Child entity not found",
                description=f"Child entity with runtime ID {child_id} not found in memory!",
                data={"child_id": child_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("add_entity_child failed: child not found", channel="entities", error=err)
            return err

        if not self.is_entity(child_id):
            err = Error(
                message="Resource is not an entity",
                description=f"Runtime ID {child_id} has type {self.resources[child_id].get('type')}, expected Entity ({Entity})!",
                data={"child_id": child_id},
                code=EntityTypeMismatchError,
            )
            logger.trace("add_entity_child failed: child not an entity", channel="entities", error=err)
            return err

        curr = parent_id
        visited_ancestors: set[RuntimeID] = set()
        while curr is not None:
            if curr == child_id:
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

        parent_sid = self.get_storage_id(parent_id)
        if isinstance(parent_sid, Error):
            return parent_sid
        child_sid = self.get_storage_id(child_id)
        if isinstance(child_sid, Error):
            return child_sid

        parent_hex = parent_sid.hex()
        child_hex = child_sid.hex()

        parent_data = self.resources[parent_id]["data"]
        child_data = self.resources[child_id]["data"]

        if "children" not in parent_data or not isinstance(parent_data["children"], list):
            parent_data["children"] = []

        # If child already has another parent, detach from old parent
        old_parent_hex = child_data.get("parent")
        if old_parent_hex and old_parent_hex != parent_hex:
            try:
                old_p_sid = bytes.fromhex(old_parent_hex)
                if old_p_sid in self.resource_runtime_ids:
                    old_p_rid = self.resource_runtime_ids[old_p_sid]
                else:
                    old_p_rid = self.load_resource(old_p_sid)
                if isinstance(old_p_rid, int):
                    old_p_data = self.resources.get(old_p_rid, {}).get("data", {})
                    if "children" in old_p_data and child_hex in old_p_data["children"]:
                        old_p_data["children"].remove(child_hex)
                        self.mark_dirty(old_p_rid)
            except Exception:
                pass

        if child_hex not in parent_data["children"]:
            parent_data["children"].append(child_hex)

        child_data["parent"] = parent_hex

        self.mark_dirty(parent_id)
        self.mark_dirty(child_id)

        logger.trace(
            f"Added child {child_id} (0x{child_hex[:8]}...) to parent {parent_id} (0x{parent_hex[:8]}...)",
            channel="entities",
            entity_id=parent_id,
            action="added_child",
            data={"parent_id": parent_id, "child_id": child_id},
        )
        return None

    def remove_entity_child(self, parent_id: RuntimeID, child_id: RuntimeID) -> None | Error:
        """Removes child's StorageID from parent's data['children'], clears child's data['parent'] = None, and marks both dirty."""
        if hasattr(parent_id, "id"):
            parent_id = parent_id.id
        if hasattr(child_id, "id"):
            child_id = child_id.id

        if parent_id not in self.resources:
            err = Error(
                message="Parent entity not found",
                description=f"Parent entity with runtime ID {parent_id} not found in memory!",
                data={"parent_id": parent_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("remove_entity_child failed: parent not found", channel="entities", error=err)
            return err

        if not self.is_entity(parent_id):
            err = Error(
                message="Resource is not an entity",
                description=f"Runtime ID {parent_id} has type {self.resources[parent_id].get('type')}, expected Entity ({Entity})!",
                data={"parent_id": parent_id},
                code=EntityTypeMismatchError,
            )
            logger.trace("remove_entity_child failed: parent not an entity", channel="entities", error=err)
            return err

        if child_id not in self.resources:
            err = Error(
                message="Child entity not found",
                description=f"Child entity with runtime ID {child_id} not found in memory!",
                data={"child_id": child_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("remove_entity_child failed: child not found", channel="entities", error=err)
            return err

        if not self.is_entity(child_id):
            err = Error(
                message="Resource is not an entity",
                description=f"Runtime ID {child_id} has type {self.resources[child_id].get('type')}, expected Entity ({Entity})!",
                data={"child_id": child_id},
                code=EntityTypeMismatchError,
            )
            logger.trace("remove_entity_child failed: child not an entity", channel="entities", error=err)
            return err

        child_sid = self.get_storage_id(child_id)
        if isinstance(child_sid, Error):
            return child_sid

        parent_sid = self.get_storage_id(parent_id)
        if isinstance(parent_sid, Error):
            return parent_sid

        child_hex = child_sid.hex()
        parent_hex = parent_sid.hex()

        parent_data = self.resources[parent_id]["data"]
        child_data = self.resources[child_id]["data"]

        if "children" in parent_data and isinstance(parent_data["children"], list):
            if child_hex in parent_data["children"]:
                parent_data["children"].remove(child_hex)
                self.mark_dirty(parent_id)

        if child_data.get("parent") == parent_hex:
            child_data["parent"] = None
            self.mark_dirty(child_id)

        logger.trace(
            f"Removed child {child_id} (0x{child_hex[:8]}...) from parent {parent_id}",
            channel="entities",
            entity_id=parent_id,
            action="removed_child",
            data={"parent_id": parent_id, "child_id": child_id},
        )
        return None

    def get_entity_children(self, parent_id: RuntimeID) -> list[RuntimeID]:
        """Return in-memory runtime IDs of children of parent entity."""
        if hasattr(parent_id, "id"):
            parent_id = parent_id.id

        if parent_id not in self.resources or not self.is_entity(parent_id):
            return []

        parent_data = self.resources[parent_id].get("data", {})
        children_hexes = parent_data.get("children", [])
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

        if child_id not in self.resources or not self.is_entity(child_id):
            return None

        child_data = self.resources[child_id].get("data", {})
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

    def resolve_proxy(self, resource_type: int, storage_id_hex: str) -> Any | Error:
        """Resolve a resource by type and hex StorageID into a proxy or loaded resource."""
        try:
            storage_id = bytes.fromhex(storage_id_hex)
        except ValueError as ex:
            err = Error(
                message="Invalid storage ID hex",
                description=f"Failed to parse storage ID hex '{storage_id_hex}': {ex}",
                data={"storage_id_hex": storage_id_hex, "error": str(ex)},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to resolve proxy: invalid hex", channel="storage", error=err)
            return err

        runtime_id = self.get_resource_id(storage_id)
        if isinstance(runtime_id, Error):
            runtime_id = self.load_resource(storage_id)
            if isinstance(runtime_id, Error):
                return runtime_id

        if resource_type == Entity or resource_type == 0:
            return self.get_entity_proxy(runtime_id)

        if resource_type == Script or resource_type == 1:
            return self.get_script_proxy(runtime_id)

        res = self.get_resource(runtime_id)
        if isinstance(res, Error):
            return res

        actual_type = res.get("type") if isinstance(res, dict) else None
        if actual_type != resource_type:
            err = Error(
                message="Resource type mismatch",
                description=f"Resource {runtime_id} has type {actual_type}, expected {resource_type}!",
                data={"runtime_id": runtime_id, "actual_type": actual_type, "expected_type": resource_type},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to resolve proxy: type mismatch", channel="resources", error=err)
            return err
        return res

    def execute_script(
        self,
        source: str,
        filename: str = "<lbe_script>",
        extra_globals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a script with preprocessed reference binding and optional extra globals."""
        import types
        from .preprocessor import RuntimeBinder

        module = types.ModuleType(filename)
        module.__dict__["__builtins__"] = __builtins__
        if extra_globals:
            module.__dict__.update(extra_globals)
        RuntimeBinder.bind_module(module, source, self, filename=filename)
        return module.__dict__

    def _resolve_script_id(self, script_id: RuntimeID | StorageID | str) -> tuple[StorageID, str, RuntimeID] | Error:
        if isinstance(script_id, int):
            runtime_id = script_id
            sid = self.get_storage_id(runtime_id)
            if isinstance(sid, Error):
                return sid
            return sid, sid.hex(), runtime_id
        elif isinstance(script_id, bytes):
            sid = script_id
            runtime_id = self.get_resource_id(sid)
            if isinstance(runtime_id, Error):
                runtime_id = self.load_resource(sid)
                if isinstance(runtime_id, Error):
                    return runtime_id
            return sid, sid.hex(), runtime_id
        elif isinstance(script_id, str):
            try:
                sid = bytes.fromhex(script_id)
            except ValueError as ex:
                return Error(
                    message="Invalid script storage ID",
                    description=f"Cannot parse hex string '{script_id}': {ex}",
                    data={"script_id": script_id, "error": str(ex)},
                    code=InvalidResourceDataError,
                )
            runtime_id = self.get_resource_id(sid)
            if isinstance(runtime_id, Error):
                runtime_id = self.load_resource(sid)
                if isinstance(runtime_id, Error):
                    return runtime_id
            return sid, sid.hex(), runtime_id
        return Error(
            message="Invalid script ID type",
            description=f"Expected RuntimeID, StorageID, or hex str, got {type(script_id).__name__}!",
            data={"script_id": script_id},
            code=InvalidResourceDataError,
        )

    def create_script_resource(
        self,
        name: str,
        source_path: str = "",
        code: str = "",
        requires: list[str] | None = None,
        storage_id: StorageID | None = None,
        immediate_save: bool = False,
    ) -> RuntimeID | Error:
        """Create a new Script resource."""
        from .preprocessor import extract_script_symbols

        symbols = {}
        if code:
            symbols = extract_script_symbols(code)
        elif source_path:
            try:
                s_file = Path(source_path)
                if not s_file.is_absolute():
                    s_file = self.folder_location / s_file
                if s_file.exists():
                    symbols = extract_script_symbols(s_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        script_data = {
            "name": name,
            "source_path": source_path,
            "code": code,
            "requires": list(requires) if requires is not None else [],
            "symbols": symbols,
        }
        return self.create_resource(
            resource_type=Script,
            resource_data=script_data,
            name=name,
            storage_id=storage_id,
            immediate_save=immediate_save,
        )

    def get_script_proxy(self, script_id: RuntimeID) -> ScriptProxy | Error:
        """Get a ScriptProxy for a script resource in memory."""
        if not isinstance(script_id, int) or script_id not in self.resources:
            err = Error(
                message="Resource not found",
                description=f"RuntimeID {script_id} was not found in memory!",
                data={"script_id": script_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to get script proxy: resource not found", channel="resources", error=err, entity_id=script_id)
            return err

        res = self.resources[script_id]
        if res.get("type") != Script:
            err = Error(
                message="Resource is not a script",
                description=f"RuntimeID {script_id} has type {res.get('type')}, expected Script ({Script})!",
                data={"script_id": script_id, "type": res.get("type")},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to get script proxy: not a script", channel="resources", error=err, entity_id=script_id)
            return err

        return ScriptProxy(self, script_id)

    def get_script_module(self, script_id: RuntimeID) -> dict[str, Any] | Error:
        """Load, bind, and execute a script resource module, returning its namespace globals."""
        if not isinstance(script_id, int) or script_id not in self.resources:
            err = Error(
                message="Resource not found",
                description=f"RuntimeID {script_id} was not found in memory!",
                data={"script_id": script_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to get script module: resource not found", channel="resources", error=err, entity_id=script_id)
            return err

        res = self.resources[script_id]
        if res.get("type") != Script:
            err = Error(
                message="Resource is not a script",
                description=f"RuntimeID {script_id} has type {res.get('type')}, expected Script ({Script})!",
                data={"script_id": script_id, "type": res.get("type")},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to get script module: not a script", channel="resources", error=err, entity_id=script_id)
            return err

        s_data = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
        code = s_data.get("code", "")
        source_path = s_data.get("source_path", "")
        file_mtime = None

        if not code and source_path:
            p = Path(source_path)
            if not p.is_absolute():
                p = self.folder_location / p
            if p.exists():
                try:
                    file_mtime = p.stat().st_mtime_ns
                except Exception:
                    file_mtime = None

                cached = self._script_module_cache.get(script_id)
                cached_mtime = self._script_mtime_cache.get(script_id)
                if cached is not None and file_mtime is not None and cached_mtime == file_mtime:
                    return cached[1]

                try:
                    code = p.read_text(encoding="utf-8")
                except Exception as ex:
                    err = Error(
                        message="Failed to read script file",
                        description=f"Could not read source_path '{source_path}': {ex}",
                        data={"script_id": script_id, "source_path": source_path, "error": str(ex)},
                        code=InvalidResourceDataError,
                    )
                    logger.trace("Failed to read script source", channel="scripts", error=err, entity_id=script_id)
                    return err
        else:
            cached = self._script_module_cache.get(script_id)
            if cached is not None and cached[0] == code:
                return cached[1]

        import types
        from .preprocessor import ReferencePreprocessor, extract_script_symbols

        filename = f"<script_{script_id}>"
        module = types.ModuleType(f"<lbe_script_{script_id}>")
        module.__dict__["__builtins__"] = __builtins__
        module.__dict__["kernel"] = self

        cached_script = self._script_cache.get(script_id)
        if cached_script is not None and cached_script[0] == code:
            code_obj = cached_script[1]
            dependencies = cached_script[2]
        else:
            try:
                transformed_code, dependencies = ReferencePreprocessor.preprocess(code, filename=filename)
                code_obj = compile(transformed_code, filename, "exec")
                self._script_cache[script_id] = (code, code_obj, dependencies)
            except Error as err:
                logger.trace("Failed to bind script module references", channel="scripts", error=err, entity_id=script_id)
                return err
            except Exception as ex:
                err = Error(
                    message="Script module compilation error",
                    description=f"Script {script_id} failed to compile or execute: {ex}",
                    data={"script_id": script_id, "error": str(ex)},
                    code=InvalidResourceDataError,
                )
                logger.trace("Failed to compile script module", channel="scripts", error=err, entity_id=script_id)
                return err

        for res_type, storage_id_hex in dependencies:
            var_name = f"_{res_type}_{storage_id_hex}"
            proxy = self.resolve_proxy(res_type, storage_id_hex)
            if isinstance(proxy, Error):
                return proxy
            module.__dict__[var_name] = proxy

        try:
            exec(code_obj, module.__dict__)
        except Error as err:
            logger.trace("Failed to execute script module", channel="scripts", error=err, entity_id=script_id)
            return err
        except Exception as ex:
            err = Error(
                message="Script module compilation error",
                description=f"Script {script_id} failed to compile or execute: {ex}",
                data={"script_id": script_id, "error": str(ex)},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to compile script module", channel="scripts", error=err, entity_id=script_id)
            return err

        try:
            s_data["symbols"] = extract_script_symbols(code)
        except Exception:
            pass

        if file_mtime is not None:
            self._script_mtime_cache[script_id] = file_mtime
            self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != script_id}

        self._script_module_cache[script_id] = (code, module.__dict__)
        return module.__dict__

    def get_script_callable(self, script_id: RuntimeID, func_name: str) -> Callable | None | Error:
        """Retrieve a callable function from a script resource by function name."""
        mod_globals = self.get_script_module(script_id)
        if isinstance(mod_globals, Error):
            return mod_globals
        func = mod_globals.get(func_name)
        if callable(func):
            return func
        return None

    def attach_script(self, entity_id: RuntimeID, script_id: RuntimeID | StorageID | str) -> None | Error:
        """Attach a script resource to an Entity, storing its canonical StorageID hex."""
        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to attach script: entity not found", channel="entities", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
        if res.get("type") != Entity:
            err = Error(
                message="Resource is not an entity",
                description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
                data={"entity_id": entity_id, "type": res.get("type")},
                code=EntityTypeMismatchError,
            )
            logger.trace("Failed to attach script: not an entity", channel="entities", error=err, entity_id=entity_id)
            return err

        resolved = self._resolve_script_id(script_id)
        if isinstance(resolved, Error):
            return resolved
        _, sid_hex, script_rid = resolved

        script_res = self.resources.get(script_rid)
        if not script_res or script_res.get("type") != Script:
            err = Error(
                message="Resource is not a script",
                description=f"Resource {script_rid} has type {script_res.get('type') if script_res else None}, expected Script ({Script})!",
                data={"script_id": script_id, "resolved_id": script_rid},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to attach script: target is not a script", channel="entities", error=err, entity_id=entity_id)
            return err

        scripts = res.setdefault("data", {}).setdefault("scripts", [])
        if sid_hex not in scripts:
            before = copy.deepcopy(scripts)
            scripts.append(sid_hex)
            self.dirty_runtime_ids.add(entity_id)
            logger.trace(
                f"Attached script '{sid_hex[:8]}...' to Entity {entity_id}",
                channel="entities",
                entity_id=entity_id,
                action="attach_script",
                before=before,
                after=copy.deepcopy(scripts),
                data={"script_storage_id": sid_hex},
            )
        return None

    def detach_script(self, entity_id: RuntimeID, script_id: RuntimeID | StorageID | str) -> None | Error:
        """Detach a script from an Entity."""
        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to detach script: entity not found", channel="entities", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
        if res.get("type") != Entity:
            err = Error(
                message="Resource is not an entity",
                description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
                data={"entity_id": entity_id, "type": res.get("type")},
                code=EntityTypeMismatchError,
            )
            logger.trace("Failed to detach script: not an entity", channel="entities", error=err, entity_id=entity_id)
            return err

        resolved = self._resolve_script_id(script_id)
        if isinstance(resolved, Error):
            sid_hex = script_id if isinstance(script_id, str) else None
            if not sid_hex:
                return resolved
        else:
            _, sid_hex, _ = resolved

        scripts = res.get("data", {}).get("scripts", [])
        if sid_hex in scripts:
            before = copy.deepcopy(scripts)
            scripts.remove(sid_hex)
            self.dirty_runtime_ids.add(entity_id)
            logger.trace(
                f"Detached script '{sid_hex[:8]}...' from Entity {entity_id}",
                channel="entities",
                entity_id=entity_id,
                action="detach_script",
                before=before,
                after=copy.deepcopy(scripts),
                data={"script_storage_id": sid_hex},
            )
        return None

    def get_entity_scripts(self, entity_id: RuntimeID) -> list[RuntimeID]:
        """Get RuntimeIDs of all scripts attached to an Entity."""
        if entity_id not in self.resources:
            return []

        res = self.resources[entity_id]
        if res.get("type") != Entity:
            return []

        script_hexes = res.get("data", {}).get("scripts", [])
        runtime_ids: list[RuntimeID] = []
        for sid_hex in script_hexes:
            try:
                sid = bytes.fromhex(sid_hex)
            except (ValueError, TypeError):
                continue
            rid = self.get_resource_id(sid)
            if isinstance(rid, Error):
                rid = self.load_resource(sid)
                if isinstance(rid, Error):
                    continue
            runtime_ids.append(rid)
        return runtime_ids

    def run_entity_scripts(
        self,
        entity_id: RuntimeID,
        dt: float = 0.0,
        method_name: str = "update",
    ) -> None | Error:
        """Execute all scripts attached to an Entity with self context."""
        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to run entity scripts: entity not found", channel="entities", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
        if res.get("type") != Entity:
            err = Error(
                message="Resource is not an entity",
                description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
                data={"entity_id": entity_id, "type": res.get("type")},
                code=EntityTypeMismatchError,
            )
            logger.trace("Failed to run entity scripts: not an entity", channel="entities", error=err, entity_id=entity_id)
            return err

        entity_proxy = self.get_entity_proxy(entity_id)
        if isinstance(entity_proxy, Error):
            return entity_proxy

        script_rids = self.get_entity_scripts(entity_id)
        for s_rid in script_rids:
            s_res = self.get_resource(s_rid)
            if isinstance(s_res, Error) or not isinstance(s_res, dict):
                continue

            s_data = s_res.get("data", {})
            requires = s_data.get("requires", [])
            for req_comp in requires:
                if not entity_proxy.has(req_comp):
                    err = Error(
                        message="Missing component requirement",
                        description=f"Entity {entity_id} missing required component '{req_comp}' for script '{s_res.get('name', s_rid)}'!",
                        data={"entity_id": entity_id, "required_component": req_comp, "script_id": s_rid},
                        code=MissingComponentRequirementError,
                    )
                    logger.trace(f"Script run failed: missing component requirement '{req_comp}'", channel="entities", error=err, entity_id=entity_id)
                    return err

            mod_globals = self.get_script_module(s_rid)
            if isinstance(mod_globals, Error):
                return mod_globals

            func = mod_globals.get(method_name)
            if callable(func):
                sig_key = (s_rid, method_name)
                if sig_key not in self._method_sig_cache:
                    try:
                        import inspect
                        sig = inspect.signature(func)
                        params = list(sig.parameters.values())
                        param_count = len(params)
                        first_param_name = params[0].name if params else ""
                        self._method_sig_cache[sig_key] = (param_count, first_param_name)
                    except Exception:
                        self._method_sig_cache[sig_key] = (1, "dt")
                param_count, first_param_name = self._method_sig_cache[sig_key]

                mod_globals["self"] = entity_proxy
                mod_globals["dt"] = dt

                try:
                    if param_count >= 2:
                        func(entity_proxy, dt)
                    elif param_count == 1:
                        if first_param_name in ("self", "entity", "target", "e", "proxy"):
                            func(entity_proxy)
                        else:
                            func(dt)
                    else:
                        func()
                except Exception as ex:
                    err = Error(
                        message="Script method execution error",
                        description=f"Script '{s_res.get('name', s_rid)}' method '{method_name}' raised an error: {ex}",
                        data={"entity_id": entity_id, "script_id": s_rid, "method": method_name, "error": str(ex)},
                        code=InvalidResourceDataError,
                    )
                    logger.trace(f"Script method '{method_name}' failed", channel="entities", error=err, entity_id=entity_id)
                    return err
        return None

    def tick(self, dt: float = 0.0) -> None | list[Error]:
        """Iterate over all active entities with attached scripts and run update(dt)."""
        errors: list[Error] = []
        for entity_id in list(self.resources.keys()):
            if self.is_entity(entity_id):
                scripts = self.resources[entity_id].get("data", {}).get("scripts", [])
                if scripts:
                    err = self.run_entity_scripts(entity_id, dt=dt, method_name="update")
                    if isinstance(err, Error):
                        errors.append(err)
        return errors if errors else None

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
        if not isinstance(component_type, str):
            err = Error(
                message="Invalid UI component type",
                description=f"UI component type must be a string, got {type(component_type).__name__} instead!",
                data={"component_type": component_type},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to create UI entity: invalid component type type", channel="ui", error=err)
            return err

        canonical_type = UI_COMPONENT_ALIASES.get(component_type.lower())
        if canonical_type is None:
            err = Error(
                message="Invalid UI component type",
                description=f"Unknown UI component type '{component_type}'",
                data={"component_type": component_type},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to create UI entity: unknown component type", channel="ui", error=err)
            return err

        props = copy.deepcopy(UI_SCHEMAS[canonical_type])
        if component_props is not None:
            if not isinstance(component_props, dict):
                err = Error(
                    message="Invalid UI component props",
                    description=f"Component props must be a dictionary, got {type(component_props).__name__} instead!",
                    data={"component_props": component_props},
                    code=InvalidResourceDataError,
                )
                logger.trace("Failed to create UI entity: invalid props", channel="ui", error=err)
                return err
            props.update(component_props)

        val_err = Validate.ui_component(canonical_type, props)
        if isinstance(val_err, Error):
            return val_err

        return self.create_entity(
            components={canonical_type: props},
            name=name,
            parent_id=parent_id,
            storage_id=storage_id,
            immediate_save=immediate_save,
        )

    def trigger_ui_event(
        self,
        entity_id: RuntimeID | Any,
        event_name: str = "on_click",
        *args: Any,
        **kwargs: Any,
    ) -> Any | Error:
        """Trigger a UI event handler on an Entity."""
        if hasattr(entity_id, "id"):
            entity_id = entity_id.id
        if entity_id not in self.resources:
            err = Error(
                message="Entity not found",
                description=f"RuntimeID {entity_id} was not found in memory!",
                data={"entity_id": entity_id},
                code=RuntimeIDNotFoundOnMemoryError,
            )
            logger.trace("Failed to trigger UI event: entity not found", channel="ui", error=err, entity_id=entity_id)
            return err

        res = self.resources[entity_id]
        if res.get("type") != Entity:
            err = Error(
                message="Resource is not an entity",
                description=f"RuntimeID {entity_id} has type {res.get('type')}, expected Entity ({Entity})!",
                data={"entity_id": entity_id, "type": res.get("type")},
                code=EntityTypeMismatchError,
            )
            logger.trace("Failed to trigger UI event: not an entity", channel="ui", error=err, entity_id=entity_id)
            return err

        components = res.get("data", {}).get("components", {})
        if not isinstance(components, dict):
            return None

        handler_ref = None
        target_keys = (event_name, f"on_{event_name}" if not event_name.startswith("on_") else event_name)
        found_key = False
        for comp in components.values():
            if isinstance(comp, dict):
                for k in target_keys:
                    if k in comp:
                        found_key = True
                        val = comp[k]
                        if val:
                            handler_ref = val
                            break
                        elif handler_ref is None:
                            handler_ref = val
                if handler_ref and isinstance(handler_ref, str) and handler_ref.strip():
                    break

        if not found_key or handler_ref is None:
            return None

        if isinstance(handler_ref, str) and not handler_ref.strip():
            return None

        if not isinstance(handler_ref, str):
            err = Error(
                message="Invalid UI event handler reference",
                description=f"Handler attribute '{event_name}' must be a string, got {type(handler_ref).__name__} instead!",
                data={"entity_id": entity_id, "event_name": event_name, "handler_ref": handler_ref},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to trigger UI event: handler reference not a string", channel="ui", error=err, entity_id=entity_id)
            return err

        match = UI_EVENT_HANDLER_REGEX.match(handler_ref.strip())
        if not match:
            err = Error(
                message="Invalid UI event handler reference",
                description=f"Handler reference '{handler_ref}' does not match expected pattern '<|1|<storage_id>|>.<function_name>'",
                data={"entity_id": entity_id, "event_name": event_name, "handler_ref": handler_ref},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to trigger UI event: invalid reference format", channel="ui", error=err, entity_id=entity_id)
            return err

        sid_hex = match.group("sid")
        fn_name = match.group("fn")

        script_proxy = self.resolve_proxy(Script, sid_hex)
        if isinstance(script_proxy, Error):
            return script_proxy

        try:
            func = getattr(script_proxy, fn_name)
        except AttributeError as ex:
            err = Error(
                message="UI event handler failed",
                description=f"Function '{fn_name}' not found on script proxy: {ex}",
                data={"entity_id": entity_id, "handler_ref": handler_ref, "error": str(ex)},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to trigger UI event: function not found", channel="ui", error=err, entity_id=entity_id)
            return err
        except Exception as ex:
            err = Error(
                message="UI event handler failed",
                description=str(ex),
                data={"entity_id": entity_id, "handler_ref": handler_ref, "error": str(ex)},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to trigger UI event: error resolving function", channel="ui", error=err, entity_id=entity_id)
            return err

        if not callable(func):
            err = Error(
                message="UI event handler failed",
                description=f"Attribute '{fn_name}' on script proxy is not callable",
                data={"entity_id": entity_id, "handler_ref": handler_ref},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to trigger UI event: attribute not callable", channel="ui", error=err, entity_id=entity_id)
            return err

        entity_proxy = self.get_entity_proxy(entity_id)
        if isinstance(entity_proxy, Error):
            return entity_proxy

        pass_entity = True
        try:
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            if len(params) == 0:
                pass_entity = False
            else:
                has_pos = any(
                    p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                    for p in params
                )
                if not has_pos:
                    pass_entity = False
        except (ValueError, TypeError):
            pass_entity = True

        try:
            if pass_entity:
                try:
                    return func(entity_proxy, *args, **kwargs)
                except TypeError as ex:
                    if ex.__traceback__ and ex.__traceback__.tb_next is None:
                        return func(*args, **kwargs)
                    raise
            else:
                return func(*args, **kwargs)
        except Exception as ex:
            err = Error(
                message="UI event handler failed",
                description=str(ex),
                data={"entity_id": entity_id, "event_name": event_name, "error": str(ex)},
                code=InvalidResourceDataError,
            )
            logger.trace("Failed to trigger UI event: execution raised exception", channel="ui", error=err, entity_id=entity_id)
            return err


