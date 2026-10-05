"""An editor application composed with the public LBE and UI APIs."""

import ast
import keyword
import os
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
from uuid import UUID

from lbe.ui import (UI, put, contains, parse_box, content_rect, stack, dock,
                    row, column, apply_layout, BG, PANEL, FIELD, ACCENT,
                    INK, MUTED, PITCH, LINE, STACK_COLORS)
from lbe.text import TextBuffer
from lbe.space import screen_to_world, world_to_screen, world_bounds, world_position
from lbe.project import save_project, load_project_data, deserialize_entities, activate_entities, PersistentGraph
from lbe.project_files import ProjectFiles
from lbe.menus import open_menu
from lbe.dock import DockTree, SplitNode, TabGroupNode

state = entity.components.get("application_state")


def message(text):
    state.app.status = text


def selected():
    sel = state.app.relations.get('selection')
    if sel is None or not sel.alive:
        sel = state.game
        state.app.relations['selection'] = sel
    return sel


def inspected():
    ins = state.app.relations.get('inspected')
    if ins is None or not ins.alive:
        ins = selected()
        state.app.relations['inspected'] = ins
    return ins


def select(entity):
    if entity is None or not entity.alive:
        entity = state.game
    state.app.relations['selection'] = entity
    state.game.relations['selection'] = entity
    state.app.relations['inspected'] = entity
    state.inspector.scroll = 0
    if 'focus' in state.app.relations:
        del state.app.relations['focus']
    for ancestor in entity.ancestors:
        state.hierarchy.expanded.add(ancestor.id)
    if hasattr(state, "inspector_sync"):
        state.inspector_sync()


def inspect_entity(entity):
    select(entity)



def format_float_clean(f):
    if hasattr(state, "format_float_clean"):
        return state.format_float_clean(f)
    if abs(f) < 1e-12:
        return "0.0"
    rounded = round(f, 6)
    if rounded == int(rounded):
        return f"{int(rounded)}.0"
    s = f"{rounded:.6f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def clean_repr(value):
    if hasattr(state, "clean_repr"):
        return state.clean_repr(value)
    if isinstance(value, float):
        return format_float_clean(value)
    if isinstance(value, tuple):
        if len(value) == 1:
            return f"({clean_repr(value[0])},)"
        return f"({', '.join(clean_repr(v) for v in value)})"
    if isinstance(value, list):
        return f"[{', '.join(clean_repr(v) for v in value)}]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{clean_repr(k)}: {clean_repr(v)}" for k, v in value.items()) + "}"
    return repr(value)


def safe_repr(value):
    if hasattr(state, "safe_repr"):
        return state.safe_repr(value)
    try:
        return clean_repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def parse_value(text):
    if hasattr(state, "parse_value"):
        return state.parse_value(text)
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        raise ValueError("Use a Python literal; put text in quotes") from None


def on_drag_col_splitter(*args, **kwargs):
    callback = getattr(state, "on_drag_col_splitter", None)
    if callback is not None:
        return callback(*args, **kwargs)


def on_drag_hierarchy_splitter(*args, **kwargs):
    callback = getattr(state, "on_drag_hierarchy_splitter", None)
    if callback is not None:
        return callback(*args, **kwargs)


def on_drag_code_splitter(*args, **kwargs):
    callback = getattr(state, "on_drag_code_splitter", None)
    if callback is not None:
        return callback(*args, **kwargs)


def contains_box(*args, **kwargs):
    callback = getattr(state, "contains_box", None)
    if callback is not None:
        return callback(*args, **kwargs)


def start_panel_dock_drag(*args, **kwargs):
    callback = getattr(state, "start_panel_dock_drag", None)
    if callback is not None:
        return callback(*args, **kwargs)


def on_dock_drag(*args, **kwargs):
    callback = getattr(state, "on_dock_drag", None)
    if callback is not None:
        return callback(*args, **kwargs)


def on_dock_drop(*args, **kwargs):
    callback = getattr(state, "on_dock_drop", None)
    if callback is not None:
        return callback(*args, **kwargs)


def sync_all_editor_panels(*args, **kwargs):
    callback = getattr(state, "sync_all_editor_panels", None)
    if callback is not None:
        return callback(*args, **kwargs)


def close_panel(*args, **kwargs):
    callback = getattr(state, "close_panel", None)
    if callback is not None:
        return callback(*args, **kwargs)


def toggle_panel_view(*args, **kwargs):
    callback = getattr(state, "toggle_panel_view", None)
    if callback is not None:
        return callback(*args, **kwargs)


def reset_default_layout(*args, **kwargs):
    callback = getattr(state, "reset_default_layout", None)
    if callback is not None:
        return callback(*args, **kwargs)


def open_launcher_project():
    switch = state.runtime.services.get("switch_project")
    if switch:
        switch(None)


def open_file_menu_dropdown(button):
    actions = [
        {"label": "Save Project (Ctrl+S)", "run": lambda _: save_project_action()},
        {"label": "Project Manager / Switch...", "run": lambda _: open_launcher_project()},
        None,
        {"label": "New System...", "run": lambda _: new_source()},
        {"label": "Open System...", "run": lambda _: open_path()},
    ]
    open_menu(state.ui, button, button.x, button.y + button.h + 2, actions=actions)


def open_edit_menu_dropdown(button):
    actions = [
        {"label": "Run / Pause (F5)", "run": lambda _: toggle_game_running()},
        {"label": "Inspect Selection", "run": lambda _: open_panel()},
        None,
        {"label": "Reset Default Layout", "run": lambda _: reset_default_layout()},
    ]
    open_menu(state.ui, button, button.x, button.y + button.h + 2, actions=actions)


def open_view_menu_dropdown(button):
    dt = getattr(state, "dock_tree", None)
    panels_open = {
        "hierarchy": bool(dt and dt.find_tab_group_with_panel("hierarchy")),
        "files": bool(dt and dt.find_tab_group_with_panel("files")),
        "inspector": bool(dt and dt.find_tab_group_with_panel("inspector")),
        "viewport": bool(dt and dt.find_tab_group_with_panel("viewport")),
        "code_panel": bool(dt and dt.find_tab_group_with_panel("code_panel")),
    }
    actions = [
        {"label": f"{'[x]' if panels_open['hierarchy'] else '[  ]'} Hierarchy", "run": lambda _: toggle_panel_view("hierarchy")},
        {"label": f"{'[x]' if panels_open['files'] else '[  ]'} Project Files", "run": lambda _: toggle_panel_view("files")},
        {"label": f"{'[x]' if panels_open['inspector'] else '[  ]'} Inspector", "run": lambda _: toggle_panel_view("inspector")},
        {"label": f"{'[x]' if panels_open['viewport'] else '[  ]'} Viewport", "run": lambda _: toggle_panel_view("viewport")},
        {"label": f"{'[x]' if panels_open['code_panel'] else '[  ]'} System Source", "run": lambda _: toggle_panel_view("code_panel")},
        None,
        {"label": "System Log (Ctrl+L)", "run": lambda _: open_system_log()},
        None,
        {"label": "Frame all game entities", "run": lambda _: frame_game()},
        {"label": "Frame selected entity", "run": lambda _: context_focus_camera(selected())},
        {"label": "Reset Default Layout", "run": lambda _: reset_default_layout()},
    ]
    open_menu(state.ui, button, button.x, button.y + button.h + 2, actions=actions)


def select_dock_tab(*args, **kwargs):
    callback = getattr(state, "select_dock_tab", None)
    if callback is not None:
        return callback(*args, **kwargs)


def initialize():
    global state
    state = SimpleNamespace(runtime=entity.runtime, project=project, window=window,
                            graphics=graphics, input=input, app=entity)
    entity.components["application_state"] = state
    state.hierarchy_sync = hierarchy_sync
    state.inspector_sync = inspector_sync
    state.message = message
    state.save_editor_project = save_editor_project
    entity.systems.attach("docking", assets["31c71ace-2c53-52f9-9164-56b175f5d969"])
    entity.systems.attach("effects", assets["d6929c06-9cca-576e-b179-d577c2da8312"])
    (state.project / "systems/game").mkdir(parents=True, exist_ok=True)
    state.files = ProjectFiles(state.runtime, state.project)
    state.ui = UI(entity, window, graphics, input)
    state.background = state.ui.create(entity, "Background", "rect", color=BG, layer=0)

    project_data = load_project_data(project)
    if project_data is not None and project_data.get("entities"):
        restored = deserialize_entities(project_data["entities"], state.runtime, default_parent=entity, project_dir=project, activate=False)
        state.game = next((e for e in restored.values() if "root" in e.tags and e.components.get("name") == "Game"), None)
        if state.game is None:
            state.game = next((e for e in restored.values() if e.parent is entity), next(iter(restored.values())))
    else:
        state.game = create(parent=entity, name="Game", tags=["root"])
        create(parent=state.game, name="Entity A", x=-3.0, y=-1.0, w=2.0, h=2.0, color=(75, 185, 210))
        create(parent=state.game, name="Entity B", x=1.0, y=0.0, w=1.5, h=1.5, color=(232, 165, 80))
        if (assets.registry.get_path("cd53cb27-f893-5a6b-a3d2-52f550f7d35d") is not None and assets.registry.get_path("cd53cb27-f893-5a6b-a3d2-52f550f7d35d").exists()):
            state.game.systems.attach("render", assets["cd53cb27-f893-5a6b-a3d2-52f550f7d35d"])

    state.camera = create(parent=entity, name="Camera", x=0.0, y=0.0, zoom=48.0)
    state.viewport_panel = state.ui.create(entity, "ViewportPanel", "panel", color=PANEL, layer=0)
    state.viewport = state.ui.create(state.viewport_panel, "Viewport", "surface", color=(12, 18, 25), layer=0)
    space.configure(scope=state.game, bounds_fn=world_bounds)
    state.game.relations["camera"] = state.camera
    state.game.relations["viewport"] = state.viewport
    if project_data and project_data.get("entities"):
        activate_entities(restored.values(), state.runtime, project_dir=project)

    drawing = assets["f084e424-d2d9-5fd1-8624-63580396274c"]
    outline = assets["dbc0d180-5a28-56a1-bc9c-85d63174e431"]
    for target in state.game.descendants:
        if 'color' in target.components and drawing not in target.scripts:
            target.scripts.attach(drawing)
        if 'color' in target.components and outline not in target.scripts:
            target.scripts.attach(outline)

    state.hierarchy_rows = []
    state.component_rows = []
    state.system_rows = []
    state.system_edit_buttons = []
    state.system_detach_buttons = []
    state.child_rows = []
    state.extra_panels = []
    state.quick_component_presets = [
        ("pos", {"x": 0.0, "y": 0.0}),
        ("size", {"w": 32.0, "h": 32.0}),
        ("vel", {"vx": 0.0, "vy": 0.0}),
        ("color", {"color": (200, 200, 200)}),
        ("speed", {"speed": 100.0}),
    ]
    state.quick_presets_scroll = 0
    state.quick_preset_chips = []
    state.collapsed_sections = set()
    state._saved_source = None
    state._pending_discard = None
    state.app.status = 'Ready | Select an entity to inspect its data'

    layout_data = project_data.get("layout", {}) if project_data else {}
    saved_sel_id = layout_data.get("selection")
    initial_sel = None
    if saved_sel_id:
        try:
            initial_sel = state.runtime.resolve(UUID(saved_sel_id))
        except (KeyError, ValueError):
            initial_sel = None
    if initial_sel is None or not initial_sel.alive:
        initial_sel = state.game.children[0] if state.game.children else state.game
    state.app.relations['selection'] = initial_sel
    state.game.relations['selection'] = initial_sel

    state.app.components["left_column_w"] = layout_data.get("left_column_w", 370)
    state.header = state.ui.create(state.app, 'Header', 'panel', text='LBE', color=BG, dock='top', h=44, padding=(8, 16, 8, 16))

    # Top menu bar buttons (File, Edit, View)
    state.menu_file_btn = state.ui.button(state.header, 'MenuFile', 'File', lambda: open_file_menu_dropdown(state.menu_file_btn),
                                          color=BG, normal_color=BG, hover_color=(38, 55, 75), ink=INK)
    state.menu_edit_btn = state.ui.button(state.header, 'MenuEdit', 'Edit', lambda: open_edit_menu_dropdown(state.menu_edit_btn),
                                          color=BG, normal_color=BG, hover_color=(38, 55, 75), ink=INK)
    state.menu_view_btn = state.ui.button(state.header, 'MenuView', 'View', lambda: open_view_menu_dropdown(state.menu_view_btn),
                                          color=BG, normal_color=BG, hover_color=(38, 55, 75), ink=INK)

    # Panel close buttons (X)
    state.close_hierarchy_btn = state.ui.button(state.app, 'CloseHierarchy', 'X', lambda: close_panel('hierarchy'),
                                                color=PANEL, normal_color=PANEL, hover_color=(80, 35, 40), ink=MUTED, layer=5)
    state.close_files_btn = state.ui.button(state.app, 'CloseFiles', 'X', lambda: close_panel('files'),
                                            color=PANEL, normal_color=PANEL, hover_color=(80, 35, 40), ink=MUTED, layer=5)
    state.close_inspector_btn = state.ui.button(state.app, 'CloseInspector', 'X', lambda: close_panel('inspector'),
                                                color=PANEL, normal_color=PANEL, hover_color=(80, 35, 40), ink=MUTED, layer=5)
    state.close_viewport_btn = state.ui.button(state.app, 'CloseViewport', 'X', lambda: close_panel('viewport'),
                                               color=PANEL, normal_color=PANEL, hover_color=(80, 35, 40), ink=MUTED, layer=5)
    state.close_code_btn = state.ui.button(state.app, 'CloseCode', 'X', lambda: close_panel('code_panel'),
                                           color=PANEL, normal_color=PANEL, hover_color=(80, 35, 40), ink=MUTED, layer=5)

    state.dock_tab_buttons = []
    state.extra_splitters = []

    dock_data = layout_data.get("dock_tree")
    if dock_data:
        try:
            state.dock_tree = DockTree.from_dict(dock_data)
        except Exception:
            state.dock_tree = DockTree()
    else:
        state.dock_tree = DockTree()

    state.app.components["on_dock_drag"] = on_dock_drag
    state.app.components["on_dock_drop"] = on_dock_drop

    state.active_left_tab = "hierarchy"
    state.tab_hierarchy = state.ui.button(state.app, 'TabHierarchy', 'HIERARCHY', lambda: switch_left_tab('hierarchy'),
                                          color=(38, 55, 75), normal_color=(38, 55, 75), hover_color=(45, 60, 80))
    state.tab_files = state.ui.button(state.app, 'TabFiles', 'PROJECT FILES', lambda: switch_left_tab('files'),
                                      color=PANEL, normal_color=PANEL, hover_color=(45, 60, 80))
    h_conf = layout_data.get("hierarchy", {})
    state.hierarchy = state.ui.create(state.app, 'HierarchyPanel', 'panel', text='HIERARCHY', scroll=0,
                                     expanded={state.app.id, state.game.id}, dock=h_conf.get("dock", 'left_top'),
                                     panel_h=h_conf.get("panel_h", 240), margin=(8, 8, 4, 8), resizable=True)
    if "expanded" in h_conf:
        state.hierarchy.expanded = {UUID(x) for x in h_conf["expanded"]} | {state.app.id, state.game.id}
    if "panel_w" in h_conf and h_conf["panel_w"] is not None:
        state.hierarchy.components["panel_w"] = h_conf["panel_w"]

    state.file_explorer = state.ui.create(state.app, 'FileExplorerPanel', 'panel', text='PROJECT FILES', scroll=0,
                                          expanded=set(), dock='left_top', panel_h=h_conf.get("panel_h", 240),
                                          margin=(8, 8, 4, 8), resizable=True, visible=False)
    state.file_explorer_rows = []
    state.file_scroll_track = state.ui.create(state.file_explorer, 'FileScrollTrack', 'scrollbar_track', color=(28, 36, 48))
    state.file_scroll_thumb = state.ui.create(state.file_explorer, 'FileScrollThumb', 'scrollbar_thumb', color=(55, 75, 95), hover_color=(75, 115, 155), layer=3)

    i_conf = layout_data.get("inspector", {})
    state.inspector = state.ui.create(state.app, 'InspectorPanel', 'panel', text='INSPECTOR', scroll=0,
                                     dock=i_conf.get("dock", 'left_bottom'), margin=(4, 8, 6, 8), resizable=True)
    if "panel_h" in i_conf and i_conf["panel_h"] is not None:
        state.inspector.components["panel_h"] = i_conf["panel_h"]
    if "panel_w" in i_conf and i_conf["panel_w"] is not None:
        state.inspector.components["panel_w"] = i_conf["panel_w"]

    cp_conf = layout_data.get("code_panel", {})
    state.code_panel = state.ui.create(state.app, 'CodeEditorPanel', 'panel', text='SYSTEM SOURCE',
                                       dock=cp_conf.get("dock", 'right_bottom'), padding=(8, 12, 8, 12), resizable=True)
    if "split_y" in cp_conf and cp_conf["split_y"] is not None:
        state.code_panel.components["split_y"] = cp_conf["split_y"]
    if "panel_h" in cp_conf and cp_conf["panel_h"] is not None:
        state.code_panel.components["panel_h"] = cp_conf["panel_h"]
    if "panel_w" in cp_conf and cp_conf["panel_w"] is not None:
        state.code_panel.components["panel_w"] = cp_conf["panel_w"]

    cam_conf = layout_data.get("camera", {})
    if "x" in cam_conf:
        state.camera.x = cam_conf["x"]
    if "y" in cam_conf:
        state.camera.y = cam_conf["y"]
    if "zoom" in cam_conf:
        state.camera.zoom = cam_conf["zoom"]

    state.status = state.ui.create(state.app, 'StatusBar', 'label', text='', dock='bottom', h=20, margin=(0, 16, 5, 16))
    state.code = state.ui.multiline(state.code_panel, 'TextArea')
    state.path_field = state.ui.field(state.code_panel, 'SourcePath', 'render.py', hint='system_name.py', readonly=True, ink=(160, 180, 205))
    state.path_field.on_click = on_path_field_click
    state.new_button = state.ui.button(state.code_panel, 'NewSource', 'New', new_source)
    state.open_button = state.ui.button(state.code_panel, 'OpenSource', 'Open', open_path)
    state.save_button = state.ui.button(state.code_panel, 'SaveSource', 'Save / reload', save)
    state.attach_button = state.ui.button(state.code_panel, 'AttachSource', 'Attach', attach)
    state.save_project_button = state.ui.button(state.header, 'SaveProject', 'Save project', save_project_action)
    state.panel_button = state.ui.button(state.header, 'OpenPanel', 'Inspect in panel', open_panel)
    state.system_panel_button = state.ui.button(state.header, 'InspectSystem', 'Inspect system', inspect_system)
    state.detach_button = state.ui.button(state.header, 'DetachSystem', 'Detach system', detach_system)
    state.run_button = state.ui.button(state.header, 'ToggleRun', 'Pause (F5)', toggle_game_running)
    state.zoom_label = state.ui.create(state.app, 'ViewportCaption', 'label', text='WORLD', ink=MUTED)
    state.selection_label = state.ui.create(state.inspector, 'Selection', 'label', text='')
    state.name_label = state.ui.create(state.inspector, 'EntityNameLabel', 'label', text='Name', ink=MUTED)
    state.name_field = state.ui.field(state.inspector, 'EntityName', '', hint='entity name')
    state.name_field.on_commit = commit_name
    state.identity_label = state.ui.create(state.inspector, 'Identity', 'label', text='', ink=MUTED)
    state.add_child_button = state.ui.button(state.inspector, 'AddChildBtn', '+ Child', inspector_add_child)
    state.duplicate_button = state.ui.button(state.inspector, 'DuplicateBtn', 'Duplicate', inspector_duplicate_entity)
    state.delete_button = state.ui.button(state.inspector, 'DeleteBtn', 'Delete', inspector_delete_entity, color=(60, 30, 35))
    state.quick_pos_btn = state.ui.button(state.inspector, 'QuickPosBtn', 'pos', quick_add_pos, color=PANEL, hover_color=(45, 60, 80))
    state.quick_size_btn = state.ui.button(state.inspector, 'QuickSizeBtn', 'size', quick_add_size, color=PANEL, hover_color=(45, 60, 80))
    state.quick_vel_btn = state.ui.button(state.inspector, 'QuickVelBtn', 'vel', quick_add_vel, color=PANEL, hover_color=(45, 60, 80))
    state.quick_color_btn = state.ui.button(state.inspector, 'QuickColorBtn', 'color', quick_add_color, color=PANEL, hover_color=(45, 60, 80))
    state.quick_speed_btn = state.ui.button(state.inspector, 'QuickSpeedBtn', 'speed', quick_add_speed, color=PANEL, hover_color=(45, 60, 80))
    state.quick_preset_chips = [state.quick_pos_btn, state.quick_size_btn, state.quick_vel_btn, state.quick_color_btn, state.quick_speed_btn]
    state.quick_add_chip_btn = state.ui.button(state.inspector, 'QuickAddChip', '+', open_add_chip_menu, color=PANEL, hover_color=(45, 60, 80))
    state.components_title = state.ui.button(state.inspector, 'ComponentsTitle', '▼ COMPONENTS', lambda: toggle_section('components'), color=PANEL, hover_color=(38, 50, 66))
    state.add_comp_menu_button = state.ui.button(state.inspector, 'AddCompMenuBtn', '+ Add', open_add_component_menu)
    state.divider_identity = state.ui.create(state.inspector, 'DividerIdentity', 'rect', color=(38, 48, 62), layer=2)
    state.divider_components = state.ui.create(state.inspector, 'DividerComponents', 'rect', color=(38, 48, 62), layer=2)
    state.divider_systems = state.ui.create(state.inspector, 'DividerSystems', 'rect', color=(38, 48, 62), layer=2)
    state.component_delete_buttons = []
    state.relation_rows = []
    state.relation_edit_buttons = []
    state.hierarchy_scroll_track = state.ui.create(state.hierarchy, 'HierarchyScrollTrack', 'scrollbar_track', color=(28, 36, 48))
    state.hierarchy_scroll_track.on_click = hierarchy_track_click
    state.hierarchy_scroll_thumb = state.ui.create(state.hierarchy, 'HierarchyScrollThumb', 'scrollbar_thumb', color=(55, 75, 95), hover_color=(75, 115, 155), layer=3)
    state.hierarchy_scroll_thumb.on_drag = hierarchy_scroll_drag
    state.inspector_scroll_track = state.ui.create(state.inspector, 'InspectorScrollTrack', 'scrollbar_track', color=(28, 36, 48))
    state.inspector_scroll_track.on_click = inspector_track_click
    state.inspector_scroll_thumb = state.ui.create(state.inspector, 'InspectorScrollThumb', 'scrollbar_thumb', color=(55, 75, 95), hover_color=(75, 115, 155), layer=3)
    state.inspector_scroll_thumb.on_drag = inspector_scroll_drag
    state.add_name = state.ui.field(state.inspector, 'ComponentName', '', hint='component name')
    state.add_name.on_commit = lambda: state.ui.focus(state.add_value) if not state.add_value.buffer.text else add_component()
    state.add_value = state.ui.field(state.inspector, 'ComponentValue', '', hint='value, e.g. 2.0')
    state.add_value.on_commit = add_component
    state.add_button = state.ui.button(state.inspector, 'AddComponent', '+', add_component)
    state.tags_field = state.ui.field(state.inspector, 'Tags', '', hint='tags, comma separated')
    state.tags_field.on_commit = commit_tags
    state.parent_field = state.ui.field(state.inspector, 'Parent', '', hint='parent name or UUID; blank detaches')
    state.parent_field.on_commit = commit_parent
    state.relation_field = state.ui.field(state.inspector, 'Relations', '', hint='relation=target or target name')
    state.relation_field.on_commit = commit_relation
    state.link_add_button = state.ui.button(state.inspector, 'AddLinkBtn', '+', commit_relation)
    state.metadata = state.ui.create(state.inspector, 'Metadata', 'label', text='', ink=MUTED)
    state.system_label = state.ui.button(state.inspector, 'SystemsTitle', '▼ SYSTEMS', lambda: toggle_section('systems'), color=PANEL, hover_color=(38, 50, 66))
    state.add_system_button = state.ui.button(state.inspector, 'AddSystemBtn', '+ Attach', open_attach_system_menu)
    state.add_sys_menu_button = state.add_system_button
    state.no_systems_label = state.ui.create(state.inspector, 'NoSystemsLabel', 'label', text='No systems attached', ink=MUTED)
    state.links_header = state.ui.button(state.inspector, 'LinksHeader', '▼ LINKS & PARENT', lambda: toggle_section('links'), color=PANEL, hover_color=(38, 50, 66))
    state.links_title = state.links_header
    state.tags_label = state.ui.create(state.inspector, 'TagsLabel', 'label', text='Tags', ink=MUTED)
    state.parent_label = state.ui.create(state.inspector, 'ParentLabel', 'label', text='Parent', ink=MUTED)
    state.relations_label = state.ui.create(state.inspector, 'RelationsLabel', 'label', text='Link', ink=MUTED)
    state.relation_label = state.relations_label
    state.code_info = state.ui.create(state.code_panel, 'SourceInfo', 'label', text='', ink=MUTED)
    state.col_splitter = state.ui.splitter(state.app, 'ColumnSplitter', axis='x', on_drag=on_drag_col_splitter)
    state.hierarchy_splitter = state.ui.splitter(state.app, 'HierarchySplitter', axis='y', on_drag=on_drag_hierarchy_splitter)
    state.code_splitter = state.ui.splitter(state.app, 'CodeSplitter', axis='y', on_drag=on_drag_code_splitter)
    state.tab_hierarchy.on_drag = lambda c, ev: start_panel_dock_drag("hierarchy", ev)
    state.tab_files.on_drag = lambda c, ev: start_panel_dock_drag("files", ev)
    state.hierarchy.on_drag = lambda c, ev: start_panel_dock_drag("hierarchy", ev) if len(ev) > 2 and ev[2] <= c.y + 30 else None
    state.file_explorer.on_drag = lambda c, ev: start_panel_dock_drag("files", ev) if len(ev) > 2 and ev[2] <= c.y + 30 else None
    state.inspector.on_drag = lambda c, ev: start_panel_dock_drag("inspector", ev) if len(ev) > 2 and ev[2] <= c.y + 30 else None
    state.code_panel.on_drag = lambda c, ev: start_panel_dock_drag("code_panel", ev) if len(ev) > 2 and ev[2] <= c.y + 30 else None
    state.zoom_label.on_drag = lambda c, ev: start_panel_dock_drag("viewport", ev)
    if (assets.registry.get_path("97c33cfb-4f26-5e7a-bd0b-d689a72be2f5") is not None and assets.registry.get_path("97c33cfb-4f26-5e7a-bd0b-d689a72be2f5").exists()):
        if 'code_editor' not in state.code_panel.systems:
            state.code_panel.systems.attach('code_editor', assets["97c33cfb-4f26-5e7a-bd0b-d689a72be2f5"])
        if 'code_editor' not in state.code.systems:
            state.code.systems.attach('code_editor', assets["97c33cfb-4f26-5e7a-bd0b-d689a72be2f5"])
    if (assets.registry.get_path("62f6264e-f862-5aa2-9561-5e782dedd755") is not None and assets.registry.get_path("62f6264e-f862-5aa2-9561-5e782dedd755").exists()):
        if 'text_area' in state.code.systems:
            state.code.systems.reload('text_area', assets["62f6264e-f862-5aa2-9561-5e782dedd755"])
        else:
            state.code.systems.attach('text_area', assets["62f6264e-f862-5aa2-9561-5e782dedd755"])
    state.selected = selected
    state.inspected = inspected
    state.select = select
    state.inspect_entity = inspect_entity
    state.message = message
    state.open_system = open_system
    state.open_panel = open_panel
    state.save_editor_project = lambda: save_editor_project()
    state.new_source = lambda: new_source()
    state.rename_file = rename_file
    state.prompt_rename_file = prompt_rename_file
    state.open_file_menu = open_file_menu
    state.open_specific_file = open_specific_file
    state.switch_left_tab = switch_left_tab
    state.locate_in_file_explorer = locate_in_file_explorer
    state.open_launcher_project = open_launcher_project
    if (assets.registry.get_path("333b5454-9934-566b-90c6-19ddb72f2da1") is not None and assets.registry.get_path("333b5454-9934-566b-90c6-19ddb72f2da1").exists()) and 'hierarchy' not in state.hierarchy.systems:
        state.hierarchy.systems.attach('hierarchy', assets["333b5454-9934-566b-90c6-19ddb72f2da1"])
    if (assets.registry.get_path("ed74702d-a604-5ce0-ae65-6b79c63918ee") is not None and assets.registry.get_path("ed74702d-a604-5ce0-ae65-6b79c63918ee").exists()) and 'file_explorer' not in state.file_explorer.systems:
        state.file_explorer.systems.attach('file_explorer', assets["ed74702d-a604-5ce0-ae65-6b79c63918ee"])
    if (assets.registry.get_path("88190356-1ae0-55a2-af97-f45905e5910b") is not None and assets.registry.get_path("88190356-1ae0-55a2-af97-f45905e5910b").exists()) and 'inspector' not in state.inspector.systems:
        state.inspector.systems.attach('inspector', assets["88190356-1ae0-55a2-af97-f45905e5910b"])
    entity.systems.attach("source_files", assets["1e1ba739-27d5-552a-a816-91b1fa7081b3"])
    state.project_graph = PersistentGraph(state.runtime, tuple(restored.values()) + state.game.descendants if project_data and project_data.get("entities") else (state.game,) + state.game.descendants, application=state.app)
    if "render" in state.game.systems:
        open_system(state.game, "render")
    elif state.game.systems:
        open_system(state.game, next(iter(state.game.systems)))
    state.ready = True


def layout(*args, **kwargs):
    callback = getattr(state, "layout", None)
    if callback is not None:
        return callback(*args, **kwargs)

def hierarchy_sync():
    fn = getattr(state, "hierarchy_sync", None)
    if fn and fn is not hierarchy_sync:
        return fn()


def inspector_sync():
    fn = getattr(state, "inspector_sync", None)
    if fn and fn is not inspector_sync:
        return fn()


def hierarchy_click(row, event):
    fn = getattr(state, "hierarchy_click", None)
    if fn and fn is not hierarchy_click:
        return fn(row, event)


def hierarchy_scroll_drag(thumb, event):
    fn = getattr(state, "hierarchy_scroll_drag", None)
    if fn and fn is not hierarchy_scroll_drag:
        return fn(thumb, event)
    return True


def hierarchy_track_click(track, event):
    fn = getattr(state, "hierarchy_track_click", None)
    if fn and fn is not hierarchy_track_click:
        return fn(track, event)
    return True


def inspector_scroll_drag(thumb, event):
    fn = getattr(state, "inspector_scroll_drag", None)
    if fn and fn is not inspector_scroll_drag:
        return fn(thumb, event)
    return True


def inspector_track_click(track, event):
    fn = getattr(state, "inspector_track_click", None)
    if fn and fn is not inspector_track_click:
        return fn(track, event)
    return True


def switch_left_tab(tab_name):
    state.active_left_tab = tab_name
    # Sync dock tree active index
    if hasattr(state, "dock_tree"):
        group = state.dock_tree.find_tab_group_with_panel(tab_name)
        if group and tab_name in group.panels:
            group.active = group.panels.index(tab_name)
    layout()
    if tab_name == "files":
        fn = getattr(state, "file_explorer_sync", None)
        if fn:
            fn()
    else:
        hierarchy_sync()


def locate_in_file_explorer(target):
    reg = getattr(state.runtime.assets, "registry", None)
    rel_path = None
    if isinstance(target, UUID):
        item = reg.get(target) if reg else None
        if item:
            rel_path = item["path"]
    elif isinstance(target, str):
        try:
            u = UUID(target)
            item = reg.get(u) if reg else None
            if item:
                rel_path = item["path"]
        except ValueError:
            p = Path(target)
            if state.project and p.is_relative_to(state.project):
                rel_path = str(p.relative_to(state.project)).replace("\\", "/")
            else:
                rel_path = target.replace("\\", "/")
    elif isinstance(target, Path):
        try:
            rel_path = str(target.relative_to(state.project)).replace("\\", "/")
        except ValueError:
            rel_path = str(target).replace("\\", "/")

    if rel_path:
        if hasattr(state, "reveal_file"):
            state.reveal_file(state.project / rel_path)
        parts = rel_path.split("/")
        fe = getattr(state, "file_explorer", None)
        if fe:
            expanded = fe.components.setdefault("expanded", set())
            cur = ""
            for part in parts[:-1]:
                cur = f"{cur}/{part}" if cur else part
                expanded.add(cur)
        switch_left_tab("files")
        message(f"Located {parts[-1]} in Project Files")


def file_scroll_drag(thumb, event):
    fn = getattr(state, "file_scroll_drag", None)
    if fn and fn is not file_scroll_drag:
        return fn(thumb, event)
    return True


def file_track_click(track, event):
    fn = getattr(state, "file_track_click", None)
    if fn and fn is not file_track_click:
        return fn(track, event)
    return True


def component_click(control, event):
    fn = getattr(state, "component_click", None)
    if fn and fn is not component_click:
        return fn(control, event)
    return False


def commit_component(*args, **kwargs):
    fn = getattr(state, "commit_component", None)
    if fn and fn is not commit_component:
        return fn(*args, **kwargs)


def add_component(*args, **kwargs):
    fn = getattr(state, "add_component", None)
    if fn and fn is not add_component:
        return fn(*args, **kwargs)


def delete_component(*args, **kwargs):
    fn = getattr(state, "delete_component", None)
    if fn and fn is not delete_component:
        return fn(*args, **kwargs)


def commit_tags(*args, **kwargs):
    fn = getattr(state, "commit_tags", None)
    if fn and fn is not commit_tags:
        return fn(*args, **kwargs)


def resolve_name(text):
    fn = getattr(state, "resolve_name", None)
    if fn and fn is not resolve_name:
        return fn(text)


def commit_parent(*args, **kwargs):
    fn = getattr(state, "commit_parent", None)
    if fn and fn is not commit_parent:
        return fn(*args, **kwargs)


def commit_relation(*args, **kwargs):
    fn = getattr(state, "commit_relation", None)
    if fn and fn is not commit_relation:
        return fn(*args, **kwargs)


def start_edit_link(*args, **kwargs):
    fn = getattr(state, "start_edit_link", None)
    if fn and fn is not start_edit_link:
        return fn(*args, **kwargs)


def quick_link_to(*args, **kwargs):
    fn = getattr(state, "quick_link_to", None)
    if fn and fn is not quick_link_to:
        return fn(*args, **kwargs)


def commit_name(*args, **kwargs):
    fn = getattr(state, "commit_name", None)
    if fn and fn is not commit_name:
        return fn(*args, **kwargs)


def inspector_add_child(*args, **kwargs):
    fn = getattr(state, "inspector_add_child", None)
    if fn and fn is not inspector_add_child:
        return fn(*args, **kwargs)


def inspector_duplicate_entity(*args, **kwargs):
    fn = getattr(state, "inspector_duplicate_entity", None)
    if fn and fn is not inspector_duplicate_entity:
        return fn(*args, **kwargs)


def inspector_delete_entity(*args, **kwargs):
    fn = getattr(state, "inspector_delete_entity", None)
    if fn and fn is not inspector_delete_entity:
        return fn(*args, **kwargs)


def unlink_relation(*args, **kwargs):
    fn = getattr(state, "unlink_relation", None)
    if fn and fn is not unlink_relation:
        return fn(*args, **kwargs)


def focus_component_value(*args, **kwargs):
    fn = getattr(state, "focus_component_value", None)
    if fn and fn is not focus_component_value:
        return fn(*args, **kwargs)


def quick_add_pos(*args, **kwargs):
    fn = getattr(state, "quick_add_pos", None)
    if fn and fn is not quick_add_pos:
        return fn(*args, **kwargs)


def quick_add_size(*args, **kwargs):
    fn = getattr(state, "quick_add_size", None)
    if fn and fn is not quick_add_size:
        return fn(*args, **kwargs)


def quick_add_vel(*args, **kwargs):
    fn = getattr(state, "quick_add_vel", None)
    if fn and fn is not quick_add_vel:
        return fn(*args, **kwargs)


def quick_add_color(*args, **kwargs):
    fn = getattr(state, "quick_add_color", None)
    if fn and fn is not quick_add_color:
        return fn(*args, **kwargs)


def quick_add_speed(*args, **kwargs):
    fn = getattr(state, "quick_add_speed", None)
    if fn and fn is not quick_add_speed:
        return fn(*args, **kwargs)


def add_custom_component(*args, **kwargs):
    fn = getattr(state, "add_custom_component", None)
    if fn and fn is not add_custom_component:
        return fn(*args, **kwargs)


def commit_component_key(*args, **kwargs):
    fn = getattr(state, "commit_component_key", None)
    if fn and fn is not commit_component_key:
        return fn(*args, **kwargs)


def open_add_component_menu(*args, **kwargs):
    fn = getattr(state, "open_add_component_menu", None)
    if fn and fn is not open_add_component_menu:
        return fn(*args, **kwargs)


def open_attach_system_menu(*args, **kwargs):
    fn = getattr(state, "open_attach_system_menu", None)
    if fn and fn is not open_attach_system_menu:
        return fn(*args, **kwargs)


def prompt_new_system(*args, **kwargs):
    fn = getattr(state, "prompt_new_system", None)
    if fn and fn is not prompt_new_system:
        return fn(*args, **kwargs)


def attach_system_to_entity(*args, **kwargs):
    fn = getattr(state, "attach_system_to_entity", None)
    if fn and fn is not attach_system_to_entity:
        return fn(*args, **kwargs)


def detach_system_from_entity(*args, **kwargs):
    fn = getattr(state, "detach_system_from_entity", None)
    if fn and fn is not detach_system_from_entity:
        return fn(*args, **kwargs)


def toggle_section(*args, **kwargs):
    fn = getattr(state, "toggle_section", None)
    if fn and fn is not toggle_section:
        return fn(*args, **kwargs)


def open_add_chip_menu(*args, **kwargs):
    fn = getattr(state, "open_add_chip_menu", None)
    if fn and fn is not open_add_chip_menu:
        return fn(*args, **kwargs)


def prompt_add_preset(*args, **kwargs):
    fn = getattr(state, "prompt_add_preset", None)
    if fn and fn is not prompt_add_preset:
        return fn(*args, **kwargs)


def pin_to_quick_bar(*args, **kwargs):
    fn = getattr(state, "pin_to_quick_bar", None)
    if fn and fn is not pin_to_quick_bar:
        return fn(*args, **kwargs)


def apply_quick_preset(*args, **kwargs):
    fn = getattr(state, "apply_quick_preset", None)
    if fn and fn is not apply_quick_preset:
        return fn(*args, **kwargs)


def remove_quick_preset(*args, **kwargs):
    fn = getattr(state, "remove_quick_preset", None)
    if fn and fn is not remove_quick_preset:
        return fn(*args, **kwargs)


def start_rename_component(*args, **kwargs):
    fn = getattr(state, "start_rename_component", None)
    if fn and fn is not start_rename_component:
        return fn(*args, **kwargs)


def start_rename_tag(*args, **kwargs):
    fn = getattr(state, "start_rename_tag", None)
    if fn and fn is not start_rename_tag:
        return fn(*args, **kwargs)


def remove_tag(*args, **kwargs):
    fn = getattr(state, "remove_tag", None)
    if fn and fn is not remove_tag:
        return fn(*args, **kwargs)


def start_add_tag(*args, **kwargs):
    fn = getattr(state, "start_add_tag", None)
    if fn and fn is not start_add_tag:
        return fn(*args, **kwargs)


def change_component_type(*args, **kwargs):
    fn = getattr(state, "change_component_type", None)
    if fn and fn is not change_component_type:
        return fn(*args, **kwargs)


def open_change_type_menu(*args, **kwargs):
    fn = getattr(state, "open_change_type_menu", None)
    if fn and fn is not open_change_type_menu:
        return fn(*args, **kwargs)


def source_path(*args, **kwargs):
    callback = getattr(state, "source_path", None)
    if callback is not None:
        return callback(*args, **kwargs)


def new_source(*args, **kwargs):
    callback = getattr(state, "new_source", None)
    if callback is not None:
        return callback(*args, **kwargs)


def open_path(*args, **kwargs):
    callback = getattr(state, "open_path", None)
    if callback is not None:
        return callback(*args, **kwargs)


def open_specific_file(*args, **kwargs):
    callback = getattr(state, "open_specific_file", None)
    if callback is not None:
        return callback(*args, **kwargs)


def open_file_menu(*args, **kwargs):
    callback = getattr(state, "open_file_menu", None)
    if callback is not None:
        return callback(*args, **kwargs)


def on_path_field_click(*args, **kwargs):
    callback = getattr(state, "on_path_field_click", None)
    if callback is not None:
        return callback(*args, **kwargs)


def prompt_rename_file(*args, **kwargs):
    callback = getattr(state, "prompt_rename_file", None)
    if callback is not None:
        return callback(*args, **kwargs)


def commit_rename_file(*args, **kwargs):
    callback = getattr(state, "commit_rename_file", None)
    if callback is not None:
        return callback(*args, **kwargs)


def rename_file(*args, **kwargs):
    callback = getattr(state, "rename_file", None)
    if callback is not None:
        return callback(*args, **kwargs)


def update_open_source_location(*args, **kwargs):
    callback = getattr(state, "update_open_source_location", None)
    if callback is not None:
        return callback(*args, **kwargs)

def open_system(*args, **kwargs):
    callback = getattr(state, "open_system", None)
    if callback is not None:
        return callback(*args, **kwargs)

def confirm_discard(*args, **kwargs):
    callback = getattr(state, "confirm_discard", None)
    if callback is not None:
        return callback(*args, **kwargs)

def get_project_entities():
    return list(state.project_graph.entities)


def extract_completion_context():
    owner = state.code.relations.get('owner', selected())
    owner_comps = {}
    if owner and owner.alive:
        for k, v in owner.components.items():
            if isinstance(k, str) and k.isidentifier() and not keyword.iskeyword(k):
                owner_comps[k] = type(v).__name__

    entities_info = {}
    all_comps = {}
    for ent in get_project_entities():
        if not ent.alive:
            continue
        ent_comps = {}
        for k, v in ent.components.items():
            if isinstance(k, str) and k.isidentifier() and not keyword.iskeyword(k):
                tname = type(v).__name__
                ent_comps[k] = tname
                all_comps[k] = tname
        name = ent.components.get("name")
        if name and isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name):
            entities_info[name] = {"components": ent_comps, "id": str(ent.id)}

    return {
        "owner": {"components": owner_comps},
        "entities": entities_info,
        "all_components": all_comps,
    }


def get_editor_layout():
    sel = state.app.relations.get('selection')
    return {
        "left_column_w": state.app.components.get("left_column_w", 370),
        "hierarchy": {
            "panel_h": state.hierarchy.components.get("panel_h", 240),
            "panel_w": state.hierarchy.components.get("panel_w"),
            "dock": state.hierarchy.components.get("dock", "left_top"),
            "expanded": [str(eid) for eid in state.hierarchy.components.get("expanded", set()) if isinstance(eid, UUID)],
        },
        "inspector": {
            "panel_h": state.inspector.components.get("panel_h"),
            "panel_w": state.inspector.components.get("panel_w"),
            "dock": state.inspector.components.get("dock", "left_bottom"),
        },
        "code_panel": {
            "split_y": state.code_panel.components.get("split_y"),
            "panel_w": state.code_panel.components.get("panel_w"),
            "panel_h": state.code_panel.components.get("panel_h"),
            "dock": state.code_panel.components.get("dock", "right_bottom"),
        },
        "camera": {
            "x": state.camera.x,
            "y": state.camera.y,
            "zoom": state.camera.zoom,
        },
        "selection": str(sel.id) if sel is not None and sel.alive else None,
        "dock_tree": state.dock_tree.to_dict() if hasattr(state, "dock_tree") else None,
    }


def save_editor_project():
    if not hasattr(state, "project") or state.project is None:
        return
    try:
        from lbe.project import template_path
        if state.project.resolve() == template_path("editor").resolve():
            return
    except Exception:
        pass
    entities_to_save = get_project_entities()
    reg = getattr(state.runtime.assets, "registry", None)
    app_id = getattr(getattr(state, "app", None), "id", None)
    save_project(state.project, entities=entities_to_save, layout=get_editor_layout(), assets=reg, application_id=app_id, transient_relations={state.game.id: ("camera", "viewport", "selection")})


def save_project_action():
    save_editor_project()
    message("Saved project state and editor layout")


def save(*args, **kwargs):
    callback = getattr(state, "save", None)
    if callback is not None:
        return callback(*args, **kwargs)

def attach(*args, **kwargs):
    callback = getattr(state, "attach", None)
    if callback is not None:
        return callback(*args, **kwargs)

def inspect_system():
    owner = state.code.relations.get('owner')
    name = state.code.components.get('system_name')
    if owner is None or name not in owner.systems:
        raise ValueError('Open an attached system first')
    open_panel(name, owner)

def detach_system():
    owner = state.code.relations.get('owner')
    name = state.code.components.get('system_name')
    if owner is None or name not in owner.systems:
        raise ValueError('Open an attached system first')
    if owner is state.app and name in ('app', 'ui'):
        raise ValueError('The active editor cannot detach itself')
    del owner.systems[name]
    message(f'Detached {name}')

def open_panel(system_name=None, target=None, component=None):
    target = target or selected()
    n = len(state.extra_panels)
    view_type = 'system' if system_name else 'component' if component else 'entity'
    panel = state.ui.create(state.app, f'InspectionPanel{n}', 'panel', text=view_type.upper() + ' INSPECTION',
                            x=state.viewport.x + 20 + n * 20, y=state.viewport.y + 20 + n * 20, w=440, h=270,
                            layer=4, modal=True, view_type=view_type, system_name=system_name, component=component,
                            dock='float', movable=True, resizable=True)
    panel.relations['target'] = target
    close = state.ui.button(panel, f'ClosePanel{n}', 'X', panel.destroy)
    put(close, x=panel.x + 400, y=panel.y + 5, w=30, h=24, layer=6)
    for index in range(10):
        state.ui.create(panel, f'Panel{n}Line{index}', 'label', text='', x=panel.x + 12, y=panel.y + 35 + index * 22, w=416, h=20, layer=5, line_index=index)
    state.extra_panels.append(panel)

def panels_sync():
    state.extra_panels[:] = [panel for panel in state.extra_panels if panel.alive]
    for panel in state.extra_panels:
        close = next((c for c in panel.children if 'button' in c.tags), None)
        if close:
            put(close, x=panel.x + max(10, panel.w - 40), y=panel.y + 5, w=30, h=24)
        for child in panel.children:
            if 'line_index' in child.components:
                idx = child.components['line_index']
                put(child, x=panel.x + 12, y=panel.y + 35 + idx * 22, w=max(0, panel.w - 24), h=20)
        target = panel.relations.get('target')
        if target is None:
            lines = ['Target no longer exists']
        elif panel.view_type == 'system':
            instance = target.systems.get(panel.system_name)
            if instance is None:
                lines = ['System detached']
            else:
                lines = [f'{instance.name} | running={instance.running}', str(instance.definition.path), 'Lifecycle: ' + ', '.join(instance.lifecycle)]
                lines += [f'ERROR: {error.message}' for error in instance.errors]
                lines += [f'{k}: {safe_repr(v)}' for k, v in instance.globals.items()]
        elif panel.view_type == 'component':
            value = safe_repr(target.components.get(panel.component, '<removed>'))
            lines = [panel.component] + [value[i:i + 50] for i in range(0, len(value), 50)]
        else:
            lines = [str(target.id), 'Tags: ' + ', '.join(target.tags)]
            lines += [f'{k}: {safe_repr(v)}' for k, v in target.components.items()]
            lines += [f"{k} -> {v.components.get('name', v.id)}" for k, v in target.relations.items()]
        for child in panel.children:
            if 'line_index' in child.components:
                index = child.line_index
                put(child, text=lines[index] if index < len(lines) else '')


def scroll_list(control, event):
    control.scroll = max(0, control.scroll-int(event[4])*3)


def get_game_world_pos(e):
    return world_position(e, root=state.game)


def find_hit_game_entity(wx, wy):
    for child in reversed(state.game.descendants):
        if "x" in child.components and "y" in child.components:
            x, y = get_game_world_pos(child)
            w = child.components.get("w", 0.0)
            h = child.components.get("h", 0.0)
            l, r = min(x, x + w), max(x, x + w)
            b, t = min(y, y + h), max(y, y + h)
            if l <= wx <= r and b <= wy <= t:
                return child
    return None


def viewport_click(control, event):
    if state.app.components.get("asset_drag") is not None or state.app.components.get("entity_drag") is not None:
        return False
    control.drag_pos = None
    wx, wy = screen_to_world(state.camera, control, event[1], event[2])
    target = find_hit_game_entity(wx, wy)
    if target is None:
        hits = set(space.query(wx, wy))
        target = next((child for child in reversed(state.game.descendants) if child in hits), None)
    if target:
        click_count = event[5] if len(event) >= 6 else 1
        if click_count >= 2:
            inspect_entity(target)
        else:
            select(target)


def viewport_drag(control, event):
    if state.app.components.get("asset_drag") is not None or state.app.components.get("entity_drag") is not None:
        return False
    x, y = event[1], event[2]
    if len(event) >= 7:
        dx, dy = event[5], event[6]
    else:
        last = control.components.get("drag_pos")
        if last is None:
            control.drag_pos = (x, y)
            return True
        dx, dy = x - last[0], y - last[1]
    control.drag_pos = (x, y)
    zoom = max(1.0, state.camera.zoom)
    state.camera.x -= dx / zoom
    state.camera.y += dy / zoom
    return True


def viewport_scroll(control, event):
    sx, sy = event[1], event[2]
    wx, wy = screen_to_world(state.camera, control, sx, sy)
    old_zoom = state.camera.zoom
    new_zoom = max(4.0, min(512.0, old_zoom * 1.1 ** event[4]))
    state.camera.x = wx - (sx - (control.x + control.w / 2)) / new_zoom
    state.camera.y = wy + (sy - (control.y + control.h / 2)) / new_zoom
    state.camera.zoom = new_zoom


def toggle_game_running():
    is_paused = bool(state.game.components.get("paused", False))
    state.game.components["paused"] = not is_paused
    status = "Game paused (F5 to run)" if not is_paused else "Game running (F5 to pause)"
    message(status)


def on_asset_drop(asset_drag, event):
    if not asset_drag or len(event) < 3:
        return
    mx, my = event[1], event[2]

    # 1. Dropped on Code Editor
    if (contains(state.code, mx, my) or contains(state.code_panel, mx, my)) and getattr(state.code, "visible", True):
        uid = asset_drag.get("id")
        if uid:
            state.ui.focus(state.code)
            idx = state.ui.text_index(state.code, mx, my)
            state.code.buffer.cursor = state.code.buffer.anchor = idx
            token = f'asset("{uid}")'
            state.code.buffer.insert(token)
            state.code.components.touch("buffer")
            message(f"Inserted reference to {asset_drag.get('name', 'asset')}")
            return

    # 2. Dropped on Viewport
    if hasattr(state, "viewport") and contains(state.viewport, mx, my):
        wx, wy = screen_to_world(state.camera, state.viewport, mx, my)
        tgt = find_hit_game_entity(wx, wy)
        if tgt is None:
            hits = set(space.query(wx, wy))
            tgt = next((child for child in reversed(state.game.descendants) if child in hits), None)
        if tgt is None:
            tgt = selected()
        if tgt:
            select(tgt)
            apply_asset_to_entity(tgt, asset_drag)
        return

    # 3. Dropped on Hierarchy
    if hasattr(state, "hierarchy") and getattr(state, "active_left_tab", "hierarchy") == "hierarchy" and contains(state.hierarchy, mx, my):
        tgt = None
        for row in getattr(state, "hierarchy_rows", []):
            if state.ui.visible(row) and contains(row, mx, my):
                tgt = row.relations.get("target")
                break
        if tgt is None:
            tgt = selected()
        if tgt:
            select(tgt)
            apply_asset_to_entity(tgt, asset_drag)
        return

    # 4. Dropped on Inspector
    if hasattr(state, "inspector") and contains(state.inspector, mx, my):
        tgt = selected()
        if tgt:
            sys_y = getattr(getattr(state, "system_label", None), "y", state.inspector.y + state.inspector.h / 2)
            target_area = "systems" if my >= sys_y else "components"
            apply_asset_to_entity(tgt, asset_drag, target_area=target_area)
        return

    # 5. Dropped on File Explorer
    if hasattr(state, "file_explorer") and getattr(state, "active_left_tab", "hierarchy") == "files" and contains(state.file_explorer, mx, my):
        target_folder = None
        for row in getattr(state, "file_explorer_rows", []):
            if state.ui.visible(row) and contains(row, mx, my):
                item = row.components.get("file_item")
                if item and item.get("is_dir"):
                    target_folder = item["path"]
                    break
        if target_folder is None:
            target_folder = state.project
        src_path = (Path(state.project) / asset_drag["path"]).resolve() if "path" in asset_drag else None
        if src_path:
            move_file_or_folder(src_path, target_folder)
        return


def on_entity_drop(entity_drag, event):
    if not entity_drag or len(event) < 3:
        return
    mx, my = event[1], event[2]
    dragged_ent = entity_drag.get("entity")
    ent_id = entity_drag.get("id")
    ent_name = entity_drag.get("name", "Entity")

    # 1. Dropped on Code Editor
    if (contains(state.code, mx, my) or contains(state.code_panel, mx, my)) and getattr(state.code, "visible", True):
        if ent_id:
            state.ui.focus(state.code)
            idx = state.ui.text_index(state.code, mx, my)
            state.code.buffer.cursor = state.code.buffer.anchor = idx
            token = f'resolve("{ent_id}")'
            state.code.buffer.insert(token)
            state.code.components.touch("buffer")
            message(f"Inserted entity reference to {ent_name}")
            return

    # 2. Dropped on Inspector
    if hasattr(state, "inspector") and contains(state.inspector, mx, my):
        tgt = selected()
        if tgt and dragged_ent and tgt is not dragged_ent:
            target_comp_key = None
            for lbl, fld in getattr(state, "component_rows", []):
                if state.ui.visible(fld) and (contains(lbl, mx, my) or contains(fld, mx, my)):
                    target_comp_key = fld.components.get("component_key")
                    break
            if target_comp_key:
                tgt.components[target_comp_key] = dragged_ent
                message(f"Set component '{target_comp_key}' to {ent_name}")
            else:
                comp_key = ent_name.lower().replace(" ", "_")
                tgt.components[comp_key] = dragged_ent
                message(f"Added component '{comp_key}' referencing {ent_name}")
            save_editor_project()
            inspector_sync()
        return

    # 3. Dropped on Hierarchy
    if hasattr(state, "hierarchy") and getattr(state, "active_left_tab", "hierarchy") == "hierarchy" and contains(state.hierarchy, mx, my):
        if dragged_ent:
            target_parent = None
            for row in getattr(state, "hierarchy_rows", []):
                if state.ui.visible(row) and contains(row, mx, my):
                    target_parent = row.relations.get("target")
                    break
            if target_parent is not None and target_parent is not dragged_ent:
                dragged_ent.parent = target_parent
                message(f"Moved {ent_name} under {target_parent.components.get('name', target_parent.id)}")
            elif target_parent is None:
                dragged_ent.parent = state.game
                message(f"Moved {ent_name} to root")
            save_editor_project()
            if hasattr(state, "hierarchy_sync"):
                state.hierarchy_sync()
        return

    # 4. Dropped on Viewport
    if hasattr(state, "viewport") and contains(state.viewport, mx, my):
        if dragged_ent:
            wx, wy = screen_to_world(state.camera, state.viewport, mx, my)
            select(dragged_ent)
            if "x" in dragged_ent.components and "y" in dragged_ent.components:
                dragged_ent.x = wx
                dragged_ent.y = wy
                message(f"Placed {ent_name} at ({int(wx)}, {int(wy)})")
            else:
                message(f"Selected {ent_name}")
            save_editor_project()
        return


def apply_asset_to_entity(tgt, asset_drag, target_area=None):
    from lbe.assets import AssetRef
    atype = asset_drag.get("type")
    uid = asset_drag.get("id")
    name = asset_drag.get("name", "asset")
    path_str = asset_drag.get("path")

    if atype == "system" and path_str:
        if target_area == "systems" or target_area is None:
            path = (state.project / path_str).resolve()
            if path.exists():
                definition = state.runtime.assets.system(path)
                if path.stem in tgt.systems:
                    tgt.systems.reload(path.stem, definition)
                else:
                    tgt.systems.attach(path.stem, definition)
                save_editor_project()
                inspector_sync()
                message(f"Attached system '{path.stem}' to {tgt.components.get('name', tgt.id)}")
                return
        else:
            ref = AssetRef(id=uid, type="system", name=name)
            comp_name = Path(path_str).stem if path_str else "system"
            tgt.components[comp_name] = ref
            save_editor_project()
            inspector_sync()
            message(f"Added system component '{comp_name}' on {tgt.components.get('name', tgt.id)}")
            return

    if atype == "image":
        ref = AssetRef(id=uid, type="image", name=name)
        tgt.components["sprite"] = ref
        save_editor_project()
        inspector_sync()
        message(f"Set sprite on {tgt.components.get('name', tgt.id)} to {name}")
        return

    ref = AssetRef(id=uid, type=atype, name=name)
    comp_name = path_str.split("/")[-1].split(".")[0] if path_str else "asset"
    tgt.components[comp_name] = ref
    save_editor_project()
    inspector_sync()
    message(f"Set '{comp_name}' on {tgt.components.get('name', tgt.id)} to {name}")


def open_replace_asset_menu(pill_control):
    reg = getattr(state.runtime.assets, "registry", None)
    if not reg:
        return
    from lbe.assets import ASSET_ICONS
    cur_id = pill_control.components.get("asset_id")
    actions = []
    for uid, entry in sorted(reg.entries(), key=lambda x: (x[1]["type"], x[1]["name"].lower())):
        icon = reg.icon(uid)
        is_cur = (str(uid) == str(cur_id))
        pref = "> " if is_cur else "   "
        actions.append(dict(
            label=f"{pref}{icon} {entry['name']}",
            run=lambda _, u=uid, e=entry: replace_asset_reference(pill_control, u, e)
        ))
    if not actions:
        actions.append(dict(label="(No assets in registry)", run=None))
    mouse = getattr(state.ui, "mouse_pos", None)
    x, y = mouse if mouse else (pill_control.x, pill_control.y + pill_control.h + 2)
    open_menu(state.ui, state.code_panel, x, y, actions=actions)


def replace_asset_reference(pill_control, new_uid, new_entry):
    row = pill_control.components.get("asset_row")
    span = pill_control.components.get("asset_span")
    if row is None or span is None:
        return
    buf = state.code.buffer
    lines = buf.text.split("\n")
    if row >= len(lines):
        return
    line_text = lines[row]
    col_start, col_end = span
    new_token = f'asset("{new_uid}")'
    new_line = line_text[:col_start] + new_token + line_text[col_end:]
    lines[row] = new_line
    buf.text = "\n".join(lines)
    message(f"Replaced asset reference with '{new_entry['name']}'")


def remove_asset_reference(pill_control):
    row = pill_control.components.get("asset_row")
    span = pill_control.components.get("asset_span")
    if row is None or span is None:
        return
    buf = state.code.buffer
    lines = buf.text.split("\n")
    if row >= len(lines):
        return
    line_text = lines[row]
    col_start, col_end = span
    new_line = line_text[:col_start] + line_text[col_end:]
    lines[row] = new_line
    buf.text = "\n".join(lines)
    message("Removed asset reference")


def prompt_rename_asset(asset_id):
    reg = getattr(state.runtime.assets, "registry", None)
    if not reg:
        return
    entry = reg.get(asset_id)
    if not entry:
        return
    path = state.project / entry["path"]
    if path.suffix == ".py":
        open_specific_file(path)
        prompt_rename_file()
    else:
        message(f"To rename '{entry['name']}', right-click it in Project Files")
        locate_in_file_explorer(asset_id)


def assign_entity_sprite(ent, item):
    from lbe.assets import AssetRef
    reg = getattr(state.runtime.assets, "registry", None)
    uid = item.get("asset_id")
    if uid is None and reg:
        uid = reg.register(item["path"])
        item["asset_id"] = uid
    ent.components["sprite"] = AssetRef(id=uid, type="image", name=item["name"])
    save_editor_project()
    inspector_sync()
    message(f"Assigned sprite '{item['name']}' to {ent.components.get('name', ent.id)}")




def refresh_project_files(*args, **kwargs):
    callback = getattr(state, "refresh_project_files", None)
    if callback is not None:
        return callback(*args, **kwargs)


def new_source_in_dir(*args, **kwargs):
    callback = getattr(state, "new_source_in_dir", None)
    if callback is not None:
        return callback(*args, **kwargs)


def prompt_rename_file_item(*args, **kwargs):
    callback = getattr(state, "prompt_rename_file_item", None)
    if callback is not None:
        return callback(*args, **kwargs)


def delete_file_item(*args, **kwargs):
    callback = getattr(state, "delete_file_item", None)
    if callback is not None:
        return callback(*args, **kwargs)


def create_new_folder(*args, **kwargs):
    callback = getattr(state, "create_new_folder", None)
    if callback is not None:
        return callback(*args, **kwargs)


def move_file_or_folder(*args, **kwargs):
    callback = getattr(state, "move_file_or_folder", None)
    if callback is not None:
        return callback(*args, **kwargs)


def open_move_file_menu(*args, **kwargs):
    callback = getattr(state, "open_move_file_menu", None)
    if callback is not None:
        return callback(*args, **kwargs)


def keyboard(event):
    if event[1] == 'Z' and event[2]:
        focus = state.ui.focused
        committed = focus is not None and 'buffer' in focus.components and focus.components.get('committed_text') == focus.buffer.text
        text_history = focus is not None and 'buffer' in focus.components and focus.buffer.can_undo(redo=bool(event[3]))
        if committed or not text_history or focus is None or not state.ui.visible(focus) or 'buffer' not in focus.components:
            label = state.files.history.undo(redo=bool(event[3]))
            result = state.files.history.result
            if label is not None:
                if isinstance(result, Path) and result.exists():
                    state.reveal_file(result)
                state.file_tree_key = None
                state.file_explorer_sync()
                message(('Redid ' if event[3] else 'Undid ')+label)
            return True
    if event[1] == 'L' and event[2]:
        open_system_log()
        return True
    if event[1] == "ESCAPE":
        if not state.path_field.components.get("readonly", True):
            state.path_field.components["readonly"] = True
            state.path_field.components["ink"] = (160, 180, 205)
            state.path_field.on_commit = None
            if state._saved_source:
                state.path_field.buffer = TextBuffer(state._saved_source[0])
            state.ui.focus(None)
            message("Rename cancelled")
            return True
    if event[1] == "S" and event[2]:
        save()
        return True
    if event[1] == "F5":
        toggle_game_running()
        return True
    if event[1] == "F2":
        cur = getattr(state, "active_left_tab", "hierarchy")
        switch_left_tab("files" if cur == "hierarchy" else "hierarchy")
        return True
    if event[1] == "F3":
        cur_debug = state.app.components.get("show_spatial_debug", False)
        new_debug = not cur_debug
        state.app.components["show_spatial_debug"] = new_debug
        if hasattr(state, "game") and state.game:
            state.game.components["show_spatial_debug"] = new_debug
        message(f"Spatial debug partition: {'ON' if new_debug else 'OFF'} (F3)")
        return True
    return False


def bind_actions():
    state.app.context_target = context_target
    state.app.context_actions = context_actions
    state.app.highlight_provider = get_highlight_stack
    state.app.on_key = keyboard
    state.app.on_ui_error = message
    state.hierarchy.on_scroll = scroll_list
    state.inspector.on_scroll = scroll_list
    state.viewport.on_click = viewport_click
    state.viewport.on_drag = viewport_drag
    state.viewport.on_scroll = viewport_scroll
    for control, action in ((state.new_button, new_source), (state.open_button, open_path),
                            (state.save_button, save), (state.attach_button, attach),
                            (state.save_project_button, save_project_action),
                            (state.panel_button, open_panel), (state.system_panel_button, inspect_system),
                            (state.detach_button, detach_system), (state.add_button, add_component),
                            (state.run_button, toggle_game_running),
                            (state.add_child_button, inspector_add_child),
                            (state.duplicate_button, inspector_duplicate_entity),
                            (state.delete_button, inspector_delete_entity),
                            (state.quick_pos_btn, lambda: apply_quick_preset("pos")),
                            (state.quick_size_btn, lambda: apply_quick_preset("size")),
                            (state.quick_vel_btn, lambda: apply_quick_preset("vel")),
                            (state.quick_color_btn, lambda: apply_quick_preset("color")),
                            (state.quick_speed_btn, lambda: apply_quick_preset("speed")),
                            (state.quick_add_chip_btn, open_add_chip_menu),
                            (state.components_title, lambda: toggle_section("components")),
                            (state.add_comp_menu_button, open_add_component_menu),
                            (state.system_label, lambda: toggle_section("systems")),
                            (state.add_system_button, open_attach_system_menu),
                            (state.links_header, lambda: toggle_section("links"))):
        control.action = action
    state.path_field.on_click = on_path_field_click
    for control, action in ((state.tags_field, commit_tags),
                            (state.parent_field, commit_parent), (state.relation_field, commit_relation),
                            (state.name_field, commit_name)):
        control.on_commit = action
    state.hierarchy_scroll_track.on_click = hierarchy_track_click
    state.hierarchy_scroll_thumb.on_drag = hierarchy_scroll_drag
    state.inspector_scroll_track.on_click = inspector_track_click
    state.inspector_scroll_thumb.on_drag = inspector_scroll_drag
    for row in state.hierarchy_rows:
        row.on_click = hierarchy_click
    for label, field in state.component_rows:
        label.on_commit = lambda lbl=label: commit_component_key(lbl)
        label.on_click = component_click
        field.on_commit = lambda field=field: commit_component(field)
        field.on_click = component_click
    for button in state.system_rows:
        button.components.pop("system_key", None)
    for button in state.system_edit_buttons:
        button.components.pop("system_key", None)
    for button in state.system_detach_buttons:
        button.components.pop("system_key", None)
    state.app.components["on_asset_drop"] = on_asset_drop
    state.app.components["on_entity_drop"] = on_entity_drop
    if hasattr(state, "tab_hierarchy") and hasattr(state, "tab_files"):
        state.tab_hierarchy.action = lambda: switch_left_tab("hierarchy")
        state.tab_files.action = lambda: switch_left_tab("files")
    if hasattr(state, "file_scroll_track") and hasattr(state, "file_scroll_thumb"):
        state.file_scroll_track.on_click = file_track_click
        state.file_scroll_thumb.on_drag = file_scroll_drag


def start():
    if state is None:
        initialize()
    bind_actions()
    entity.tags.add('editor')
    if "ui" not in entity.systems:
        state.ui.install(definition=assets["20fe7e55-f05e-5d02-9ed0-a36a56f66c5d"])


def open_system_log():
    existing = state.app.relations.get('system_log_panel')
    if existing is not None:
        existing.visible = not existing.visible
        return
    panel = state.ui.create(state.app, 'SystemLogPanel', 'panel', text='SYSTEM LOG',
                            x=max(0, state.window.width-840), y=80, w=820, h=360,
                            layer=20, modal=False, dock='float', movable=True, resizable=True)
    state.app.relations['system_log_panel'] = panel
    panel.systems.attach('system_log', assets["6df949df-402f-5552-bc5e-c4566531ee40"])


def update(dt):
    failures=[r for r in log.records if r.kind=='script.error' and r.sequence>getattr(state,'last_script_error',0)]
    if failures:
        state.last_script_error=failures[-1].sequence
        panel=state.app.relations.get('system_log_panel')
        if panel is None:
            open_system_log()
        else:
            panel.visible=True
    owner = state.code.relations.get('owner', selected())
    context_key = (state.project_graph.schema_revision, owner.id, tuple((key, type(value)) for key, value in owner.components.items()))
    if getattr(state, "completion_context_key", None) != context_key:
        state.code.completion_components = tuple(owner.components) if owner.alive else ()
        state.code.completion_context = extract_completion_context()
        state.completion_context_key = context_key
    state.code.source_path = state.project / state.path_field.buffer.text
    layout()
    panels_sync()
    row, column = state.code.buffer.position
    diag = state.code.components.get("diagnostic")
    run_status = "paused" if state.game.components.get("paused") else "running"
    if diag:
        put(state.code_info, text=f"SyntaxError Ln {diag['line']}, Col {diag['column']}: {diag['message']}", ink=(248, 81, 73, 255))
    elif state.code.components.get('completion_error'):
        put(state.code_info, text=f"Completion unavailable: {state.code.completion_error}", ink=(248, 81, 73, 255))
    else:
        put(state.code_info, text=f"Ln {row+1}, Col {column+1} | Attach target: {selected().components.get('name', selected().id)} | Ctrl+S save | F5 {run_status}", ink=MUTED)


def context_rename(target):
    select(target)
    inspector_sync()
    state.ui.focus(state.name_field)
    buf = state.name_field.buffer
    buf.anchor = 0
    buf.cursor = len(buf.text)
    ent_name = str(target.components.get('name', str(target.id)[:8]))
    message(f"Renaming '{ent_name}' (type new name and press Enter)")


def editor_select_all():
    buf = state.code.buffer
    buf.anchor, buf.cursor = 0, len(buf.text)


def editor_copy():
    buf = state.code.buffer
    if buf.selected_text:
        state.window.set_clipboard_text(buf.selected_text)


def editor_cut():
    buf = state.code.buffer
    if buf.selected_text:
        state.window.set_clipboard_text(buf.selected_text)
        buf.insert("")


def editor_paste():
    buf = state.code.buffer
    text = state.window.get_clipboard_text()
    if text:
        buf.insert(text)


def get_highlight_stack(mx, my):
    stack = []
    # 1. Check if mouse is inside the viewport
    if hasattr(state, "viewport") and contains(state.viewport, mx, my):
        wx, wy = screen_to_world(state.camera, state.viewport, mx, my)
        hit_entity = find_hit_game_entity(wx, wy)
        if hit_entity is None:
            hits = set(space.query(wx, wy))
            hit_entity = next((child for child in reversed(state.game.descendants) if child in hits), None)
        if hit_entity is not None:
            curr = hit_entity
            idx = 0
            while curr is not None and curr is not state.game and hasattr(curr, "x") and hasattr(curr, "y"):
                wx_e, wy_e = get_game_world_pos(curr)
                bw = curr.components.get("w", 0)
                bh = curr.components.get("h", 0)
                sx0, sy0 = world_to_screen(state.camera, state.viewport, wx_e, wy_e + bh)
                sw = max(4, bw * state.camera.zoom)
                sh = max(4, bh * state.camera.zoom)
                rx = max(state.viewport.x, sx0)
                ry = max(state.viewport.y, sy0)
                rw = max(0, min(sx0 + sw, state.viewport.x + state.viewport.w) - rx)
                rh = max(0, min(sy0 + sh, state.viewport.y + state.viewport.h) - ry)
                if rw > 0 and rh > 0:
                    stack.append((curr, (rx, ry, rw, rh), STACK_COLORS[idx % len(STACK_COLORS)]))
                    idx += 1
                curr = curr.parent
            vp = state.viewport
            stack.append((vp, (vp.x, vp.y, vp.w, vp.h), STACK_COLORS[idx % len(STACK_COLORS)]))
            idx += 1
            app = state.app
            stack.append((app, (app.x, app.y, app.w, app.h), STACK_COLORS[idx % len(STACK_COLORS)]))
            return stack

    # 2. Controls in UI
    hits = [c for c in state.ui.controls() if state.ui.visible(c) and contains(c, mx, my)]
    if hits:
        hits.reverse()
        hits.sort(key=lambda c: (c.components.get("layer", 2), c.depth), reverse=True)
        leaf = hits[0]
        curr = leaf
        idx = 0
        while curr is not None and hasattr(curr, "w"):
            if curr.w > 0 and curr.h > 0:
                stack.append((curr, (curr.x, curr.y, curr.w, curr.h), STACK_COLORS[idx % len(STACK_COLORS)]))
                idx += 1
            curr = curr.parent
    return stack


def context_target(control, event):
    ctrl = False
    if len(event) > 4 and isinstance(event[4], int):
        ctrl = bool(event[4] & 2)
    if not ctrl:
        ctrl = bool(getattr(state.ui.input, "ctrl", False) or getattr(state.ui, "ctrl_held", False))

    if ctrl:
        stack = get_highlight_stack(event[1], event[2])
        leaf = stack[0][0] if stack else control
        return dict(deep=True, stack=stack, entity=leaf)

    if 'preset_key' in control.components:
        return dict(preset=control.components['preset_key'], control=control)
    if 'system_key' in control.components:
        owner_id, sys_name = control.components['system_key']
        owner = next((e for e in state.runtime.entities if e.id == owner_id), None)
        if owner:
            return dict(entity=owner, system=sys_name)
    if "asset_pill" in control.tags:
        return dict(asset_pill=control, asset_id=control.components.get("asset_id"),
                    asset_name=control.components.get("asset_name"), control=control)
    for candidate in (control,) + control.ancestors:
        if "file_item" in candidate.components:
            return dict(file_item=candidate.components["file_item"], control=candidate)
    if hasattr(state, "file_explorer") and (control is state.file_explorer or state.file_explorer in control.ancestors):
        return dict(file_explorer=True, control=state.file_explorer)
    if control is state.tags_field or control is state.tags_label:
        return dict(entity=inspected(), tags=True)
    if 'component_key' in control.components and 'target' in control.relations:
        return dict(entity=control.relations['target'], component=control.component_key)
    if 'relation_key' in control.components and 'target' in control.relations:
        return dict(entity=control.relations['target'], relation=control.relation_key)
    if control is state.viewport:
        wx, wy = screen_to_world(state.camera, control, event[1], event[2])
        tgt = find_hit_game_entity(wx, wy)
        if tgt is None:
            hits = set(space.query(wx, wy))
            tgt = next((child for child in reversed(state.game.descendants) if child in hits), state.game)
        select(tgt)
        return tgt
    for candidate in (control,) + control.ancestors:
        if candidate in state.hierarchy_rows and 'target' in candidate.relations:
            tgt = candidate.relations['target']
            select(tgt)
            return tgt
        if 'target' in candidate.relations:
            return candidate.relations['target']
    if control is state.inspector or state.inspector in control.ancestors:
        return inspected()
    if control is state.code or state.code in control.ancestors or control is state.code_panel or state.code_panel in control.ancestors:
        return dict(code=True, control=state.code)
    if control is state.hierarchy or state.hierarchy in control.ancestors:
        return state.game
    return None


def context_actions(target):
    if target is None:
        return []
    if isinstance(target, dict) and target.get('deep'):
        stack = target.get('stack', [])
        leaf_ent = target.get('entity')
        actions = []
        if stack:
            # 1. Color-coded Selection options for EVERY entity in the stack
            for i, (ent, _, color) in enumerate(stack):
                role = "Leaf" if i == 0 else ("Parent" if i == 1 else ("Root" if i == len(stack) - 1 else f"Depth {i}"))
                ent_name = str(ent.components.get('name', str(getattr(ent, 'id', 'Entity'))[:8]))
                actions.append(dict(
                    label=f"> Select '{ent_name}' ({role})",
                    ink=color,
                    run=lambda _, e=ent: select(e)
                ))
            actions.append(None)

            # 2. Detailed editing actions for the primary / leaf entity
            leaf_name = str(leaf_ent.components.get('name', str(getattr(leaf_ent, 'id', 'Entity'))[:8]))
            leaf_color = stack[0][2]
            actions.extend([
                dict(label=f"Inspect '{leaf_name}'", ink=leaf_color, run=lambda _: open_panel(target=leaf_ent)),
                dict(label=f"Rename '{leaf_name}'...", ink=leaf_color, run=lambda _: context_rename(leaf_ent)),
                dict(label=f"+ Add Component to '{leaf_name}'...", ink=leaf_color, run=lambda _: (select(leaf_ent), open_add_component_menu())),
                dict(label=f"Add child to '{leaf_name}'", ink=leaf_color, run=lambda _: context_add_child(leaf_ent)),
                dict(label=f"Duplicate '{leaf_name}'", ink=leaf_color, run=lambda _: (select(leaf_ent), inspector_duplicate_entity())),
            ])
            protected = (state.app, state.background, state.viewport_panel, state.viewport, state.header, state.hierarchy, state.inspector)
            if leaf_ent not in protected:
                actions.append(dict(label=f"Delete '{leaf_name}'", ink=leaf_color, run=lambda _: (select(leaf_ent), inspector_delete_entity())))

            # 3. Quick Inspect actions for intermediate ancestors and root
            if len(stack) > 1:
                actions.append(None)
                for ent, _, color in stack[1:]:
                    e_name = str(ent.components.get('name', str(getattr(ent, 'id', 'Entity'))[:8]))
                    actions.append(dict(
                        label=f"Inspect '{e_name}'",
                        ink=color,
                        run=lambda _, e=ent: open_panel(target=e)
                    ))
        else:
            ent = leaf_ent
            ent_name = str(ent.components.get('name', str(getattr(ent, 'id', 'Entity'))[:8]))
            actions = [
                dict(label=f"Select '{ent_name}'", run=lambda _: select(ent)),
                dict(label=f"Inspect '{ent_name}'", run=lambda _: open_panel(target=ent)),
                dict(label=f"Rename '{ent_name}'...", run=lambda _: context_rename(ent)),
                None,
                dict(label="+ Add Component...", run=lambda _: (select(ent), open_add_component_menu())),
                dict(label="Add child entity", run=lambda _: context_add_child(ent)),
                dict(label="Duplicate entity", run=lambda _: (select(ent), inspector_duplicate_entity())),
            ]
            protected = (state.app, state.background, state.viewport_panel, state.viewport, state.header, state.hierarchy, state.inspector)
            if ent not in protected:
                actions.append(dict(label=f"Delete '{ent_name}'", run=lambda _: (select(ent), inspector_delete_entity())))
        return actions

    if isinstance(target, dict) and target.get('asset_pill'):
        pill = target['control']
        uid = target.get('asset_id')
        name = target.get('asset_name', 'asset')
        return [
            dict(label=f"Locate '{name}' in Project Files", run=lambda _: locate_in_file_explorer(uid)),
            dict(label=f"Rename '{name}'...", run=lambda _: prompt_rename_asset(uid)),
            dict(label="Replace asset reference...", run=lambda _: open_replace_asset_menu(pill)),
            dict(label="Copy Asset UUID", run=lambda _: (state.window.set_clipboard_text(str(uid)), message(f"Copied UUID: {uid}"))),
            None,
            dict(label="Remove reference", run=lambda _: remove_asset_reference(pill)),
        ]

    if isinstance(target, dict) and target.get('file_item'):
        item = target['file_item']
        actions = []
        if item['is_dir']:
            actions.append(dict(label="View as root folder", run=lambda _: state.set_file_root(item['path'])))
            root = (state.project / state.file_explorer.components.get('view_root','systems/game')).resolve()
            if item['path'].resolve() == root and root != state.project:
                actions.append(dict(label="Set parent as root folder", run=lambda _: state.set_file_root(root.parent)))
            actions.append(dict(label=f"+ New folder in '{item['name']}'...", run=lambda _: create_new_folder(item['path'])))
            actions.append(dict(label=f"+ New script in '{item['name']}'...", run=lambda _: new_source_in_dir(item['path'], kind="script")))
            actions.append(dict(label="Move folder to...", run=lambda _: open_move_file_menu(item['path'])))
            actions.append(dict(label=f"Rename folder '{item['name']}'...", run=lambda _: prompt_rename_file_item(item)))
            actions.append(None)
            actions.append(dict(label=f"Delete folder '{item['name']}'", run=lambda _: delete_file_item(item)))
        else:
            if item['type'] in ('system','script'):
                actions.append(dict(label=f"Open '{item['name']}' in editor", run=lambda _: open_specific_file(item['path'])))
                identity = item.get("asset_id") or assets.registry.get_id(item["path"])
                if identity is not None:
                    actions.append(dict(label="Highlight affected entities", run=lambda _, uid=identity: state.highlight_system(uid)))
                sel = selected()
                if sel:
                    if item['type']=='script':
                        actions.append(dict(label="Attach script to selected entity", run=lambda _: sel.scripts.attach(assets[identity])))
                    sel_name = str(sel.components.get('name', sel.id))
                    if item['type']=='system':
                        actions.append(dict(label=f"Attach to '{sel_name}'", run=lambda _: attach_system_to_entity(sel, item['path'])))
            elif item['type'] == 'image':
                sel = selected()
                if sel:
                    sel_name = str(sel.components.get('name', sel.id))
                    actions.append(dict(label=f"Assign sprite to '{sel_name}'", run=lambda _: assign_entity_sprite(sel, item)))
            actions.append(dict(label="Move to folder...", run=lambda _: open_move_file_menu(item['path'])))
            actions.append(dict(label=f"Rename '{item['name']}'...", run=lambda _: prompt_rename_file_item(item)))
            actions.append(dict(label="Copy relative path", run=lambda _: (state.window.set_clipboard_text(item['rel_path']), message(f"Copied path '{item['rel_path']}'"))))
            if item.get('asset_id'):
                actions.append(dict(label="Copy Asset UUID", run=lambda _: (state.window.set_clipboard_text(str(item['asset_id'])), message(f"Copied UUID: {item['asset_id']}"))))
            actions.append(None)
            actions.append(dict(label=f"Delete '{item['name']}'", run=lambda _: delete_file_item(item)))
        return actions

    if isinstance(target, dict) and target.get('file_explorer'):
        return [
            dict(label="+ New folder...", run=lambda _: create_new_folder(state.project / state.file_explorer.components.get("view_root", "systems/game"))),
            dict(label="+ New system script...", run=lambda _: new_source_in_dir(state.project / state.file_explorer.components.get("view_root", "systems/game"))),
            dict(label="+ New script...", run=lambda _: new_source_in_dir(state.project / state.file_explorer.components.get("view_root", "systems/game"), kind="script")),
            dict(label="Refresh project files", run=lambda _: refresh_project_files()),
        ]

    if isinstance(target, dict) and target.get('code'):
        cur_file = state.path_field.buffer.text.strip() or "system.py"
        actions = [
            dict(label=f"Save / reload ('{cur_file}')", run=lambda _: save()),
            dict(label=f"Rename '{cur_file}'...", run=lambda _: prompt_rename_file()),
            dict(label="Open file...", run=lambda _: open_file_menu()),
            dict(label="+ New system script...", run=lambda _: new_source_in_dir(state.project / state.file_explorer.components.get("view_root", "systems/game"))),
        ]
        if state.code.components.get("system_name") and 'owner' in state.code.relations:
            owner = state.code.relations['owner']
            sys_name = state.code.components['system_name']
            actions.append(dict(label=f"Revert system '{sys_name}'", run=lambda _: open_system(owner, sys_name)))
        actions.append(None)
        actions.extend([
            dict(label="Select All", run=lambda _: editor_select_all()),
            dict(label="Copy", run=lambda _: editor_copy()),
            dict(label="Cut", run=lambda _: editor_cut()),
            dict(label="Paste", run=lambda _: editor_paste()),
        ])
        return actions

    if isinstance(target, dict) and 'preset' in target:
        name = target['preset']
        return [
            dict(label=f"Apply '{name}'", run=lambda t: apply_quick_preset(name)),
            dict(label=f"Remove '{name}' from quick-bar", run=lambda t: remove_quick_preset(name)),
            None,
            dict(label="+ New quick-add preset...", run=lambda t: prompt_add_preset()),
        ]
    if isinstance(target, dict) and 'system' in target:
        ent = target['entity']
        name = target['system']
        return [
            dict(label=f"Edit system '{name}'", run=lambda t: open_system(ent, name)),
            None,
            dict(label=f"Detach system '{name}'", run=lambda t: detach_system_from_entity(ent, name)),
        ]
    if isinstance(target, dict) and 'tags' in target:
        ent = target['entity']
        actions = []
        for t in sorted(ent.tags):
            actions.append(dict(label=f"Rename tag '{t}'...", run=lambda _, tag=t: start_rename_tag(ent, tag)))
            actions.append(dict(label=f"Remove tag '{t}'", run=lambda _, tag=t: remove_tag(ent, tag)))
        if actions:
            actions.append(None)
        actions.append(dict(label="+ Add new tag...", run=lambda _: start_add_tag(ent)))
        return actions
    if isinstance(target, dict) and 'component' in target:
        ent = target['entity']
        comp = target['component']
        val = ent.components.get(comp)
        type_name = type(val).__name__
        actions = [
            dict(label='Inspect component', run=lambda t: open_panel(target=ent, component=comp)),
            dict(label=f"Rename '{comp}'...", run=lambda t: start_rename_component(ent, comp)),
            dict(label=f"Change type... ({type_name})", run=lambda t: open_change_type_menu(ent, comp)),
            dict(label=f"Delete '{comp}'", run=lambda t: delete_component(comp)),
            None,
            dict(label="+ Add Component...", run=lambda t: open_add_component_menu()),
        ]
        from lbe.core import Entity
        if isinstance(val, Entity) and val.alive:
            val_name = str(val.components.get('name', str(val.id)[:8]))
            actions.extend([
                None,
                dict(label=f"> Select Entity '{val_name}'", run=lambda _: select(val)),
                dict(label=f"Inspect Entity '{val_name}'", run=lambda _: open_panel(target=val)),
                dict(label=f"Rename Entity '{val_name}'...", run=lambda _: context_rename(val)),
                dict(label=f"+ Add Component to '{val_name}'...", run=lambda _: (select(val), open_add_component_menu())),
                dict(label=f"Add child to '{val_name}'", run=lambda _: context_add_child(val)),
                dict(label=f"Duplicate Entity '{val_name}'", run=lambda _: (select(val), inspector_duplicate_entity())),
            ])
            protected = (state.app, state.background, state.viewport_panel, state.viewport, state.header, state.hierarchy, state.inspector)
            if val not in protected:
                actions.append(dict(label=f"Delete Entity '{val_name}'", run=lambda _: (select(val), inspector_delete_entity())))
        return actions
    if isinstance(target, dict) and 'relation' in target:
        ent = target['entity']
        rel = target['relation']
        tgt = ent.relations.get(rel)
        tgt_label = str(tgt.components.get('name', str(tgt.id)[:8])) if tgt else 'None'
        actions = []
        if tgt:
            actions.append(dict(label=f"Select target ({tgt_label})", run=lambda t: select(tgt)))
        actions.append(dict(label=f"Edit link '{rel}'...", run=lambda t: start_edit_link(rel)))
        actions.append(dict(label=f"Unlink '{rel}'", run=lambda t: unlink_relation(rel)))
        return actions

    if not hasattr(target, 'components') or not target.alive:
        return []

    actions = [
        dict(label='View as root entity', run=lambda e: state.set_hierarchy_root(e)),
        dict(label='Select', run=select),
        dict(label='Rename', run=context_rename),
        dict(label='Inspect entity', run=lambda e: open_panel(target=e)),
        dict(label='View affecting systems', run=lambda e: (inspect_entity(e), inspector_sync())),
        None,
        dict(label="+ Add Component...", run=lambda e: (select(e), open_add_component_menu())),
    ]

    if target is state.hierarchy.relations.get('view_root') and target.parent is not None:
        actions.append(dict(label='Set parent as root entity', run=lambda e: state.set_hierarchy_root(e.parent)))
    sel = selected()
    if target is not sel and sel is not None and sel.alive:
        tgt_name = str(target.components.get('name', str(target.id)[:8]))
        actions.append(None)
        actions.append(dict(label=f"Link from selected as '{tgt_name.lower()}'", run=lambda e: quick_link_to(e)))

    if target is state.game or state.game in target.ancestors:
        actions += [
            None,
            dict(label='Add child entity', run=context_add_child),
            dict(label='Duplicate entity', run=lambda e: (select(e), inspector_duplicate_entity())),
        ]
        if target is not state.game:
            actions.append(dict(label='Delete entity', run=lambda e: (select(e), inspector_delete_entity())))
        if 'x' in target.components and 'y' in target.components:
            actions.append(dict(label='Focus camera', run=context_focus_camera))

    return actions


def context_add_component(target):
    select(target)
    inspector_sync()
    state.ui.focus(state.add_name)


def context_add_child(target):
    child = create(parent=target, name='Entity')
    select(child)


def context_focus_camera(target):
    x,y = world_position(target, state.game)
    w,h = target.components.get('w',0),target.components.get('h',0)
    state.camera.x, state.camera.y = x+w/2,y+h/2
    state.camera.zoom = max(0.1,min(48,max(1,state.viewport.w-48)/max(1,w),max(1,state.viewport.h-48)/max(1,h)))
    save_editor_project()


def frame_game():
    if not state.dock_tree.find_tab_group_with_panel('viewport'):
        toggle_panel_view('viewport')
    group = state.dock_tree.find_tab_group_with_panel('viewport')
    group.active = group.panels.index('viewport')
    layout()
    boxes = [world_bounds(e) for e in state.game.descendants if e.components.get('color') is not None]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        message('No drawable game entities to frame')
        return
    left,bottom = min(b[0] for b in boxes),min(b[1] for b in boxes)
    right,top = max(b[2] for b in boxes),max(b[3] for b in boxes)
    state.camera.x, state.camera.y = (left+right)/2,(bottom+top)/2
    state.camera.zoom = max(0.1,min(max(1,state.viewport.w-48)/max(1,right-left),max(1,state.viewport.h-48)/max(1,top-bottom),256))
    save_editor_project()
    message('Framed drawable game entities')
