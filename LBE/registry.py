"""Runtime identity and resource access.

These functions operate on the Kernel's authoritative state.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any
import copy

from .logger import logger
from .views import _make_readonly_view
from .types import (
    StorageID,
    RuntimeID,
    Error,
    StorageIDNotFoundOnMemoryError,
    RuntimeIDNotFoundOnMemoryError,
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


def _unpack_handle(self, runtime_id: RuntimeID) -> tuple[int, int]:
    """Unpack a RuntimeID handle into (slot_index, generation)."""
    if not isinstance(runtime_id, int) or runtime_id < 0:
        return (-1, -1)
    if runtime_id < (1 << 32):
        return (runtime_id, self._slot_generations.get(runtime_id, 1))
    return (runtime_id & 0xFFFFFFFF, runtime_id >> 32)


def is_valid_runtime_id(self, runtime_id: RuntimeID) -> bool:
    """Check if a runtime handle is alive and matches the current slot generation."""
    slot, gen = self._unpack_handle(runtime_id)
    if slot < 0:
        return False
    return slot in self._active_slots and self._slot_generations.get(slot) == gen


def _resolve_handle(self, runtime_id: RuntimeID) -> RuntimeID:
    """Resolve a potentially plain slot index to its active packed handle."""
    if isinstance(runtime_id, int) and 0 <= runtime_id < (1 << 32):
        gen = self._slot_generations.get(runtime_id, 1)
        packed = (gen << 32) | runtime_id
        if packed in self.resources:
            return packed
    return runtime_id


def get_storage_id(self, runtime_id: RuntimeID) -> StorageID | Error:
    """Get the Storage ID corresponding to the given Resource ID only if it has been loaded."""
    if not self.is_valid_runtime_id(runtime_id):
        err = Error(
            message="Resource not found",
            description=f"Runtime ID {runtime_id} is invalid or stale (referencing a deleted resource)!",
            data={"resource_storage_ids": self.resource_storage_ids, "runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to resolve RuntimeID to StorageID: invalid or stale", channel="storage", error=err, entity_id=runtime_id)
        return err
    resolved_id = self._resolve_handle(runtime_id)
    if resolved_id not in self.resource_storage_ids:
        err = Error(
            message="Resource not found",
            description=f"Resource with runtime ID {runtime_id} not found on memory!",
            data={"resource_storage_ids": self.resource_storage_ids, "runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to resolve RuntimeID to StorageID", channel="storage", error=err, entity_id=runtime_id)
        return err
    sid = self.resource_storage_ids[resolved_id]
    logger.trace(
        f"Resolved RuntimeID {runtime_id} to StorageID 0x{sid.hex()[:8]}...",
        channel="storage",
        entity_id=runtime_id,
        data={"runtime_id": runtime_id, "storage_id": sid.hex()},
    )
    return sid


def get_resource(self, runtime_id: RuntimeID) -> MappingProxyType | Error:
    """Get the loaded resource data for a given Runtime ID as a read-only view."""
    if not self.is_valid_runtime_id(runtime_id):
        err = Error(
            message="Resource not found",
            description=f"Runtime ID {runtime_id} is invalid or stale (referencing a deleted resource)!",
            data={"resources": self.resources, "runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get resource from memory: invalid or stale", channel="resources", error=err, entity_id=runtime_id)
        return err
    resolved_id = self._resolve_handle(runtime_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Resource not found",
            description=f"Resource with runtime ID {runtime_id} not found on memory!",
            data={"resources": self.resources, "runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to get resource from memory", channel="resources", error=err, entity_id=runtime_id)
    return _make_readonly_view(self.resources[resolved_id])


def mutate_resource(self, runtime_id: RuntimeID, new_data: dict[str, Any]) -> None | Error:
    """Update a resource's payload in memory and trace the before/after mutation."""
    if not self.is_valid_runtime_id(runtime_id):
        err = Error(
            message="Resource not found",
            description=f"Cannot mutate: Runtime ID {runtime_id} is invalid or stale (referencing a deleted resource)!",
            data={"runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Resource mutation failed: invalid or stale", channel="resources", error=err, entity_id=runtime_id)
        return err
    resolved_id = self._resolve_handle(runtime_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Resource not found",
            description=f"Cannot mutate: Runtime ID {runtime_id} not found in memory!",
            data={"runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Resource mutation failed: not in memory", channel="resources", error=err, entity_id=runtime_id)
        return err

    before_state = copy.deepcopy(self.resources[resolved_id].get("data"))
    self.resources[resolved_id]["data"] = new_data
    self.dirty_runtime_ids.add(resolved_id)
    self._script_cache.pop(resolved_id, None)
    self._script_module_cache.pop(resolved_id, None)
    self._script_mtime_cache.pop(resolved_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != resolved_id}

    logger.trace(
        f"Resource {resolved_id} mutated in memory",
        channel="resources",
        entity_id=resolved_id,
        action="mutated",
        before=before_state,
        after=copy.deepcopy(new_data),
    )
    return None


def get_fresh_runtime_id(self) -> RuntimeID:
    """Get the fresh runtime ID packed with generation counter."""
    if len(self.stale_runtime_ids) > 0:
        slot = self.stale_runtime_ids.pop()
        gen = self._slot_generations.get(slot, 1)
        logger.trace(f"Recycled stale slot {slot} (gen={gen})", channel="allocation", entity_id=slot)
    else:
        slot = self.runtime_idx
        self.runtime_idx += 1
        gen = 1
        self._slot_generations[slot] = gen
        logger.trace(f"Allocated fresh slot {slot} (gen={gen})", channel="allocation", entity_id=slot)

    self._active_slots.add(slot)
    handle = (gen << 32) | slot
    return handle


def delete_resource(self, runtime_id: RuntimeID) -> bool | Error:
    """Delete a resource from memory, advancing its slot generation so existing handles become invalid."""
    if not self.is_valid_runtime_id(runtime_id):
        err = Error(
            message="Resource not found",
            description=f"Runtime ID {runtime_id} is invalid or stale (referencing a deleted resource)!",
            data={"runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to delete resource: invalid or stale", channel="resources", error=err, entity_id=runtime_id)
        return err

    resolved_id = self._resolve_handle(runtime_id)
    slot, gen = self._unpack_handle(resolved_id)
    self._active_slots.discard(slot)
    self._slot_generations[slot] = gen + 1
    self.stale_runtime_ids.append(slot)

    self.resources.pop(resolved_id, None)
    self.dirty_runtime_ids.discard(resolved_id)
    storage_id = self.resource_storage_ids.pop(resolved_id, None)
    if storage_id is not None:
        self.resource_runtime_ids.pop(storage_id, None)

    self._script_cache.pop(resolved_id, None)
    self._script_module_cache.pop(resolved_id, None)
    self._script_mtime_cache.pop(resolved_id, None)
    self._last_good_script_modules.pop(resolved_id, None)
    self._script_reload_errors.pop(resolved_id, None)
    self._script_failed_sources.pop(resolved_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != resolved_id}

    logger.trace(
        f"Deleted resource {resolved_id} (slot={slot}, next_gen={gen + 1})",
        channel="resources",
        entity_id=resolved_id,
        action="deleted",
    )
    return True


def is_dirty(self, runtime_id: RuntimeID) -> bool:
    """Check if a runtime ID has unpersisted changes in memory."""
    if not self.is_valid_runtime_id(runtime_id):
        return False
    resolved_id = self._resolve_handle(runtime_id)
    return resolved_id in self.dirty_runtime_ids


def mark_dirty(self, runtime_id: RuntimeID) -> None | Error:
    """Mark a resource as dirty so it will be saved on next flush."""
    if not self.is_valid_runtime_id(runtime_id):
        err = Error(
            message="Resource not found",
            description=f"Runtime ID {runtime_id} is invalid or stale (referencing a deleted resource)!",
            data={"runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to mark resource dirty: invalid or stale", channel="storage", error=err, entity_id=runtime_id)
        return err
    resolved_id = self._resolve_handle(runtime_id)
    if resolved_id not in self.resources:
        err = Error(
            message="Resource not found",
            description=f"Resource with runtime ID {runtime_id} not found on memory!",
            data={"runtime_id": runtime_id},
            code=RuntimeIDNotFoundOnMemoryError,
        )
        logger.trace("Failed to mark resource dirty: not in memory", channel="storage", error=err, entity_id=runtime_id)
        return err
    self.dirty_runtime_ids.add(resolved_id)
    self._script_cache.pop(resolved_id, None)
    self._script_module_cache.pop(resolved_id, None)
    self._script_mtime_cache.pop(resolved_id, None)
    self._method_sig_cache = {k: v for k, v in self._method_sig_cache.items() if k[0] != resolved_id}
    logger.trace(f"Resource {resolved_id} marked dirty", channel="storage", entity_id=resolved_id, action="marked_dirty")
    return None

