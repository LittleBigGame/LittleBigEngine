"""UI Bridge panel connecting engine-native UI component hierarchies to Dear PyGui widgets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import dearpygui.dearpygui as dpg

from LBE.types import Error, RuntimeID
from .session import EditorSession


class UIBridgePanel:
    """Dockable panel rendering live interactive Dear PyGui previews of engine UI trees."""

    def __init__(self, session: EditorSession, tag: str = "window_ui_preview") -> None:
        self.session = session
        self.tag = tag
        self.content_tag = f"{self.tag}_content"
        self.mount_selector_tag = f"{self.tag}_mount_selector"
        self.selected_mount_id: RuntimeID | None = None
        self._mount_options: dict[str, RuntimeID | None] = {"Auto (First UI Root)": None}
        self._suppress_rebuild: bool = False
        self._panel_windows: dict[RuntimeID, str] = {}

        self._unsubscribe_state = self.session.subscribe_state_changed(self._on_state_changed)
        self._unsubscribe_selection = self.session.subscribe_selection_changed(
            self._on_selection_changed
        )

    def build(self) -> str:
        """Create the dockable UI preview window structure."""
        with dpg.window(
            label="UI Preview & Tools",
            tag=self.tag,
            width=360,
            height=500,
            pos=(650, 30),
        ):
            # Toolbar header: mount selector and refresh button
            with dpg.group(horizontal=True):
                dpg.add_text("Mount:")
                dpg.add_combo(
                    items=["Auto (First UI Root)"],
                    default_value="Auto (First UI Root)",
                    tag=self.mount_selector_tag,
                    width=180,
                    callback=self._on_mount_selected,
                )
                dpg.add_button(
                    label="Refresh Preview",
                    callback=lambda: self.rebuild(),
                )
            dpg.add_separator()

            # Content container
            with dpg.child_window(
                tag=self.content_tag,
                autosize_x=True,
                autosize_y=True,
            ):
                pass

        self.rebuild()
        return self.tag

    def _on_state_changed(self) -> None:
        if self._suppress_rebuild:
            return
        self.rebuild()

    def _on_selection_changed(self, entity_id: RuntimeID | None) -> None:
        if self._suppress_rebuild:
            return
        self.rebuild()

    def _on_mount_selected(self, sender: str | int, app_data: str) -> None:
        self.selected_mount_id = self._mount_options.get(app_data)
        self.rebuild()

    def _get_all_uicontainers(self) -> list[RuntimeID]:
        containers: list[RuntimeID] = []
        for rid in sorted(self.session.kernel.resources.keys()):
            if self.session.kernel.is_entity(rid) and self._has_component(rid, "UIContainer"):
                containers.append(rid)
        return containers

    def _update_mount_options(self) -> None:
        if not dpg.does_item_exist(self.mount_selector_tag):
            return

        containers = self._get_all_uicontainers()
        items = ["Auto (First UI Root)"]
        self._mount_options = {"Auto (First UI Root)": None}

        for cid in containers:
            name = self.session.get_entity_name(cid)
            label = f"{name} [ID: {cid}]"
            items.append(label)
            self._mount_options[label] = cid

        current_val = "Auto (First UI Root)"
        if self.selected_mount_id is not None:
            if self.selected_mount_id in containers:
                name = self.session.get_entity_name(self.selected_mount_id)
                current_val = f"{name} [ID: {self.selected_mount_id}]"
            else:
                self.selected_mount_id = None

        dpg.configure_item(self.mount_selector_tag, items=items, default_value=current_val)

    def _find_first_ui_root(self) -> RuntimeID | None:
        # Check scene roots with UIContainer first
        for rid in self.session.get_root_entities():
            if self._has_component(rid, "UIContainer"):
                return rid
        # Then any entity with UIContainer
        for rid in sorted(self.session.kernel.resources.keys()):
            if self.session.kernel.is_entity(rid) and self._has_component(rid, "UIContainer"):
                return rid
        # Fallback: check any root entity with any UI component
        ui_types = {"uibutton", "uislider", "uitextinput", "uitext"}
        for rid in self.session.get_root_entities():
            comps = self.session.get_components(rid)
            if any(c.lower() in ui_types for c in comps):
                return rid
        return None

    def _get_mounted_root(self) -> RuntimeID | None:
        if self.selected_mount_id is not None:
            if self.session.kernel.is_entity(self.selected_mount_id):
                return self.selected_mount_id
            self.selected_mount_id = None

        return self._find_first_ui_root()

    def rebuild(self) -> None:
        """Re-render the mounted UI hierarchy inside the content container and dynamic UIPanel windows."""
        # 1. Manage dynamic UIPanel Windows
        active_panel_rids: set[RuntimeID] = set()
        for rid in sorted(self.session.kernel.resources.keys()):
            if not self.session.kernel.is_entity(rid):
                continue
            comps = self.session.get_components(rid)
            panel_comp = self._get_ui_comp(comps, "UIPanel")
            if panel_comp is None:
                p = self._get_ui_comp(comps, "panel")
                if p is not None and "panel_type" not in p:
                    panel_comp = p
            if panel_comp is not None:
                active_panel_rids.add(rid)
                title = panel_comp.get("title") or self.session.get_entity_name(rid) or "Panel"
                width = int(panel_comp.get("width", 300))
                height = int(panel_comp.get("height", 200))
                is_minimized = bool(panel_comp.get("minimized", False))
                is_closable = bool(panel_comp.get("closable", True))
                win_tag = f"ui_panel_win_{rid}"

                if not dpg.does_item_exist(win_tag):
                    offset_idx = len(self._panel_windows)
                    with dpg.window(
                        label=title,
                        tag=win_tag,
                        width=width,
                        height=height,
                        pos=(350 + (offset_idx * 30), 100 + (offset_idx * 30)),
                        show=not is_minimized,
                        no_close=not is_closable,
                        on_close=lambda s=None, a=None, u=rid: self._on_panel_closed(u),
                    ):
                        pass
                    self._panel_windows[rid] = win_tag

                dpg.configure_item(win_tag, label=title, show=not is_minimized, no_close=not is_closable)
                dpg.delete_item(win_tag, children_only=True)

                children = self.session.get_children(rid)
                for cid in children:
                    self._render_ui_entity(cid, parent=win_tag)

        for pid in list(self._panel_windows.keys()):
            if pid not in active_panel_rids:
                win_tag = self._panel_windows.pop(pid)
                if dpg.does_item_exist(win_tag):
                    dpg.delete_item(win_tag)

        # 2. Render standard mounted UI Preview hierarchy
        if not dpg.does_item_exist(self.content_tag):
            return

        self._update_mount_options()
        dpg.delete_item(self.content_tag, children_only=True)

        mounted_root = self._get_mounted_root()
        if mounted_root is None:
            dpg.add_text(
                "No UI tree mounted. Create a UIContainer entity to preview.",
                parent=self.content_tag,
                color=(130, 135, 145),
            )
            return

        self._render_ui_entity(mounted_root, parent=self.content_tag)

    def _render_ui_entity(
        self,
        entity_id: RuntimeID,
        parent: str | int | None = None,
        visited: set[RuntimeID] | None = None,
    ) -> None:
        if visited is None:
            visited = set()
        if entity_id in visited:
            return
        visited.add(entity_id)

        if not self.session.kernel.is_entity(entity_id):
            return

        comps = self.session.get_components(entity_id)

        # UIPanel entities are standalone floating windows, not nested inside widgets
        panel_comp = self._get_ui_comp(comps, "UIPanel")
        if panel_comp is None:
            p = self._get_ui_comp(comps, "panel")
            if p is not None and "panel_type" not in p:
                panel_comp = p
        if panel_comp is not None and parent != f"ui_panel_win_{entity_id}":
            return

        name = self.session.get_entity_name(entity_id)
        children = self.session.get_children(entity_id)

        container_comp = self._get_ui_comp(comps, "UIContainer")
        if container_comp is not None:
            layout = container_comp.get("layout", "vertical")
            collapsible = bool(container_comp.get("collapsible", False))
            collapsed = bool(container_comp.get("collapsed", False))

            kwargs = {"parent": parent} if parent is not None else {}

            if collapsible:
                with dpg.collapsing_header(label=name, default_open=not collapsed, **kwargs):
                    for child_id in children:
                        self._render_ui_entity(child_id, parent=None, visited=visited)
            elif layout == "horizontal":
                with dpg.group(horizontal=True, **kwargs):
                    for child_id in children:
                        self._render_ui_entity(child_id, parent=None, visited=visited)
            else:
                with dpg.group(**kwargs):
                    for child_id in children:
                        self._render_ui_entity(child_id, parent=None, visited=visited)
            return

        kwargs = {"parent": parent} if parent is not None else {}

        button_comp = self._get_ui_comp(comps, "UIButton")
        if button_comp is not None:
            raw_w = button_comp.get("width", 0)
            raw_h = button_comp.get("height", 0)
            width = int(raw_w) if raw_w else -1
            height = int(raw_h) if raw_h else 0
            label = button_comp.get("label") or "Button"

            dpg.add_button(
                label=label,
                width=width,
                height=height,
                callback=lambda s, a, u=entity_id: self._on_button_clicked(u),
                **kwargs,
            )
            for child_id in children:
                self._render_ui_entity(child_id, parent=parent, visited=visited)
            return

        slider_comp = self._get_ui_comp(comps, "UISlider")
        if slider_comp is not None:
            label = slider_comp.get("label") or "Slider"
            min_val = float(slider_comp.get("min", 0.0))
            max_val = float(slider_comp.get("max", 1.0))
            cur_val = float(slider_comp.get("value", 0.0))

            dpg.add_slider_float(
                label=label,
                min_value=min_val,
                max_value=max_val,
                default_value=cur_val,
                callback=lambda s, a, u=entity_id: self._on_slider_changed(u, a),
                **kwargs,
            )
            for child_id in children:
                self._render_ui_entity(child_id, parent=parent, visited=visited)
            return

        input_comp = self._get_ui_comp(comps, "UITextInput")
        if input_comp is not None:
            label = input_comp.get("label", "")
            text = str(input_comp.get("text", ""))
            hint = str(input_comp.get("hint", ""))

            dpg.add_input_text(
                label=label,
                default_value=text,
                hint=hint,
                callback=lambda s, a, u=entity_id: self._on_input_text_changed(u, a),
                **kwargs,
            )
            for child_id in children:
                self._render_ui_entity(child_id, parent=parent, visited=visited)
            return

        text_comp = self._get_ui_comp(comps, "UIText")
        if text_comp is not None:
            content = str(text_comp.get("content", ""))
            raw_color = text_comp.get("color")
            color = None
            if isinstance(raw_color, (list, tuple)) and len(raw_color) in (3, 4):
                if all(isinstance(c, (int, float)) for c in raw_color):
                    if any(isinstance(c, float) for c in raw_color) and all(0.0 <= c <= 1.0 for c in raw_color):
                        color = tuple(int(c * 255) for c in raw_color)
                    else:
                        color = tuple(int(c) for c in raw_color)

            bullet = bool(text_comp.get("bullet", False))
            text_kwargs = dict(kwargs)
            if color is not None:
                text_kwargs["color"] = color

            dpg.add_text(
                default_value=content,
                bullet=bullet,
                **text_kwargs,
            )
            for child_id in children:
                self._render_ui_entity(child_id, parent=parent, visited=visited)
            return

        # Fallback for entities with children without specific UI components
        for child_id in children:
            self._render_ui_entity(child_id, parent=parent, visited=visited)

    def _on_button_clicked(self, entity_id: RuntimeID) -> None:
        self.session.kernel.trigger_ui_event(entity_id, "on_click")
        self.session.refresh()

    def _on_slider_changed(self, entity_id: RuntimeID, new_val: Any) -> None:
        val = float(new_val)
        comp = self._get_tracked_component(entity_id, "UISlider")
        if comp is not None and hasattr(comp, "__setitem__"):
            comp["value"] = val
        self.session.kernel.trigger_ui_event(entity_id, "on_change", val)
        self._suppress_rebuild = True
        try:
            self.session.refresh()
        finally:
            self._suppress_rebuild = False

    def _on_input_text_changed(self, entity_id: RuntimeID, new_val: Any) -> None:
        val = str(new_val)
        comp = self._get_tracked_component(entity_id, "UITextInput")
        if comp is not None and hasattr(comp, "__setitem__"):
            comp["text"] = val
        self.session.kernel.trigger_ui_event(entity_id, "on_change", val)
        self._suppress_rebuild = True
        try:
            self.session.refresh()
        finally:
            self._suppress_rebuild = False

    def _get_tracked_component(self, entity_id: RuntimeID, comp_type: str) -> Any | None:
        comps = self.session.get_components(entity_id)
        target_name = comp_type
        for k in comps:
            if k.lower() == comp_type.lower():
                target_name = k
                break
        comp = self.session.kernel.get_component(entity_id, target_name)
        if not isinstance(comp, Error) and comp is not None:
            return comp
        return None

    def _get_ui_comp(self, comps: dict[str, Any], type_name: str) -> dict[str, Any] | None:
        for k, v in comps.items():
            if k.lower() == type_name.lower() and isinstance(v, Mapping):
                return v
        return None

    def _has_component(self, entity_id: RuntimeID, type_name: str) -> bool:
        comps = self.session.get_components(entity_id)
        return any(k.lower() == type_name.lower() for k in comps)

    def _on_panel_closed(self, pid: RuntimeID) -> None:
        """Handle user closing a dynamic UIPanel window."""
        if pid in self._panel_windows:
            comp = self._get_tracked_component(pid, "UIPanel")
            if comp is None:
                comp = self._get_tracked_component(pid, "panel")
            if comp is not None and hasattr(comp, "__setitem__"):
                comp["minimized"] = True

    def destroy(self) -> None:
        """Clean up session event subscriptions and dynamic windows."""
        if hasattr(self, "_unsubscribe_state"):
            self._unsubscribe_state()
        if hasattr(self, "_unsubscribe_selection"):
            self._unsubscribe_selection()
        for win_tag in list(self._panel_windows.values()):
            if dpg.does_item_exist(win_tag):
                dpg.delete_item(win_tag)
        self._panel_windows.clear()
