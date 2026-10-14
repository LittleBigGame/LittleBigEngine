"""Unit and integration tests for the Bootstrapped Editor workstation architecture.

Verifies:
1. Bootstrapped Scene Structure (Application -> Game and Editor hierarchy).
2. Tree Scoping (session.set_view_root isolates Game and hides Editor).
3. Pure Vector Geometry Glyphs (chevrons, radio dots, window chrome, branch lines).
4. Multi-Inspector Active Focus and Lock Pinning (locked stays pinned, selection routes to active unlocked).
5. Dynamic Multi-Inspector Spawning (app.spawn_inspector & context menu).
6. 3-Layer Context Menu (Target, Panel, Engine layers and action execution).
7. Auto-Hiding Corner Chrome & Flyouts (▷ slide-out with close, min, max).
"""

from __future__ import annotations

from pathlib import Path
import dearpygui.dearpygui as dpg
import pytest

from editor.app import EditorApp
from editor.context_menu import (
    open_context_menu,
    _on_add_child,
    _on_duplicate,
    _on_delete,
    _on_set_view_root,
    _on_reset_view_root,
    _on_toggle_play,
)
from editor.hierarchy_panel import HierarchyPanel
from editor.inspector_panel import InspectorPanel
from editor.session import EditorSession
from editor.vector_glyphs import (
    draw_chevron_down,
    draw_chevron_right,
    draw_radio_dot,
    draw_window_chrome,
    draw_branch_lines,
    draw_dashed_rect,
)
from LBE import Error, Kernel
from main import populate_demo_world_if_empty


@pytest.fixture
def dpg_context():
    """Ensure a fresh, isolated Dear PyGui context for headless testing."""
    dpg.create_context()
    yield
    dpg.destroy_context()


class TestBootstrappedSceneStructure:
    """Tests for default world population adhering to the Application -> Game & Editor structure."""

    def test_default_world_population_hierarchy(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)

        # 1. Root must be 'Application'
        roots = [rid for rid in kernel.resources if kernel.is_entity(rid) and kernel.get_entity_parent(rid) is None]
        assert len(roots) == 1
        app_id = roots[0]
        assert kernel.resources[app_id]["name"] == "Application"

        # 2. Direct children of Application must be 'Game' and 'Editor'
        app_children = kernel.get_entity_children(app_id)
        assert len(app_children) == 2
        child_names = {kernel.resources[c]["name"] for c in app_children}
        assert child_names == {"Game", "Editor"}

        # 3. Game contains Player, Goblin, GameGUI
        game_id = next(c for c in app_children if kernel.resources[c]["name"] == "Game")
        game_children = kernel.get_entity_children(game_id)
        game_child_names = {kernel.resources[c]["name"] for c in game_children}
        assert "Player" in game_child_names
        assert "Goblin" in game_child_names
        assert "GameGUI" in game_child_names

        # Player contains equipped Excalibur
        player_id = next(c for c in game_children if kernel.resources[c]["name"] == "Player")
        player_children = kernel.get_entity_children(player_id)
        player_child_names = {kernel.resources[c]["name"] for c in player_children}
        assert "Excalibur" in player_child_names

        # 4. Editor contains Hierarchy Panel, Inspector Panel
        editor_id = next(c for c in app_children if kernel.resources[c]["name"] == "Editor")
        editor_children = kernel.get_entity_children(editor_id)
        editor_child_names = {kernel.resources[c]["name"] for c in editor_children}
        assert "Hierarchy Panel" in editor_child_names
        assert "Inspector Panel" in editor_child_names


class TestRootScoping:
    """Tests for scoping the visible hierarchy to specific subtrees."""

    def test_view_root_scoping_and_visibility(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)
        session = EditorSession(kernel)

        app_id = next(r for r in kernel.resources if kernel.is_entity(r) and kernel.get_entity_parent(r) is None)
        game_id = next(c for c in kernel.get_entity_children(app_id) if kernel.resources[c]["name"] == "Game")

        # By default, root scope is None -> displays Application
        assert session.get_visible_root_ids() == [app_id]

        panel = HierarchyPanel(session)
        panel.build()

        roots_default = dpg.get_item_children(panel.content_tag, 1)
        assert len(roots_default) == 1
        assert "Application" in dpg.get_item_configuration(roots_default[0])["label"]

        # Scope to Game
        session.set_view_root(game_id)
        assert session.get_visible_root_ids() == [game_id]
        panel.rebuild()

        roots_scoped = dpg.get_item_children(panel.content_tag, 1)
        assert len(roots_scoped) == 1
        assert "Game" in dpg.get_item_configuration(roots_scoped[0])["label"]
        # Editor is completely hidden from the hierarchy view!
        all_labels = [dpg.get_item_configuration(i).get("label", "") for i in roots_scoped]
        assert not any("Editor" in l for l in all_labels)

        # Reset scope to None -> restores Application
        session.set_view_root(None)
        assert session.get_visible_root_ids() == [app_id]
        panel.rebuild()
        roots_restored = dpg.get_item_children(panel.content_tag, 1)
        assert "Application" in dpg.get_item_configuration(roots_restored[0])["label"]


class TestVectorGeometryGlyphs:
    """Tests for procedural vector drawing primitives."""

    def test_vector_glyph_drawing_functions(self, dpg_context):
        with dpg.window(label="Vector Canvas"):
            with dpg.drawlist(width=300, height=300) as dl:
                draw_chevron_down(dl, (10, 10), (255, 255, 255, 255))
                draw_chevron_right(dl, (30, 10), (255, 255, 255, 255))
                draw_radio_dot(dl, (50, 10), selected=True, color=(0, 120, 255, 255))
                draw_radio_dot(dl, (70, 10), selected=False, color=(100, 100, 100, 255))
                draw_window_chrome(dl, "close", (90, 10))
                draw_window_chrome(dl, "min", (110, 10))
                draw_window_chrome(dl, "max", (130, 10))
                draw_window_chrome(dl, "flyout_arrow", (150, 10))
                draw_branch_lines(dl, (10, 50), (30, 70))
                draw_dashed_rect(dl, (10, 90), (100, 140))

        # Ensure drawing commands were executed without raising exceptions
        assert dpg.does_item_exist(dl)
        children = dpg.get_item_children(dl, 2)
        assert len(children) > 0


class TestMultiInspectorFocusAndLock:
    """Tests for multi-inspector instances, active focus routing, and lock pinning."""

    def test_multi_inspector_registration_and_routing(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        e1 = session.create_entity(name="Player")
        e2 = session.create_entity(name="Goblin")
        session.select_entity(None)

        insp1 = InspectorPanel(session, tag="test_insp_1")
        insp1.build()
        insp2 = InspectorPanel(session, tag="test_insp_2")
        insp2.build()

        assert len(session._inspectors) == 2
        assert session.active_inspector is insp1

        # Selection routes to active inspector (insp1)
        session.select_entity(e1)
        assert insp1.target_entity_id == e1
        assert insp2.target_entity_id is None

        # Lock insp1 to Player
        assert not insp1.is_locked
        insp1.toggle_lock()
        assert insp1.is_locked

        # Selection of Goblin now routes to unlocked insp2 because insp1 is locked!
        session.select_entity(e2)
        assert insp1.target_entity_id == e1  # Stayed pinned!
        assert insp2.target_entity_id == e2  # Received selection!

        # Set active inspector to insp2
        insp2.set_active()
        assert session.active_inspector is insp2

        # Unlock insp1, but selection continues to insp2 because insp2 is active!
        insp1.toggle_lock()
        assert not insp1.is_locked
        e3 = session.create_entity(name="Boss")
        session.select_entity(e3)
        assert insp2.target_entity_id == e3

        # Cleanup
        insp1.destroy()
        insp2.destroy()
        assert len(session._inspectors) == 0

    def test_both_locked_inspectors_bypass_selections(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        e1 = session.create_entity(name="ItemA")
        e2 = session.create_entity(name="ItemB")
        e3 = session.create_entity(name="ItemC")

        insp1 = InspectorPanel(session, tag="test_insp_a", target_entity_id=e1, is_locked=True)
        insp2 = InspectorPanel(session, tag="test_insp_b", target_entity_id=e2, is_locked=True)
        insp1.build()
        insp2.build()

        session.select_entity(e3)
        # Neither locked inspector updates its target
        assert insp1.target_entity_id == e1
        assert insp2.target_entity_id == e2

        insp1.destroy()
        insp2.destroy()


class TestDynamicInspectorSpawning:
    """Tests for spawning multiple independent inspector panels via EditorApp."""

    def test_app_spawn_inspector(self, tmp_path: Path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)
        e1 = session.create_entity(name="Hero")
        e2 = session.create_entity(name="Sword")

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.start_non_blocking(render_frame=True)
            assert app.inspector_panel is not None
            assert len(app.extra_inspectors) == 0

            # Spawn extra inspector pinned to Sword
            extra_insp = app.spawn_inspector(target_id=e2, locked=True)
            assert len(app.extra_inspectors) == 1
            assert extra_insp.target_entity_id == e2
            assert extra_insp.is_locked is True
            assert dpg.does_item_exist(extra_insp.tag)

            # Default inspector targets Hero
            app.session.select_entity(e1)
            assert app.inspector_panel.target_entity_id == e1
            assert extra_insp.target_entity_id == e2
        finally:
            app.destroy()


class TestLayeredContextMenu:
    """Tests for the 3-layer right-click context menu and verb execution."""

    def test_context_menu_layers_and_actions(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)
        parent = session.create_entity(name="RootNode")

        # Open context menu on RootNode inside hierarchy panel
        open_context_menu(session, target_id=parent, panel_type="hierarchy")
        assert dpg.does_item_exist("popup_context_menu")

        # 1. Action: Add Child
        _on_add_child(session, parent_id=parent, popup_tag="popup_context_menu")
        children = session.get_children(parent)
        assert len(children) == 1
        child_id = children[0]

        # Add components to child
        session.add_component(child_id, "Transform", {"x": 42.0, "y": 84.0})
        session.add_component(child_id, "Health", {"current": 90, "max": 100})

        # 2. Action: Duplicate entity with components (tests CRITICAL finding fix)
        _on_duplicate(session, entity_id=child_id, popup_tag="popup_context_menu")
        children_after_dup = session.get_children(parent)
        assert len(children_after_dup) == 2
        dup_id = [c for c in children_after_dup if c != child_id][0]
        dup_comps = session.get_components(dup_id)
        assert "Transform" in dup_comps
        assert dup_comps["Transform"]["x"] == 42.0
        assert "Health" in dup_comps
        assert dup_comps["Health"]["current"] == 90

        # Verify deep-copy (mutating duplicate does not affect original)
        session.mutate_component(dup_id, "Transform", {"x": 999.0})
        assert session.get_components(child_id)["Transform"]["x"] == 42.0
        assert session.get_components(dup_id)["Transform"]["x"] == 999.0

        # 3. Action: Delete
        _on_delete(session, entity_id=child_id, popup_tag="popup_context_menu")
        assert not kernel.is_entity(child_id)
        assert len(session.get_children(parent)) == 1

        # 4. Action: Toggle Simulation Play
        assert not session.is_playing
        _on_toggle_play(session, popup_tag="popup_context_menu")
        assert session.is_playing
        _on_toggle_play(session, popup_tag="popup_context_menu")
        assert not session.is_playing

        # 5. Action: Root Scoping via Context Menu
        _on_set_view_root(session, root_id=parent, popup_tag="popup_context_menu")
        assert session.view_root_id == parent
        _on_reset_view_root(session, popup_tag="popup_context_menu")
        assert session.view_root_id is None


class TestCornerChromeAndFlyouts:
    """Tests for auto-hiding corner chrome and window size adjustments."""

    def test_hierarchy_and_inspector_flyout_chrome(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        h_panel = HierarchyPanel(session)
        h_panel.build()

        i_panel = InspectorPanel(session)
        i_panel.build()

        # Neither panel has the white arrow button or flyout dock
        assert not dpg.does_item_exist(f"{h_panel.tag}_arrow_btn")
        assert not dpg.does_item_exist(f"{h_panel.tag}_flyout_dock")
        assert not dpg.does_item_exist(f"{i_panel.tag}_arrow_btn")
        assert not dpg.does_item_exist(f"{i_panel.tag}_flyout_dock")

        # Test minimize & maximize on inspector
        assert not i_panel._is_minimized
        i_panel._toggle_minimize()
        assert i_panel._is_minimized
        assert dpg.get_item_height(i_panel.tag) == 60

        i_panel._toggle_minimize()
        assert not i_panel._is_minimized
        assert dpg.get_item_height(i_panel.tag) == 760

        # Close inspector completely cleans up item and unregisters from session
        assert i_panel in session._inspectors
        i_panel.close()
        assert not dpg.does_item_exist(i_panel.tag)
        assert i_panel not in session._inspectors

    def test_vector_card_click_handler_safe_from_keyerror(self, dpg_context, tmp_path: Path):
        """Regression test: clicking a vector card must use dl_tag and never crash with KeyError('rect_min')."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)
        session = EditorSession(kernel)

        h_panel = HierarchyPanel(session, use_vector_cards=True)
        h_panel.build()

        for rid in kernel.resources:
            if not kernel.is_entity(rid):
                continue
            if rid in h_panel._node_tags:
                row_tag = h_panel._node_tags[rid]
                dl_tag = f"{row_tag}_dl"
                # Invoking the callback must never raise KeyError: 'rect_min'
                h_panel._on_vector_card_clicked(
                    _sender=0,
                    _app_data=None,
                    user_data=(rid, True, 8.0, dl_tag),
                )
                assert session.selected_entity_id == rid

    def test_selection_does_not_collapse_vector_card_tree(self, dpg_context, tmp_path: Path):
        """Regression test: selecting an entity must not collapse the vector card tree."""
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)
        session = EditorSession(kernel)

        h_panel = HierarchyPanel(session, use_vector_cards=True)
        h_panel.build()

        # All entities start expanded (collapsed_entities is empty)
        assert len(h_panel._collapsed_entities) == 0

        # Selecting an entity triggers rebuild() via session subscription
        entities = [rid for rid in kernel.resources if kernel.is_entity(rid)]
        for eid in entities[:5]:
            session.select_entity(eid)
            # Must remain 0 collapsed entities
            assert len(h_panel._collapsed_entities) == 0
