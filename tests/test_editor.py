"""Comprehensive independent tests for the Dear PyGui Editor package (editor/).

Derives tests from observable user requirements and editor contracts:
1. EditorSession Lifecycle & Selection:
   - Creation of entities and child entities.
   - Selection state tracking and event subscriptions (subscribe_selection_changed, subscribe_state_changed, unsubscribe).
   - Component reading, mutation (mutate_component), addition, and removal.
   - Script attachment and detachment.
   - Subtree deletion (delete_entity) verifying children and parents are detached and deleted from memory.
   - Storage save operations (save_dirty_resources, save_resource, save_all_resources, reload_resource).
   - Resource summary inspection (get_all_resources, get_root_entities, get_entity_name).
2. EditorApp Headless Smoke Test:
   - Initialize EditorApp with a temporary directory Kernel.
   - Call app.start_non_blocking() to step frames without blocking.
   - Select an entity, mutate a component via session, verify status bar text and panel callbacks.
   - Clean teardown with app.destroy().
"""

import dearpygui.dearpygui as dpg

from editor.app import EditorApp
from editor.inspector_panel import InspectorPanel
from editor.session import EditorSession
from LBE import Error, Kernel


class TestEditorSessionLifecycleAndSelection:
    """Tests for EditorSession headless controller, selection, and mutation tracking."""

    def test_entity_creation_and_selection_events(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        selection_events: list[int | None] = []
        state_changes: int = 0

        unsub_sel = session.subscribe_selection_changed(lambda e_id: selection_events.append(e_id))
        unsub_state = session.subscribe_state_changed(lambda: nonlocal_increment())

        def nonlocal_increment():
            nonlocal state_changes
            state_changes += 1

        # Creating entity auto-selects it and triggers callbacks
        e1 = session.create_entity(name="Hero")
        assert not isinstance(e1, Error)
        assert session.selected_entity_id == e1
        assert e1 in selection_events
        assert state_changes > 0

        # Change selection explicitly
        e2 = session.create_entity(name="Monster")
        assert session.selected_entity_id == e2
        session.select_entity(e1)
        assert session.selected_entity_id == e1
        assert selection_events[-1] == e1

        # Deselect
        session.select_entity(None)
        assert session.selected_entity_id is None
        assert selection_events[-1] is None

        # Verify unsubscribe
        unsub_sel()
        unsub_state()
        count_before = len(selection_events)
        session.select_entity(e1)
        assert len(selection_events) == count_before

    def test_child_entity_creation_and_root_listing(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        p = session.create_entity(name="ParentNode")
        c1 = session.create_child_entity(parent_id=p, name="Child1")
        c2 = session.create_child_entity(parent_id=p, name="Child2")

        roots = session.get_root_entities()
        assert roots == [p]

        children = session.get_children(p)
        assert set(children) == {c1, c2}

        assert session.get_entity_name(p) == "ParentNode"
        assert session.get_entity_name(c1) == "Child1"

        session.set_entity_name(c1, "RenamedChild")
        assert session.get_entity_name(c1) == "RenamedChild"

    def test_component_inspection_and_mutation(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        e = session.create_entity(
            name="Actor",
            components={"Health": {"current": 100, "max": 100}},
        )

        comps = session.get_components(e)
        assert "Health" in comps
        assert comps["Health"]["current"] == 100

        # Mutate existing component
        err = session.mutate_component(e, "Health", {"current": 45, "max": 100})
        assert not isinstance(err, Error)
        assert session.get_components(e)["Health"]["current"] == 45
        assert session.is_dirty(e)

        # Add new component
        session.add_component(e, "Armor", {"defense": 20})
        assert "Armor" in session.get_components(e)
        assert session.get_components(e)["Armor"]["defense"] == 20

        # Remove component
        removed = session.remove_component(e, "Armor")
        assert not isinstance(removed, Error)
        assert "Armor" not in session.get_components(e)

    def test_script_attachment_and_detachment(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        e = session.create_entity(name="AICharacter")
        s = kernel.create_script_resource(name="PatrolScript", code="def update(dt): pass")

        assert session.get_entity_scripts(e) == []

        # Attach
        err = session.attach_script(e, s)
        assert not isinstance(err, Error)
        assert session.get_entity_scripts(e) == [s]
        assert session.is_dirty(e)

        # Detach
        err2 = session.detach_script(e, s)
        assert not isinstance(err2, Error)
        assert session.get_entity_scripts(e) == []

    def test_subtree_deletion(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        p = session.create_entity(name="RootNode")
        c = session.create_child_entity(parent_id=p, name="ChildNode")
        gc = session.create_child_entity(parent_id=c, name="GrandChild")

        session.select_entity(c)
        assert session.selected_entity_id == c

        # Deleting 'c' should delete 'c' and 'gc', detach from 'p', and clear selection
        res = session.delete_entity(c)
        assert res is True
        assert session.selected_entity_id is None
        assert not kernel.is_entity(c)
        assert not kernel.is_entity(gc)
        assert kernel.is_entity(p)
        assert session.get_children(p) == []

    def test_delete_entity_disk_option(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        e1 = session.create_entity(name="SavedEntity1", components={"Pos": {"x": 10}})
        e2 = session.create_entity(name="SavedEntity2", components={"Pos": {"x": 20}})
        session.save_all_resources()

        e1_file = tmp_path / f"{session.get_storage_id_hex(e1)}.json"
        e2_file = tmp_path / f"{session.get_storage_id_hex(e2)}.json"
        assert e1_file.exists()
        assert e2_file.exists()

        # Delete e1 without delete_from_disk (default False): disk file remains intact
        res1 = session.delete_entity(e1, delete_from_disk=False)
        assert res1 is True
        assert not kernel.is_entity(e1)
        assert e1_file.exists(), "Disk file must remain when delete_from_disk=False"

        # Delete e2 with delete_from_disk=True: entity removed from memory AND disk file deleted
        res2 = session.delete_entity(e2, delete_from_disk=True)
        assert res2 is True
        assert not kernel.is_entity(e2)
        assert not e2_file.exists(), "Disk file must be deleted when delete_from_disk=True"

    def test_storage_operations_and_resource_summaries(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        e1 = session.create_entity(name="E1", components={"Pos": {"x": 1}})
        e2 = session.create_entity(name="E2", components={"Pos": {"x": 2}})

        assert session.get_dirty_count() >= 2
        assert session.is_dirty(e1)
        assert session.is_dirty(e2)

        hex_id = session.get_storage_id_hex(e1)
        assert len(hex_id) == 32

        # Save single resource
        session.save_resource(e1)
        assert not session.is_dirty(e1)
        assert session.is_dirty(e2)

        # Save dirty resources
        session.save_dirty_resources()
        assert session.get_dirty_count() == 0

        # Reload resource
        session.mutate_component(e1, "Pos", {"x": 999})
        assert session.is_dirty(e1)
        session.reload_resource(e1)
        assert not session.is_dirty(e1)
        assert session.get_components(e1)["Pos"]["x"] == 1

        # Resource summary listing
        summaries = session.get_all_resources()
        assert len(summaries) >= 2
        names = {item["name"] for item in summaries}
        assert "E1" in names
        assert "E2" in names


class TestEditorAppHeadlessSmoke:
    """Headless initialization and stepping of EditorApp GUI."""

    def test_editor_app_headless_lifecycle(self, tmp_path):
        kernel = Kernel(tmp_path)
        e1 = kernel.create_entity(name="Hero", components={"Health": {"current": 100}})
        kernel.create_entity(name="Chest", components={"Treasure": {"gold": 500}})
        kernel.save_dirty_resources()

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            # Start in non-blocking mode, rendering a frame without blocking
            app.start_non_blocking(render_frame=True)

            # Verify panels built
            assert app.hierarchy_panel is not None
            assert app.viewport_panel is not None
            assert app.inspector_panel is not None
            assert app.storage_panel is not None

            # Verify status bar reflects current kernel stats
            assert dpg.does_item_exist("app_status_text")
            status_text = dpg.get_value("app_status_text")
            assert "Loaded Entities: 2" in status_text

            # Select an entity via session and verify selection propagates
            app.session.select_entity(e1)
            assert app.session.selected_entity_id == e1

            # Mutate component via session and verify dirty count updates
            app.session.mutate_component(e1, "Health", {"current": 42})
            app.start_non_blocking(render_frame=True)
            status_text_updated = dpg.get_value("app_status_text")
            assert "Dirty Resources: 1" in status_text_updated

            # Toggle window visibility
            app.toggle_window("window_hierarchy")
            assert not dpg.is_item_shown("window_hierarchy")
            app.toggle_window("window_hierarchy")
            assert dpg.is_item_shown("window_hierarchy")

        finally:
            # Clean teardown
            app.destroy()
            assert not app._is_setup
            assert not app._viewport_created

    def test_simulation_playback_and_stepping(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        ticks: list[float] = []
        unsub = session.subscribe_tick(lambda dt: ticks.append(dt))

        assert not session.is_playing
        assert session.toggle_play() is True
        assert session.is_playing is True

        session.step_simulation(0.016)
        assert len(ticks) == 1
        assert abs(session.sim_time - 0.016) < 1e-4

        session.sim_speed = 2.0
        session.step_simulation(0.016)
        assert len(ticks) == 2
        assert abs(session.sim_time - 0.048) < 1e-4

        assert session.toggle_play() is False
        assert not session.is_playing

        unsub()
        session.step_simulation(0.016)
        assert len(ticks) == 2

    def test_inspector_panel_renders_sequence_component_without_error(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)
        entity = session.create_entity(
            name="Hero",
            components={"Inventory": {"items": ["sword", "shield", "potion"]}},
        )
        assert not isinstance(entity, Error)
        session.select_entity(entity)

        # In DPG context, build inspector panel and verify rebuild handles sequences cleanly
        dpg.create_context()
        try:
            panel = InspectorPanel(session, tag="test_seq_inspector")
            panel.build()
            assert dpg.does_item_exist("test_seq_inspector")
            # Trigger rebuild to ensure no TypeError occurs when serializing sequence
            panel.rebuild()
        finally:
            dpg.destroy_context()
