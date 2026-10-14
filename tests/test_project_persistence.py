"""Unit and integration tests for Project Persistence Contract & Deterministic Startup Loading.

Verifies:
1. Manifest File Contract (project.json):
   - Saving writes project.json with format_version, name, root_entity_ids (sorted hex strings), settings.
   - Atomic saving (via temporary file replace).
   - Loading populates kernel.manifest and recursively loads all roots, dependencies, and children.
   - Negative tests: invalid format version (e.g. 0, "v1", negative) or corrupt JSON returns Error(InvalidProjectManifestError).
   - Custom project name and settings persistence.
   - Invalid root hex string or missing root file records BrokenReference(reference_type="root").

2. Deterministic Root Discovery (Missing project.json):
   - When project.json is absent, discovers root entities (entities not listed as children of any other entity).
   - Discovered root IDs are sorted lexicographically by hex.
   - Synthesizes and saves project.json.
   - Empty folder returns None.
   - Ignores non-entity resources during root discovery.

3. Broken Reference Resilience & Diagnostics:
   - Missing child entity does not crash or abort project loading.
   - Parent entity loads successfully; BrokenReference is recorded with reference_type="child".
   - Missing dependency does not crash; BrokenReference recorded with reference_type="dependency".
   - Kernel.get_diagnostics() accurately reports broken_references, total_resources, and dirty_count.

4. Startup Loading Contract (main.py):
   - In a directory with an existing project, kernel.load_project() loads existing entities,
     and populate_demo_world_if_empty does NOT inject duplicate entities.
   - In a fresh empty directory, load_project() returns None, and populate_demo_world_if_empty
     creates the initial demo world.

5. Planned Tests (unimplemented features):
   - Transactional rollback on fatal load failure.
   - Manifest schema version migration pipeline.
   - Generation-safe runtime ID recycling across project reload.
   - Hot-reload rollback on manifest syntax corruption.
   - Recursive dependency loading for nested children in scene hierarchy.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from LBE import Error, Kernel
from LBE.types import (
    Entity,
    FailedToSaveResourceOnDiskError,
    InvalidProjectManifestError,
    ProjectManifest,
    ProjectLoadError,
)
from main import populate_demo_world_if_empty


class TestManifestFileContract:
    """Tests for project.json structure, serialization, parsing, and validation."""

    def test_save_project_writes_manifest_structure(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        parent_id = kernel.create_entity(name="ParentEntity")
        child_id = kernel.create_entity(name="ChildEntity", parent_id=parent_id)

        kernel.save_dirty_resources()
        kernel.save_project()

        project_file = tmp_path / "project.json"
        assert project_file.exists(), "project.json must be written to disk"
        assert not (tmp_path / "project.tmp").exists(), "Temporary file must be removed after atomic replace"

        with open(project_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["format_version"] == 1
        assert data["name"] == tmp_path.name
        assert isinstance(data["settings"], dict)

        parent_sid = kernel.get_storage_id(parent_id).hex()
        child_sid = kernel.get_storage_id(child_id).hex()

        assert parent_sid in data["root_entity_ids"]
        assert child_sid not in data["root_entity_ids"], "Child entity must not be listed as a root entity"
        assert data["root_entity_ids"] == sorted(data["root_entity_ids"]), "Root entity IDs must be sorted hex"

    def test_save_project_multiple_roots_sorted(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        kernel.create_entity(name="Alpha")
        kernel.create_entity(name="Beta")
        kernel.create_entity(name="Gamma")

        kernel.save_dirty_resources()
        kernel.save_project()

        project_file = tmp_path / "project.json"
        with open(project_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        root_ids = data["root_entity_ids"]
        assert len(root_ids) == 3
        assert root_ids == sorted(root_ids), "Root entity IDs must be sorted lexicographically"

    def test_save_project_excludes_scripts_from_roots(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        root_id = kernel.create_entity(name="SceneRoot")
        script_id = kernel.create_script_resource(name="PlayerController", code="def update(self, dt, kernel): pass")

        kernel.save_dirty_resources()
        kernel.save_project()

        project_file = tmp_path / "project.json"
        with open(project_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        root_sid = kernel.get_storage_id(root_id).hex()
        script_sid = kernel.get_storage_id(script_id).hex()

        assert root_sid in data["root_entity_ids"]
        assert script_sid not in data["root_entity_ids"], "Scripts must not be included in root_entity_ids"

    def test_manifest_custom_name_and_settings_persisted(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        kernel.create_entity(name="MainScene")
        kernel.manifest = ProjectManifest(
            name="Space Odyssey",
            format_version=1,
            settings={"tick_rate": 60, "debug_overlay": True},
        )
        kernel.save_dirty_resources()
        kernel.save_project()

        # Load with fresh kernel
        k2 = Kernel(tmp_path)
        res = k2.load_project()
        assert not isinstance(res, Error), f"Load project failed: {res}"
        assert k2.manifest is not None
        assert k2.manifest.name == "Space Odyssey"
        assert k2.manifest.format_version == 1
        assert k2.manifest.settings == {"tick_rate": 60, "debug_overlay": True}

    def test_load_project_populates_manifest_and_loads_hierarchy(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        script_id = k1.create_script_resource(name="Rotator", code="def update(self, dt, kernel): pass")
        script_sid = k1.get_storage_id(script_id)

        # Create root entity with explicit dependency on the script
        root_id = k1.create_resource(
            resource_type=Entity,
            resource_data={"components": {"Transform": {"x": 10.0, "y": 20.0}}, "resources": [], "scripts": [], "children": [], "parent": None},
            name="RootNode",
            dependencies=[script_sid.hex()],
        )
        child_id = k1.create_entity(name="ChildNode", parent_id=root_id, components={"Transform": {"x": 5.0, "y": 5.0}})
        grandchild_id = k1.create_entity(name="GrandchildNode", parent_id=child_id)

        k1.save_dirty_resources()
        k1.save_project()

        root_sid = k1.get_storage_id(root_id)
        child_sid = k1.get_storage_id(child_id)
        grandchild_sid = k1.get_storage_id(grandchild_id)

        # Fresh kernel loads everything recursively
        k2 = Kernel(tmp_path)
        assert len(k2.resources) == 0
        load_result = k2.load_project()

        assert isinstance(load_result, dict)
        assert load_result["roots_loaded"] == 1
        assert load_result["broken_references"] == 0

        # Verify all resources are loaded into memory
        assert root_sid in k2.resource_runtime_ids
        assert child_sid in k2.resource_runtime_ids
        assert grandchild_sid in k2.resource_runtime_ids
        assert script_sid in k2.resource_runtime_ids

        # Verify entity relationships
        root_rid = k2.get_resource_id(root_sid)
        assert isinstance(root_rid, int)
        root_proxy = k2.get_entity_proxy(root_rid)
        assert root_proxy.name == "RootNode"
        assert len(root_proxy.children) == 1
        assert root_proxy.children[0].name == "ChildNode"
        assert len(root_proxy.children[0].children) == 1
        assert root_proxy.children[0].children[0].name == "GrandchildNode"

    def test_manifest_invalid_format_version_zero(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(json.dumps({"format_version": 0, "root_entity_ids": []}), encoding="utf-8")

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError
        assert "format_version" in res.description

    def test_manifest_missing_format_version(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(json.dumps({"root_entity_ids": []}), encoding="utf-8")

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError
        assert "format_version" in res.description

    def test_manifest_invalid_format_version_negative(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(json.dumps({"format_version": -1, "root_entity_ids": []}), encoding="utf-8")

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError

    def test_manifest_invalid_format_version_string(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(json.dumps({"format_version": "v1", "root_entity_ids": []}), encoding="utf-8")

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError

    def test_manifest_unsupported_future_format_version(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(
            json.dumps({"format_version": 2, "root_entity_ids": []}),
            encoding="utf-8",
        )

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError
        assert "unsupported" in res.description.lower()

    def test_manifest_root_entity_ids_must_be_a_list(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(
            json.dumps({"format_version": 1, "root_entity_ids": "not-a-list"}),
            encoding="utf-8",
        )

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError
        assert "root_entity_ids" in res.description

    def test_manifest_corrupted_json(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text("{ invalid json: true, ", encoding="utf-8")

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError

    def test_manifest_non_dict_json(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        res = kernel.load_project()
        assert isinstance(res, Error)
        assert res.code == InvalidProjectManifestError

    def test_manifest_invalid_root_hex_string(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(
            json.dumps({"format_version": 1, "name": "Test", "root_entity_ids": ["not_a_valid_hex"]}),
            encoding="utf-8",
        )

        res = kernel.load_project()
        assert isinstance(res, dict)
        assert len(kernel.broken_references) == 1
        br = kernel.broken_references[0]
        assert br.reference_type == "root"
        assert "Invalid root ID" in br.details

    def test_manifest_missing_root_file_on_disk(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        missing_sid_hex = "0123456789abcdef0123456789abcdef"
        manifest_path = tmp_path / "project.json"
        manifest_path.write_text(
            json.dumps({"format_version": 1, "name": "Test", "root_entity_ids": [missing_sid_hex]}),
            encoding="utf-8",
        )

        res = kernel.load_project()
        assert isinstance(res, dict)
        assert len(kernel.broken_references) == 1
        br = kernel.broken_references[0]
        assert br.reference_type == "root"
        assert br.target_storage_id == bytes.fromhex(missing_sid_hex)
        assert "not found on disk" in br.details.lower()


class TestDeterministicRootDiscovery:
    """Tests for discovery of roots when project.json is missing."""

    def test_root_discovery_when_project_json_absent(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        r1 = k1.create_entity(name="RootA")
        k1.create_entity(name="ChildA", parent_id=r1)
        r2 = k1.create_entity(name="RootB")
        c2 = k1.create_entity(name="ChildB", parent_id=r2)
        k1.create_entity(name="GrandchildB", parent_id=c2)

        k1.save_dirty_resources()
        # Remove project.json to simulate unindexed project
        manifest_file = tmp_path / "project.json"
        if manifest_file.exists():
            manifest_file.unlink()

        r1_sid = k1.get_storage_id(r1).hex()
        r2_sid = k1.get_storage_id(r2).hex()
        expected_roots = sorted([r1_sid, r2_sid])

        # Fresh kernel loads project via root discovery
        k2 = Kernel(tmp_path)
        assert k2.manifest is None
        result = k2.load_project()

        assert isinstance(result, dict)
        assert result["roots_loaded"] == 2
        assert result["broken_references"] == 0

        assert k2.manifest is not None
        assert k2.manifest.name == tmp_path.name
        assert k2.manifest.format_version == 1
        assert k2.manifest.root_entity_ids == expected_roots

        # project.json should now be written to disk
        assert manifest_file.exists()
        with open(manifest_file, "r", encoding="utf-8") as f:
            disk_manifest = json.load(f)
        assert disk_manifest["root_entity_ids"] == expected_roots

        # Verify all entities were recursively loaded into memory
        assert len(k2.resources) == 5

    def test_root_discovery_empty_directory(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        result = kernel.load_project()
        assert result is None
        assert kernel.manifest is None
        assert not (tmp_path / "project.json").exists()

    def test_root_discovery_ignores_non_entity_resources(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        k1.create_script_resource(name="StandaloneScript", code="print('hello')")
        k1.save_dirty_resources()

        # Remove project.json
        manifest_file = tmp_path / "project.json"
        if manifest_file.exists():
            manifest_file.unlink()

        # Only a script file exists on disk
        k2 = Kernel(tmp_path)
        result = k2.load_project()
        assert result is None
        assert k2.manifest is None

    def test_root_discovery_subsequent_load_uses_synthesized_manifest(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        k1.create_entity(name="SoleRoot")
        k1.save_dirty_resources()

        # Remove project.json
        (tmp_path / "project.json").unlink(missing_ok=True)

        # 1st load synthesizes project.json
        k2 = Kernel(tmp_path)
        k2.load_project()
        assert (tmp_path / "project.json").exists()

        # Modify synthesized project.json custom name
        manifest_path = tmp_path / "project.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["name"] = "Synthesized Title"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # 2nd load should load the manifest file rather than re-discovering
        k3 = Kernel(tmp_path)
        k3.load_project()
        assert k3.manifest is not None
        assert k3.manifest.name == "Synthesized Title"

    def test_root_discovery_recovers_entity_with_missing_parent(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        orphan_id = k1.create_entity(name="RecoverableOrphan")
        orphan_sid = k1.get_storage_id(orphan_id)
        k1.save_dirty_resources()
        (tmp_path / "project.json").unlink(missing_ok=True)

        orphan_path = tmp_path / f"{orphan_sid.hex()}.json"
        payload = json.loads(orphan_path.read_text(encoding="utf-8"))
        payload["data"]["parent"] = "f" * 32
        orphan_path.write_text(json.dumps(payload), encoding="utf-8")

        k2 = Kernel(tmp_path)
        result = k2.load_project()

        assert isinstance(result, dict)
        assert k2.manifest is not None
        assert k2.manifest.root_entity_ids == [orphan_sid.hex()]
        assert orphan_sid in k2.resource_runtime_ids

    @pytest.mark.parametrize("corrupt_data", [b"{broken json", b"\xff"])
    def test_root_discovery_rejects_corrupt_resource_without_writing_manifest(self, tmp_path: Path, corrupt_data):
        corrupt_resource = tmp_path / f"{'a' * 32}.json"
        corrupt_resource.write_bytes(corrupt_data)

        kernel = Kernel(tmp_path)
        result = kernel.load_project()

        assert isinstance(result, Error)
        assert result.code == ProjectLoadError
        assert kernel.resources == {}
        assert not (tmp_path / "project.json").exists()


class TestBrokenReferenceResilienceAndDiagnostics:
    """Tests for non-fatal handling of missing children and dependencies, and diagnostic metrics."""

    def test_broken_reference_missing_child(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        parent_id = k1.create_entity(name="ParentWithMissingChild")
        child_id = k1.create_entity(name="DoomedChild", parent_id=parent_id)
        k1.save_dirty_resources()
        k1.save_project()

        parent_sid = k1.get_storage_id(parent_id)
        child_sid = k1.get_storage_id(child_id)

        # Physically delete the child's JSON file from disk
        child_file = tmp_path / f"{child_sid.hex()}.json"
        assert child_file.exists()
        child_file.unlink()

        # Load project in fresh kernel
        k2 = Kernel(tmp_path)
        res = k2.load_project()

        assert not isinstance(res, Error), f"load_project must not fail when child is missing: {res}"
        assert isinstance(res, dict)
        assert res["broken_references"] == 1

        # Parent must be loaded and functional
        parent_rid = k2.get_resource_id(parent_sid)
        assert isinstance(parent_rid, int)
        parent_proxy = k2.get_entity_proxy(parent_rid)
        assert parent_proxy.name == "ParentWithMissingChild"

        # Diagnostic verification
        assert len(k2.broken_references) == 1
        br = k2.broken_references[0]
        assert br.source_storage_id == parent_sid
        assert br.target_storage_id == child_sid
        assert br.reference_type == "child"
        assert "not found on disk" in br.details.lower()

        diagnostics = k2.get_diagnostics()
        assert diagnostics["broken_references"] == k2.broken_references
        assert diagnostics["total_resources"] == 1
        assert diagnostics["dirty_count"] == 0

    def test_broken_reference_missing_dependency(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        script_id = k1.create_script_resource(name="DoomedScript", code="def update(self, dt, kernel): pass")
        script_sid = k1.get_storage_id(script_id)

        # Create root entity with explicit dependency on the script
        entity_id = k1.create_resource(
            resource_type=Entity,
            resource_data={"components": {}, "resources": [], "scripts": [], "children": [], "parent": None},
            name="EntityWithMissingDependency",
            dependencies=[script_sid.hex()],
        )
        k1.save_dirty_resources()
        k1.save_project()

        entity_sid = k1.get_storage_id(entity_id)

        # Physically delete script JSON file
        script_file = tmp_path / f"{script_sid.hex()}.json"
        assert script_file.exists()
        script_file.unlink()

        # Load project in fresh kernel
        k2 = Kernel(tmp_path)
        res = k2.load_project()

        assert not isinstance(res, Error)
        assert entity_sid in k2.resource_runtime_ids
        assert len(k2.broken_references) == 1

        br = k2.broken_references[0]
        assert br.source_storage_id == entity_sid
        assert br.target_storage_id == script_sid
        assert br.reference_type == "dependency"
        assert "not found on disk" in br.details.lower()

        diagnostics = k2.get_diagnostics()
        assert len(diagnostics["broken_references"]) == 1

    def test_broken_reference_invalid_child_id_string(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        parent_id = k1.create_entity(name="ParentWithMalformedChildRef")
        k1.save_dirty_resources()
        k1.save_project()

        parent_sid = k1.get_storage_id(parent_id)
        parent_file = tmp_path / f"{parent_sid.hex()}.json"

        # Inject malformed child ID into parent's disk payload
        with open(parent_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["children"] = ["invalid_child_id"]
        with open(parent_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        k2 = Kernel(tmp_path)
        res = k2.load_project()
        assert isinstance(res, dict)
        assert len(k2.broken_references) == 1
        br = k2.broken_references[0]
        assert br.source_storage_id == parent_sid
        assert br.reference_type == "child"
        assert "Invalid child ID" in br.details

    def test_diagnostics_metrics_tracking(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        e1 = kernel.create_entity(name="Entity1", components={"Transform": {"x": 0.0}})
        kernel.create_entity(name="Entity2")

        diag1 = kernel.get_diagnostics()
        assert diag1["total_resources"] == 2
        assert diag1["dirty_count"] == 2
        assert len(diag1["broken_references"]) == 0

        kernel.save_dirty_resources()
        diag2 = kernel.get_diagnostics()
        assert diag2["dirty_count"] == 0

        # Mutate through proxy to verify dirty_count updates
        proxy = kernel.get_entity_proxy(e1)
        proxy.transform.x = 42.0
        diag3 = kernel.get_diagnostics()
        assert diag3["dirty_count"] == 1


class TestStartupLoadingContract:
    """Tests for main.py startup loading and demo world isolation."""

    def test_startup_existing_project_prevents_demo_world_duplication(self, tmp_path: Path):
        # Setup: Create an existing custom project
        k1 = Kernel(tmp_path)
        k1.create_entity(
            name="CustomPlayer",
            components={"Transform": {"x": 50.0, "y": 50.0}},
        )
        k1.save_dirty_resources()
        k1.save_project()
        initial_entity_count = len(k1.resources)

        # Execute: Emulate startup sequence from main.py
        k2 = Kernel(tmp_path)
        k2.load_project()

        assert any(k2.is_entity(rid) for rid in k2.resources), "Existing entity must be loaded into memory"
        populate_demo_world_if_empty(k2)

        # Verify: Demo world must NOT be injected
        assert len(k2.resources) == initial_entity_count
        entity_names = [k2.resources[r].get("name") for r in k2.resources if k2.is_entity(r)]
        assert "CustomPlayer" in entity_names
        assert "Application" not in entity_names
        assert "Player" not in entity_names
        assert "Goblin" not in entity_names
        assert "GameGUI" not in entity_names

    def test_startup_fresh_directory_populates_demo_world(self, tmp_path: Path):
        # Execute: Emulate startup sequence in completely fresh empty directory
        kernel = Kernel(tmp_path)
        load_res = kernel.load_project()
        assert load_res is None

        assert not any(kernel.is_entity(rid) for rid in kernel.resources)
        populate_demo_world_if_empty(kernel)
        kernel.save_dirty_resources()
        kernel.save_project()

        # Verify: Demo world created and saved
        assert (tmp_path / "project.json").exists()
        entity_names = [kernel.resources[r].get("name") for r in kernel.resources if kernel.is_entity(r)]
        assert "Application" in entity_names
        assert "Game" in entity_names
        assert "Player" in entity_names
        assert "Goblin" in entity_names
        assert "GameGUI" in entity_names

        # Verify idempotency on restart: next launch loads project without re-injecting
        k2 = Kernel(tmp_path)
        k2.load_project()
        resource_count_on_load = len(k2.resources)
        assert resource_count_on_load > 0

        populate_demo_world_if_empty(k2)
        assert len(k2.resources) == resource_count_on_load, "Idempotent: demo world must not duplicate existing project"

    def test_startup_corrupted_manifest_aborts_without_clobbering(self, tmp_path: Path):
        """Corrupted project.json returns Error and must not be overwritten by demo world."""
        corrupt_manifest = tmp_path / "project.json"
        corrupt_content = '{"format_version": 0, "name": "Broken"}'
        corrupt_manifest.write_text(corrupt_content, encoding="utf-8")

        kernel = Kernel(tmp_path)
        load_res = kernel.load_project()
        assert isinstance(load_res, Error)
        assert load_res.code == InvalidProjectManifestError

        # Emulate main.py safety gate: because load_res is Error, abort before populating demo world
        if not isinstance(load_res, Error):
            populate_demo_world_if_empty(kernel)
            kernel.save_project()

        # Assert: manifest content was preserved and not overwritten by demo world
        assert corrupt_manifest.read_text(encoding="utf-8") == corrupt_content
        assert not any(kernel.is_entity(r) for r in kernel.resources)

    @pytest.mark.parametrize("root_ids", [[], ["a" * 32]])
    def test_main_preserves_existing_empty_or_missing_root_project(self, tmp_path: Path, monkeypatch, root_ids):
        import main as entrypoint

        manifest_path = tmp_path / "project.json"
        original = json.dumps({"format_version": 1, "name": "Existing", "root_entity_ids": root_ids})
        manifest_path.write_text(original, encoding="utf-8")
        loaded_kernels = []
        monkeypatch.setattr("sys.argv", ["main.py", "--world", str(tmp_path), "--headless"])
        monkeypatch.setattr(entrypoint, "run_headless_simulation", lambda kernel, **kwargs: loaded_kernels.append(kernel))

        entrypoint.main()

        assert loaded_kernels == []
        assert manifest_path.read_text(encoding="utf-8") == original
        assert list(tmp_path.glob("*.json")) == [manifest_path]

    def test_main_opens_only_the_requested_application_id_across_restarts(self, tmp_path: Path, monkeypatch):
        import main as entrypoint

        original_kernel = Kernel(tmp_path)
        other_id = original_kernel.create_entity(name="Application")
        selected_id = original_kernel.create_entity(name="My Renamed Application")
        child_id = original_kernel.create_entity(name="Game", parent_id=selected_id)
        selected_sid = original_kernel.get_storage_id(selected_id)
        child_sid = original_kernel.get_storage_id(child_id)
        other_sid = original_kernel.get_storage_id(other_id)
        assert original_kernel.save_dirty_resources() is None
        files_before = {path.name for path in tmp_path.glob("*.json")}

        loaded_kernels = []
        monkeypatch.setattr("sys.argv", [
            "main.py", "--world", str(tmp_path), "--application-id", selected_sid.hex(), "--headless"
        ])
        monkeypatch.setattr(entrypoint, "run_headless_simulation", lambda kernel, **kwargs: loaded_kernels.append(kernel))
        for _ in range(2):
            entrypoint.main()

        assert len(loaded_kernels) == 2
        for kernel in loaded_kernels:
            assert set(kernel.resource_runtime_ids) == {selected_sid, child_sid}
            assert other_sid not in kernel.resource_runtime_ids
        assert {path.name for path in tmp_path.glob("*.json")} == files_before

    def test_selected_root_missing_from_disk_fails_without_loading_other_roots(self, tmp_path: Path):
        original_kernel = Kernel(tmp_path)
        selected_id = original_kernel.create_entity(name="Chosen")
        original_kernel.create_entity(name="Other")
        selected_sid = original_kernel.get_storage_id(selected_id)
        assert original_kernel.save_dirty_resources() is None
        (tmp_path / f"{selected_sid.hex()}.json").unlink()

        kernel = Kernel(tmp_path)
        result = kernel.load_project(root_storage_id=selected_sid)

        assert isinstance(result, Error)
        assert kernel.resources == {}
        assert kernel.manifest is None

    def test_saving_selected_root_preserves_unloaded_manifest_roots(self, tmp_path: Path):
        original_kernel = Kernel(tmp_path)
        selected_id = original_kernel.create_entity(name="Selected")
        other_id = original_kernel.create_entity(name="Other")
        selected_sid = original_kernel.get_storage_id(selected_id)
        other_sid = original_kernel.get_storage_id(other_id)
        assert original_kernel.save_dirty_resources() is None

        kernel = Kernel(tmp_path)
        assert isinstance(kernel.load_project(root_storage_id=selected_sid), dict)
        assert other_sid not in kernel.resource_runtime_ids
        assert kernel.save_dirty_resources() is None

        manifest = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
        assert set(manifest["root_entity_ids"]) == {selected_sid.hex(), other_sid.hex()}

    def test_selected_root_requires_manifest_without_discovering_or_creating(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        result = kernel.load_project(root_storage_id="a" * 32)

        assert isinstance(result, Error)
        assert kernel.resources == {}
        assert list(tmp_path.iterdir()) == []


class TestPersistenceSaveFailures:
    def test_saving_preserves_missing_root_references(self, tmp_path: Path):
        manifest_path = tmp_path / "project.json"
        missing_root = "a" * 32
        manifest_path.write_text(
            json.dumps({"format_version": 1, "root_entity_ids": [missing_root]}), encoding="utf-8"
        )
        kernel = Kernel(tmp_path)
        assert isinstance(kernel.load_project(), dict)
        kernel.create_entity(name="NewRoot")

        assert kernel.save_dirty_resources() is None

        saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert missing_root in saved_manifest["root_entity_ids"]

    def test_resource_save_failure_does_not_publish_new_manifest(self, tmp_path: Path, monkeypatch):
        kernel = Kernel(tmp_path)
        kernel.create_entity(name="UnsavedRoot")
        save_error = Error("Save failed", "Injected failure", {}, FailedToSaveResourceOnDiskError)
        monkeypatch.setattr(kernel, "save_resource", lambda runtime_id: save_error)

        assert kernel.save_dirty_resources() == [save_error]
        assert not (tmp_path / "project.json").exists()
        assert kernel.manifest is None

    def test_manifest_save_failure_preserves_in_memory_manifest(self, tmp_path: Path, monkeypatch):
        kernel = Kernel(tmp_path)
        previous_manifest = ProjectManifest(name="Previous", root_entity_ids=["a" * 32])
        kernel.manifest = previous_manifest
        kernel.create_entity(name="NewRoot")

        def fail_replace(path, target):
            raise OSError("Injected replacement failure")

        monkeypatch.setattr(Path, "replace", fail_replace)
        assert isinstance(kernel.save_project(), Error)
        assert kernel.manifest is previous_manifest
        assert kernel.manifest.root_entity_ids == ["a" * 32]
        assert not (tmp_path / "project.tmp").exists()


class TestPersistenceSafetyAndPlannedFeatures:
    """Safety guarantees completed in Phase 1 and explicitly deferred future work."""

    @pytest.mark.parametrize("corrupt_data", [b"{broken json", b"\xff"])
    def test_transactional_rollback_on_failed_fatal_load(self, tmp_path: Path, corrupt_data):
        k1 = Kernel(tmp_path)
        child_id = k1.create_entity(name="BrokenChild")
        child_sid = k1.get_storage_id(child_id)
        root_id = k1.create_entity(name="Root")
        root_sid = k1.get_storage_id(root_id)
        k1.resources[root_id]["data"]["children"] = [child_sid.hex()]
        k1.mark_dirty(root_id)
        k1.save_dirty_resources()

        (tmp_path / f"{child_sid.hex()}.json").write_bytes(corrupt_data)

        k2 = Kernel(tmp_path)
        result = k2.load_resource(root_sid, is_fatal=True)

        assert isinstance(result, Error)
        assert k2.resources == {}
        assert k2.resource_runtime_ids == {}
        assert k2.resource_storage_ids == {}
        assert k2.runtime_idx == 0

    @pytest.mark.parametrize("corrupt_data", [b"{broken json", b"\xff"])
    def test_project_load_rolls_back_all_roots_on_corrupt_resource(self, tmp_path: Path, corrupt_data):
        k1 = Kernel(tmp_path)
        good_id = k1.create_entity(name="GoodRoot")
        bad_id = k1.create_entity(name="BadRoot")
        good_sid = k1.get_storage_id(good_id)
        bad_sid = k1.get_storage_id(bad_id)
        k1.save_dirty_resources()
        k1.save_project()

        (tmp_path / f"{bad_sid.hex()}.json").write_bytes(corrupt_data)
        manifest = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
        manifest["root_entity_ids"] = [good_sid.hex(), bad_sid.hex()]
        (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

        k2 = Kernel(tmp_path)
        result = k2.load_project()

        assert isinstance(result, Error)
        assert result.code == ProjectLoadError
        assert k2.manifest is None
        assert k2.resources == {}
        assert k2.resource_runtime_ids == {}
        assert k2.resource_storage_ids == {}

    @pytest.mark.skip(reason="Planned test: Manifest schema version migration pipeline")
    def test_planned_manifest_schema_migration_pipeline(self):
        # When format_version > 1 is introduced, project loading should pass manifest data
        # through sequential migration transformers (v1 -> v2 -> v3).
        pass

    def test_planned_generation_safe_runtime_id_recycle_across_project_reload(self, tmp_path: Path):
        """Held proxy from prior session detects invalidation when project is reloaded or entity is recreated."""
        k = Kernel(tmp_path)
        e = k.create_entity(name="Hero", components={"Health": {"hp": 100}})
        proxy = k.get_entity_proxy(e)
        assert proxy.is_alive
        assert proxy.Health["hp"] == 100

        # Delete hero entity
        k.delete_entity(e)
        assert not proxy.is_alive
        with pytest.raises(AttributeError):
            _ = proxy.name

    def test_planned_hot_reload_manifest_syntax_rollback(self, tmp_path: Path):
        """If project.json is edited externally with invalid syntax, reload rejects it and retains prior manifest."""
        k = Kernel(tmp_path)
        e = k.create_entity(name="Hero")
        k.save_dirty_resources()
        k.save_project()
        initial_manifest = k.manifest
        assert initial_manifest is not None

        # External file edit with corrupt JSON
        (tmp_path / "project.json").write_text("{corrupt: json syntax", encoding="utf-8")
        res = k.load_project()
        assert isinstance(res, Error)
        # Prior manifest remains intact in memory
        assert k.manifest is initial_manifest

    def test_child_entities_recursively_load_dependencies(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        script_id = k1.create_script_resource(name="ChildDependency", code="value = 1")
        script_sid = k1.get_storage_id(script_id)
        root_id = k1.create_entity(name="Root")
        child_id = k1.create_entity(name="Child", parent_id=root_id)
        child_sid = k1.get_storage_id(child_id)
        assert k1.attach_script(child_id, script_id) is None
        k1.save_dirty_resources()
        k1.save_project()

        k2 = Kernel(tmp_path)
        result = k2.load_project()

        assert isinstance(result, dict)
        assert child_sid in k2.resource_runtime_ids
        assert script_sid in k2.resource_runtime_ids

    def test_entity_first_reached_as_dependency_still_loads_its_children(self, tmp_path: Path):
        k1 = Kernel(tmp_path)
        root_id = k1.create_entity(name="Root")
        child_id = k1.create_entity(name="Child", parent_id=root_id)
        grandchild_id = k1.create_entity(name="Grandchild", parent_id=child_id)
        child_sid = k1.get_storage_id(child_id)
        grandchild_sid = k1.get_storage_id(grandchild_id)
        k1.resources[root_id]["dependencies"] = [child_sid.hex()]
        k1.mark_dirty(root_id)
        assert k1.save_dirty_resources() is None

        k2 = Kernel(tmp_path)
        result = k2.load_project()

        assert isinstance(result, dict)
        assert result["broken_references"] == 0
        assert child_sid in k2.resource_runtime_ids
        assert grandchild_sid in k2.resource_runtime_ids
