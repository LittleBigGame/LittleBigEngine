"""Comprehensive verification tests for Transactional Graph Operations & Single Hierarchy Authority.

Tests derive from observable engine and editor contracts:
1. Single Canonical Hierarchy Authority:
   - Synchronization of envelope 'children' and data['children'] across all mutations.
   - Atomic linking on create_entity(parent_id=...).
   - Idempotent reparenting (add_entity_child no-ops on existing parent).
   - Cycle prevention and rollback for direct, deep, and self-parenting loops.
   - Multi-level reparenting with bi-directional link and dirty-cache updates.
2. Transactional Subtree Deletion (delete_entity):
   - Detachment of deleted root from parent.
   - Recursive cascade deletion of all descendants.
   - Generation advancement invalidating stale handles and proxies.
   - Negative tests: stale handle, non-entity type mismatch.
3. Transaction Context Manager (kernel.transaction):
   - Clean commit of created and modified entities.
   - Rollback of newly created entities and restored state on exception.
   - Sequential transaction isolation.
4. Atomic Disk Persistence:
   - Write-to-temp and atomic replace semantics.
   - Clean disk state with zero orphan .tmp files.
   - Rollback and temp cleanup on simulated disk write or replace failures.
5. Editor Session Subtree Deletion:
   - In-memory deletion delegation with selection clearing and event dispatch.
   - Cascade disk file deletion with delete_from_disk=True.
   - Preservation of unrelated project files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from editor import EditorSession
from LBE import Error, Kernel
from LBE.types import (
    EntityTypeMismatchError,
    FailedToSaveResourceOnDiskError,
    InvalidResourceDataError,
    RuntimeIDNotFoundOnMemoryError,
)


class TestHierarchySingleAuthority:
    """Verifies res['children'] and res['data']['children'] maintain strict synchronization."""

    def test_hierarchy_sync_on_create_entity_with_parent(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        parent_id = kernel.create_entity(name="ParentNode")
        assert not isinstance(parent_id, Error)
        parent_sid = kernel.get_storage_id(parent_id)
        assert not isinstance(parent_sid, Error)

        child_id = kernel.create_entity(name="ChildNode", parent_id=parent_id)
        assert not isinstance(child_id, Error)
        child_sid = kernel.get_storage_id(child_id)
        assert not isinstance(child_sid, Error)

        parent_env = kernel.resources[kernel._resolve_handle(parent_id)]
        child_env = kernel.resources[kernel._resolve_handle(child_id)]

        # Verify envelope and data children match exactly
        assert parent_env["children"] == [child_sid.hex()]
        assert parent_env["data"]["children"] == [child_sid.hex()]
        assert parent_env["children"] == parent_env["data"]["children"]

        # Verify child parent reference
        assert child_env["data"]["parent"] == parent_sid.hex()

        # Verify kernel navigation helpers
        assert kernel.get_entity_children(parent_id) == [child_id]
        assert kernel.get_entity_parent(child_id) == parent_id

        # Add second child with parent_id
        child2_id = kernel.create_entity(name="ChildNode2", parent_id=parent_id)
        assert not isinstance(child2_id, Error)
        child2_sid = kernel.get_storage_id(child2_id)
        assert not isinstance(child2_sid, Error)

        assert parent_env["children"] == [child_sid.hex(), child2_sid.hex()]
        assert parent_env["data"]["children"] == [child_sid.hex(), child2_sid.hex()]
        assert parent_env["children"] == parent_env["data"]["children"]

    def test_hierarchy_sync_on_add_entity_child(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        root_id = kernel.create_entity(name="RootNode")
        child1_id = kernel.create_entity(name="Child1")
        child2_id = kernel.create_entity(name="Child2")

        root_sid = kernel.get_storage_id(root_id)
        c1_sid = kernel.get_storage_id(child1_id)
        c2_sid = kernel.get_storage_id(child2_id)

        # Attach child 1
        res1 = kernel.add_entity_child(root_id, child1_id)
        assert res1 is None

        root_env = kernel.resources[kernel._resolve_handle(root_id)]
        c1_env = kernel.resources[kernel._resolve_handle(child1_id)]
        assert root_env["children"] == [c1_sid.hex()]
        assert root_env["data"]["children"] == [c1_sid.hex()]
        assert c1_env["data"]["parent"] == root_sid.hex()

        # Attach child 2
        res2 = kernel.add_entity_child(root_id, child2_id)
        assert res2 is None

        c2_env = kernel.resources[kernel._resolve_handle(child2_id)]
        assert root_env["children"] == [c1_sid.hex(), c2_sid.hex()]
        assert root_env["data"]["children"] == [c1_sid.hex(), c2_sid.hex()]
        assert c2_env["data"]["parent"] == root_sid.hex()

    def test_hierarchy_sync_on_remove_entity_child(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        root_id = kernel.create_entity(name="RootNode")
        child1_id = kernel.create_entity(name="Child1", parent_id=root_id)
        child2_id = kernel.create_entity(name="Child2", parent_id=root_id)

        c1_sid = kernel.get_storage_id(child1_id)
        c2_sid = kernel.get_storage_id(child2_id)

        root_env = kernel.resources[kernel._resolve_handle(root_id)]
        c1_env = kernel.resources[kernel._resolve_handle(child1_id)]
        c2_env = kernel.resources[kernel._resolve_handle(child2_id)]

        # Remove child 1
        rem_res1 = kernel.remove_entity_child(root_id, child1_id)
        assert rem_res1 is None

        assert root_env["children"] == [c2_sid.hex()]
        assert root_env["data"]["children"] == [c2_sid.hex()]
        assert c1_sid.hex() not in root_env["children"]
        assert c1_env["data"]["parent"] is None
        assert kernel.get_entity_parent(child1_id) is None

        # Remove child 2
        rem_res2 = kernel.remove_entity_child(root_id, child2_id)
        assert rem_res2 is None

        assert root_env["children"] == []
        assert root_env["data"]["children"] == []
        assert c2_env["data"]["parent"] is None
        assert kernel.get_entity_parent(child2_id) is None

    def test_hierarchy_sync_persists_across_disk_save_and_reload(self, tmp_path: Path):
        kernel1 = Kernel(tmp_path)
        root_id = kernel1.create_entity(name="Root")
        branch_id = kernel1.create_entity(name="Branch", parent_id=root_id)
        leaf_id = kernel1.create_entity(name="Leaf", parent_id=branch_id)

        root_sid = kernel1.get_storage_id(root_id)
        branch_sid = kernel1.get_storage_id(branch_id)
        leaf_sid = kernel1.get_storage_id(leaf_id)

        assert kernel1.save_dirty_resources() is None

        kernel2 = Kernel(tmp_path)
        loaded_root = kernel2.load_resource(root_sid, load_children=-1)
        assert not isinstance(loaded_root, Error)

        root_res = kernel2.resources[kernel2._resolve_handle(loaded_root)]
        branch_rid = kernel2.resource_runtime_ids[branch_sid]
        branch_res = kernel2.resources[kernel2._resolve_handle(branch_rid)]
        leaf_rid = kernel2.resource_runtime_ids[leaf_sid]
        leaf_res = kernel2.resources[kernel2._resolve_handle(leaf_rid)]

        # All loaded entities must have synchronized hierarchy authority
        assert root_res["children"] == [branch_sid.hex()]
        assert root_res["data"]["children"] == [branch_sid.hex()]
        assert branch_res["children"] == [leaf_sid.hex()]
        assert branch_res["data"]["children"] == [leaf_sid.hex()]
        assert leaf_res["children"] == []
        assert leaf_res["data"]["children"] == []
        assert branch_res["data"]["parent"] == root_sid.hex()
        assert leaf_res["data"]["parent"] == branch_sid.hex()


class TestReparentingAndCyclePrevention:
    """Verifies reparenting contracts, idempotency, and strict cycle prevention."""

    def test_idempotent_reparenting_no_duplicates(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        parent_id = kernel.create_entity(name="Parent")
        child_id = kernel.create_entity(name="Child", parent_id=parent_id)

        c_sid = kernel.get_storage_id(child_id)
        p_env = kernel.resources[kernel._resolve_handle(parent_id)]

        # Calling add_entity_child when parent is already parent of child must return None
        res = kernel.add_entity_child(parent_id, child_id)
        assert res is None

        # Must not produce duplicate entries
        assert p_env["children"] == [c_sid.hex()]
        assert p_env["data"]["children"] == [c_sid.hex()]
        assert len(p_env["children"]) == 1
        assert len(p_env["data"]["children"]) == 1

    def test_cycle_prevention_direct_parent_child(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        a_id = kernel.create_entity(name="NodeA")
        b_id = kernel.create_entity(name="NodeB", parent_id=a_id)

        a_sid = kernel.get_storage_id(a_id)
        b_sid = kernel.get_storage_id(b_id)

        # Attempt to make A a child of B (which creates cycle B -> A -> B)
        err = kernel.add_entity_child(b_id, a_id)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

        # State must remain unchanged
        a_env = kernel.resources[kernel._resolve_handle(a_id)]
        b_env = kernel.resources[kernel._resolve_handle(b_id)]

        assert a_env["children"] == [b_sid.hex()]
        assert a_env["data"]["children"] == [b_sid.hex()]
        assert a_env["data"]["parent"] is None

        assert b_env["children"] == []
        assert b_env["data"]["children"] == []
        assert b_env["data"]["parent"] == a_sid.hex()

    def test_cycle_prevention_self_parenting(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        a_id = kernel.create_entity(name="SelfNode")

        # Attempt to parent A to itself
        err = kernel.add_entity_child(a_id, a_id)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

        a_env = kernel.resources[kernel._resolve_handle(a_id)]
        assert a_env["children"] == []
        assert a_env["data"]["children"] == []
        assert a_env["data"]["parent"] is None

    def test_cycle_prevention_deep_ancestor(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        a_id = kernel.create_entity(name="A")
        b_id = kernel.create_entity(name="B", parent_id=a_id)
        c_id = kernel.create_entity(name="C", parent_id=b_id)
        d_id = kernel.create_entity(name="D", parent_id=c_id)

        # Attempt to parent A to D (D -> A cycle across 4 levels)
        err = kernel.add_entity_child(d_id, a_id)
        assert isinstance(err, Error)
        assert err.code == InvalidResourceDataError

        # Hierarchy should remain A -> B -> C -> D
        assert kernel.get_entity_children(a_id) == [b_id]
        assert kernel.get_entity_children(b_id) == [c_id]
        assert kernel.get_entity_children(c_id) == [d_id]
        assert kernel.get_entity_children(d_id) == []
        assert kernel.get_entity_parent(a_id) is None
        assert kernel.get_entity_parent(d_id) == c_id

    def test_multi_level_reparenting(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        a_id = kernel.create_entity(name="ParentA")
        b_id = kernel.create_entity(name="ParentB")
        c_id = kernel.create_entity(name="ChildC", parent_id=a_id)

        a_sid = kernel.get_storage_id(a_id)
        b_sid = kernel.get_storage_id(b_id)
        c_sid = kernel.get_storage_id(c_id)

        kernel.dirty_runtime_ids.clear()

        # Reparent C from A to B
        reparent_res = kernel.add_entity_child(b_id, c_id)
        assert reparent_res is None

        a_env = kernel.resources[kernel._resolve_handle(a_id)]
        b_env = kernel.resources[kernel._resolve_handle(b_id)]
        c_env = kernel.resources[kernel._resolve_handle(c_id)]

        # A does not contain C
        assert c_sid.hex() not in a_env["children"]
        assert c_sid.hex() not in a_env["data"]["children"]

        # B contains C
        assert c_sid.hex() in b_env["children"]
        assert c_sid.hex() in b_env["data"]["children"]

        # C's parent is B
        assert c_env["data"]["parent"] == b_sid.hex()
        assert c_env["data"]["parent"] != a_sid.hex()
        assert kernel.get_entity_parent(c_id) == b_id

        # A, B, and C must be marked dirty
        assert kernel._resolve_handle(a_id) in kernel.dirty_runtime_ids
        assert kernel._resolve_handle(b_id) in kernel.dirty_runtime_ids
        assert kernel._resolve_handle(c_id) in kernel.dirty_runtime_ids


class TestCascadeSubtreeDeletion:
    """Verifies kernel.delete_entity cleans subtrees, detaches parents, and tombstones handles."""

    def test_cascade_subtree_deletion_memory(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        scene_root = kernel.create_entity(name="SceneRoot")
        sub_root = kernel.create_entity(name="SubRoot", parent_id=scene_root)
        child1 = kernel.create_entity(name="Child1", parent_id=sub_root)
        child2 = kernel.create_entity(name="Child2", parent_id=sub_root)
        grandchild = kernel.create_entity(name="Grandchild", parent_id=child1)
        sibling = kernel.create_entity(name="Sibling", parent_id=scene_root)

        sub_root_proxy = kernel.get_entity_proxy(sub_root)
        child1_proxy = kernel.get_entity_proxy(child1)
        grandchild_proxy = kernel.get_entity_proxy(grandchild)
        sibling_proxy = kernel.get_entity_proxy(sibling)

        assert sub_root_proxy.is_alive
        assert child1_proxy.is_alive
        assert grandchild_proxy.is_alive
        assert sibling_proxy.is_alive

        # Delete sub_root: should delete sub_root, child1, child2, grandchild
        del_res = kernel.delete_entity(sub_root)
        assert del_res is True

        # SceneRoot must still be alive and have only Sibling as child
        scene_env = kernel.resources[kernel._resolve_handle(scene_root)]
        sib_sid = kernel.get_storage_id(sibling)
        assert scene_env["children"] == [sib_sid.hex()]
        assert scene_env["data"]["children"] == [sib_sid.hex()]
        assert kernel.get_entity_children(scene_root) == [sibling]

        # Deleted entities must no longer be valid runtime IDs
        assert not kernel.is_valid_runtime_id(sub_root)
        assert not kernel.is_valid_runtime_id(child1)
        assert not kernel.is_valid_runtime_id(child2)
        assert not kernel.is_valid_runtime_id(grandchild)

        # Proxies must report is_alive == False
        assert not sub_root_proxy.is_alive
        assert not child1_proxy.is_alive
        assert not grandchild_proxy.is_alive
        assert sibling_proxy.is_alive

    def test_slot_generation_advancement_on_delete(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        e1 = kernel.create_entity(name="E1", components={"Transform": {"x": 1.0, "y": 2.0}})
        slot1, gen1 = kernel._unpack_handle(e1)

        proxy1 = kernel.get_entity_proxy(e1)
        assert proxy1.is_alive

        assert kernel.delete_entity(e1) is True
        assert not proxy1.is_alive
        assert not kernel.is_valid_runtime_id(e1)

        # Create entity E2 which may recycle slot1
        e2 = kernel.create_entity(name="E2", components={"Transform": {"x": 99.0, "y": 99.0}})
        slot2, gen2 = kernel._unpack_handle(e2)

        if slot2 == slot1:
            assert gen2 > gen1

        # The old handle e1 and old proxy1 must NOT refer to e2
        assert not kernel.is_valid_runtime_id(e1)
        assert not proxy1.is_alive
        with pytest.raises(AttributeError):
            _ = proxy1.Transform

    def test_delete_entity_root_without_parent(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        root = kernel.create_entity(name="StandaloneRoot")
        child = kernel.create_entity(name="Child", parent_id=root)

        assert kernel.delete_entity(root) is True
        assert kernel.resources == {}
        assert not kernel.is_valid_runtime_id(root)
        assert not kernel.is_valid_runtime_id(child)

    def test_delete_entity_invalid_or_stale_handle(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        e = kernel.create_entity(name="Temp")
        assert kernel.delete_entity(e) is True

        # Second deletion should return RuntimeIDNotFoundOnMemoryError
        res = kernel.delete_entity(e)
        assert isinstance(res, Error)
        assert res.code == RuntimeIDNotFoundOnMemoryError

    def test_delete_entity_non_entity_type_error(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        script_id = kernel.create_script_resource(name="MyScript", code="def _fn_run(): pass")
        assert not isinstance(script_id, Error)

        err = kernel.delete_entity(script_id)
        assert isinstance(err, Error)
        assert err.code == EntityTypeMismatchError


class TestKernelTransactionContext:
    """Verifies kernel.transaction context manager for atomicity and rollback on failure."""

    def test_transaction_commits_clean_execution(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        with kernel.transaction():
            p = kernel.create_entity(name="Parent", components={"Transform": {"x": 5.0}})
            c = kernel.create_entity(name="Child", parent_id=p)

        assert kernel.is_valid_runtime_id(p)
        assert kernel.is_valid_runtime_id(c)
        assert kernel.get_entity_children(p) == [c]

    def test_transaction_rolls_back_on_exception(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        initial_e = kernel.create_entity(name="Initial", components={"Transform": {"x": 10.0, "y": 20.0}})
        initial_proxy = kernel.get_entity_proxy(initial_e)
        assert initial_proxy.Transform["x"] == 10.0

        created_inside: list[int] = []

        with pytest.raises(RuntimeError, match="Transaction aborted"):
            with kernel.transaction():
                e1 = kernel.create_entity(name="Inside1")
                created_inside.append(e1)
                kernel.set_component(initial_e, "Transform", {"x": 999.0, "y": 999.0})
                assert initial_proxy.Transform["x"] == 999.0
                e2 = kernel.create_entity(name="Inside2", parent_id=e1)
                created_inside.append(e2)
                raise RuntimeError("Transaction aborted")

        # Entities created inside transaction must be completely removed
        for handle in created_inside:
            assert not kernel.is_valid_runtime_id(handle)
            assert kernel._resolve_handle(handle) not in kernel.resources

        # Initial entity must be restored to its pre-transaction state
        assert kernel.is_valid_runtime_id(initial_e)
        assert initial_proxy.is_alive
        assert initial_proxy.Transform["x"] == 10.0
        assert initial_proxy.Transform["y"] == 20.0
        assert len(kernel.resources) == 1

    def test_transaction_sequential_isolation(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        with kernel.transaction():
            e1 = kernel.create_entity(name="Persistent1")

        assert kernel.is_valid_runtime_id(e1)

        with pytest.raises(ValueError, match="Failed in second transaction"):
            with kernel.transaction():
                e2 = kernel.create_entity(name="RolledBack2")
                raise ValueError("Failed in second transaction")

        assert kernel.is_valid_runtime_id(e1)
        assert not kernel.is_valid_runtime_id(e2)
        assert len(kernel.resources) == 1


class TestAtomicDiskSave:
    """Verifies atomic write-to-temp-then-replace persistence contracts."""

    def test_atomic_save_creates_valid_json_no_tmp_left(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        p = kernel.create_entity(name="Parent", components={"Transform": {"x": 1.0, "y": 2.0}})
        c = kernel.create_entity(name="Child", parent_id=p)

        save_err = kernel.save_dirty_resources()
        assert save_err is None

        # Verify no .tmp files exist
        all_files = list(tmp_path.iterdir())
        tmp_files = [f for f in all_files if f.suffix == ".tmp"]
        resource_json_files = [f for f in all_files if f.suffix == ".json" and f.name != "project.json"]

        assert tmp_files == []
        assert len(resource_json_files) == 2

        # Verify all resource JSON files are valid and contain matching data
        expected_sids = {kernel.get_storage_id(p).hex(), kernel.get_storage_id(c).hex()}
        found_sids = set()
        for jf in resource_json_files:
            found_sids.add(jf.stem)
            data = json.loads(jf.read_text(encoding="utf-8"))
            assert "type" in data
            assert "data" in data
            assert "children" in data
        assert found_sids == expected_sids

    def test_atomic_save_simulated_write_failure_cleans_tmp(self, tmp_path: Path, monkeypatch):
        kernel = Kernel(tmp_path)
        e = kernel.create_entity(name="EntityToFail")
        sid = kernel.get_storage_id(e)

        # Force write failure by monkeypatching open when opening .tmp file
        real_open = open

        def failing_open(path, mode="r", *args, **kwargs):
            if str(path).endswith(".tmp"):
                raise OSError("Disk full simulation")
            return real_open(path, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", failing_open)

        err = kernel.save_resource(e)
        assert isinstance(err, Error)
        assert err.code == FailedToSaveResourceOnDiskError

        # Ensure no orphan .tmp file
        assert not (tmp_path / f"{sid.hex()}.tmp").exists()
        assert not (tmp_path / f"{sid.hex()}.json").exists()

    def test_atomic_save_simulated_replace_failure_cleans_tmp_preserves_original(self, tmp_path: Path, monkeypatch):
        kernel = Kernel(tmp_path)
        e = kernel.create_entity(name="OriginalEntity", components={"Health": {"hp": 100}})
        sid = kernel.get_storage_id(e)

        # Save first successfully
        assert kernel.save_resource(e) is None
        json_path = tmp_path / f"{sid.hex()}.json"
        assert json_path.exists()
        original_json_text = json_path.read_text(encoding="utf-8")

        # Mutate in memory
        kernel.set_component(e, "Health", {"hp": 50})

        # Inject replace failure
        def failing_replace(src, dst):
            raise PermissionError("Simulated locked file replace error")

        monkeypatch.setattr(os, "replace", failing_replace)

        err = kernel.save_resource(e)
        assert isinstance(err, Error)
        assert err.code == FailedToSaveResourceOnDiskError

        # Verify no orphan .tmp remains
        assert not (tmp_path / f"{sid.hex()}.tmp").exists()

        # Verify original .json file content was preserved untouched
        assert json_path.read_text(encoding="utf-8") == original_json_text


class TestSessionTransactionalDelete:
    """Verifies EditorSession.delete_entity integration with selection and disk options."""

    def test_session_delete_entity_clears_selection_within_subtree(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = kernel.create_entity(name="UIRoot")
        child = kernel.create_entity(name="UIChild", parent_id=root)
        grandchild = kernel.create_entity(name="UIGrandchild", parent_id=child)

        # Select grandchild
        session.select_entity(grandchild)
        assert session.selected_entity_id == grandchild

        state_changed_events: list[bool] = []
        selection_changed_events: list[int | None] = []

        unsub_state = session.subscribe_state_changed(lambda: state_changed_events.append(True))
        unsub_sel = session.subscribe_selection_changed(lambda eid: selection_changed_events.append(eid))

        # Delete child (which cascades to grandchild)
        del_res = session.delete_entity(child)
        assert del_res is True

        # Grandchild was selected, so selection must be cleared to None
        assert session.selected_entity_id is None
        assert None in selection_changed_events
        assert len(state_changed_events) > 0

        unsub_state()
        unsub_sel()

        # Memory verification
        assert not kernel.is_valid_runtime_id(child)
        assert not kernel.is_valid_runtime_id(grandchild)
        assert kernel.is_valid_runtime_id(root)

    def test_session_delete_entity_with_delete_from_disk(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = kernel.create_entity(name="RootToDelete")
        child = kernel.create_entity(name="ChildToDelete", parent_id=root)
        root_sid = kernel.get_storage_id(root)
        child_sid = kernel.get_storage_id(child)

        # Save to disk first
        assert kernel.save_dirty_resources() is None
        root_file = tmp_path / f"{root_sid.hex()}.json"
        child_file = tmp_path / f"{child_sid.hex()}.json"
        assert root_file.exists()
        assert child_file.exists()

        # Delete from session with delete_from_disk=True
        del_res = session.delete_entity(root, delete_from_disk=True)
        assert del_res is True

        # Both files must be deleted from disk
        assert not root_file.exists()
        assert not child_file.exists()

    def test_session_delete_entity_delete_from_disk_leaves_unrelated_files(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        tree1 = kernel.create_entity(name="Tree1")
        tree2 = kernel.create_entity(name="Tree2")
        t1_sid = kernel.get_storage_id(tree1)
        t2_sid = kernel.get_storage_id(tree2)

        assert kernel.save_dirty_resources() is None
        t1_file = tmp_path / f"{t1_sid.hex()}.json"
        t2_file = tmp_path / f"{t2_sid.hex()}.json"
        assert t1_file.exists()
        assert t2_file.exists()

        assert session.delete_entity(tree1, delete_from_disk=True) is True

        assert not t1_file.exists()
        assert t2_file.exists()
        assert kernel.is_valid_runtime_id(tree2)

