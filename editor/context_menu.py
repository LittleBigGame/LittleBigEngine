"""Layered Context Menu System for LittleBigEngine Dear PyGui Editor.

Universal right-click menu operating in 3 structured layers:
- Layer 1 (Top): Target Actions (Verbs for whatever was clicked: Entity, Component, etc.)
- Layer 2 (Middle): Panel Actions (Verbs for the active panel, followed by other valid panels)
- Layer 3 (Bottom): Engine Actions (Global actions: Save Dirty, Play/Pause, Reload)
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Any
import dearpygui.dearpygui as dpg

from LBE.types import RuntimeID
from LBE.proxy import _unwrap
from .session import EditorSession


def open_context_menu(
    session: EditorSession,
    target_id: RuntimeID | None = None,
    panel_type: str = "hierarchy",
    panel_instance: Any = None,
    popup_tag: str = "popup_context_menu",
) -> None:
    """Construct and display the 3-layer right-click context menu at the mouse cursor."""
    if dpg.does_item_exist(popup_tag):
        dpg.delete_item(popup_tag)

    # When clicking an entity, ensure it is selected
    if target_id is not None:
        session.select_entity(target_id)

    with dpg.window(
        tag=popup_tag,
        popup=True,
        no_title_bar=True,
        no_move=True,
        no_resize=True,
        autosize=True,
    ):
        # ---------------------------------------------------------------------
        # LAYER 1: Target Actions (What was clicked)
        # ---------------------------------------------------------------------
        if target_id is not None and session.kernel.is_entity(target_id):
            name = session.get_entity_name(target_id)
            dpg.add_text(f"Entity: {name}", color=(120, 215, 255, 255))
            dpg.add_separator()

            dpg.add_menu_item(
                label="  + Add Child Entity",
                callback=lambda: _on_add_child(session, target_id, popup_tag),
            )
            dpg.add_menu_item(
                label="  Duplicate Entity",
                callback=lambda: _on_duplicate(session, target_id, popup_tag),
            )
            dpg.add_menu_item(
                label="  Delete Entity",
                callback=lambda: _on_delete(session, target_id, popup_tag),
            )
            dpg.add_menu_item(
                label="  + Add Component...",
                callback=lambda: _on_prompt_add_component(session, target_id, popup_tag),
            )
            dpg.add_separator()

        # ---------------------------------------------------------------------
        # LAYER 2: Panel Actions (Where you are & Other valid panels)
        # ---------------------------------------------------------------------
        dpg.add_text(f"Panel: {panel_type.capitalize()}", color=(170, 180, 200, 255))

        # 2A. Actions for THIS panel
        if panel_type == "hierarchy":
            if target_id is not None:
                dpg.add_menu_item(
                    label="  Set as View Root (Scope)",
                    callback=lambda: _on_set_view_root(session, target_id, popup_tag),
                )
            if session.view_root_id is not None:
                dpg.add_menu_item(
                    label="  Reset Root Scope (Show All)",
                    callback=lambda: _on_reset_view_root(session, popup_tag),
                )
            if panel_instance is not None and hasattr(panel_instance, "collapse_all"):
                dpg.add_menu_item(
                    label="  Collapse All",
                    callback=lambda: _on_collapse_all(panel_instance, popup_tag),
                )
                dpg.add_menu_item(
                    label="  Expand All",
                    callback=lambda: _on_expand_all(panel_instance, popup_tag),
                )
        elif panel_type == "inspector":
            if panel_instance is not None and hasattr(panel_instance, "toggle_lock"):
                is_locked = getattr(panel_instance, "is_locked", False)
                lock_label = "  Unlock Panel" if is_locked else "  Lock [Pin] to Target"
                dpg.add_menu_item(
                    label=lock_label,
                    callback=lambda: _on_toggle_lock(panel_instance, popup_tag),
                )
            if panel_instance is not None and hasattr(panel_instance, "set_active"):
                dpg.add_menu_item(
                    label="  Set as Active Inspector",
                    callback=lambda: _on_set_active_inspector(panel_instance, popup_tag),
                )
            dpg.add_menu_item(
                label="  Clear Target",
                callback=lambda: _on_clear_inspector_target(panel_instance, popup_tag),
            )

        # 2B. Actions for OTHER valid panels
        dpg.add_separator()
        dpg.add_text("Other Panels", color=(140, 150, 170, 255))
        if target_id is not None:
            dpg.add_menu_item(
                label="  Focus in Viewport",
                callback=lambda: _on_focus_in_viewport(session, target_id, popup_tag),
            )
        else:
            dpg.add_menu_item(
                label="  + Create Root Entity",
                callback=lambda: _on_create_root_entity(session, popup_tag),
            )

        # ---------------------------------------------------------------------
        # LAYER 3: Engine Actions (Global)
        # ---------------------------------------------------------------------
        dpg.add_separator()
        dpg.add_text("Engine", color=(180, 180, 190, 255))
        dirty_cnt = session.get_dirty_count()
        save_label = f"  Save Dirty Resources ({dirty_cnt})  [Ctrl+S]" if dirty_cnt > 0 else "  Save Resources  [Ctrl+S]"
        dpg.add_menu_item(
            label=save_label,
            callback=lambda: _on_save_all(session, popup_tag),
        )
        play_label = "  Pause Simulation" if session.is_playing else "  Play Simulation"
        dpg.add_menu_item(
            label=play_label,
            callback=lambda: _on_toggle_play(session, popup_tag),
        )
        dpg.add_menu_item(
            label="  Reload Project from Disk",
            callback=lambda: _on_reload_all(session, popup_tag),
        )


def _close_popup(popup_tag: str) -> None:
    if dpg.does_item_exist(popup_tag):
        dpg.delete_item(popup_tag)


def _on_add_child(session: EditorSession, parent_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.create_child_entity(parent_id=parent_id, name=f"Entity_{session.kernel.runtime_idx}")


def _on_duplicate(session: EditorSession, entity_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    comps = _unwrap(session.get_components(entity_id))
    parent = session.kernel.get_entity_parent(entity_id)
    name = f"{session.get_entity_name(entity_id)}_Copy"
    session.create_entity(name=name, parent_id=parent, components=comps)


def _on_delete(session: EditorSession, entity_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.delete_entity(entity_id)


def _on_set_view_root(session: EditorSession, root_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.set_view_root(root_id)


def _on_reset_view_root(session: EditorSession, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.set_view_root(None)


def _on_collapse_all(panel: Any, popup_tag: str) -> None:
    _close_popup(popup_tag)
    panel.collapse_all()


def _on_expand_all(panel: Any, popup_tag: str) -> None:
    _close_popup(popup_tag)
    panel.expand_all()


def _on_toggle_lock(panel: Any, popup_tag: str) -> None:
    _close_popup(popup_tag)
    panel.toggle_lock()


def _on_set_active_inspector(panel: Any, popup_tag: str) -> None:
    _close_popup(popup_tag)
    if hasattr(panel, "set_active"):
        panel.set_active()


def _on_clear_inspector_target(panel: Any, popup_tag: str) -> None:
    _close_popup(popup_tag)
    if hasattr(panel, "set_target"):
        panel.set_target(None)


def _on_prompt_add_component(session: EditorSession, target_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    modal_tag = "window_add_component_modal"
    if dpg.does_item_exist(modal_tag):
        dpg.delete_item(modal_tag)

    with dpg.window(
        label="+ Add Component",
        tag=modal_tag,
        modal=True,
        width=320,
        height=140,
        pos=(500, 300),
    ):
        dpg.add_text(f"Target: {session.get_entity_name(target_id)}", color=(120, 215, 255))
        inp = dpg.add_input_text(hint="Component Name (e.g. Health)", width=-1)

        def _do_add() -> None:
            cname = dpg.get_value(inp).strip()
            if cname:
                session.add_component(target_id, cname, {})
                if dpg.does_item_exist(modal_tag):
                    dpg.delete_item(modal_tag)

        with dpg.group(horizontal=True):
            dpg.add_button(label="Add", width=120, callback=_do_add)
            dpg.add_button(
                label="Cancel",
                width=120,
                callback=lambda: dpg.delete_item(modal_tag) if dpg.does_item_exist(modal_tag) else None,
            )


def _on_open_in_new_inspector(session: EditorSession, target_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    # If app or session has spawn_inspector callback
    if hasattr(session, "spawn_inspector"):
        session.spawn_inspector(target_id=target_id, locked=True)
    else:
        # Route to active inspector and lock it
        if session.active_inspector is not None:
            session.active_inspector.set_target(target_id)
            if hasattr(session.active_inspector, "is_locked"):
                session.active_inspector.is_locked = True
                if hasattr(session.active_inspector, "rebuild"):
                    session.active_inspector.rebuild()


def _on_focus_in_viewport(session: EditorSession, target_id: RuntimeID, popup_tag: str) -> None:
    _close_popup(popup_tag)
    if hasattr(session, "active_viewport") and session.active_viewport is not None:
        if hasattr(session.active_viewport, "focus_entity"):
            session.active_viewport.focus_entity(target_id)


def _on_create_root_entity(session: EditorSession, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.create_entity(name=f"Entity_{session.kernel.runtime_idx}")


def _on_save_all(session: EditorSession, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.save_dirty_resources()


def _on_toggle_play(session: EditorSession, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.toggle_play()


def _on_reload_all(session: EditorSession, popup_tag: str) -> None:
    _close_popup(popup_tag)
    session.reload_all_resources()
