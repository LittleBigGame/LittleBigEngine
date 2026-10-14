"""Independent verification test suite for Stage 3: Subtree Separation & Dear PyGui UI Bridge.

Derives tests from observable user requirements and contracts:
1. UI Bridge Headless Rendering & Widget Translation:
   - UIContainer with UIButton, UISlider, UITextInput, UIText translated to DPG widgets.
   - Layout modes (vertical, horizontal, collapsible).
   - Widget properties (button dimensions, slider ranges, input text/hints, text color/bullet).
   - Empty scene placeholder text display.
   - Mount selector combo management and root switching.
   - Cycle detection preventing infinite recursion.
2. Interactive Event Dispatch via UI Bridge:
   - Button click callback triggers kernel.trigger_ui_event, executes script function, and mutates state.
   - Slider change callback updates component value and triggers on_change handler.
   - Text input change callback updates component text and triggers on_change handler.
   - Self-rebuild suppression prevents destroying input focus during continuous editing.
   - Graceful error handling for stale/deleted entities and broken script references.
3. Subtree Separation in Hierarchy Panel:
   - Filter 'All': shows both game world entities and UI entities.
   - Filter 'Game World': displays only non-UI game entities, excluding UI subtrees.
   - Filter 'UI & Tools': displays only UI entities, excluding game entities.
   - Child UI entities under game entities correctly classified and separated.
   - Toolbar '+ UI Element' action creates, parents, selects, and refreshes UI entities.
   - Search query filtering respects active subtree filter mode.
4. EditorApp Integration Smoke Test:
   - EditorApp(auto_build=True) headless lifecycle with UIBridgePanel.
   - Window toggling via app.toggle_window('window_ui_preview').
   - Clean shutdown with app.destroy().
5. UI Persistence Roundtrip via UI Bridge:
   - UI hierarchies saved to disk and reloaded into fresh kernel/session render properly.
6. Planned Features:
   - Two-way reactive data binding, undo/redo rollback, custom DPG widget plugins.
"""

import dearpygui.dearpygui as dpg
import pytest
from pathlib import Path

from editor.app import EditorApp
from editor.hierarchy_panel import HierarchyPanel
from editor.session import EditorSession
from editor.ui_bridge import UIBridgePanel
from LBE import Error, Kernel, Script


@pytest.fixture
def dpg_context():
    """Fixture providing an isolated Dear PyGui context per test."""
    try:
        dpg.destroy_context()
    except Exception:
        pass
    dpg.create_context()
    yield
    try:
        dpg.destroy_context()
    except Exception:
        pass


class TestUIBridgeHeadlessRenderingAndTranslation:
    """Tests translation of engine UI component subtrees into Dear PyGui widgets."""

    def test_empty_scene_shows_placeholder_text(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)
        panel = UIBridgePanel(session)
        panel.build()

        assert dpg.does_item_exist(panel.content_tag)
        children = dpg.get_item_children(panel.content_tag, 1)
        assert len(children) == 1

        placeholder_item = children[0]
        assert dpg.get_item_type(placeholder_item) == "mvAppItemType::mvText"
        val = dpg.get_value(placeholder_item)
        assert "No UI tree mounted" in val

    def test_render_all_ui_widget_types_in_container(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="MainMenu", component_type="UIContainer")
        btn = session.create_ui_entity(
            name="StartBtn",
            component_type="UIButton",
            parent_id=root,
            component_props={"label": "Start Game", "width": 120, "height": 40},
        )
        slider = session.create_ui_entity(
            name="VolumeSlider",
            component_type="UISlider",
            parent_id=root,
            component_props={"label": "Master Volume", "min": 0.0, "max": 100.0, "value": 75.0},
        )
        txt_in = session.create_ui_entity(
            name="PlayerNameInput",
            component_type="UITextInput",
            parent_id=root,
            component_props={"label": "Name", "text": "Hero", "hint": "Enter hero name"},
        )
        txt = session.create_ui_entity(
            name="StatusLabel",
            component_type="UIText",
            parent_id=root,
            component_props={"content": "Ready to Play", "bullet": True, "color": [255, 200, 0]},
        )

        panel = UIBridgePanel(session)
        panel.build()

        content_children = dpg.get_item_children(panel.content_tag, 1)
        assert len(content_children) == 1
        container_group = content_children[0]
        assert dpg.get_item_type(container_group) == "mvAppItemType::mvGroup"

        child_widgets = dpg.get_item_children(container_group, 1)
        assert len(child_widgets) == 4

        # 1. UIButton widget
        btn_item = child_widgets[0]
        assert dpg.get_item_type(btn_item) == "mvAppItemType::mvButton"
        btn_cfg = dpg.get_item_configuration(btn_item)
        assert btn_cfg["label"] == "Start Game"
        assert btn_cfg["width"] == 120
        assert btn_cfg["height"] == 40

        # 2. UISlider widget
        slider_item = child_widgets[1]
        assert dpg.get_item_type(slider_item) == "mvAppItemType::mvSliderFloat"
        slider_cfg = dpg.get_item_configuration(slider_item)
        assert slider_cfg["label"] == "Master Volume"
        assert abs(slider_cfg["min_value"] - 0.0) < 1e-5
        assert abs(slider_cfg["max_value"] - 100.0) < 1e-5
        assert abs(dpg.get_value(slider_item) - 75.0) < 1e-5

        # 3. UITextInput widget
        input_item = child_widgets[2]
        assert dpg.get_item_type(input_item) == "mvAppItemType::mvInputText"
        input_cfg = dpg.get_item_configuration(input_item)
        assert input_cfg["label"] == "Name"
        assert input_cfg["hint"] == "Enter hero name"
        assert dpg.get_value(input_item) == "Hero"

        # 4. UIText widget
        text_item = child_widgets[3]
        assert dpg.get_item_type(text_item) == "mvAppItemType::mvText"
        text_cfg = dpg.get_item_configuration(text_item)
        assert dpg.get_value(text_item) == "Ready to Play"
        assert text_cfg["bullet"] is True

    def test_text_color_normalization_variations(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="TextContainer", component_type="UIContainer")

        # Normalized float RGB (0.0 to 1.0)
        t_float = session.create_ui_entity(
            name="FloatColorText",
            component_type="UIText",
            parent_id=root,
            component_props={"content": "Float", "color": [1.0, 0.5, 0.0]},
        )
        # Integer RGB (0 to 255)
        t_int = session.create_ui_entity(
            name="IntColorText",
            component_type="UIText",
            parent_id=root,
            component_props={"content": "Int", "color": [255, 128, 0]},
        )

        panel = UIBridgePanel(session)
        panel.build()

        container_group = dpg.get_item_children(panel.content_tag, 1)[0]
        text_items = dpg.get_item_children(container_group, 1)

        cfg_float = dpg.get_item_configuration(text_items[0])
        cfg_int = dpg.get_item_configuration(text_items[1])

        assert cfg_float.get("color") is not None
        assert cfg_int.get("color") is not None

    def test_container_layout_variations(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        # Horizontal container
        h_root = session.create_ui_entity(
            name="HLayout",
            component_type="UIContainer",
            component_props={"layout": "horizontal"},
        )
        session.create_ui_entity(name="B1", component_type="UIButton", parent_id=h_root)

        # Collapsible container
        c_root = session.create_ui_entity(
            name="CollapsibleSection",
            component_type="UIContainer",
            component_props={"collapsible": True, "collapsed": False},
        )
        session.create_ui_entity(name="B2", component_type="UIButton", parent_id=c_root)

        panel = UIBridgePanel(session)
        panel.build()

        # Mount HLayout
        panel.selected_mount_id = h_root
        panel.rebuild()
        h_group = dpg.get_item_children(panel.content_tag, 1)[0]
        assert dpg.get_item_type(h_group) == "mvAppItemType::mvGroup"
        assert dpg.get_item_configuration(h_group)["horizontal"] is True

        # Mount CollapsibleSection
        panel.selected_mount_id = c_root
        panel.rebuild()
        c_header = dpg.get_item_children(panel.content_tag, 1)[0]
        assert dpg.get_item_type(c_header) == "mvAppItemType::mvCollapsingHeader"
        assert dpg.get_item_configuration(c_header)["label"] == "CollapsibleSection"

    def test_cycle_detection_prevents_infinite_recursion(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        c1 = session.create_ui_entity(name="Container1", component_type="UIContainer")
        c2 = session.create_ui_entity(name="Container2", component_type="UIContainer", parent_id=c1)

        # Artificially create cycle in parent-child relationship
        kernel.add_entity_child(c2, c1)

        panel = UIBridgePanel(session)
        panel.build()
        assert dpg.does_item_exist(panel.content_tag)

    def test_mount_selector_options_and_switching(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root_a = session.create_ui_entity(name="HUD_A", component_type="UIContainer")
        btn_a = session.create_ui_entity(
            name="BtnA",
            component_type="UIButton",
            parent_id=root_a,
            component_props={"label": "HUD A Button"},
        )

        root_b = session.create_ui_entity(name="Menu_B", component_type="UIContainer")
        btn_b = session.create_ui_entity(
            name="BtnB",
            component_type="UIButton",
            parent_id=root_b,
            component_props={"label": "Menu B Button"},
        )

        panel = UIBridgePanel(session)
        panel.build()

        assert dpg.does_item_exist(panel.mount_selector_tag)
        combo_items = dpg.get_item_configuration(panel.mount_selector_tag)["items"]
        assert any("HUD_A" in item for item in combo_items)
        assert any("Menu_B" in item for item in combo_items)

        # Switch mount to Menu_B
        panel.selected_mount_id = root_b
        panel.rebuild()
        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        btn_widget = dpg.get_item_children(grp, 1)[0]
        assert dpg.get_item_configuration(btn_widget)["label"] == "Menu B Button"

        # Deleting root_b resets mount cleanly
        session.delete_entity(root_b)
        assert panel.selected_mount_id is None
        grp_fallback = dpg.get_item_children(panel.content_tag, 1)[0]
        btn_fallback = dpg.get_item_children(grp_fallback, 1)[0]
        assert dpg.get_item_configuration(btn_fallback)["label"] == "HUD A Button"


class TestUIBridgeInteractiveEventDispatch:
    """Tests interactive event triggers and callback executions from DPG widgets."""

    def test_button_click_callback_triggers_script_and_refreshes(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        script_code = (
            "def _fn_on_btn_click(entity):\n"
            "    entity.uibutton.label = 'Clicked Successfully'\n"
            "    entity.stats.clicks += 1\n"
        )
        script_id = kernel.create_script_resource(name="BtnEvents", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        btn = session.create_ui_entity(
            name="ActionBtn",
            component_type="UIButton",
            parent_id=root,
            component_props={
                "label": "Click Me",
                "on_click": f"<|1|{sid_hex}|>._fn_on_btn_click",
            },
        )
        kernel.set_component(btn, "Stats", {"clicks": 0})

        panel = UIBridgePanel(session)
        panel.build()

        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        btn_item = dpg.get_item_children(grp, 1)[0]

        # Retrieve and invoke DPG callback
        cb = dpg.get_item_configuration(btn_item)["callback"]
        assert callable(cb)
        cb(btn_item, None)

        # Verify state mutated in kernel memory
        comps = session.get_components(btn)
        assert comps["UIButton"]["label"] == "Clicked Successfully"
        assert comps["Stats"]["clicks"] == 1
        assert session.is_dirty(btn)

    def test_slider_change_callback_updates_value_and_triggers_event(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        script_code = (
            "def _fn_on_slider_change(entity, val):\n"
            "    entity.stats.target_val = val\n"
        )
        script_id = kernel.create_script_resource(name="SliderEvents", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        slider = session.create_ui_entity(
            name="VolumeSlider",
            component_type="UISlider",
            parent_id=root,
            component_props={
                "label": "Volume",
                "min": 0.0,
                "max": 1.0,
                "value": 0.1,
                "on_change": f"<|1|{sid_hex}|>._fn_on_slider_change",
            },
        )
        kernel.set_component(slider, "Stats", {"target_val": 0.1})

        panel = UIBridgePanel(session)
        panel.build()

        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        slider_item = dpg.get_item_children(grp, 1)[0]

        cb = dpg.get_item_configuration(slider_item)["callback"]
        assert callable(cb)
        cb(slider_item, 0.85)

        comps = session.get_components(slider)
        assert abs(comps["UISlider"]["value"] - 0.85) < 1e-4
        assert abs(comps["Stats"]["target_val"] - 0.85) < 1e-4
        assert session.is_dirty(slider)

    def test_text_input_change_callback_updates_text_and_triggers_event(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        script_code = (
            "def _fn_on_text_change(entity, new_text):\n"
            "    entity.stats.history = f'Set to: {new_text}'\n"
        )
        script_id = kernel.create_script_resource(name="TextEvents", code=script_code)
        sid_hex = kernel.get_storage_id(script_id).hex()

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        inp = session.create_ui_entity(
            name="PlayerNameInput",
            component_type="UITextInput",
            parent_id=root,
            component_props={
                "label": "Name",
                "text": "InitialName",
                "on_change": f"<|1|{sid_hex}|>._fn_on_text_change",
            },
        )
        kernel.set_component(inp, "Stats", {"history": "none"})

        panel = UIBridgePanel(session)
        panel.build()

        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        input_item = dpg.get_item_children(grp, 1)[0]

        cb = dpg.get_item_configuration(input_item)["callback"]
        assert callable(cb)
        cb(input_item, "SuperHero")

        comps = session.get_components(inp)
        assert comps["UITextInput"]["text"] == "SuperHero"
        assert comps["Stats"]["history"] == "Set to: SuperHero"
        assert session.is_dirty(inp)

    def test_rebuild_suppression_during_continuous_editing(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        slider = session.create_ui_entity(
            name="Slider",
            component_type="UISlider",
            parent_id=root,
            component_props={"value": 0.2},
        )

        panel = UIBridgePanel(session)
        panel.build()

        rebuild_calls = 0
        original_rebuild = panel.rebuild

        def tracking_rebuild():
            nonlocal rebuild_calls
            rebuild_calls += 1
            original_rebuild()

        panel.rebuild = tracking_rebuild

        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        slider_item = dpg.get_item_children(grp, 1)[0]
        cb = dpg.get_item_configuration(slider_item)["callback"]

        # Firing slider callback should update component and refresh session
        # but suppress rebuilding the UIBridgePanel DOM during the edit
        cb(slider_item, 0.9)
        assert rebuild_calls == 0
        assert abs(session.get_components(slider)["UISlider"]["value"] - 0.9) < 1e-4

    def test_deleted_entity_callback_safety(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        btn = session.create_ui_entity(name="Btn", component_type="UIButton", parent_id=root)

        panel = UIBridgePanel(session)
        panel.build()

        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        btn_item = dpg.get_item_children(grp, 1)[0]
        cb = dpg.get_item_configuration(btn_item)["callback"]

        # Delete entity from session
        session.delete_entity(btn)

        # Invoking lingering callback must not raise an unhandled exception
        cb(btn_item, None)

    def test_broken_handler_reference_does_not_crash_editor(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        btn = session.create_ui_entity(
            name="BrokenBtn",
            component_type="UIButton",
            parent_id=root,
            component_props={
                "label": "Broken",
                "on_click": "<|1|00000000000000000000000000000000|>._fn_missing",
            },
        )

        panel = UIBridgePanel(session)
        panel.build()

        grp = dpg.get_item_children(panel.content_tag, 1)[0]
        btn_item = dpg.get_item_children(grp, 1)[0]
        cb = dpg.get_item_configuration(btn_item)["callback"]

        # Calling broken handler must handle error cleanly and not crash
        cb(btn_item, None)


class TestSubtreeSeparationInHierarchyPanel:
    """Tests subtree separation filtering between game world entities and UI hierarchies."""

    def test_hierarchy_panel_filter_modes_game_world_and_ui(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        # Game world entities
        player = session.create_entity(name="Player", components={"Transform": {"x": 0, "y": 0}})
        enemy = session.create_entity(name="Enemy", components={"Transform": {"x": 10, "y": 0}})

        # UI tree
        ui_root = session.create_ui_entity(name="RootContainer", component_type="UIContainer")
        ui_btn = session.create_ui_entity(name="ActionBtn", component_type="UIButton", parent_id=ui_root)

        # Clear selection so prefix '▶ ' does not alter label tests
        session.select_entity(None)

        panel = HierarchyPanel(session)
        panel.build()

        def get_rendered_labels():
            children = dpg.get_item_children(panel.content_tag, 1)
            return [dpg.get_item_configuration(c)["label"] for c in children]

        # 1. 'All' mode contains both game world and UI entities
        panel.subtree_filter = "All"
        all_labels = get_rendered_labels()
        assert any("Player" in l for l in all_labels)
        assert any("Enemy" in l for l in all_labels)
        assert any("RootContainer" in l for l in all_labels)

        # 2. 'Game World' mode contains ONLY game entities, excludes UI
        panel.subtree_filter = "Game World"
        game_labels = get_rendered_labels()
        assert any("Player" in l for l in game_labels)
        assert any("Enemy" in l for l in game_labels)
        assert not any("RootContainer" in l for l in game_labels)
        assert not any("ActionBtn" in l for l in game_labels)

        # 3. 'UI & Tools' mode contains ONLY UI entities, excludes game entities
        panel.subtree_filter = "UI & Tools"
        ui_labels = get_rendered_labels()
        assert not any("Player" in l for l in ui_labels)
        assert not any("Enemy" in l for l in ui_labels)
        assert any("RootContainer" in l for l in ui_labels)

    def test_game_entity_with_child_ui_element_subtree_separation(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(name="PlayerEntity")
        # Attach UI element as child of game entity (e.g. overhead nameplate / health bar)
        nameplate = session.create_ui_entity(name="NameplateUI", component_type="UIContainer", parent_id=player)
        session.select_entity(None)

        panel = HierarchyPanel(session)
        panel.build()

        # In 'Game World' mode, the UI child is excluded from the Player tree
        panel.subtree_filter = "Game World"
        roots = dpg.get_item_children(panel.content_tag, 1)
        assert len(roots) == 1
        player_tree_item = roots[0]
        player_children = dpg.get_item_children(player_tree_item, 1)
        # UI child should not be rendered under Player in Game World mode
        assert len(player_children) == 0

        # In 'UI & Tools' mode, the UI child is promoted as a root UI entity
        panel.subtree_filter = "UI & Tools"
        ui_roots = dpg.get_item_children(panel.content_tag, 1)
        assert len(ui_roots) == 1
        assert "NameplateUI" in dpg.get_item_configuration(ui_roots[0])["label"]

    def test_toolbar_create_ui_element_menu(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel = HierarchyPanel(session)
        panel.build()

        # Create UIContainer via toolbar helper
        container_id = panel.create_ui_element("UIContainer")
        assert not isinstance(container_id, Error)
        assert session.selected_entity_id == container_id
        comps = session.get_components(container_id)
        assert "UIContainer" in comps

        # Create UIButton under selected container
        btn_id = panel.create_ui_element("UIButton")
        assert not isinstance(btn_id, Error)
        assert session.selected_entity_id == btn_id
        assert kernel.get_entity_parent(btn_id) == container_id
        assert "UIButton" in session.get_components(btn_id)

    def test_hierarchy_search_query_combined_with_subtree_filter(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        session.create_entity(name="PlayfieldTerrain")
        session.create_entity(name="EnemySpawner")
        session.create_ui_entity(name="PlayButton", component_type="UIButton")
        session.select_entity(None)

        panel = HierarchyPanel(session)
        panel.build()

        # Search for 'Play' in 'Game World' mode
        panel.subtree_filter = "Game World"
        panel._filter_query = "play"
        panel.rebuild()

        labels = [
            dpg.get_item_configuration(c)["label"]
            for c in dpg.get_item_children(panel.content_tag, 1)
        ]
        # Should match PlayfieldTerrain, but NOT EnemySpawner or PlayButton (which is UI)
        assert any("PlayfieldTerrain" in l for l in labels)
        assert not any("EnemySpawner" in l for l in labels)
        assert not any("PlayButton" in l for l in labels)


class TestEditorAppUIBridgeIntegration:
    """Tests integration of UIBridgePanel within the complete EditorApp."""

    def test_editor_app_headless_ui_bridge_smoke(self, tmp_path):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="HudRoot", component_type="UIContainer")
        btn = session.create_ui_entity(name="FireBtn", component_type="UIButton", parent_id=root)
        kernel.save_dirty_resources()

        app = EditorApp(kernel=kernel, auto_build=True)
        try:
            app.ui_bridge_panel = UIBridgePanel(app.session)
            app.ui_bridge_panel.build()

            assert app.ui_bridge_panel is not None
            assert dpg.does_item_exist("window_ui_preview")
            assert dpg.is_item_shown("window_ui_preview")

            # Toggle window visibility via app method
            app.toggle_window("window_ui_preview")
            assert not dpg.is_item_shown("window_ui_preview")
            app.toggle_window("window_ui_preview")
            assert dpg.is_item_shown("window_ui_preview")

            # Verify UIBridgePanel content is alive inside app
            content_children = dpg.get_item_children(app.ui_bridge_panel.content_tag, 1)
            assert len(content_children) >= 1

            # Status bar reflects loaded entities
            assert dpg.does_item_exist("app_status_text")
            status = dpg.get_value("app_status_text")
            assert "Loaded Entities: 2" in status

        finally:
            app.destroy()
            assert not app._is_setup
            assert not app._viewport_created


class TestUIPersistenceRoundtripViaUIBridge:
    """Tests serialization, disk persistence, and reloaded rendering of UI components."""

    def test_ui_hierarchy_save_reload_bridge_render(self, tmp_path, dpg_context):
        # 1. Create and save UI hierarchy
        kernel1 = Kernel(tmp_path)
        session1 = EditorSession(kernel1)

        root = session1.create_ui_entity(
            name="DialogBox",
            component_type="UIContainer",
            component_props={"layout": "vertical", "collapsible": True},
        )
        btn = session1.create_ui_entity(
            name="OkBtn",
            component_type="UIButton",
            parent_id=root,
            component_props={"label": "Accept", "width": 80, "height": 30},
        )
        slider = session1.create_ui_entity(
            name="OpacitySlider",
            component_type="UISlider",
            parent_id=root,
            component_props={"label": "Opacity", "min": 0.0, "max": 1.0, "value": 0.95},
        )
        root_sid = kernel1.get_storage_id(root)
        btn_sid = kernel1.get_storage_id(btn)
        slider_sid = kernel1.get_storage_id(slider)

        session1.save_all_resources()

        # 2. Reload into fresh Kernel and EditorSession
        kernel2 = Kernel(tmp_path)
        loaded_root = kernel2.load_entity(root_sid)
        assert not isinstance(loaded_root, Error)

        session2 = EditorSession(kernel2)
        assert len(session2.get_all_resources()) >= 3

        # 3. Build UIBridgePanel and verify translated DPG widgets
        panel2 = UIBridgePanel(session2)
        panel2.build()

        c_header = dpg.get_item_children(panel2.content_tag, 1)[0]
        assert dpg.get_item_type(c_header) == "mvAppItemType::mvCollapsingHeader"
        assert dpg.get_item_configuration(c_header)["label"] == "DialogBox"

        children = dpg.get_item_children(c_header, 1)
        assert len(children) == 2

        btn_item, slider_item = children[0], children[1]
        assert dpg.get_item_type(btn_item) == "mvAppItemType::mvButton"
        assert dpg.get_item_configuration(btn_item)["label"] == "Accept"

        assert dpg.get_item_type(slider_item) == "mvAppItemType::mvSliderFloat"
        assert abs(dpg.get_value(slider_item) - 0.95) < 1e-4


class TestDynamicUIPanelWindowMountingAndLifecycle:
    """Tests dynamic Dear PyGui window mounting, hierarchy rendering, and lifecycle for UIPanel."""

    def test_uipanel_dynamic_window_creation_and_child_rendering(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel_eid = session.create_entity(
            name="QuickTools",
            components={
                "UIPanel": {"title": "Utility Tools", "width": 340.0, "height": 220.0, "closable": True},
            },
        )
        btn_eid = session.create_entity(
            name="HealAction",
            parent_id=panel_eid,
            components={
                "UIButton": {"label": "Heal Hero", "width": 140.0},
            },
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        win_tag = f"ui_panel_win_{panel_eid}"
        assert dpg.does_item_exist(win_tag), f"Expected dynamic window {win_tag} to exist"

        config = dpg.get_item_configuration(win_tag)
        assert config["label"] == "Utility Tools"
        assert config["width"] == 340
        assert config["height"] == 220

        # Verify child button rendered inside window
        win_children = dpg.get_item_children(win_tag, 1)
        assert len(win_children) == 1
        btn_tag = win_children[0]
        assert dpg.get_item_type(btn_tag) == "mvAppItemType::mvButton"
        assert dpg.get_item_configuration(btn_tag)["label"] == "Heal Hero"

    def test_uipanel_title_and_dimensions_fallback_to_entity_name(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel_eid = session.create_entity(
            name="PaletteWin",
            components={
                "UIPanel": {"title": "", "width": 310.0, "height": 210.0},
            },
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        win_tag = f"ui_panel_win_{panel_eid}"
        assert dpg.does_item_exist(win_tag)
        assert dpg.get_item_configuration(win_tag)["label"] == "PaletteWin"

    def test_uipanel_rebuild_reflects_mutations(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel_eid = session.create_entity(
            name="Tools",
            components={"UIPanel": {"title": "Original Title", "width": 300.0, "height": 200.0}},
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        win_tag = f"ui_panel_win_{panel_eid}"
        assert dpg.get_item_configuration(win_tag)["label"] == "Original Title"

        # Mutate title via tracked proxy
        proxy = kernel.get_entity_proxy(panel_eid)
        proxy.uipanel.title = "Refreshed Title"
        ui_bridge.rebuild()

        assert dpg.get_item_configuration(win_tag)["label"] == "Refreshed Title"

    def test_uipanel_entity_deletion_cleans_up_dpg_window(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel_eid = session.create_entity(
            name="EphemeralPanel",
            components={"UIPanel": {"title": "To Be Deleted", "width": 300.0, "height": 200.0}},
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        win_tag = f"ui_panel_win_{panel_eid}"
        assert dpg.does_item_exist(win_tag)
        assert panel_eid in ui_bridge._panel_windows

        # Delete entity and rebuild
        session.delete_entity(panel_eid)
        ui_bridge.rebuild()

        assert not dpg.does_item_exist(win_tag), "Window should be deleted from DPG"
        assert panel_eid not in ui_bridge._panel_windows

    def test_uipanel_close_callback_sets_minimized(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel_eid = session.create_entity(
            name="CloseableTools",
            components={"UIPanel": {"title": "Closable", "width": 300.0, "height": 200.0, "minimized": False}},
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        # Simulate user closing window via close callback
        ui_bridge._on_panel_closed(panel_eid)

        comp = session.get_components(panel_eid)["UIPanel"]
        assert comp["minimized"] is True
        assert kernel.is_dirty(panel_eid), "Resource should be marked dirty on close"

    def test_internal_workstation_panels_not_hijacked_as_runtime_windows(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        # Workstation panels use "Panel" with "panel_type": "hierarchy" / "inspector"
        hier_eid = session.create_entity(
            name="Hierarchy Panel",
            components={"Panel": {"title": "Hierarchy", "panel_type": "hierarchy", "minimized": False}},
        )
        insp_eid = session.create_entity(
            name="Inspector Panel",
            components={"Panel": {"title": "Inspector", "panel_type": "inspector", "minimized": False}},
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        assert not dpg.does_item_exist(f"ui_panel_win_{hier_eid}")
        assert not dpg.does_item_exist(f"ui_panel_win_{insp_eid}")
        assert hier_eid not in ui_bridge._panel_windows
        assert insp_eid not in ui_bridge._panel_windows

    def test_uipanel_not_rendered_as_nested_widget_inside_uicontainer(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        root = session.create_ui_entity(name="UIRoot", component_type="UIContainer")
        child_panel = session.create_entity(
            name="SubPanel",
            parent_id=root,
            components={"UIPanel": {"title": "Sub Panel", "width": 300.0, "height": 200.0}},
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        # It must mount as a top-level window
        assert dpg.does_item_exist(f"ui_panel_win_{child_panel}")

        # Inside content_tag (the mounted UIContainer), the subpanel must NOT be rendered as a nested child
        main_children = dpg.get_item_children(ui_bridge.content_tag, 1)
        # Content tag has the root UIContainer group
        if main_children:
            root_group = main_children[0]
            group_children = dpg.get_item_children(root_group, 1)
            # group_children should NOT contain any items because child_panel was skipped
            assert len(group_children) == 0

    def test_ui_bridge_destroy_cleans_up_all_panel_windows(self, tmp_path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        p1 = session.create_entity(name="P1", components={"UIPanel": {"title": "P1", "width": 300.0, "height": 200.0}})
        p2 = session.create_entity(name="P2", components={"UIPanel": {"title": "P2", "width": 300.0, "height": 200.0}})

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        assert dpg.does_item_exist(f"ui_panel_win_{p1}")
        assert dpg.does_item_exist(f"ui_panel_win_{p2}")

        ui_bridge.destroy()

        assert not dpg.does_item_exist(f"ui_panel_win_{p1}")
        assert not dpg.does_item_exist(f"ui_panel_win_{p2}")
        assert len(ui_bridge._panel_windows) == 0


class TestPlannedUIBridgeFeatures:
    """Planned tests for future UI Bridge capabilities."""

    @pytest.mark.skip(reason="Planned test: Two-way reactive data binding between ECS components and DPG input fields")
    def test_planned_two_way_data_binding(self):
        """When an external ECS system mutates a component, the active DPG input widget must update without losing focus."""
        pass

    @pytest.mark.skip(reason="Planned test: Undo/Redo stack for UI bridge widget modifications")
    def test_planned_ui_bridge_undo_redo_rollback(self):
        """Changes made to UI widgets in UIBridgePanel should be captured in an undo/redo command stack."""
        pass

    @pytest.mark.skip(reason="Planned test: Custom Dear PyGui widget component plugin registration")
    def test_planned_custom_dpg_widget_plugin_registry(self):
        """Allowing engine users to register custom DPG widgets corresponding to custom component types."""
        pass
