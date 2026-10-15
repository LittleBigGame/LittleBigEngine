"""Inspector panel rendering selected entity properties, scripts, and components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any
import dearpygui.dearpygui as dpg

from LBE.types import Error, RuntimeID
from LBE.proxy import _unwrap
from .context_menu import open_context_menu
from .pills import (
    PillData,
    get_available_function_pills,
    get_pill_theme,
    parse_reference_pill,
    rename_script_function_display_name,
)
from .session import EditorSession
from .theme import get_card_theme


class InspectorPanel:
    """Dockable panel for inspecting and modifying entity details and components."""

    def __init__(
        self,
        session: EditorSession,
        tag: str = "window_inspector",
        target_entity_id: RuntimeID | None = None,
        is_locked: bool = False,
    ) -> None:
        self.session = session
        self.tag = tag
        self.content_tag = f"{self.tag}_content"
        self.target_entity_id: RuntimeID | None = target_entity_id
        self.is_locked: bool = is_locked
        self._is_minimized: bool = False
        self._orig_height: int = 760
        self._handler_registries: list[int | str] = []
        self._suppress_rebuild: bool = False

        self.session.register_inspector(self)
        self._unsubscribe_state = self.session.subscribe_state_changed(self._on_state_changed)
        self._unsubscribe_selection = self.session.subscribe_selection_changed(
            lambda _: None
        )

    def set_target(self, entity_id: RuntimeID | None) -> None:
        """Explicitly set the inspected target entity."""
        self.target_entity_id = entity_id
        self.rebuild()

    def _find_panel_entity(self) -> RuntimeID | None:
        """Find the Inspector Panel entity in the session kernel."""
        for rid in self.session.kernel.resources:
            if not self.session.kernel.is_entity(rid):
                continue
            comps = self.session.get_components(rid)
            p_comp = comps.get("Panel") or comps.get("panel")
            if isinstance(p_comp, Mapping) and p_comp.get("panel_type") == "inspector":
                return rid
            if self.session.get_entity_name(rid) == "Inspector Panel":
                return rid
        return None

    def _get_header_props(self) -> tuple[str, str, str]:
        """Read title, focus button label, and lock button label from child entities under Inspector Panel."""
        title = "Inspector"
        focus_label = "Focus"
        lock_label = "Unlock" if self.is_locked else "Lock"

        panel_id = self._find_panel_entity()
        if panel_id is None:
            return title, focus_label, lock_label

        for child_id in self.session.get_children(panel_id):
            c_name = self.session.get_entity_name(child_id)
            c_comps = self.session.get_components(child_id)
            if c_name == "HeaderBar" or "UIContainer" in c_comps or "uicontainer" in c_comps:
                for sub_id in self.session.get_children(child_id):
                    sub_name = self.session.get_entity_name(sub_id)
                    sub_comps = self.session.get_components(sub_id)
                    if sub_name == "TitleText" or "UIText" in sub_comps:
                        tc = sub_comps.get("UIText") or sub_comps.get("uitext", {})
                        if isinstance(tc, Mapping) and "content" in tc and tc["content"]:
                            title = str(tc["content"])
                    elif sub_name == "FocusBtn":
                        bc = sub_comps.get("UIButton") or sub_comps.get("uibutton", {})
                        if isinstance(bc, Mapping) and "label" in bc and bc["label"]:
                            focus_label = str(bc["label"])
                    elif sub_name == "LockBtn":
                        bc = sub_comps.get("UIButton") or sub_comps.get("uibutton", {})
                        if isinstance(bc, Mapping):
                            if "label" in bc and bc["label"]:
                                lock_label = str(bc["label"])
        return title, focus_label, lock_label

    def toggle_lock(self) -> bool:
        """Toggle lock state. When locked, hierarchy selections bypass this panel."""
        self.is_locked = not self.is_locked
        panel_id = self._find_panel_entity()
        if panel_id is not None:
            self.session.mutate_component(panel_id, "Panel", {"locked": self.is_locked})

            for child_id in self.session.get_children(panel_id):
                c_name = self.session.get_entity_name(child_id)
                c_comps = self.session.get_components(child_id)
                if c_name == "HeaderBar" or "UIContainer" in c_comps or "uicontainer" in c_comps:
                    for sub_id in self.session.get_children(child_id):
                        if self.session.get_entity_name(sub_id) == "LockBtn":
                            self.session.mutate_component(
                                sub_id,
                                "UIButton",
                                {"label": "Unlock" if self.is_locked else "Lock"},
                            )
        self.rebuild()
        return self.is_locked

    def set_active(self) -> None:
        """Designate this inspector as the active recipient of global selections."""
        self.session.set_active_inspector(self)
        self.rebuild()

    def close(self) -> None:
        """Unregister, clean up listeners, and destroy this inspector window."""
        self.destroy()
        if dpg.does_item_exist(self.tag):
            dpg.delete_item(self.tag)

    def destroy(self) -> None:
        """Clean up subscriptions and handlers."""
        self.session.unregister_inspector(self)
        if hasattr(self, "_unsubscribe_state") and callable(self._unsubscribe_state):
            try:
                self._unsubscribe_state()
            except Exception:
                pass
            self._unsubscribe_state = None
        if hasattr(self, "_unsubscribe_selection") and callable(self._unsubscribe_selection):
            try:
                self._unsubscribe_selection()
            except Exception:
                pass
            self._unsubscribe_selection = None
        for reg in self._handler_registries:
            if dpg.does_item_exist(reg):
                dpg.delete_item(reg)
        self._handler_registries.clear()
        if hasattr(self.session, "app") and hasattr(self.session.app, "extra_inspectors"):
            if self in self.session.app.extra_inspectors:
                self.session.app.extra_inspectors.remove(self)

    def _toggle_flyout(self, dock_tag: str) -> None:
        if dpg.does_item_exist(dock_tag):
            is_shown = dpg.is_item_shown(dock_tag)
            dpg.configure_item(dock_tag, show=not is_shown)

    def _toggle_minimize(self) -> None:
        self._is_minimized = not self._is_minimized
        if self._is_minimized:
            self._orig_height = dpg.get_item_height(self.tag) or 760
            dpg.set_item_height(self.tag, 60)
        else:
            dpg.set_item_height(self.tag, self._orig_height)

    def _toggle_maximize(self) -> None:
        curr_w = dpg.get_item_width(self.tag) or 380
        new_w = 640 if curr_w < 500 else 380
        dpg.set_item_width(self.tag, new_w)

    def build(self) -> str:
        """Create the inspector window structure with auto-hiding chrome and status."""
        with dpg.window(
            label="Inspector",
            tag=self.tag,
            width=380,
            height=760,
            pos=(1010, 30),
        ):
            # Window Header with Status & Controls
            with dpg.group(horizontal=True):
                title, focus_lbl, lock_lbl = self._get_header_props()
                is_active = (self.session.active_inspector is self)
                title_col = (0, 180, 255, 255) if is_active else (235, 240, 250, 255)
                dpg.add_text(title, tag=f"{self.tag}_title_text", color=title_col)

                dpg.add_text(
                    "[Active]",
                    tag=f"{self.tag}_active_text",
                    color=(0, 210, 255, 255),
                    show=is_active,
                )
                dpg.add_button(
                    label=focus_lbl,
                    tag=f"{self.tag}_focus_btn",
                    callback=lambda: self.set_active(),
                    small=True,
                    show=not is_active,
                )

                lock_btn = dpg.add_button(
                    label=lock_lbl,
                    tag=f"{self.tag}_lock_btn",
                    callback=lambda: self.toggle_lock(),
                    small=True,
                )
                with dpg.tooltip(lock_btn):
                    dpg.add_text("Click to toggle Lock (Locked panels ignore hierarchy clicks)")

            with dpg.child_window(
                tag=self.content_tag,
                autosize_x=True,
                autosize_y=True,
                border=True,
            ):
                pass

        self._setup_mouse_handlers()
        self.rebuild()
        return self.tag

    def _setup_flyout_handlers(self) -> None:
        pass

    def _setup_mouse_handlers(self) -> None:
        """Handle background right-clicks and left-click focus activation."""
        with dpg.handler_registry() as reg:
            self._handler_registries.append(reg)
            dpg.add_mouse_click_handler(button=1, callback=self._on_mouse_right_click)
            dpg.add_mouse_click_handler(button=0, callback=self._on_mouse_left_click)

    def _on_mouse_right_click(self) -> None:
        if dpg.does_item_exist(self.content_tag) and dpg.is_item_hovered(self.content_tag):
            entity_id = self._get_current_entity_id()
            open_context_menu(
                self.session,
                target_id=entity_id,
                panel_type="inspector",
                panel_instance=self,
            )

    def _on_mouse_left_click(self) -> None:
        if dpg.does_item_exist(self.tag) and (
            dpg.is_item_hovered(self.tag)
            or (dpg.does_item_exist(self.content_tag) and dpg.is_item_hovered(self.content_tag))
        ):
            if self.session.active_inspector is not self:
                self.session.set_active_inspector(self)

    def _get_current_entity_id(self) -> RuntimeID | None:
        entity_id = (
            self.target_entity_id
            if self.target_entity_id is not None
            else self.session.selected_entity_id
        )
        if entity_id is not None and not self.session.kernel.is_entity(entity_id):
            return None
        return entity_id

    def _on_state_changed(self) -> None:
        if self._suppress_rebuild:
            return
        self.rebuild()

    def rebuild(self) -> None:
        """Re-render the inspector view for the inspected entity."""
        if not dpg.does_item_exist(self.content_tag):
            return

        title, focus_lbl, lock_lbl = self._get_header_props()
        is_active = (self.session.active_inspector is self)
        title_col = (0, 180, 255, 255) if is_active else (235, 240, 250, 255)

        title_tag = f"{self.tag}_title_text"
        if dpg.does_item_exist(title_tag):
            dpg.set_value(title_tag, title)
            dpg.configure_item(title_tag, color=title_col)

        active_tag = f"{self.tag}_active_text"
        focus_btn_tag = f"{self.tag}_focus_btn"
        if dpg.does_item_exist(active_tag) and dpg.does_item_exist(focus_btn_tag):
            dpg.configure_item(active_tag, show=is_active)
            dpg.configure_item(focus_btn_tag, show=not is_active, label=focus_lbl)

        lock_btn_tag = f"{self.tag}_lock_btn"
        if dpg.does_item_exist(lock_btn_tag):
            dpg.configure_item(lock_btn_tag, label=lock_lbl)

        dpg.delete_item(self.content_tag, children_only=True)

        entity_id = self._get_current_entity_id()
        if entity_id is None:
            msg = "No entity selected"
            if self.is_locked and self.target_entity_id is not None:
                msg = f"Locked target (ID: {self.target_entity_id}) no longer exists"
            dpg.add_text(
                msg,
                parent=self.content_tag,
                color=(130, 135, 145),
            )
            return

        # -----------------------------------------------------------------
        # Entity Header
        # -----------------------------------------------------------------
        dpg.add_text("Entity Identification", parent=self.content_tag, color=(100, 150, 255))
        dpg.add_text("Name", parent=self.content_tag, color=(165, 175, 195))
        dpg.add_input_text(
            default_value=self.session.get_entity_name(entity_id),
            callback=self._on_name_changed,
            user_data=entity_id,
            width=-1,
            parent=self.content_tag,
        )

        dpg.add_text(f"RuntimeID: {entity_id}", parent=self.content_tag)
        dpg.add_text(
            f"StorageID (Hex): {self.session.get_storage_id_hex(entity_id)}",
            parent=self.content_tag,
        )

        parent_id = self.session.kernel.get_entity_parent(entity_id)
        if parent_id is not None:
            parent_name = self.session.get_entity_name(parent_id)
            with dpg.group(horizontal=True, parent=self.content_tag):
                dpg.add_text(f"Parent ID: {parent_id} ({parent_name})")
                dpg.add_button(
                    label="Select Parent",
                    callback=lambda: self.session.select_entity(parent_id),
                )
        else:
            dpg.add_text("Parent ID: None (Root Entity)", parent=self.content_tag)

        dpg.add_separator(parent=self.content_tag)

        # -----------------------------------------------------------------
        # Scripts Section
        # -----------------------------------------------------------------
        dpg.add_text("Attached Scripts", parent=self.content_tag, color=(100, 150, 255))
        scripts = self.session.get_entity_scripts(entity_id)
        if not scripts:
            dpg.add_text("  No scripts attached", parent=self.content_tag, color=(130, 135, 145))
        else:
            for script_id in scripts:
                with dpg.group(horizontal=True, parent=self.content_tag):
                    dpg.add_text(f"  - Script [ID: {script_id}]")
                    dpg.add_button(
                        label="Detach",
                        callback=self._on_detach_script,
                        user_data=(entity_id, script_id),
                    )

        # Attach Script input
        with dpg.table(
            header_row=False,
            policy=dpg.mvTable_SizingStretchProp,
            borders_innerH=False,
            borders_innerV=False,
            borders_outerH=False,
            borders_outerV=False,
            parent=self.content_tag,
        ):
            dpg.add_table_column(init_width_or_weight=0.68)
            dpg.add_table_column(init_width_or_weight=0.32)
            with dpg.table_row():
                input_tag = f"{self.tag}_attach_script_input_{entity_id}"
                dpg.add_input_text(
                    hint="Script ID / Hex",
                    width=-1,
                    tag=input_tag,
                )
                dpg.add_button(
                    label="Attach",
                    width=-1,
                    callback=self._on_attach_script,
                    user_data=(entity_id, input_tag),
                )

        dpg.add_separator(parent=self.content_tag)

        # -----------------------------------------------------------------
        # Components Section
        # -----------------------------------------------------------------
        dpg.add_text("Components", parent=self.content_tag, color=(100, 150, 255))
        components = self.session.get_components(entity_id)

        for comp_name, comp_data in components.items():
            self._render_component_card(entity_id, comp_name, comp_data)

        # -----------------------------------------------------------------
        # Add Component Section
        # -----------------------------------------------------------------
        dpg.add_spacer(height=6, parent=self.content_tag)
        dpg.add_text("Add Component", parent=self.content_tag, color=(100, 150, 255))
        with dpg.table(
            header_row=False,
            policy=dpg.mvTable_SizingStretchProp,
            borders_innerH=False,
            borders_innerV=False,
            borders_outerH=False,
            borders_outerV=False,
            parent=self.content_tag,
        ):
            dpg.add_table_column(init_width_or_weight=0.68)
            dpg.add_table_column(init_width_or_weight=0.32)
            with dpg.table_row():
                add_comp_input_tag = f"{self.tag}_add_comp_name_{entity_id}"
                dpg.add_input_text(
                    hint="Name (e.g. Health)",
                    width=-1,
                    tag=add_comp_input_tag,
                )
                dpg.add_button(
                    label="Add",
                    width=-1,
                    callback=self._on_add_component,
                    user_data=(entity_id, add_comp_input_tag),
                )

    def _render_component_card(
        self, entity_id: RuntimeID, comp_name: str, comp_data: dict[str, Any]
    ) -> None:
        with dpg.collapsing_header(
            label=f"Component: {comp_name}",
            parent=self.content_tag,
            default_open=True,
        ) as header:
            dpg.bind_item_theme(header, get_card_theme(selected=False))
            with dpg.table(
                header_row=False,
                policy=dpg.mvTable_SizingStretchProp,
                borders_innerH=False,
                borders_innerV=False,
                borders_outerH=False,
                borders_outerV=False,
            ):
                dpg.add_table_column(init_width_or_weight=0.55)
                dpg.add_table_column(init_width_or_weight=0.45)
                with dpg.table_row():
                    field_count = len(comp_data) if isinstance(comp_data, Mapping) else 0
                    dpg.add_text(f"Fields ({field_count}):", color=(150, 155, 170))
                    dpg.add_button(
                        label="Remove",
                        width=-1,
                        callback=self._on_remove_component,
                        user_data=(entity_id, comp_name),
                    )

            if isinstance(comp_data, Mapping):
                self._render_fields(entity_id, comp_name, comp_data, path=[])

                # Add Field helper inside component card
                with dpg.tree_node(label="+ Add Field", default_open=False):
                    fn_tag = f"new_fn_{entity_id}_{comp_name}"
                    ft_tag = f"new_ft_{entity_id}_{comp_name}"
                    fv_tag = f"new_fv_{entity_id}_{comp_name}"
                    with dpg.table(
                        header_row=False,
                        policy=dpg.mvTable_SizingStretchProp,
                        borders_innerH=False,
                        borders_innerV=False,
                        borders_outerH=False,
                        borders_outerV=False,
                    ):
                        dpg.add_table_column(init_width_or_weight=0.35)
                        dpg.add_table_column(init_width_or_weight=0.30)
                        dpg.add_table_column(init_width_or_weight=0.25)
                        dpg.add_table_column(init_width_or_weight=0.10)
                        with dpg.table_row():
                            dpg.add_input_text(hint="Field", width=-1, tag=fn_tag)
                            dpg.add_combo(
                                items=["float", "int", "str", "bool", "dict"],
                                default_value="float",
                                width=-1,
                                tag=ft_tag,
                            )
                            dpg.add_input_text(hint="Val", width=-1, tag=fv_tag)
                            dpg.add_button(
                                label="+",
                                width=-1,
                                callback=self._on_add_field,
                                user_data=(entity_id, comp_name, fn_tag, ft_tag, fv_tag),
                            )

    def _render_fields(
        self,
        entity_id: RuntimeID,
        comp_name: str,
        data: dict[str, Any],
        path: list[str],
        parent_container: str | int | None = None,
    ) -> None:
        for key, value in data.items():
            curr_path = path + [key]
            field_label = key

            # Note: bool is a subclass of int in Python, check bool first!
            if isinstance(value, bool):
                kwargs = {"parent": parent_container} if parent_container else {}
                dpg.add_checkbox(
                    label=field_label,
                    default_value=value,
                    callback=self._on_field_value_changed,
                    user_data=(entity_id, comp_name, curr_path, "bool"),
                    **kwargs,
                )
            elif isinstance(value, int):
                kwargs = {"parent": parent_container} if parent_container else {}
                dpg.add_text(field_label, color=(165, 175, 195), **kwargs)
                dpg.add_input_int(
                    default_value=value,
                    width=-1,
                    callback=self._on_field_value_changed,
                    user_data=(entity_id, comp_name, curr_path, "int"),
                    **kwargs,
                )
            elif isinstance(value, float):
                kwargs = {"parent": parent_container} if parent_container else {}
                dpg.add_text(field_label, color=(165, 175, 195), **kwargs)
                dpg.add_input_float(
                    default_value=value,
                    format="%.4f",
                    width=-1,
                    callback=self._on_field_value_changed,
                    user_data=(entity_id, comp_name, curr_path, "float"),
                    **kwargs,
                )
            elif isinstance(value, str):
                kwargs = {"parent": parent_container} if parent_container else {}
                pill_data = parse_reference_pill(value, self.session.kernel)
                is_handler_field = key in ("on_click", "on_change") or key.endswith("_handler")

                if pill_data is not None:
                    dpg.add_text(field_label, color=(165, 175, 195), **kwargs)
                    pill_text = pill_data.display_label
                    with dpg.group(horizontal=True, **kwargs):
                        badge_btn = dpg.add_button(
                            label=pill_text,
                            callback=self._open_pill_info_modal,
                            user_data=pill_data,
                        )
                        dpg.bind_item_theme(badge_btn, get_pill_theme())

                    with dpg.group(horizontal=True, **kwargs):
                        input_tag = f"{self.tag}_pill_inp_{entity_id}_{comp_name}_{'_'.join(curr_path)}"
                        if dpg.does_item_exist(input_tag):
                            dpg.delete_item(input_tag)
                        dpg.add_input_text(
                            default_value=value,
                            width=-75,
                            tag=input_tag,
                            callback=self._on_field_value_changed,
                            user_data=(entity_id, comp_name, curr_path, "str"),
                        )
                        dpg.add_button(
                            label="[Pick]",
                            width=-1,
                            callback=self._open_function_picker,
                            user_data=(entity_id, comp_name, curr_path, input_tag),
                        )
                elif is_handler_field:
                    dpg.add_text(field_label, color=(165, 175, 195), **kwargs)
                    with dpg.group(horizontal=True, **kwargs):
                        input_tag = f"{self.tag}_hnd_inp_{entity_id}_{comp_name}_{'_'.join(curr_path)}"
                        if dpg.does_item_exist(input_tag):
                            dpg.delete_item(input_tag)
                        dpg.add_input_text(
                            default_value=value,
                            width=-75,
                            tag=input_tag,
                            callback=self._on_field_value_changed,
                            user_data=(entity_id, comp_name, curr_path, "str"),
                        )
                        dpg.add_button(
                            label="[Pick]",
                            width=-1,
                            callback=self._open_function_picker,
                            user_data=(entity_id, comp_name, curr_path, input_tag),
                        )
                else:
                    dpg.add_text(field_label, color=(165, 175, 195), **kwargs)
                    dpg.add_input_text(
                        default_value=value,
                        width=-1,
                        callback=self._on_field_value_changed,
                        user_data=(entity_id, comp_name, curr_path, "str"),
                        **kwargs,
                    )
            elif isinstance(value, Mapping):
                kwargs = {"parent": parent_container} if parent_container else {}
                with dpg.tree_node(label=f"{field_label} (dict)", default_open=True, **kwargs) as dict_node:
                    self._render_fields(entity_id, comp_name, value, curr_path, parent_container=dict_node)
            else:
                kwargs = {"parent": parent_container} if parent_container else {}
                val_type_name = "list" if isinstance(value, (list, tuple, Sequence)) and not isinstance(value, (str, bytes)) else type(value).__name__
                dpg.add_text(f"{field_label} ({val_type_name})", color=(165, 175, 195), **kwargs)
                dpg.add_input_text(
                    default_value=json.dumps(_unwrap(value)),
                    width=-1,
                    callback=self._on_field_value_changed,
                    user_data=(entity_id, comp_name, curr_path, "json"),
                    **kwargs,
                )

    def _on_field_value_changed(
        self, sender: str | int, app_data: Any, user_data: tuple[RuntimeID, str, list[str], str]
    ) -> None:
        entity_id, comp_name, path, val_type = user_data

        if val_type == "int":
            try:
                val = int(app_data)
            except (ValueError, TypeError):
                return
        elif val_type == "float":
            try:
                val = float(app_data)
            except (ValueError, TypeError):
                return
        elif val_type == "bool":
            val = bool(app_data)
        elif val_type == "str":
            val = str(app_data)
        elif val_type == "json":
            try:
                val = json.loads(app_data)
            except Exception:
                val = app_data
        else:
            val = app_data

        comps = self.session.get_components(entity_id)
        if comp_name not in comps or not isinstance(comps[comp_name], Mapping):
            return

        comp_data = _unwrap(comps[comp_name])
        target_dict = comp_data
        for key in path[:-1]:
            if key not in target_dict or not isinstance(target_dict[key], dict):
                return
            target_dict = target_dict[key]

        target_dict[path[-1]] = val

        self._suppress_rebuild = True
        try:
            self.session.mutate_component(entity_id, comp_name, comp_data)
        finally:
            self._suppress_rebuild = False

    def _on_name_changed(self, sender: str | int, app_data: str, user_data: RuntimeID) -> None:
        entity_id = user_data
        self._suppress_rebuild = True
        try:
            self.session.set_entity_name(entity_id, app_data)
        finally:
            self._suppress_rebuild = False

    def _on_add_component(self, sender: str | int, app_data: Any, user_data: tuple[RuntimeID, str]) -> None:
        entity_id, input_tag = user_data
        if not dpg.does_item_exist(input_tag):
            return
        name = dpg.get_value(input_tag).strip()
        if name:
            self.session.add_component(entity_id, name, {})
            dpg.set_value(input_tag, "")
            self.rebuild()

    def _on_remove_component(
        self, sender: str | int, app_data: Any, user_data: tuple[RuntimeID, str]
    ) -> None:
        entity_id, comp_name = user_data
        self.session.remove_component(entity_id, comp_name)
        self.rebuild()

    def _on_add_field(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[RuntimeID, str, str, str, str],
    ) -> None:
        entity_id, comp_name, fn_tag, ft_tag, fv_tag = user_data
        if not dpg.does_item_exist(fn_tag):
            return

        field_name = dpg.get_value(fn_tag).strip()
        field_type = dpg.get_value(ft_tag)
        field_val_str = dpg.get_value(fv_tag).strip()

        if not field_name:
            return

        if field_type == "float":
            try:
                field_val = float(field_val_str) if field_val_str else 0.0
            except ValueError:
                field_val = 0.0
        elif field_type == "int":
            try:
                field_val = int(field_val_str) if field_val_str else 0
            except ValueError:
                field_val = 0
        elif field_type == "bool":
            field_val = field_val_str.lower() in ("true", "1", "yes")
        elif field_type == "dict":
            field_val = {}
        else:
            field_val = field_val_str

        comps = self.session.get_components(entity_id)
        if comp_name in comps:
            self.session.mutate_component(entity_id, comp_name, {field_name: field_val})
            self.rebuild()

    def _on_attach_script(
        self, sender: str | int, app_data: Any, user_data: tuple[RuntimeID, str]
    ) -> None:
        entity_id, input_tag = user_data
        if not dpg.does_item_exist(input_tag):
            return
        script_val = dpg.get_value(input_tag).strip()
        if not script_val:
            return

        try:
            script_id: int | str = int(script_val)
        except ValueError:
            script_id = script_val

        self.session.attach_script(entity_id, script_id)
        dpg.set_value(input_tag, "")
        self.rebuild()

    def _on_detach_script(
        self, sender: str | int, app_data: Any, user_data: tuple[RuntimeID, int]
    ) -> None:
        entity_id, script_id = user_data
        self.session.detach_script(entity_id, script_id)
        self.rebuild()

    def _open_pill_info_modal(
        self, sender: str | int, app_data: Any, user_data: PillData
    ) -> None:
        pill = user_data
        modal_tag = "window_pill_info_modal"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        label = "Entity Reference Details" if pill.res_type == 0 else "Function Pill Details"
        res_type_name = "Target Entity" if pill.res_type == 0 else "Target Script"

        with dpg.window(
            label=label,
            tag=modal_tag,
            modal=True,
            width=480,
            height=280,
            pos=(420, 220),
        ):
            dpg.add_text(f"Raw Reference: {pill.raw_ref}", color=(180, 180, 200))
            dpg.add_text(
                f"{res_type_name}: {pill.res_name} (Storage Hex: {pill.storage_id_hex[:16]}...)",
                color=(180, 180, 200),
            )
            dpg.add_text(f"Symbol ID: {pill.fn_symbol or 'None'}", color=(180, 180, 200))
            dpg.add_text(f"Display Name: {pill.fn_display_name or 'None'}", color=(180, 180, 200))
            dpg.add_separator()

            if pill.fn_symbol:
                dpg.add_text("Rename Display Name (updates trailing comment):")
                rename_input_tag = f"{modal_tag}_rename_input"
                if dpg.does_item_exist(rename_input_tag):
                    dpg.delete_item(rename_input_tag)
                dpg.add_input_text(
                    default_value=pill.fn_display_name or pill.fn_symbol,
                    tag=rename_input_tag,
                    width=-1,
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Rename Display Name",
                        callback=self._on_rename_display_name_submit,
                        user_data=(pill, rename_input_tag, modal_tag),
                    )
                    dpg.add_button(
                        label="Close",
                        callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None,
                    )
            else:
                dpg.add_button(
                    label="Close",
                    callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None,
                )

    def _on_rename_display_name_submit(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[PillData, str, str],
    ) -> None:
        pill, rename_input_tag, modal_tag = user_data
        if not dpg.does_item_exist(rename_input_tag):
            return
        new_name = dpg.get_value(rename_input_tag).strip()
        if not new_name or not pill.fn_symbol:
            return

        err = rename_script_function_display_name(
            self.session.kernel,
            pill.storage_id_hex,
            pill.fn_symbol,
            new_name,
        )
        if isinstance(err, Error):
            return

        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        self.session.refresh()
        self.rebuild()

    def _open_function_picker(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[RuntimeID, str, list[str], str],
    ) -> None:
        entity_id, comp_name, curr_path, input_tag = user_data
        picker_tag = "window_function_picker"
        if dpg.does_item_exist(picker_tag):
            dpg.delete_item(picker_tag)

        pills = get_available_function_pills(self.session.kernel)

        with dpg.window(
            label="Function Picker",
            tag=picker_tag,
            modal=True,
            width=460,
            height=340,
            pos=(400, 200),
        ):
            dpg.add_text("Select a script function reference:", color=(160, 180, 220))
            dpg.add_separator()

            if not pills:
                dpg.add_text("No exported script functions found in project.", color=(150, 150, 150))
            else:
                with dpg.child_window(height=-40, autosize_x=True):
                    for p in pills:
                        label = f"[{p.res_name}] :: [{p.fn_display_name or p.fn_symbol}] ({p.fn_symbol})"
                        btn = dpg.add_button(
                            label=label,
                            width=-1,
                            callback=self._on_picker_select_pill,
                            user_data=(p, entity_id, comp_name, curr_path, input_tag, picker_tag),
                        )
                        dpg.bind_item_theme(btn, get_pill_theme())

            dpg.add_button(
                label="Cancel",
                callback=lambda: dpg.delete_item(picker_tag) if dpg.does_item_exist(picker_tag) else None,
            )

    def _on_picker_select_pill(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[PillData, RuntimeID, str, list[str], str, str],
    ) -> None:
        pill, entity_id, comp_name, curr_path, input_tag, picker_tag = user_data
        ref_value = f"<|1|{pill.storage_id_hex}|>.{pill.fn_symbol}"

        if dpg.does_item_exist(input_tag):
            dpg.set_value(input_tag, ref_value)

        if dpg.does_item_exist(picker_tag):
            dpg.delete_item(picker_tag)

        self._on_field_value_changed(input_tag, ref_value, (entity_id, comp_name, curr_path, "str"))
        self.rebuild()

