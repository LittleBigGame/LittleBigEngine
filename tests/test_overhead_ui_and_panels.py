"""Independent verification test suite for Overhead UI Billboarding and Dynamic UIPanels.

Derives tests from observable user requirements and kernel/editor contracts:
1. Dynamic UIPanel Window Mounting & Lifecycle (UIBridgePanel, rebuild, delete_entity, on_close).
2. World-Space Overhead UI Billboard Rendering (ViewportPanel, UISlider, UIText, UIButton, UIContainer).
   - Rotation locked at 0.0 deg (screen-aligned).
   - Suppression of standalone circle bodies/lines for child UI entities.
   - Color shifts for low health and clamping for out-of-bound values.
   - Click picking skips overhead UI entities.
3. End-to-End Persistence Roundtrip:
   - Full mutation tracking, save to disk, reload in fresh Kernel and EditorSession.
   - Verification that both ViewportPanel billboards and UIBridge dynamic windows render accurately from reloaded state.
4. Planned Features:
   - 3D billboard matrix projection, dynamic docking serialization, stale handle safety, hot reload rollback.
"""

from __future__ import annotations

import math
from pathlib import Path
import dearpygui.dearpygui as dpg
import pytest

from editor.app import EditorApp
from editor.session import EditorSession
from editor.ui_bridge import UIBridgePanel
from editor.viewport_panel import ViewportPanel
from LBE import Error, Kernel, Script, UI_SCHEMAS, Validate
from LBE.types import InvalidResourceDataError, RuntimeID
from main import populate_demo_world_if_empty


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


def _normalize_rgba(color: Any) -> list[float] | None:
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        return None
    is_255 = any(c > 1.0 for c in color)
    return [float(c) / 255.0 if is_255 else float(c) for c in color]


def colors_match(c1: Any, c2: Any, tol: float = 0.03) -> bool:
    """Helper to compare DPG normalized colors [0.0..1.0] with 0..255 ints or 0.0..1.0 floats."""
    n1 = _normalize_rgba(c1)
    n2 = _normalize_rgba(c2)
    if n1 is None or n2 is None or len(n1) != len(n2):
        return False
    return all(abs(a - b) < tol for a, b in zip(n1, n2))


class TestOverheadUIBillboardSceneView:
    """Tests world-space overhead UI billboarding in ViewportPanel."""

    def test_player_with_healthbar_overhead_billboard_rendering(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="Player",
            components={
                "Transform": {"x": 100.0, "y": 100.0, "rot_z": 45.0},
            },
        )
        healthbar = session.create_child_entity(
            parent_id=player,
            name="HealthBar",
            components={
                "Transform": {"x": 0.0, "y": -20.0},
                "UISlider": {"value": 0.75, "label": "HP"},
            },
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        assert len(items) > 0

        # Find draw rectangle items
        rects = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawRect"]
        # Draw background and fill for the slider (plus canvas background rect)
        assert len(rects) >= 3

        # Background slider rect: dark fill (20, 20, 20, 220)
        bg_rects = [r for r in rects if colors_match(dpg.get_item_configuration(r).get("fill"), (20, 20, 20, 220))]
        assert len(bg_rects) == 1
        bg_cfg = dpg.get_item_configuration(bg_rects[0])

        # Width should be 40.0 * cam_zoom (default zoom 1.0 = 40.0), height 5.0
        pmin = bg_cfg["pmin"]
        pmax = bg_cfg["pmax"]
        width = pmax[0] - pmin[0]
        height = pmax[1] - pmin[1]
        assert abs(width - 40.0) < 1e-3
        assert abs(height - 5.0) < 1e-3

        # Fill slider rect: value is 0.75 (> 0.25) -> green fill (50, 215, 80, 230)
        fill_rects = [r for r in rects if colors_match(dpg.get_item_configuration(r).get("fill"), (50, 215, 80, 230))]
        assert len(fill_rects) == 1

        # Text label "HP"
        texts = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawText"]
        hp_texts = [t for t in texts if dpg.get_item_configuration(t).get("text") == "HP"]
        assert len(hp_texts) == 1

    def test_overhead_ui_child_suppresses_body_circle_and_hierarchy_line(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="Hero",
            components={"Transform": {"x": 50.0, "y": 50.0}},
        )
        session.create_child_entity(
            parent_id=player,
            name="HeroHP",
            components={
                "Transform": {"x": 0.0, "y": -20.0},
                "UISlider": {"value": 1.0, "label": "HP"},
            },
        )
        session.create_child_entity(
            parent_id=player,
            name="HeroNameTag",
            components={
                "Transform": {"x": 0.0, "y": -30.0},
                "UIText": {"content": "HeroTag"},
            },
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)

        # There should be exactly 1 body circle in the drawlist: the player
        circles = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawCircle"]
        assert len(circles) == 1

        # There should NOT be any hierarchy connection line linking parent to overhead UI child
        # Hierarchy lines have color (80, 160, 220, 130)
        lines = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawLine"]
        hier_lines = [l for l in lines if colors_match(dpg.get_item_configuration(l).get("color"), (80, 160, 220, 130))]
        assert len(hier_lines) == 0

    def test_overhead_ui_rotation_locked_screen_aligned(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="TiltedPlayer",
            components={"Transform": {"x": 120.0, "y": 120.0, "rot_z": 77.5}},
        )
        session.create_child_entity(
            parent_id=player,
            name="TiltedHP",
            components={
                "Transform": {"x": 0.0, "y": -22.0},
                "UISlider": {"value": 0.6, "label": "HP"},
            },
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)

        # Verify parent rotation indicator line has angle 77.5 deg
        lines = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawLine"]
        heading_lines = [l for l in lines if colors_match(dpg.get_item_configuration(l).get("color"), (255, 255, 255, 220))]
        assert len(heading_lines) == 1
        hcfg = dpg.get_item_configuration(heading_lines[0])
        p1 = hcfg["p1"]
        p2 = hcfg["p2"]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        angle_deg = math.degrees(math.atan2(dy, dx))
        assert abs(angle_deg - 77.5) < 1.0

        # Verify overhead UI slider rect is axis-aligned (strictly horizontal AABB)
        rects = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawRect"]
        bg_rects = [r for r in rects if colors_match(dpg.get_item_configuration(r).get("fill"), (20, 20, 20, 220))]
        assert len(bg_rects) == 1
        rcfg = dpg.get_item_configuration(bg_rects[0])
        pmin = rcfg["pmin"]
        pmax = rcfg["pmax"]
        assert pmin[0] < pmax[0]
        assert pmin[1] < pmax[1]
        assert abs((pmax[0] - pmin[0]) - 40.0) < 1e-3
        assert abs((pmax[1] - pmin[1]) - 5.0) < 1e-3

    def test_overhead_ui_name_tag_text_billboard(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="Player",
            components={"Transform": {"x": 200.0, "y": 150.0}},
        )
        session.create_child_entity(
            parent_id=player,
            name="PlayerNameTag",
            components={
                "Transform": {"x": 0.0, "y": -26.0},
                "UIText": {"content": "Champion of Light"},
            },
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        texts = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawText"]
        name_tag_items = [t for t in texts if dpg.get_item_configuration(t).get("text") == "Champion of Light"]
        assert len(name_tag_items) == 1
        tcfg = dpg.get_item_configuration(name_tag_items[0])
        assert colors_match(tcfg["color"], (240, 240, 250, 230))

    def test_overhead_ui_interact_button_badge_billboard(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        npc = session.create_entity(
            name="Blacksmith",
            components={"Transform": {"x": 250.0, "y": 180.0}},
        )
        session.create_child_entity(
            parent_id=npc,
            name="InteractPrompt",
            components={
                "Transform": {"x": 0.0, "y": -24.0},
                "UIButton": {"label": "Interact"},
            },
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)

        # Button badge rect has fill (0, 120, 255, 200)
        rects = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawRect"]
        btn_rects = [r for r in rects if colors_match(dpg.get_item_configuration(r).get("fill"), (0, 120, 255, 200))]
        assert len(btn_rects) == 1
        b_cfg = dpg.get_item_configuration(btn_rects[0])
        assert b_cfg["rounding"] == 3.0

        # Button label text "[Interact]"
        texts = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawText"]
        btn_texts = [t for t in texts if dpg.get_item_configuration(t).get("text") == "[Interact]"]
        assert len(btn_texts) == 1

    def test_overhead_ui_nested_container_rendering(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="Player",
            components={"Transform": {"x": 200.0, "y": 150.0}},
        )
        container = session.create_child_entity(
            parent_id=player,
            name="OverheadHUD",
            components={
                "Transform": {"x": 0.0, "y": -25.0},
                "UIContainer": {"layout": "vertical"},
            },
        )
        session.create_child_entity(
            parent_id=container,
            name="HUDTitle",
            components={"UIText": {"content": "Level 99"}},
        )
        session.create_child_entity(
            parent_id=container,
            name="HUDMana",
            components={"UISlider": {"label": "MP", "value": 0.9}},
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        texts = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawText"]

        assert any(dpg.get_item_configuration(t).get("text") == "Level 99" for t in texts)
        assert any(dpg.get_item_configuration(t).get("text") == "MP" for t in texts)

    def test_overhead_ui_missing_transform_fallback_offset(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="Player",
            components={"Transform": {"x": 200.0, "y": 150.0}},
        )
        # Overhead UI entity without Transform component
        session.create_child_entity(
            parent_id=player,
            name="UntransformedHP",
            components={"UISlider": {"label": "HP", "value": 0.5}},
        )

        vp = ViewportPanel(session)
        vp.build()
        # Should not raise exception; falls back to dx=0, dy=-22
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        texts = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawText"]
        assert any(dpg.get_item_configuration(t).get("text") == "HP" for t in texts)

    def test_overhead_ui_slider_value_clamping_and_low_health_color(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        # 1. Low health (value <= 0.25) -> Red fill (235, 60, 60, 230)
        e1 = session.create_entity(name="LowHealthGuy", components={"Transform": {"x": 100.0, "y": 100.0}})
        session.create_child_entity(
            parent_id=e1,
            name="HP1",
            components={"UISlider": {"value": 0.20}},
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        rects = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawRect"]
        red_fills = [r for r in rects if colors_match(dpg.get_item_configuration(r).get("fill"), (235, 60, 60, 230))]
        assert len(red_fills) == 1

        # 2. Clamping: value > 1.0 clamped to 1.0, value < 0.0 clamped to 0.0
        hp_child = session.get_children(e1)[0]
        proxy_hp = kernel.get_entity_proxy(hp_child)

        # Over 1.0
        proxy_hp.uislider.value = 5.0
        vp.redraw()
        items2 = dpg.get_item_children(vp.drawlist_tag, 2)
        green_fills = [r for r in items2 if dpg.get_item_type(r) == "mvAppItemType::mvDrawRect"]
        green_fill_matched = [r for r in green_fills if colors_match(dpg.get_item_configuration(r).get("fill"), (50, 215, 80, 230))]
        assert len(green_fill_matched) == 1
        cfg = dpg.get_item_configuration(green_fill_matched[0])
        w = cfg["pmax"][0] - cfg["pmin"][0]
        assert abs(w - 38.0) < 1e-3

        # Under 0.0
        proxy_hp.uislider.value = -1.0
        vp.redraw()
        items3 = dpg.get_item_children(vp.drawlist_tag, 2)
        inner_fills = [
            r for r in items3
            if dpg.get_item_type(r) == "mvAppItemType::mvDrawRect"
            and (
                colors_match(dpg.get_item_configuration(r).get("fill"), (235, 60, 60, 230))
                or colors_match(dpg.get_item_configuration(r).get("fill"), (50, 215, 80, 230))
            )
        ]
        assert len(inner_fills) == 0

    def test_overhead_ui_canvas_click_picking_does_not_select_child_as_body(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        player = session.create_entity(
            name="Player",
            components={"Transform": {"x": 200.0, "y": 150.0}},
        )
        child_ui = session.create_child_entity(
            parent_id=player,
            name="HPBar",
            components={
                "Transform": {"x": 0.0, "y": -20.0},
                "UISlider": {"value": 0.8},
            },
        )

        vp = ViewportPanel(session)
        vp.build()

        session.select_entity(None)
        original_get_mouse_pos = dpg.get_mouse_pos
        original_get_item_rect_min = dpg.get_item_rect_min

        try:
            dpg.get_mouse_pos = lambda local=False: (330.0, 210.0)
            dpg.get_item_rect_min = lambda item: [0.0, 0.0]
            vp._on_canvas_left_click()
            assert session.selected_entity_id == player

            # Now click near the child overhead UI position (330, 190)
            session.select_entity(None)
            dpg.get_mouse_pos = lambda local=False: (330.0, 190.0)
            vp._on_canvas_left_click()
            # Must NOT select child_ui as an entity body circle
            assert session.selected_entity_id != child_ui
        finally:
            dpg.get_mouse_pos = original_get_mouse_pos
            dpg.get_item_rect_min = original_get_item_rect_min

    def test_demo_world_overhead_ui_and_quick_tools_smoke(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        populate_demo_world_if_empty(kernel)
        session = EditorSession(kernel)

        # 1. ViewportPanel smoke
        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        texts = [dpg.get_item_configuration(t).get("text") for t in items if dpg.get_item_type(t) == "mvAppItemType::mvDrawText"]

        assert "HP" in texts
        assert "Hero" in texts

        # QuickTools removed from demo world
        quick_tools_rids = [
            rid for rid in session.kernel.resources
            if session.kernel.is_entity(rid) and session.get_entity_name(rid) == "QuickTools"
        ]
        assert len(quick_tools_rids) == 0


class TestOverheadUIAndPanelPersistenceRoundtrip:
    """Tests persistence roundtrip and JSON serialization for UIPanel and overhead UI elements."""

    def test_e2e_uipanel_and_overhead_ui_mutation_save_and_reload(self, tmp_path: Path, dpg_context):
        # 1. First session: create entities and dynamic UI elements
        kernel1 = Kernel(tmp_path)
        session1 = EditorSession(kernel1)

        player_eid = session1.create_entity(
            name="PlayerHero",
            components={"Transform": {"x": 100.0, "y": 150.0, "rot_z": 0.0}},
        )
        hp_eid = session1.create_child_entity(
            parent_id=player_eid,
            name="HeroHP",
            components={
                "Transform": {"x": 0.0, "y": -20.0},
                "UISlider": {"value": 0.85, "label": "HP"},
            },
        )
        nametag_eid = session1.create_child_entity(
            parent_id=player_eid,
            name="HeroTag",
            components={
                "Transform": {"x": 0.0, "y": -30.0},
                "UIText": {"content": "Champion"},
            },
        )
        tools_eid = session1.create_entity(
            name="CustomTools",
            components={
                "UIPanel": {"title": "Custom Tools", "width": 320.0, "height": 240.0, "closable": True},
            },
        )
        btn_eid = session1.create_child_entity(
            parent_id=tools_eid,
            name="ActionBtn",
            components={
                "UIButton": {"label": "Cast Spell", "width": 160.0},
            },
        )

        player_sid = kernel1.get_storage_id(player_eid)
        hp_sid = kernel1.get_storage_id(hp_eid)
        nametag_sid = kernel1.get_storage_id(nametag_eid)
        tools_sid = kernel1.get_storage_id(tools_eid)
        btn_sid = kernel1.get_storage_id(btn_eid)

        # Mutate components via EntityProxy
        tools_proxy = kernel1.get_entity_proxy(tools_eid)
        tools_proxy.uipanel.title = "Enchanted Tools"
        tools_proxy.uipanel.width = 420.0

        hp_proxy = kernel1.get_entity_proxy(hp_eid)
        hp_proxy.uislider.value = 0.45

        tag_proxy = kernel1.get_entity_proxy(nametag_eid)
        tag_proxy.uitext.content = "Grand Champion"

        assert kernel1.is_dirty(tools_eid)
        assert kernel1.is_dirty(hp_eid)
        assert kernel1.is_dirty(nametag_eid)

        # Save all dirty resources to disk
        save_res = kernel1.save_dirty_resources()
        assert not isinstance(save_res, Error)

        # 2. Reload into clean Kernel and EditorSession
        kernel2 = Kernel(tmp_path)
        p_loaded = kernel2.load_entity(player_sid)
        hp_loaded = kernel2.load_entity(hp_sid)
        tag_loaded = kernel2.load_entity(nametag_sid)
        tools_loaded = kernel2.load_entity(tools_sid)
        btn_loaded = kernel2.load_entity(btn_sid)

        assert not isinstance(p_loaded, Error)
        assert not isinstance(hp_loaded, Error)
        assert not isinstance(tag_loaded, Error)
        assert not isinstance(tools_loaded, Error)
        assert not isinstance(btn_loaded, Error)

        session2 = EditorSession(kernel2)

        # Verify mutated values persisted cleanly
        tools_comp = session2.get_components(tools_loaded)["UIPanel"]
        assert tools_comp["title"] == "Enchanted Tools"
        assert tools_comp["width"] == 420.0

        hp_comp = session2.get_components(hp_loaded)["UISlider"]
        assert abs(hp_comp["value"] - 0.45) < 1e-4

        tag_comp = session2.get_components(tag_loaded)["UIText"]
        assert tag_comp["content"] == "Grand Champion"

        # 3. Mount in ViewportPanel and UIBridgePanel in the fresh session
        vp2 = ViewportPanel(session2)
        vp2.build()
        vp2.redraw()

        items2 = dpg.get_item_children(vp2.drawlist_tag, 2)
        texts2 = [dpg.get_item_configuration(t).get("text") for t in items2 if dpg.get_item_type(t) == "mvAppItemType::mvDrawText"]
        assert "Grand Champion" in texts2
        assert "HP" in texts2

        ui_bridge2 = UIBridgePanel(session2)
        ui_bridge2.build()

        win_tag2 = f"ui_panel_win_{tools_loaded}"
        assert dpg.does_item_exist(win_tag2)
        cfg2 = dpg.get_item_configuration(win_tag2)
        assert cfg2["label"] == "Enchanted Tools"
        assert cfg2["width"] == 420

        children2 = dpg.get_item_children(win_tag2, 1)
        assert len(children2) == 1
        assert dpg.get_item_configuration(children2[0])["label"] == "Cast Spell"


class TestRemediations:
    """Regression tests for the 5 review remediations."""

    def test_uipanel_minimized_and_closable_window_configuration(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        panel = session.create_entity(
            name="ConfigPanel",
            components={
                "UIPanel": {
                    "title": "Options",
                    "width": 300.0,
                    "height": 200.0,
                    "minimized": True,
                    "closable": False,
                }
            },
        )

        ui_bridge = UIBridgePanel(session)
        ui_bridge.build()

        win_tag = f"ui_panel_win_{panel}"
        assert dpg.does_item_exist(win_tag)
        cfg = dpg.get_item_configuration(win_tag)
        assert cfg.get("show") is False
        assert cfg.get("no_close") is True

        # Update panel to unminimized and closable, then rebuild
        session.mutate_component(panel, "UIPanel", {"minimized": False, "closable": True})
        ui_bridge.rebuild()

        cfg_updated = dpg.get_item_configuration(win_tag)
        assert cfg_updated.get("show") is True
        assert cfg_updated.get("no_close") is False

        ui_bridge.destroy()

    def test_overhead_ui_container_vertical_stacking_with_gap(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        parent = session.create_entity(
            name="Actor",
            components={"Transform": {"x": 200.0, "y": 150.0}},
        )
        container = session.create_child_entity(
            parent_id=parent,
            name="StackContainer",
            components={
                "Transform": {"x": 0.0, "y": -50.0},
                "UIContainer": {"gap": 8.0},
            },
        )
        session.create_child_entity(
            parent_id=container,
            name="Line1",
            components={"UIText": {"content": "First Item"}},
        )
        session.create_child_entity(
            parent_id=container,
            name="Line2",
            components={"UIText": {"content": "Second Item"}},
        )
        session.create_child_entity(
            parent_id=container,
            name="Line3",
            components={
                "Transform": {"x": 10.0, "y": 5.0},
                "UIText": {"content": "Third Item"},
            },
        )

        vp = ViewportPanel(session)
        vp.build()
        vp.redraw()

        items = dpg.get_item_children(vp.drawlist_tag, 2)
        texts = [it for it in items if dpg.get_item_type(it) == "mvAppItemType::mvDrawText"]

        t1 = next(t for t in texts if dpg.get_item_configuration(t).get("text") == "First Item")
        t2 = next(t for t in texts if dpg.get_item_configuration(t).get("text") == "Second Item")
        t3 = next(t for t in texts if dpg.get_item_configuration(t).get("text") == "Third Item")

        y1 = dpg.get_item_configuration(t1)["pos"][1]
        y2 = dpg.get_item_configuration(t2)["pos"][1]
        y3 = dpg.get_item_configuration(t3)["pos"][1]

        # Verify items are stacked vertically rather than drawn on the exact same pixel
        assert y2 > y1
        assert abs((y2 - y1) - (14.0 * 1.0 + 8.0)) < 1e-3
        # Third item has local Transform offset y=5.0 plus advanced baseline
        assert y3 > y2

        vp.destroy()

    def test_overhead_ui_circular_hierarchy_protection(self, tmp_path: Path, dpg_context):
        kernel = Kernel(tmp_path)
        session = EditorSession(kernel)

        parent = session.create_entity(
            name="EntityA",
            components={"Transform": {"x": 100.0, "y": 100.0}},
        )
        c1 = session.create_child_entity(
            parent_id=parent,
            name="Container1",
            components={"UIContainer": {"gap": 4.0}},
        )
        c2 = session.create_child_entity(
            parent_id=c1,
            name="Container2",
            components={"UIContainer": {"gap": 4.0}},
        )
        # Artificially inject cycle: c2 has child c1
        kernel.resources[c2]["data"]["children"].append(c1)

        vp = ViewportPanel(session)
        vp.build()
        # Must not raise RecursionError
        vp.redraw()
        vp.destroy()

    def test_viewport_panel_and_editor_app_destroy(self, tmp_path: Path, dpg_context):
        app = EditorApp(folder_location=tmp_path)
        vp = app.viewport_panel
        bridge = UIBridgePanel(app.session)
        bridge.build()
        app.ui_bridge_panel = bridge

        assert vp is not None
        assert bridge is not None
        assert vp._unsubscribe_state is not None
        assert vp._unsubscribe_selection is not None
        assert vp._unsubscribe_tick is not None
        assert vp._unsubscribe_play is not None

        # Clean up via app.destroy
        app.destroy()

        assert vp._unsubscribe_state is None
        assert vp._unsubscribe_selection is None
        assert vp._unsubscribe_tick is None
        assert vp._unsubscribe_play is None

        # Idempotent second destroy call
        vp.destroy()
        bridge.destroy()


class TestPlannedOverheadUIAndPanelFeatures:
    """Planned tests for future overhead UI and dynamic panel capabilities."""

    @pytest.mark.skip(reason="Planned test: 3D billboard matrix projection for overhead UI under perspective camera")
    def test_planned_3d_billboard_matrix_projection(self):
        """Under a perspective 3D projection, overhead UI widgets must rotate to always face the camera viewport."""
        pass

    @pytest.mark.skip(reason="Planned test: Dynamic runtime docking state persistence for UIPanel windows across sessions")
    def test_planned_uipanel_docking_layout_serialization(self):
        """DPG docking layouts and floating window coordinates for UIPanel should persist in project settings."""
        pass

    @pytest.mark.skip(reason="Planned test: Stale handle safety when dynamic UIPanel window triggers an event after entity deletion")
    def test_planned_uipanel_stale_handle_safety_on_async_dpg_event(self):
        """Async DPG callbacks arriving after an entity is deleted from memory must be safely ignored without raising exceptions."""
        pass

    @pytest.mark.skip(reason="Planned test: Hot-reload rollback preserves previous UIPanel state on script syntax error")
    def test_planned_uipanel_script_hot_reload_syntax_error_rollback(self):
        """Syntax errors in scripts driving dynamic UIPanel widgets should roll back to the previous valid bytecode."""
        pass