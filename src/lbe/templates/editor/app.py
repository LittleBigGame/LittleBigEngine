"""An editor application composed with the public LBE and UI APIs."""

import ast
import keyword
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
from uuid import UUID

from lbe.ui import (UI, put, contains, parse_box, content_rect, stack, dock,
                    row, column, apply_layout, Layout, BG, PANEL, FIELD, ACCENT,
                    INK, MUTED, PITCH, LINE, STACK_COLORS)
from lbe.text import TextBuffer
from lbe.space import screen_to_world, world_to_screen
from lbe.project import save_project, load_project_data, deserialize_entities
from lbe.menus import open_menu

state = entity.components.get("application_state")


def selected():
    sel = state.app.relations.get('selection')
    if sel is None or not sel.alive:
        sel = state.game
        state.app.relations['selection'] = sel
        state.game.relations['selection'] = sel
    return sel


def message(text):
    state.app.status = text


def select(entity):
    if entity is None or not entity.alive:
        entity = state.game
    state.app.relations['selection'] = entity
    state.game.relations['selection'] = entity
    state.inspector.scroll = 0
    if 'focus' in state.app.relations:
        del state.app.relations['focus']
    for ancestor in entity.ancestors:
        state.hierarchy.expanded.add(ancestor.id)


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


def on_drag_col_splitter(control, event):
    w = state.window.width
    min_w = 200
    max_w = max(min_w, w - 300)
    cur_w = state.app.components.get("left_column_w", 370)
    if len(event) > 5 and event[5] != 0:
        new_w = max(min_w, min(max_w, cur_w + event[5]))
    elif len(event) > 1:
        new_w = max(min_w, min(max_w, event[1]))
    else:
        return
    put(state.app, left_column_w=new_w)
    layout()


def on_drag_hierarchy_splitter(control, event):
    top_y = state.header.y + state.header.h
    status_m = parse_box(state.status.components.get("margin", (0, 16, 5, 16)))
    status_h = state.status.components.get("h", 20)
    status_y = state.window.height - status_m[2] - status_h
    available_h = status_y - top_y
    min_h = 100
    max_h = max(min_h, available_h - 150)
    cur_h = state.hierarchy.components.get("panel_h", 240)
    if len(event) > 6 and event[6] != 0:
        new_h = max(min_h, min(max_h, cur_h + event[6]))
    elif len(event) > 2:
        hm = parse_box(state.hierarchy.components.get("margin", (8, 8, 4, 8)))
        new_h = max(min_h, min(max_h, event[2] - top_y - hm[0]))
    else:
        return
    put(state.hierarchy, panel_h=new_h)
    layout()


def on_drag_code_splitter(control, event):
    top_y = state.header.y + state.header.h
    status_m = parse_box(state.status.components.get("margin", (0, 16, 5, 16)))
    status_h = state.status.components.get("h", 20)
    status_y = state.window.height - status_m[2] - status_h
    min_y = top_y + 80
    max_y = max(min_y, status_y - 120)
    cur_split = state.code_panel.components.get("split_y", max(330, int(state.window.height * 0.45)))
    if len(event) > 6 and event[6] != 0:
        new_split = max(min_y, min(max_y, cur_split + event[6]))
    elif len(event) > 2:
        new_split = max(min_y, min(max_y, event[2]))
    else:
        return
    put(state.code_panel, split_y=new_split)
    layout()


def initialize():
    global state
    state = SimpleNamespace(runtime=entity.runtime, project=project, window=window,
                            graphics=graphics, input=input, app=entity)
    entity.components["application_state"] = state
    state.ui = UI(entity, window, graphics, input)
    state.background = state.ui.create(entity, "Background", "rect", color=BG, layer=0)

    project_data = load_project_data(project)
    if project_data is not None and project_data.get("entities"):
        restored = deserialize_entities(project_data["entities"], state.runtime, default_parent=entity, project_dir=project)
        state.game = next((e for e in restored.values() if "root" in e.tags and e.components.get("name") == "Game"), None)
        if state.game is None:
            state.game = next((e for e in restored.values() if e.parent is entity), next(iter(restored.values())))
    else:
        state.game = create(parent=entity, name="Game", tags=["root"])
        create(parent=state.game, name="Entity A", x=-3.0, y=-1.0, w=2.0, h=2.0, color=(75, 185, 210))
        create(parent=state.game, name="Entity B", x=1.0, y=0.0, w=1.5, h=1.5, color=(232, 165, 80))
        if (project / "render.py").exists():
            state.game.systems.attach("render", assets.system(project / "render.py"))

    state.camera = create(parent=entity, name="Camera", x=0.0, y=0.0, zoom=48.0)
    state.viewport = state.ui.create(entity, "Viewport", "surface", color=(12, 18, 25), layer=0)
    state.game.relations["camera"] = state.camera
    state.game.relations["viewport"] = state.viewport

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
    state.header = state.ui.create(state.app, 'Header', 'panel', text='LBE  /  LittleBigEngine', color=BG, dock='top', h=44, padding=(8, 16, 8, 16))

    h_conf = layout_data.get("hierarchy", {})
    state.hierarchy = state.ui.create(state.app, 'HierarchyPanel', 'panel', text='HIERARCHY', scroll=0,
                                     expanded={state.app.id, state.game.id}, dock=h_conf.get("dock", 'left_top'),
                                     panel_h=h_conf.get("panel_h", 240), margin=(8, 8, 4, 8), resizable=True)
    if "expanded" in h_conf:
        state.hierarchy.expanded = {UUID(x) for x in h_conf["expanded"]} | {state.app.id, state.game.id}
    if "panel_w" in h_conf and h_conf["panel_w"] is not None:
        state.hierarchy.components["panel_w"] = h_conf["panel_w"]

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
    if (project / 'code_editor.py').exists():
        if 'code_editor' not in state.code_panel.systems:
            state.code_panel.systems.attach('code_editor', assets.system(project / 'code_editor.py'))
        if 'code_editor' not in state.code.systems:
            state.code.systems.attach('code_editor', assets.system(project / 'code_editor.py'))
    if (project / 'text_area.py').exists():
        if 'text_area' in state.code.systems:
            state.code.systems.reload('text_area', assets.system(project / 'text_area.py'))
        else:
            state.code.systems.attach('text_area', assets.system(project / 'text_area.py'))
    state.selected = selected
    state.select = select
    state.message = message
    state.open_system = open_system
    state.open_panel = open_panel
    state.save_editor_project = lambda: save_editor_project()
    state.new_source = lambda: new_source()
    state.rename_file = rename_file
    state.prompt_rename_file = prompt_rename_file
    state.open_file_menu = open_file_menu
    state.open_specific_file = open_specific_file
    if (project / 'hierarchy.py').exists() and 'hierarchy' not in state.hierarchy.systems:
        state.hierarchy.systems.attach('hierarchy', assets.system(project / 'hierarchy.py'))
    if (project / 'inspector.py').exists() and 'inspector' not in state.inspector.systems:
        state.inspector.systems.attach('inspector', assets.system(project / 'inspector.py'))
    if "render" in state.game.systems:
        open_system(state.game, "render")
    elif state.game.systems:
        open_system(state.game, next(iter(state.game.systems)))


def layout():
    w, h = (state.window.width, state.window.height)
    put(state.app, x=0, y=0, w=w, h=h)
    put(state.background, x=0, y=0, w=w, h=h)

    # Header layout (docked top with padding)
    header_h = state.header.components.get("h", 44)
    put(state.header, x=0, y=0, w=w, h=header_h)
    # Header action buttons: aligned along right edge with margins
    btn_gap = 10
    rx = w - 16
    is_paused = bool(state.game.components.get("paused", False))
    put(state.run_button, text='Run (F5)' if is_paused else 'Pause (F5)')
    for btn, width in ((state.panel_button, 174), (state.system_panel_button, 150),
                       (state.detach_button, 150), (state.save_project_button, 130),
                       (state.run_button, 110)):
        rx -= width
        put(btn, x=rx, y=8, w=width, h=28)
        rx -= btn_gap

    # Status bar layout (docked bottom with margin)
    status_m = parse_box(state.status.components.get("margin", (0, 16, 5, 16)))
    status_h = state.status.components.get("h", 20)
    status_y = h - status_m[2] - status_h
    put(state.status, x=status_m[3], y=status_y, w=max(0, w - status_m[3] - status_m[1]), h=status_h, text=state.app.status)

    # Workspace columns between header and status
    left_col_w = state.app.components.get("left_column_w", 370)
    top_y = state.header.y + state.header.h

    # Hierarchy panel (left top, movable/resizable)
    hm = parse_box(state.hierarchy.components.get("margin", (8, 8, 4, 8)))
    if state.hierarchy.components.get("dock") == "float":
        pass  # Preserves custom/user-dragged x, y, w, h
    else:
        hw = state.hierarchy.components.get("panel_w", left_col_w - hm[3] - hm[1])
        hh = state.hierarchy.components.get("panel_h", 240)
        put(state.hierarchy, x=hm[3], y=top_y + hm[0], w=hw, h=hh)

    # Inspector panel (left bottom, fills remaining height below hierarchy or custom float)
    if state.inspector.components.get("dock") == "float":
        pass
    else:
        im = parse_box(state.inspector.components.get("margin", (4, 8, 6, 8)))
        iw = state.inspector.components.get("panel_w", left_col_w - im[3] - im[1])
        iy = state.hierarchy.y + state.hierarchy.h + hm[2] + im[0] if state.hierarchy.components.get("dock") != "float" else top_y + im[0]
        ih = max(100, status_y - iy - im[2] - 5)
        put(state.inspector, x=im[3], y=iy, w=iw, h=ih)

    # Column splitter between left and right columns
    put(state.col_splitter, x=left_col_w + 1, y=top_y, w=6, h=max(0, status_y - top_y))

    # Hierarchy splitter between hierarchy and inspector
    if state.hierarchy.components.get("dock") != "float" and state.inspector.components.get("dock") != "float":
        put(state.hierarchy_splitter, visible=True, x=hm[3], y=state.hierarchy.y + state.hierarchy.h + 1,
            w=max(0, left_col_w - hm[3] - hm[1]), h=6)
    else:
        put(state.hierarchy_splitter, visible=False)

    # Right column (Viewport and Code editor panels)
    right_x = left_col_w + 8
    right_w = max(100, w - left_col_w - 24)
    split_y = state.code_panel.components.get("split_y", max(330, int(h * 0.45)))

    # Code splitter between viewport and code panel
    if state.viewport.components.get("dock") != "float" and state.code_panel.components.get("dock") != "float":
        put(state.code_splitter, visible=True, x=right_x, y=split_y - 8, w=right_w, h=6)
    else:
        put(state.code_splitter, visible=False)

    # Viewport panel (right top)
    if state.viewport.components.get("dock") == "float":
        pass
    else:
        put(state.zoom_label, x=right_x + 4, y=top_y + 12, w=500, h=20,
            text=f'WORLD  /  {state.camera.zoom:.0f} px per metre  /  drag to pan  /  scroll to zoom')
        put(state.viewport, x=right_x, y=top_y + 36, w=right_w, h=max(50, split_y - top_y - 48))

    # Code editor panel (right bottom)
    if state.code_panel.components.get("dock") == "float":
        pass
    else:
        put(state.code_panel, x=right_x, y=split_y, w=right_w, h=max(100, status_y - split_y - 11))

    # Internal code panel layout:
    cp = state.code_panel
    c_pad = parse_box(cp.components.get("padding", (8, 12, 8, 12)))
    tb_y = cp.y + 32
    if state.ui.focused is not state.path_field and not state.path_field.components.get("readonly", True):
        state.path_field.components["readonly"] = True
        state.path_field.components["ink"] = (160, 180, 205)
        state.path_field.on_commit = None
        if state._saved_source:
            state.path_field.buffer = TextBuffer(state._saved_source[0])
    put(state.path_field, x=cp.x + c_pad[3], y=tb_y, w=max(130, cp.w - c_pad[3] - c_pad[1]), h=28)
    for button in (state.new_button, state.open_button, state.save_button, state.attach_button):
        put(button, visible=False)
    put(state.code, x=cp.x + c_pad[3], y=cp.y + 68, w=max(0, cp.w - c_pad[3] - c_pad[1]), h=max(0, cp.h - 100))
    put(state.code_info, x=cp.x + c_pad[3], y=cp.y + cp.h - 25, w=max(0, cp.w - c_pad[3] - c_pad[1]), h=20)

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


def source_path():
    name = state.path_field.buffer.text.strip()
    path = (state.project / name).resolve()
    if not name or path.suffix != '.py' or (not path.is_relative_to(state.project)):
        raise ValueError('Use a .py path inside the project folder')
    return path


def new_source():
    if not confirm_discard('new'):
        return
    state.path_field.buffer = TextBuffer('new_system.py')
    state.code.buffer = TextBuffer('def update(dt):\n    pass\n')
    state._saved_source = (state.path_field.buffer.text, state.code.buffer.text)
    state.code.components.pop('system_name', None)
    state.code.relations.pop('owner', None)
    message('New source: right-click to Rename file... or Save / reload')


def open_path():
    path = source_path()
    if not path.exists():
        message(f"File not found: {path.name}")
        return
    text = path.read_text(encoding='utf-8')
    if not confirm_discard('open'):
        return
    state.code.buffer = TextBuffer(text)
    state._saved_source = (state.path_field.buffer.text, text)
    state.code.source_path = str(path)
    state.code.components['system_name'] = path.stem
    sel = selected()
    if sel and path.stem in sel.systems:
        state.code.relations['owner'] = sel
    else:
        state.code.relations.pop('owner', None)
    message(f'Opened {path.name}')


def open_specific_file(path):
    path = Path(path).resolve()
    if not path.exists():
        message(f"File not found: {path.name}")
        return
    if not confirm_discard('open'):
        return
    text = path.read_text(encoding='utf-8')
    rel_name = str(path.relative_to(state.project)) if path.is_relative_to(state.project) else path.name
    state.path_field.buffer = TextBuffer(rel_name)
    state.code.buffer = TextBuffer(text)
    state._saved_source = (rel_name, text)
    state.code.source_path = str(path)
    state.code.components['system_name'] = path.stem
    sel = selected()
    if sel and path.stem in sel.systems:
        state.code.relations['owner'] = sel
    else:
        state.code.relations.pop('owner', None)
    message(f"Opened {rel_name}")


def open_file_menu(x=None, y=None):
    candidates = []
    if state.project and state.project.exists():
        for p in sorted(state.project.glob("*.py")):
            candidates.append(p)
    actions = []
    cur_text = state.path_field.buffer.text.strip()
    for p in candidates:
        rel = str(p.relative_to(state.project)) if p.is_relative_to(state.project) else p.name
        is_cur = (rel == cur_text or p.name == cur_text)
        label = f"• {rel}" if is_cur else f"  {rel}"
        actions.append(dict(label=label, run=lambda _, path=p: open_specific_file(path)))
    if not actions:
        actions.append(dict(label="(No .py files in project)", run=None))
    if x is None or y is None:
        mouse = getattr(state.ui, "mouse_pos", None)
        if mouse:
            x, y = mouse
        else:
            x, y = state.path_field.x, state.path_field.y + state.path_field.h + 2
    open_menu(state.ui, state.code_panel, x, y, actions=actions)


def on_path_field_click(control, event):
    if len(event) > 3 and event[3] in (2, 4):
        return False
    click_count = event[5] if len(event) >= 6 else 1
    if click_count >= 2:
        prompt_rename_file()
        return True
    return False


def prompt_rename_file():
    state.path_field.components["readonly"] = False
    state.path_field.components["ink"] = INK
    state.ui.focus(state.path_field)
    state.path_field.buffer.anchor = 0
    state.path_field.buffer.cursor = len(state.path_field.buffer.text)
    state.path_field.on_commit = commit_rename_file
    message(f"Type new name for '{state.path_field.buffer.text}' and press Enter (Esc to cancel)")


def commit_rename_file():
    new_name = state.path_field.buffer.text.strip()
    state.path_field.components["readonly"] = True
    state.path_field.components["ink"] = (160, 180, 205)
    state.path_field.on_commit = None
    old_text = state._saved_source[0] if state._saved_source else state.path_field.buffer.text
    if not new_name or new_name == old_text:
        state.path_field.buffer = TextBuffer(old_text)
        return
    try:
        rename_file(new_name, old_name=old_text)
    except Exception as e:
        message(f"Rename failed: {e}")
        state.path_field.buffer = TextBuffer(old_text)


def rename_file(new_name, old_name=None):
    new_name = new_name.strip()
    if not new_name.endswith('.py'):
        new_name += '.py'
    if old_name is None:
        old_path = source_path()
        old_name = old_path.name
    else:
        old_path = (state.project / old_name).resolve()

    new_path = (state.project / new_name).resolve()
    if not new_path.is_relative_to(state.project):
        raise ValueError('Rename destination must be inside the project folder')

    if new_path == old_path:
        return new_path

    if new_path.exists():
        raise FileExistsError(f"A file named '{new_name}' already exists in the project")

    if old_path.exists():
        old_path.rename(new_path)
    else:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(state.code.buffer.text, encoding='utf-8')

    old_stem = old_path.stem
    new_stem = new_path.stem

    # Update asset cache
    if hasattr(state.runtime.assets, "_systems"):
        state.runtime.assets._systems.pop(old_path, None)
        try:
            state.runtime.assets._systems.pop(old_path.resolve(), None)
        except Exception:
            pass
        state.runtime.assets._systems.pop(str(old_path), None)
    definition = state.runtime.assets.system(new_path)

    updated_count = 0
    for ent in state.runtime.entities:
        for name, instance in tuple(ent.systems.items()):
            inst_def_path = None
            if hasattr(instance, "definition") and hasattr(instance.definition, "path"):
                inst_def_path = Path(instance.definition.path)
            is_match = False
            if inst_def_path is not None:
                try:
                    if inst_def_path.resolve() == old_path.resolve():
                        is_match = True
                except Exception:
                    if inst_def_path == old_path:
                        is_match = True
            if is_match or name == old_stem:
                if name == old_stem:
                    del ent.systems[name]
                    ent.systems.attach(new_stem, definition)
                    updated_count += 1
                else:
                    ent.systems.reload(name, definition)
                    updated_count += 1

        for comp_k, comp_v in tuple(ent.components.items()):
            if isinstance(comp_v, str):
                if comp_v == old_path.name:
                    ent.components[comp_k] = new_path.name
                elif comp_v == old_stem:
                    ent.components[comp_k] = new_stem

    rel_name = str(new_path.relative_to(state.project))
    state.path_field.buffer = TextBuffer(rel_name)
    state._saved_source = (rel_name, state.code.buffer.text)
    state.code.source_path = str(new_path)
    if state.code.components.get("system_name") == old_stem:
        state.code.system_name = new_stem

    save_editor_project()
    inspector_sync()
    message(f"Renamed {old_path.name} to {new_path.name}; updated {updated_count} system attachment(s)")
    return new_path

def open_system(owner, name):
    if not confirm_discard((owner.id, name)):
        return
    instance = owner.systems[name]
    path = Path(instance.definition.path)
    if path.is_relative_to(state.project):
        state.path_field.buffer = TextBuffer(str(path.relative_to(state.project)))
    else:
        state.path_field.buffer = TextBuffer(f'{name}.py')
    state.code.buffer = TextBuffer(instance.definition.source)
    state._saved_source = (state.path_field.buffer.text, state.code.buffer.text)
    state.code.system_name = name
    state.code.relations['owner'] = owner
    message(f"{name} | {('running' if instance.running else 'stopped')} | {', '.join(instance.lifecycle)}")

def confirm_discard(action):
    dirty = state._saved_source is not None and state._saved_source[1] != state.code.buffer.text
    if dirty and state._pending_discard != (action, state.code.buffer.text):
        state._pending_discard = (action, state.code.buffer.text)
        message('Unsaved source. Save first, or repeat the action to discard edits.')
        return False
    state._pending_discard = None
    return True

def get_project_entities():
    splitters = (getattr(state, "col_splitter", None), getattr(state, "hierarchy_splitter", None), getattr(state, "code_splitter", None))
    editor_roots = (state.background, state.camera, state.viewport,
                    state.header, state.hierarchy, state.inspector,
                    state.code_panel, state.status, state.zoom_label,
                    *(s for s in splitters if s is not None),
                    *state.extra_panels)
    def is_editor_entity(e):
        return e is state.app or any(e is r or r in e.ancestors for r in editor_roots)
    return [e for e in state.runtime.entities if not is_editor_entity(e)]


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
            entities_info[name] = {"components": ent_comps}

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
    }


def save_editor_project():
    entities_to_save = get_project_entities()
    save_project(state.project, entities=entities_to_save, layout=get_editor_layout())


def save_project_action():
    save_editor_project()
    message("Saved project state and editor layout")


def save():
    path = source_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False, suffix='.tmp') as stream:
        stream.write(state.code.buffer.text)
        temporary = Path(stream.name)
    temporary.replace(path)
    state._saved_source = (state.path_field.buffer.text, state.code.buffer.text)
    definition = state.runtime.assets.system(path)
    count = 0
    for entity in state.runtime.entities:
        for name, instance in tuple(entity.systems.items()):
            if Path(instance.definition.path) == path:
                updated = entity.systems.reload(name, definition)
                if updated.definition is not definition or not updated.running:
                    raise RuntimeError(f"{name}: {(updated.errors[-1].message if updated.errors else 'reload failed')}")
                count += 1
    save_editor_project()
    message(f'Saved {path.name}; reloaded {count} attachment(s)')

def attach():
    save()
    path = source_path()
    definition = state.runtime.assets.system(path)
    if path.stem in selected().systems:
        instance = selected().systems.reload(path.stem, definition)
    else:
        instance = selected().systems.attach(path.stem, definition)
    if not instance.running:
        raise RuntimeError(instance.errors[-1].message)
    state.code.system_name = path.stem
    state.code.relations['owner'] = selected()
    save_editor_project()
    message(f"Attached {path.stem} to {selected().components.get('name', selected().id)}")

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
    x, y = 0.0, 0.0
    curr = e
    while curr is not None and curr is not state.game:
        x += curr.components.get("x", 0.0)
        y += curr.components.get("y", 0.0)
        curr = curr.parent
    return x, y


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
    control.drag_pos = None
    wx, wy = screen_to_world(state.camera, control, event[1], event[2])
    target = find_hit_game_entity(wx, wy)
    if target is None:
        hits = set(space.query(wx, wy))
        target = next((child for child in reversed(state.game.descendants) if child in hits), None)
    if target:
        select(target)


def viewport_drag(control, event):
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


def keyboard(event):
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


def start():
    if state is None:
        initialize()
    bind_actions()
    if "ui" not in entity.systems:
        state.ui.install(definition=assets.system(project / "ui.py"))


def update(dt):
    owner = state.code.relations.get('owner', selected())
    state.code.completion_components = tuple(owner.components) if owner.alive else ()
    state.code.completion_context = extract_completion_context()
    state.code.source_path = state.project / state.path_field.buffer.text
    layout()
    hierarchy_sync()
    inspector_sync()
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
    if control is state.tags_field or control is state.tags_label:
        return dict(entity=selected(), tags=True)
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
        return selected()
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
            protected = (state.app, state.background, state.viewport, state.header, state.hierarchy, state.inspector)
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
            protected = (state.app, state.background, state.viewport, state.header, state.hierarchy, state.inspector)
            if ent not in protected:
                actions.append(dict(label=f"Delete '{ent_name}'", run=lambda _: (select(ent), inspector_delete_entity())))
        return actions

    if isinstance(target, dict) and target.get('code'):
        cur_file = state.path_field.buffer.text.strip() or "system.py"
        actions = [
            dict(label=f"Save / reload ('{cur_file}')", run=lambda _: save()),
            dict(label=f"Rename '{cur_file}'...", run=lambda _: prompt_rename_file()),
            dict(label="Open file...", run=lambda _: open_file_menu()),
            dict(label="+ New system script...", run=lambda _: new_source()),
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
            protected = (state.app, state.background, state.viewport, state.header, state.hierarchy, state.inspector)
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
        dict(label='Select', run=select),
        dict(label='Rename', run=context_rename),
        dict(label='Inspect entity', run=lambda e: open_panel(target=e)),
        None,
        dict(label="+ Add Component...", run=lambda e: (select(e), open_add_component_menu())),
    ]

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
    state.camera.x, state.camera.y = target.x, target.y
