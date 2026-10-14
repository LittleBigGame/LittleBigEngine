"""Storage panel displaying loaded resources, dirty statuses, and persistence actions."""

from __future__ import annotations

from typing import Any
import dearpygui.dearpygui as dpg

from LBE.types import Error, RuntimeID
from .pills import (
    PillData,
    get_available_function_pills,
    get_pill_theme,
    rename_script_function_display_name,
)
from .session import EditorSession


class StoragePanel:
    """Dockable panel showing all loaded memory resources and disk persistence tools."""

    def __init__(self, session: EditorSession, tag: str = "window_storage") -> None:
        self.session = session
        self.tag = tag
        self.table_container_tag = f"{self.tag}_table_container"
        self.table_tag = f"{self.tag}_table"
        self.save_dirty_btn_tag = f"{self.tag}_save_dirty_btn"
        self.search_tag = f"{self.tag}_search"
        self._filter_query: str = ""
        self._unsubscribe_state = self.session.subscribe_state_changed(self.rebuild)

    def build(self) -> str:
        """Create the storage resources window structure."""
        with dpg.window(
            label="Storage Resources",
            tag=self.tag,
            width=850,
            height=250,
            pos=(10, 540),
        ):
            # Toolbar
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Save Dirty Resources",
                    tag=self.save_dirty_btn_tag,
                    callback=self._on_save_dirty,
                )
                dpg.add_button(
                    label="Save All",
                    callback=self._on_save_all,
                )
                dpg.add_button(
                    label="Reload All",
                    callback=self._on_reload_all,
                )
                dpg.add_text(" | Search:")
                dpg.add_input_text(
                    hint="Filter by name, ID, or storage hex...",
                    width=250,
                    tag=self.search_tag,
                    callback=self._on_search_changed,
                )

            dpg.add_separator()

            with dpg.child_window(
                tag=self.table_container_tag,
                autosize_x=True,
                autosize_y=True,
            ):
                with dpg.table(
                    tag=self.table_tag,
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    row_background=True,
                    policy=dpg.mvTable_SizingStretchProp,
                ):
                    dpg.add_table_column(label="RuntimeID", width_fixed=True, init_width_or_weight=80)
                    dpg.add_table_column(label="Type", width_fixed=True, init_width_or_weight=80)
                    dpg.add_table_column(label="Name")
                    dpg.add_table_column(label="StorageID (Hex)")
                    dpg.add_table_column(label="Dirty?", width_fixed=True, init_width_or_weight=75)
                    dpg.add_table_column(label="Actions", width_fixed=True, init_width_or_weight=220)

        self.rebuild()
        return self.tag

    def rebuild(self) -> None:
        """Re-render table rows while keeping column definitions stable."""
        if not dpg.does_item_exist(self.table_tag):
            return

        # Update dirty badge on toolbar button
        dirty_count = self.session.get_dirty_count()
        badge_label = f"Save Dirty Resources ({dirty_count})" if dirty_count > 0 else "Save Dirty Resources"
        if dpg.does_item_exist(self.save_dirty_btn_tag):
            dpg.configure_item(self.save_dirty_btn_tag, label=badge_label)

        # Delete only existing table rows (slot 1), keeping columns (slot 0) stable
        for row in dpg.get_item_children(self.table_tag, 1):
            dpg.delete_item(row)

        resources = self.session.get_all_resources()

        # Apply search filter
        if self._filter_query:
            q = self._filter_query.lower()
            resources = [
                r
                for r in resources
                if q in str(r["runtime_id"]).lower()
                or q in str(r["name"]).lower()
                or q in str(r["storage_id_hex"]).lower()
                or q in ("entity" if r["is_entity"] else "script")
            ]

        for res in resources:
            rid = res["runtime_id"]
            res_type = "Entity" if res["type"] == 0 else ("Script" if res["type"] == 1 else f"Type({res['type']})")
            name = res["name"]
            sid_hex = res["storage_id_hex"]
            is_dirty = res["is_dirty"]
            is_entity = res["is_entity"]

            with dpg.table_row(parent=self.table_tag):
                dpg.add_text(str(rid))
                dpg.add_text(res_type)
                dpg.add_text(name)
                dpg.add_text(sid_hex[:16] + "..." if len(sid_hex) > 16 else sid_hex)

                if is_dirty:
                    dpg.add_text("DIRTY", color=(255, 100, 100))
                else:
                    dpg.add_text("Clean", color=(100, 200, 100))

                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Save",
                        callback=self._on_save_single,
                        user_data=rid,
                    )
                    if is_entity:
                        dpg.add_button(
                            label="Select",
                            callback=self._on_select_entity,
                            user_data=rid,
                        )
                    if res_type == "Script":
                        dpg.add_button(
                            label="Functions",
                            callback=self._open_script_functions_modal,
                            user_data=(rid, name, sid_hex),
                        )

    def _on_save_dirty(self) -> None:
        self.session.save_dirty_resources()

    def _on_save_all(self) -> None:
        self.session.save_all_resources()

    def _on_reload_all(self) -> None:
        self.session.reload_all_resources()

    def _on_save_single(self, sender: str | int, app_data: Any, user_data: RuntimeID) -> None:
        self.session.save_resource(user_data)

    def _on_select_entity(self, sender: str | int, app_data: Any, user_data: RuntimeID) -> None:
        self.session.select_entity(user_data)

    def _on_search_changed(self, sender: str | int, app_data: str) -> None:
        self._filter_query = app_data.strip()
        self.rebuild()

    def _open_script_functions_modal(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[RuntimeID, str, str],
    ) -> None:
        rid, name, sid_hex = user_data
        modal_tag = f"window_script_functions_{rid}"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        all_pills = get_available_function_pills(self.session.kernel)
        script_pills = [p for p in all_pills if p.storage_id_hex.lower() == sid_hex.lower()]

        with dpg.window(
            label=f"Functions - {name}",
            tag=modal_tag,
            modal=True,
            width=540,
            height=340,
            pos=(380, 200),
        ):
            dpg.add_text(f"Script: {name} [RuntimeID: {rid}]", color=(100, 150, 255))
            dpg.add_text(f"StorageID: {sid_hex}", color=(140, 145, 160))
            dpg.add_separator()

            list_tag = f"{modal_tag}_list"
            if not script_pills:
                dpg.add_text("No exported functions (_fn_*) found in this script.", color=(150, 150, 150))
            else:
                with dpg.child_window(tag=list_tag, height=-40, autosize_x=True):
                    self._render_script_function_rows(modal_tag, script_pills, sid_hex, parent_container=list_tag)

            dpg.add_button(
                label="Close",
                callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None,
            )

    def _render_script_function_rows(
        self,
        modal_tag: str,
        script_pills: list[PillData],
        sid_hex: str,
        parent_container: str | int | None = None,
    ) -> None:
        kwargs = {"parent": parent_container} if parent_container else {}
        for p in script_pills:
            fn_label = f"[{p.fn_display_name or p.fn_symbol}] ({p.fn_symbol})"
            ref_str = f"<|1|{sid_hex}|>.{p.fn_symbol}"

            with dpg.group(horizontal=True, **kwargs):
                btn = dpg.add_button(label=fn_label, width=240)
                dpg.bind_item_theme(btn, get_pill_theme())

                dpg.add_button(
                    label="Copy Ref",
                    callback=lambda s, a, u: dpg.set_clipboard_text(u),
                    user_data=ref_str,
                )
                dpg.add_button(
                    label="Rename",
                    callback=self._open_rename_dialog,
                    user_data=(p, modal_tag, sid_hex),
                )

    def _open_rename_dialog(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[PillData, str, str],
    ) -> None:
        pill, parent_modal_tag, sid_hex = user_data
        rename_dialog_tag = f"dialog_rename_{pill.fn_symbol}"
        if dpg.does_item_exist(rename_dialog_tag):
            dpg.delete_item(rename_dialog_tag)

        with dpg.window(
            label=f"Rename Display Name - {pill.fn_symbol}",
            tag=rename_dialog_tag,
            modal=True,
            width=400,
            height=180,
            pos=(440, 240),
        ):
            dpg.add_text(f"Function Symbol: {pill.fn_symbol}", color=(160, 180, 220))
            dpg.add_text("Enter new display name (updates trailing comment):")
            input_tag = f"{rename_dialog_tag}_input"
            dpg.add_input_text(
                default_value=pill.fn_display_name or pill.fn_symbol,
                tag=input_tag,
                width=-1,
            )
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Apply",
                    callback=self._on_apply_function_rename,
                    user_data=(pill, input_tag, rename_dialog_tag, parent_modal_tag, sid_hex),
                )
                dpg.add_button(
                    label="Cancel",
                    callback=lambda: dpg.delete_item(rename_dialog_tag) if dpg.does_item_exist(rename_dialog_tag) else None,
                )

    def _on_apply_function_rename(
        self,
        sender: str | int,
        app_data: Any,
        user_data: tuple[PillData, str, str, str, str],
    ) -> None:
        pill, input_tag, rename_dialog_tag, parent_modal_tag, sid_hex = user_data
        if not dpg.does_item_exist(input_tag):
            return
        new_name = dpg.get_value(input_tag).strip()
        if not new_name or not pill.fn_symbol:
            return

        err = rename_script_function_display_name(
            self.session.kernel,
            sid_hex,
            pill.fn_symbol,
            new_name,
        )
        if isinstance(err, Error):
            return

        if dpg.does_item_exist(rename_dialog_tag):
            dpg.delete_item(rename_dialog_tag)

        self.session.refresh()
        self.rebuild()
        list_tag = f"{parent_modal_tag}_list"
        if dpg.does_item_exist(list_tag):
            dpg.delete_item(list_tag, children_only=True)
            updated_pills = [
                p
                for p in get_available_function_pills(self.session.kernel)
                if p.storage_id_hex.lower() == sid_hex.lower()
            ]
            self._render_script_function_rows(parent_modal_tag, updated_pills, sid_hex, parent_container=list_tag)

