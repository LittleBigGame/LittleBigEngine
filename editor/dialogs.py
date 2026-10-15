"""Shared confirmations for editor actions that discard unsaved work."""

import dearpygui.dearpygui as dpg


def confirm_reload(session, action=None):
    """Reload immediately if clean; otherwise require an explicit discard action."""
    action = action or session.reload_all_resources
    if session.get_dirty_count() == 0:
        action()
        return
    tag = "confirm_discard_unsaved"
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

    def discard():
        dpg.delete_item(tag)
        action()

    with dpg.window(label="Discard unsaved changes?", tag=tag, modal=True, width=440, height=140):
        dpg.add_text("Reloading will discard unsaved changes.")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Cancel", callback=lambda: dpg.delete_item(tag))
            dpg.add_button(label="Discard and reload", callback=discard)
