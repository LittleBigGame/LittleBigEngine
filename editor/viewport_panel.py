"""Viewport panel rendering an interactive 2D/3D Scene View with simulation playback."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any
import dearpygui.dearpygui as dpg

from LBE.types import RuntimeID
from .session import EditorSession

KEY_MAP: dict[int, str] = {
    getattr(dpg, "mvKey_W", 87): "W",
    getattr(dpg, "mvKey_S", 83): "S",
    getattr(dpg, "mvKey_A", 65): "A",
    getattr(dpg, "mvKey_D", 68): "D",
    getattr(dpg, "mvKey_Up", 38): "UP",
    getattr(dpg, "mvKey_Down", 40): "DOWN",
    getattr(dpg, "mvKey_Left", 37): "LEFT",
    getattr(dpg, "mvKey_Right", 39): "RIGHT",
    getattr(dpg, "mvKey_Spacebar", 32): "SPACE",
}
if hasattr(dpg, "mvKey_Space"):
    KEY_MAP[getattr(dpg, "mvKey_Space")] = "SPACE"


class ViewportPanel:
    """Dockable panel hosting the real-time Scene View canvas and simulation controls."""

    def __init__(self, session: EditorSession, tag: str = "window_viewport") -> None:
        self.session = session
        self.tag = tag
        self.canvas_tag = f"{self.tag}_canvas"
        self.drawlist_tag = f"{self.tag}_drawlist"
        self.play_btn_tag = f"{self.tag}_play_btn"
        self.time_text_tag = f"{self.tag}_time_text"
        self.speed_combo_tag = f"{self.tag}_speed_combo"

        # General Camera Setup (World Focus Point and Zoom)
        self.cam_focus_x: float = 200.0
        self.cam_focus_y: float = 150.0
        self.cam_zoom: float = 1.0

        # Cached canvas dimensions
        self._last_cw: float = 660.0
        self._last_ch: float = 420.0

        # Mouse panning state
        self._is_panning: bool = False
        self._pan_start_mouse: tuple[float, float] = (0.0, 0.0)
        self._pan_start_focus: tuple[float, float] = (0.0, 0.0)

        self._unsubscribe_state = self.session.subscribe_state_changed(self.redraw)
        self._unsubscribe_selection = self.session.subscribe_selection_changed(
            lambda _: self.redraw()
        )
        self._unsubscribe_tick = self.session.subscribe_tick(lambda _: self.on_tick())
        self._unsubscribe_play = self.session.subscribe_play_changed(self._on_play_changed)

    def focus_entity(self, entity_id: RuntimeID) -> None:
        """Center the viewport camera on the specified entity's Transform position."""
        if not self.session.kernel.is_entity(entity_id):
            return
        comps = self.session.get_components(entity_id)
        transform = comps.get("Transform", {})
        if "x" in transform and "y" in transform:
            self.cam_focus_x = float(transform["x"])
            self.cam_focus_y = float(transform["y"])
            self.redraw()

    def build(self) -> str:
        """Create the Scene View window and controls."""
        with dpg.window(
            label="Scene View",
            tag=self.tag,
            width=680,
            height=500,
            pos=(320, 30),
        ):
            # Simulation Controls Toolbar
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="> Play",
                    tag=self.play_btn_tag,
                    callback=self._on_toggle_play,
                    width=75,
                )
                dpg.add_button(
                    label=">> Step",
                    callback=self._on_step,
                    width=65,
                )
                dpg.add_button(
                    label="Reset View",
                    callback=self._on_reset_cam,
                    width=85,
                )
                dpg.add_spacer(width=10)
                dpg.add_text("Speed:")
                dpg.add_combo(
                    items=["0.25x", "0.5x", "1.0x", "2.0x", "5.0x"],
                    default_value="1.0x",
                    width=75,
                    tag=self.speed_combo_tag,
                    callback=self._on_speed_changed,
                )
                dpg.add_spacer(width=10)
                dpg.add_text("Time: 0.00s", tag=self.time_text_tag, color=(160, 210, 255))

            dpg.add_separator()

            # Interactive 2D Scene Canvas
            with dpg.child_window(
                tag=self.canvas_tag,
                autosize_x=True,
                autosize_y=True,
                no_scrollbar=True,
                no_scroll_with_mouse=True,
            ):
                with dpg.drawlist(
                    tag=self.drawlist_tag,
                    width=660,
                    height=420,
                ):
                    pass

                # Canvas Click Handlers
                with dpg.item_handler_registry() as registry:
                    dpg.add_item_clicked_handler(
                        button=0, callback=self._on_canvas_left_click
                    )
                dpg.bind_item_handler_registry(self.drawlist_tag, registry)

            # Global mouse wheel and drag handler for smooth zoom and pan
            handler_reg_tag = f"{self.tag}_input_handlers"
            if not dpg.does_item_exist(handler_reg_tag):
                with dpg.handler_registry(tag=handler_reg_tag):
                    dpg.add_mouse_wheel_handler(callback=self._on_mouse_wheel)
                    dpg.add_mouse_drag_handler(button=1, callback=self._on_mouse_drag)
                    dpg.add_mouse_drag_handler(button=2, callback=self._on_mouse_drag)
                    dpg.add_key_down_handler(callback=self._on_key_down)
                    dpg.add_key_release_handler(callback=self._on_key_release)

        self.redraw()
        return self.tag

    def on_tick(self) -> None:
        """Called whenever simulation advances."""
        if dpg.does_item_exist(self.time_text_tag):
            dpg.set_value(self.time_text_tag, f"Time: {self.session.sim_time:.2f}s")
        self.redraw()

    def _on_toggle_play(self) -> None:
        self.session.toggle_play()

    def _on_play_changed(self, is_playing: bool) -> None:
        if dpg.does_item_exist(self.play_btn_tag):
            label = "|| Pause" if is_playing else "> Play"
            dpg.configure_item(self.play_btn_tag, label=label)

    def _on_step(self) -> None:
        self.session.step_simulation(1.0 / 60.0)

    def _on_reset_cam(self) -> None:
        self.cam_focus_x = 200.0
        self.cam_focus_y = 150.0
        self.cam_zoom = 1.0
        self.redraw()

    def _on_speed_changed(self, sender: str | int, app_data: str) -> None:
        try:
            val = float(app_data.replace("x", ""))
            self.session.sim_speed = val
        except ValueError:
            pass

    def _world_to_screen(self, wx: float, wy: float, cw: float, ch: float) -> tuple[float, float]:
        """Convert world coordinates to screen pixels centered on the camera focus point."""
        sx = (cw * 0.5) + (wx - self.cam_focus_x) * self.cam_zoom
        sy = (ch * 0.5) + (wy - self.cam_focus_y) * self.cam_zoom
        return (sx, sy)

    def _screen_to_world(self, sx: float, sy: float, cw: float, ch: float) -> tuple[float, float]:
        """Convert screen pixels back to world coordinates."""
        wx = self.cam_focus_x + (sx - cw * 0.5) / self.cam_zoom
        wy = self.cam_focus_y + (sy - ch * 0.5) / self.cam_zoom
        return (wx, wy)

    def _is_mouse_over_canvas(self) -> bool:
        if not dpg.does_item_exist(self.drawlist_tag):
            return False
        min_pos = dpg.get_item_rect_min(self.drawlist_tag)
        size = dpg.get_item_rect_size(self.drawlist_tag)
        mx, my = dpg.get_mouse_pos(local=False)
        return (
            min_pos[0] <= mx <= min_pos[0] + size[0]
            and min_pos[1] <= my <= min_pos[1] + size[1]
        )

    def _on_mouse_wheel(self, sender: str | int, app_data: float) -> None:
        """Zoom in or out centered on the current camera focus when hovering over canvas."""
        if not self._is_mouse_over_canvas():
            return
        zoom_factor = 1.15 if app_data > 0 else (1.0 / 1.15)
        new_zoom = max(0.1, min(10.0, self.cam_zoom * zoom_factor))
        self.cam_zoom = new_zoom
        self.redraw()

    def _on_mouse_drag(self, sender: str | int, app_data: Any) -> None:
        """Pan the camera focus point when right-click or middle-click dragging."""
        if not self._is_mouse_over_canvas():
            return
        button, dx, dy = app_data[0], app_data[1], app_data[2]
        # In Dear PyGui mouse drag: dx, dy is delta movement
        self.cam_focus_x -= dx / self.cam_zoom
        self.cam_focus_y -= dy / self.cam_zoom
        dpg.reset_mouse_drag_delta(button)
        self.redraw()

    def _on_key_down(self, sender: str | int = 0, app_data: Any = 0) -> None:
        key_code = app_data[0] if isinstance(app_data, (list, tuple)) and app_data else app_data
        key = KEY_MAP.get(key_code)
        if key and hasattr(self.session.kernel, "input_state"):
            keys = self.session.kernel.input_state.get("keys")
            if isinstance(keys, set):
                keys.add(key)

    def _on_key_release(self, sender: str | int = 0, app_data: Any = 0) -> None:
        key_code = app_data[0] if isinstance(app_data, (list, tuple)) and app_data else app_data
        key = KEY_MAP.get(key_code)
        if key and hasattr(self.session.kernel, "input_state"):
            keys = self.session.kernel.input_state.get("keys")
            if isinstance(keys, set):
                keys.discard(key)

    def redraw(self) -> None:
        """Clear and redraw the canvas with grid, axes, and entities."""
        if not dpg.does_item_exist(self.drawlist_tag):
            return

        # Adapt drawlist dynamically to the actual rendered container size
        rect_size = dpg.get_item_rect_size(self.canvas_tag)
        cw = float(rect_size[0]) if rect_size and rect_size[0] > 0 else self._last_cw
        ch = float(rect_size[1]) if rect_size and rect_size[1] > 0 else self._last_ch
        cw = max(50.0, cw)
        ch = max(50.0, ch)
        self._last_cw = cw
        self._last_ch = ch

        dpg.configure_item(self.drawlist_tag, width=int(cw), height=int(ch))
        dpg.delete_item(self.drawlist_tag, children_only=True)

        w = cw
        h = ch

        # 1. Background dark canvas
        dpg.draw_rectangle(
            pmin=(0, 0),
            pmax=(w, h),
            fill=(18, 20, 24, 255),
            color=(30, 32, 38, 255),
            parent=self.drawlist_tag,
        )

        # 2. Dynamic Centered Coordinate Grid
        grid_step = max(20.0, 50.0 * self.cam_zoom)
        origin_sx, origin_sy = self._world_to_screen(0.0, 0.0, w, h)

        # Vertical grid lines
        start_x = origin_sx % grid_step
        curr_x = start_x
        while curr_x < w:
            dpg.draw_line(
                p1=(curr_x, 0),
                p2=(curr_x, h),
                color=(28, 32, 42, 180),
                thickness=1.0,
                parent=self.drawlist_tag,
            )
            curr_x += grid_step

        # Horizontal grid lines
        start_y = origin_sy % grid_step
        curr_y = start_y
        while curr_y < h:
            dpg.draw_line(
                p1=(0, curr_y),
                p2=(w, curr_y),
                color=(28, 32, 42, 180),
                thickness=1.0,
                parent=self.drawlist_tag,
            )
            curr_y += grid_step

        # 3. Origin Axes (X: Red, Y: Green)
        if 0 <= origin_sy <= h:
            dpg.draw_line(
                p1=(0, origin_sy),
                p2=(w, origin_sy),
                color=(190, 65, 65, 170),
                thickness=1.5,
                parent=self.drawlist_tag,
            )
        if 0 <= origin_sx <= w:
            dpg.draw_line(
                p1=(origin_sx, 0),
                p2=(origin_sx, h),
                color=(65, 190, 85, 170),
                thickness=1.5,
                parent=self.drawlist_tag,
            )

        # 4. Render Hierarchy Connection Lines
        for rid, res in list(self.session.kernel.resources.items()):
            if not self.session.kernel.is_entity(rid):
                continue
            parent_id = self.session.kernel.get_entity_parent(rid)
            if parent_id is not None and parent_id in self.session.kernel.resources:
                if self._is_overhead_ui_entity(self.session.get_components(rid)):
                    continue
                p_transform = self._get_entity_transform(parent_id)
                c_transform = self._get_entity_transform(rid)
                if p_transform and c_transform:
                    psx, psy = self._world_to_screen(p_transform["x"], p_transform["y"], w, h)
                    csx, csy = self._world_to_screen(c_transform["x"], c_transform["y"], w, h)
                    dpg.draw_line(
                        p1=(psx, psy),
                        p2=(csx, csy),
                        color=(80, 160, 220, 130),
                        thickness=1.5,
                        parent=self.drawlist_tag,
                    )

        # 5. Render Entities
        for rid, res in list(self.session.kernel.resources.items()):
            if not self.session.kernel.is_entity(rid):
                continue
            self._render_entity(rid, res, w, h)

    def _is_overhead_ui_entity(self, comps: dict[str, Any]) -> bool:
        ui_types = {"uislider", "slider", "uitext", "text", "uibutton", "button", "uicontainer", "container"}
        return any(k.lower() in ui_types for k in comps)

    def _get_ui_comp(self, comps: dict[str, Any], type_name: str) -> dict[str, Any] | None:
        target = type_name.lower()
        alias = target[2:] if target.startswith("ui") else f"ui{target}"
        for k, v in comps.items():
            kl = k.lower()
            if (kl == target or kl == alias) and isinstance(v, Mapping):
                return v
        return None

    def _get_entity_transform(self, entity_id: RuntimeID) -> dict[str, float] | None:
        comps = self.session.get_components(entity_id)
        if not comps:
            return None
        for name, data in comps.items():
            if name.lower() == "transform" and isinstance(data, Mapping):
                return {
                    "x": float(data.get("x", 0.0)),
                    "y": float(data.get("y", 0.0)),
                    "z": float(data.get("z", 0.0)),
                    "rot_z": float(data.get("rot_z", 0.0)),
                }
        return None

    def _render_entity(self, entity_id: RuntimeID, res: dict[str, Any], cw: float, ch: float) -> None:
        comps = self.session.get_components(entity_id)
        # Child UI entities are rendered as overhead billboards by their parent
        parent_id = self.session.kernel.get_entity_parent(entity_id)
        if parent_id is not None and self._is_overhead_ui_entity(comps):
            return

        transform = self._get_entity_transform(entity_id)
        if not transform:
            return

        name = self.session.get_entity_name(entity_id)
        is_selected = (self.session.selected_entity_id == entity_id)

        sx, sy = self._world_to_screen(transform["x"], transform["y"], cw, ch)
        rot_rad = math.radians(transform["rot_z"])
        radius = 16.0 * max(0.5, min(2.0, self.cam_zoom))

        # Color scheme based on entity role/name
        name_lower = name.lower()
        if "player" in name_lower or "hero" in name_lower:
            fill_color = (65, 135, 245, 230)
            border_color = (120, 180, 255, 255)
        elif "weapon" in name_lower or "sword" in name_lower or "excalibur" in name_lower:
            fill_color = (50, 205, 190, 230)
            border_color = (100, 245, 230, 255)
        elif "goblin" in name_lower or "enemy" in name_lower or "monster" in name_lower:
            fill_color = (235, 80, 70, 230)
            border_color = (255, 140, 130, 255)
        else:
            fill_color = (135, 110, 210, 230)
            border_color = (180, 160, 240, 255)

        # Draw AI aggro radius if present
        ai_comp = comps.get("AI") or comps.get("ai")
        if isinstance(ai_comp, Mapping) and "aggro_radius" in ai_comp:
            aggro_r = float(ai_comp["aggro_radius"]) * self.cam_zoom
            dpg.draw_circle(
                center=(sx, sy),
                radius=aggro_r,
                color=(235, 120, 80, 70),
                fill=(235, 120, 80, 25),
                thickness=1.0,
                parent=self.drawlist_tag,
            )

        # Selection glow ring
        if is_selected:
            dpg.draw_circle(
                center=(sx, sy),
                radius=radius + 5.0,
                color=(255, 215, 60, 255),
                thickness=2.5,
                parent=self.drawlist_tag,
            )

        # Entity Body Circle
        dpg.draw_circle(
            center=(sx, sy),
            radius=radius,
            fill=fill_color,
            color=border_color,
            thickness=1.8,
            parent=self.drawlist_tag,
        )

        # Rotation Heading Indicator
        hx = sx + math.cos(rot_rad) * (radius + 8.0)
        hy = sy + math.sin(rot_rad) * (radius + 8.0)
        dpg.draw_line(
            p1=(sx, sy),
            p2=(hx, hy),
            color=(255, 255, 255, 220),
            thickness=2.0,
            parent=self.drawlist_tag,
        )

        # Name & ID label
        label_text = f"{name} [{entity_id}]"
        dpg.draw_text(
            pos=(sx - len(label_text) * 3.2, sy + radius + 3.0),
            text=label_text,
            size=13,
            color=(220, 225, 235, 255),
            parent=self.drawlist_tag,
        )

        # World-Space Overhead UI billboarded screen-aligned above entity
        def _draw_widget(
            c_comps: dict[str, Any],
            px: float,
            py: float,
            target_cid: RuntimeID,
            visited: set[RuntimeID] | None = None,
        ) -> None:
            if visited is None:
                visited = set()
            if target_cid in visited:
                return
            visited.add(target_cid)

            slider_comp = self._get_ui_comp(c_comps, "UISlider")
            text_comp = self._get_ui_comp(c_comps, "UIText")
            button_comp = self._get_ui_comp(c_comps, "UIButton")
            container_comp = self._get_ui_comp(c_comps, "UIContainer")

            if slider_comp is not None:
                zoom_scale = max(0.5, min(2.0, self.cam_zoom))
                bar_w = 40.0 * zoom_scale
                bar_h = 5.0 * zoom_scale
                try:
                    val = max(0.0, min(1.0, float(slider_comp.get("value", 1.0))))
                except (ValueError, TypeError):
                    val = 1.0

                pmin = (px - bar_w / 2.0, py - bar_h / 2.0)
                pmax = (px + bar_w / 2.0, py + bar_h / 2.0)
                dpg.draw_rectangle(
                    pmin=pmin,
                    pmax=pmax,
                    fill=(20, 20, 20, 220),
                    color=(80, 80, 80, 255),
                    thickness=1.0,
                    parent=self.drawlist_tag,
                )

                inner_w = (bar_w - 2.0) * val
                if inner_w > 0:
                    bar_fill = (235, 60, 60, 230) if val <= 0.25 else (50, 215, 80, 230)
                    dpg.draw_rectangle(
                        pmin=(px - bar_w / 2.0 + 1.0, py - bar_h / 2.0 + 1.0),
                        pmax=(px - bar_w / 2.0 + 1.0 + inner_w, py + bar_h / 2.0 - 1.0),
                        fill=bar_fill,
                        color=bar_fill,
                        parent=self.drawlist_tag,
                    )

                if self.session.selected_entity_id == target_cid:
                    dpg.draw_rectangle(
                        pmin=(pmin[0] - 3.0, pmin[1] - 3.0),
                        pmax=(pmax[0] + 3.0, pmax[1] + 3.0),
                        color=(0, 140, 255, 255),
                        thickness=2.0,
                        rounding=2.0,
                        parent=self.drawlist_tag,
                    )

                label = slider_comp.get("label")
                if label:
                    dpg.draw_text(
                        pos=(px - bar_w / 2.0, py - bar_h / 2.0 - 12.0),
                        text=str(label),
                        size=11,
                        color=(210, 215, 230, 230),
                        parent=self.drawlist_tag,
                    )

            elif text_comp is not None:
                content = str(text_comp.get("content", ""))
                if content:
                    dpg.draw_text(
                        pos=(px - len(content) * 3.2, py),
                        text=content,
                        size=12,
                        color=(240, 240, 250, 230),
                        parent=self.drawlist_tag,
                    )
                    if self.session.selected_entity_id == target_cid:
                        tw = len(content) * 6.4
                        th = 13.0
                        dpg.draw_rectangle(
                            pmin=(px - tw / 2.0 - 3.0, py - 3.0),
                            pmax=(px + tw / 2.0 + 3.0, py + th + 3.0),
                            color=(0, 140, 255, 255),
                            thickness=2.0,
                            rounding=2.0,
                            parent=self.drawlist_tag,
                        )

            elif button_comp is not None:
                btn_label = str(button_comp.get("label", "Button"))
                tag_text = f"[{btn_label}]"
                tag_w = max(24.0, len(tag_text) * 6.5)
                tag_h = 16.0
                pmin = (px - tag_w / 2.0, py - tag_h / 2.0)
                pmax = (px + tag_w / 2.0, py + tag_h / 2.0)
                dpg.draw_rectangle(
                    pmin=pmin,
                    pmax=pmax,
                    fill=(0, 120, 255, 200),
                    color=(80, 170, 255, 240),
                    rounding=3.0,
                    parent=self.drawlist_tag,
                )
                dpg.draw_text(
                    pos=(px - len(tag_text) * 3.0, py - 6.0),
                    text=tag_text,
                    size=11,
                    color=(255, 255, 255, 255),
                    parent=self.drawlist_tag,
                )
                if self.session.selected_entity_id == target_cid:
                    dpg.draw_rectangle(
                        pmin=(pmin[0] - 3.0, pmin[1] - 3.0),
                        pmax=(pmax[0] + 3.0, pmax[1] + 3.0),
                        color=(0, 140, 255, 255),
                        thickness=2.0,
                        rounding=4.0,
                        parent=self.drawlist_tag,
                    )

            elif container_comp is not None:
                zoom_scale = max(0.5, min(2.0, self.cam_zoom))
                gap = float(container_comp.get("gap", 4.0)) * zoom_scale
                curr_py = py
                for sub_cid in self.session.get_children(target_cid):
                    c_trans = self._get_entity_transform(sub_cid)
                    if c_trans is not None:
                        curr_px = px + c_trans["x"] * self.cam_zoom
                        item_py = curr_py + c_trans["y"] * self.cam_zoom
                    else:
                        curr_px = px
                        item_py = curr_py
                    _draw_widget(self.session.get_components(sub_cid), curr_px, item_py, sub_cid, visited=visited)
                    curr_py += (14.0 * zoom_scale + gap)

        children = self.session.get_children(entity_id)
        for cid in children:
            c_comps = self.session.get_components(cid)
            if not self._is_overhead_ui_entity(c_comps):
                continue

            c_trans = self._get_entity_transform(cid)
            if c_trans is not None:
                dx, dy = c_trans["x"], c_trans["y"]
            else:
                dx, dy = 0.0, -22.0

            wx = transform["x"] + dx
            wy = transform["y"] + dy
            sx_ui, sy_ui = self._world_to_screen(wx, wy, cw, ch)
            _draw_widget(c_comps, sx_ui, sy_ui, cid)

    def _on_canvas_left_click(self) -> None:
        """Handle clicking inside canvas to select entity using true local coordinates."""
        if not dpg.does_item_exist(self.drawlist_tag):
            return

        min_pos = dpg.get_item_rect_min(self.drawlist_tag)
        mx, my = dpg.get_mouse_pos(local=False)
        local_mx = mx - min_pos[0]
        local_my = my - min_pos[1]

        cw = self._last_cw
        ch = self._last_ch

        closest_id = None
        closest_dist = float("inf")

        for rid in self.session.kernel.resources:
            if not self.session.kernel.is_entity(rid):
                continue
            comps = self.session.get_components(rid)
            if self._is_overhead_ui_entity(comps):
                is_canvas_selectable = any(
                    isinstance(c, Mapping) and (c.get("canvas_selectable") is True or c.get("selectable") is True)
                    for c in comps.values()
                )
                if not is_canvas_selectable:
                    continue
            transform = self._get_entity_transform(rid)
            if not transform:
                continue
            parent_id = self.session.kernel.get_entity_parent(rid)
            if parent_id is not None and self._is_overhead_ui_entity(comps):
                p_trans = self._get_entity_transform(parent_id)
                wx = (p_trans["x"] if p_trans else 0.0) + transform["x"]
                wy = (p_trans["y"] if p_trans else 0.0) + transform["y"]
            else:
                wx = transform["x"]
                wy = transform["y"]
            sx, sy = self._world_to_screen(wx, wy, cw, ch)
            dist = math.hypot(local_mx - sx, local_my - sy)
            if dist < 25.0 and dist < closest_dist:
                closest_dist = dist
                closest_id = rid

        if closest_id is not None:
            self.session.select_entity(closest_id)
        self.redraw()

    def destroy(self) -> None:
        """Unsubscribe from session events."""
        for unsub_name in ("_unsubscribe_state", "_unsubscribe_selection", "_unsubscribe_tick", "_unsubscribe_play"):
            unsub = getattr(self, unsub_name, None)
            if callable(unsub):
                try:
                    unsub()
                except Exception:
                    pass
                setattr(self, unsub_name, None)
