"""An editor application composed with the public LBE and UI APIs."""

import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
from uuid import UUID

from lbe.ui import (UI, put, contains, parse_box, content_rect, stack, dock,
                    row, column, apply_layout, Layout, BG, PANEL, FIELD, ACCENT,
                    INK, MUTED, PITCH, LINE)
from lbe.text import TextBuffer
from lbe.space import screen_to_world
from lbe.project import save_project, load_project_data, deserialize_entities
from lbe.menus import open_menu

state = entity.components.get("application_state")


def safe_repr(value):
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def parse_value(text):
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
    state.child_rows = []
    state.extra_panels = []
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
    state.path_field = state.ui.field(state.code_panel, 'SourcePath', 'render.py', hint='system_name.py')
    state.path_field.on_commit = open_path
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
    state.quick_pos_btn = state.ui.button(state.inspector, 'QuickPosBtn', '+ Pos', quick_add_pos)
    state.quick_size_btn = state.ui.button(state.inspector, 'QuickSizeBtn', '+ Size', quick_add_size)
    state.quick_vel_btn = state.ui.button(state.inspector, 'QuickVelBtn', '+ Vel', quick_add_vel)
    state.quick_color_btn = state.ui.button(state.inspector, 'QuickColorBtn', '+ Color', quick_add_color)
    state.components_title = state.ui.create(state.inspector, 'ComponentsTitle', 'label', text='COMPONENTS', ink=MUTED)
    state.add_comp_menu_button = state.ui.button(state.inspector, 'AddCompMenuBtn', '+ Component', open_add_component_menu)
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
    state.system_label = state.ui.create(state.inspector, 'SystemsTitle', 'label', text='SYSTEMS', ink=MUTED)
    state.tags_label = state.ui.create(state.inspector, 'TagsLabel', 'label', text='Tags', ink=MUTED)
    state.parent_label = state.ui.create(state.inspector, 'ParentLabel', 'label', text='Parent', ink=MUTED)
    state.relations_label = state.ui.create(state.inspector, 'RelationsLabel', 'label', text='Link', ink=MUTED)
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
    if (project / 'hierarchy.py').exists() and 'hierarchy' not in state.hierarchy.systems:
        state.hierarchy.systems.attach('hierarchy', assets.system(project / 'hierarchy.py'))
    if (project / 'inspector.py').exists() and 'inspector' not in state.inspector.systems:
        state.inspector.systems.attach('inspector', assets.system(project / 'inspector.py'))
    if "render" in state.game.systems:
        open_system(state.game, "render")
    elif state.game.systems:
        open_system(state.game, next(iter(state.game.systems)))


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
    state.app.relations['selection'] = entity
    state.game.relations['selection'] = entity
    state.inspector.scroll = 0
    if 'focus' in state.app.relations:
        del state.app.relations['focus']
    for ancestor in entity.ancestors:
        state.hierarchy.expanded.add(ancestor.id)

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
    put(state.path_field, x=cp.x + c_pad[3], y=tb_y, w=max(130, cp.w - 380), h=28)
    for button, offset, width in ((state.new_button, -360, 52), (state.open_button, -302, 52),
                                  (state.save_button, -244, 126), (state.attach_button, -112, 100)):
        put(button, x=cp.x + cp.w + offset, y=tb_y, w=width, h=28)
    put(state.code, x=cp.x + c_pad[3], y=cp.y + 68, w=max(0, cp.w - c_pad[3] - c_pad[1]), h=max(0, cp.h - 100))
    put(state.code_info, x=cp.x + c_pad[3], y=cp.y + cp.h - 25, w=max(0, cp.w - c_pad[3] - c_pad[1]), h=20)

def hierarchy_sync():
    visible = []
    traversal_stack = [(e, 0) for e in reversed(state.runtime.entities) if e.parent is None]
    expanded = state.hierarchy.expanded
    while traversal_stack and len(visible) < 10000:
        entity, depth = traversal_stack.pop()
        visible.append((entity, depth))
        if entity.id in expanded:
            traversal_stack.extend(((child, depth + 1) for child in reversed(entity.children)))
    capacity = int((state.hierarchy.h - 34) // 22)
    state.hierarchy.visible_count = len(visible)
    max_scroll = max(0, len(visible) - capacity)
    put(state.hierarchy, scroll=max(0, min(state.hierarchy.scroll, max_scroll)))
    while len(state.hierarchy_rows) < capacity:
        row = state.ui.create(state.hierarchy, f'HierarchyRow{len(state.hierarchy_rows)}', 'button', text='', indent=0)
        row.on_click = hierarchy_click
        state.hierarchy_rows.append(row)
    has_scroll = len(visible) > capacity and capacity > 0
    row_w = state.hierarchy.w - 20 if has_scroll else state.hierarchy.w - 16
    for index, row in enumerate(state.hierarchy_rows):
        source = index + state.hierarchy.scroll
        if index >= capacity or source >= len(visible):
            put(row, visible=False)
            continue
        target, depth = visible[source]
        if row.relations.get('target') is not target:
            row.relations['target'] = target
        name = str(target.components.get('name', str(target.id)[:8]))
        marker = '-' if target.id in expanded else '+'
        is_selected = target is selected()
        indicator = '> ' if is_selected else '  '
        text = '  ' * min(depth, 8) + (marker if target.children else ' ') + ' ' + indicator + name
        put(row, visible=True, x=state.hierarchy.x + 8, y=state.hierarchy.y + 32 + index * 22,
            w=row_w, h=22, text=text, indent=min(depth, 8) * 16,
            color=(45, 95, 125) if is_selected else PANEL,
            ink=(255, 255, 255, 255) if is_selected else INK)
    if has_scroll:
        track_x = state.hierarchy.x + state.hierarchy.w - 10
        track_y = state.hierarchy.y + 32
        track_w = 6
        track_h = capacity * 22
        put(state.hierarchy_scroll_track, visible=True, x=track_x, y=track_y, w=track_w, h=track_h)
        thumb_h = max(16, int(track_h * (capacity / len(visible))))
        travel = max(1, track_h - thumb_h)
        thumb_y = track_y + int(travel * (state.hierarchy.scroll / max_scroll)) if max_scroll > 0 else track_y
        put(state.hierarchy_scroll_thumb, visible=True, x=track_x, y=thumb_y, w=track_w, h=thumb_h)
    else:
        put(state.hierarchy_scroll_track, visible=False)
        put(state.hierarchy_scroll_thumb, visible=False)

def inspector_sync():
    entity = selected()
    items = tuple(entity.components.items())
    systems = tuple(entity.systems.items())
    children = tuple(entity.children)
    relations = tuple(entity.relations.items())
    ip = state.inspector
    i_pad = parse_box(ip.components.get("padding", (8, 12, 8, 12)))

    # Header: Name field
    ent_name = str(entity.components.get('name', ''))
    put(state.name_label, x=ip.x + 12, y=ip.y + 32, w=38, h=22, text='Name')
    put(state.name_field, x=ip.x + 54, y=ip.y + 30, w=max(30, ip.w - 66), h=24)
    state.ui.set_text(state.name_field, ent_name)
    put(state.selection_label, visible=False, text=ent_name or str(entity.id))

    # Row 2: Identity label
    put(state.identity_label, x=ip.x + 12, y=ip.y + 56, w=max(30, ip.w - 24), h=18,
        text=f'id: {str(entity.id)[:8]}')

    # Row 3: Quick Entity Actions (+ Child, Duplicate, Delete) with ample room to prevent text clipping
    btn_w = max(60, (ip.w - 24 - 12) // 3)
    put(state.add_child_button, x=ip.x + 12 + 0 * (btn_w + 6), y=ip.y + 76, w=btn_w, h=24, text='+ Child')
    put(state.duplicate_button, x=ip.x + 12 + 1 * (btn_w + 6), y=ip.y + 76, w=btn_w, h=24, text='Duplicate')
    put(state.delete_button, x=ip.x + 12 + 2 * (btn_w + 6), y=ip.y + 76, w=btn_w, h=24, text='Delete')

    # Row 4: Quick Preset Chips (+ Pos, + Size, + Vel, + Color)
    preset_w = max(36, (ip.w - 24 - 18) // 4)
    put(state.quick_pos_btn, x=ip.x + 12 + 0 * (preset_w + 6), y=ip.y + 104, w=preset_w, h=22)
    put(state.quick_size_btn, x=ip.x + 12 + 1 * (preset_w + 6), y=ip.y + 104, w=preset_w, h=22)
    put(state.quick_vel_btn, x=ip.x + 12 + 2 * (preset_w + 6), y=ip.y + 104, w=preset_w, h=22)
    put(state.quick_color_btn, x=ip.x + 12 + 3 * (preset_w + 6), y=ip.y + 104, w=preset_w, h=22)

    # Row 5: Components Section Header & Quick Add Menu Button
    put(state.components_title, x=ip.x + 12, y=ip.y + 130, w=120, h=22, text='COMPONENTS')
    comp_btn_w = 96
    put(state.add_comp_menu_button, x=ip.x + ip.w - 12 - comp_btn_w, y=ip.y + 130, w=comp_btn_w, h=22, text='+ Component')

    # Dynamic calculation of bottom section height
    num_rel_rows = min(len(relations), 3) if relations else 0
    rel_rows_h = (num_rel_rows * 24 + 4) if relations else 0
    num_sys_rows = min(2, (len(systems) + 2) // 3) if systems else 0
    sys_h = (20 + num_sys_rows * 26) if systems else 0
    num_child_rows = min(3, (len(children) + 2) // 3) if children else 0
    child_h = (num_child_rows * 24 + 4) if children else 0
    bottom_h = 30 * 4 + rel_rows_h + 22 + sys_h + child_h + 8

    # Component rows capacity & scroll
    comp_start_y = ip.y + 156
    avail_comp_h = max(28, ip.h - (comp_start_y - ip.y) - bottom_h)
    capacity = max(1, int(avail_comp_h // 28))
    max_scroll = max(0, len(items) - capacity)
    state.inspector.item_count = len(items)
    state.inspector.capacity = capacity
    put(state.inspector, scroll=max(0, min(state.inspector.scroll, max_scroll)))

    while len(state.component_rows) < capacity:
        n = len(state.component_rows)
        label = state.ui.create(state.inspector, f'ComponentLabel{n}', 'label', text='', ink=MUTED)
        field = state.ui.field(state.inspector, f'ComponentField{n}', '')
        state.component_rows.append((label, field))

    while len(state.component_delete_buttons) < capacity:
        n = len(state.component_delete_buttons)
        btn = state.ui.button(state.inspector, f'ComponentDel{n}', 'x', lambda: None, color=(60, 30, 35))
        state.component_delete_buttons.append(btn)

    has_comp_scroll = len(items) > capacity and capacity > 0
    sb_w = 12 if has_comp_scroll else 0

    for index, (label, field) in enumerate(state.component_rows):
        source = index + state.inspector.scroll
        shown = index < capacity and source < len(items)
        put(label, visible=shown)
        put(field, visible=shown)
        del_btn = state.component_delete_buttons[index]
        put(del_btn, visible=shown)
        if not shown:
            continue
        key, value = items[source]
        editable = type(value) in (int, float, bool, str, tuple, list, dict, type(None))
        y = comp_start_y + index * 28
        del_w = 20
        field_w = max(30, ip.w - 126 - 12 - del_w - 4 - sb_w)
        del_x = ip.x + 126 + field_w + 4
        put(label, x=ip.x + 12, y=y + 4, w=110, h=24, text=key)
        put(field, x=ip.x + 126, y=y, w=field_w, h=25, readonly=not editable)
        put(del_btn, x=del_x, y=y, w=del_w, h=25, text='x')
        del_btn.action = lambda k=key: delete_component(k)
        label.component_key = key
        label.relations['target'] = entity
        del_btn.component_key = key
        del_btn.relations['target'] = entity
        if field.components.get('component_key') != key or field.relations.get('target') is not entity:
            if state.ui.focused is field:
                del state.app.relations['focus']
            field.component_key = key
            field.relations['target'] = entity
            field.on_commit = lambda f=field: commit_component(f)
            field.on_click = component_click
        state.ui.set_text(field, safe_repr(value))

    for btn in state.component_delete_buttons[capacity:]:
        put(btn, visible=False)

    if has_comp_scroll:
        track_x = ip.x + ip.w - 10
        track_y = comp_start_y
        track_w = 6
        track_h = capacity * 28
        put(state.inspector_scroll_track, visible=True, x=track_x, y=track_y, w=track_w, h=track_h)
        thumb_h = max(16, int(track_h * (capacity / len(items))))
        travel = max(1, track_h - thumb_h)
        thumb_y = track_y + int(travel * (state.inspector.scroll / max_scroll)) if max_scroll > 0 else track_y
        put(state.inspector_scroll_thumb, visible=True, x=track_x, y=thumb_y, w=track_w, h=thumb_h)
    else:
        put(state.inspector_scroll_track, visible=False)
        put(state.inspector_scroll_thumb, visible=False)

    # Flow bottom section downwards from bottom_start_y
    bottom_start_y = max(comp_start_y + capacity * 28 + 6, ip.y + ip.h - bottom_h)
    cur_y = bottom_start_y

    # 1. Add component row
    put(state.add_name, x=ip.x + 12, y=cur_y, w=120, h=26)
    put(state.add_value, x=ip.x + 138, y=cur_y, w=max(30, ip.w - 186), h=26)
    put(state.add_button, x=ip.x + ip.w - 42, y=cur_y, w=30, h=26)
    cur_y += 30

    # 2. Tags row
    put(state.tags_label, x=ip.x + 12, y=cur_y + 4, w=60, h=22)
    put(state.tags_field, x=ip.x + 76, y=cur_y, w=max(30, ip.w - 88), h=26)
    state.ui.set_text(state.tags_field, ', '.join(entity.tags))
    cur_y += 30

    # 3. Parent row
    put(state.parent_label, x=ip.x + 12, y=cur_y + 4, w=60, h=22)
    put(state.parent_field, x=ip.x + 76, y=cur_y, w=max(30, ip.w - 88), h=26)
    state.ui.set_text(state.parent_field, str(entity.parent.components.get('name', entity.parent.id)) if entity.parent else '')
    cur_y += 30

    # 4. Relations row (with '+' commit button)
    put(state.relations_label, x=ip.x + 12, y=cur_y + 4, w=60, h=22)
    put(state.relation_field, x=ip.x + 76, y=cur_y, w=max(30, ip.w - 88 - 36), h=26)
    put(state.link_add_button, x=ip.x + ip.w - 42, y=cur_y, w=30, h=26, text='+')
    cur_y += 30

    # Interactive existing relations list (up to 3 rows) with Edit button
    while len(state.relation_rows) < num_rel_rows:
        n = len(state.relation_rows)
        r_btn = state.ui.button(state.inspector, f'RelNav{n}', '', lambda: None)
        u_btn = state.ui.button(state.inspector, f'RelUnlink{n}', 'x', lambda: None, color=(60, 30, 35))
        state.relation_rows.append((r_btn, u_btn))
        edit_btn = state.ui.button(state.inspector, f'RelEdit{n}', 'Edit', lambda: None)
        state.relation_edit_buttons.append(edit_btn)

    while len(state.relation_edit_buttons) < len(state.relation_rows):
        n = len(state.relation_edit_buttons)
        edit_btn = state.ui.button(state.inspector, f'RelEdit{n}', 'Edit', lambda: None)
        state.relation_edit_buttons.append(edit_btn)

    for index, (r_btn, u_btn) in enumerate(state.relation_rows):
        shown = index < num_rel_rows
        put(r_btn, visible=shown)
        put(u_btn, visible=shown)
        edit_btn = state.relation_edit_buttons[index]
        put(edit_btn, visible=shown)
        if shown:
            r_name, r_target = relations[index]
            tgt_name = str(r_target.components.get('name', str(r_target.id)[:8]))
            btn_del_w = 22
            btn_edit_w = 40
            r_w = max(40, ip.w - 24 - btn_del_w - btn_edit_w - 8)
            put(r_btn, x=ip.x + 12, y=cur_y, w=r_w, h=22, text=f"{r_name} -> {tgt_name}")
            put(edit_btn, x=ip.x + 12 + r_w + 4, y=cur_y, w=btn_edit_w, h=22, text='Edit')
            put(u_btn, x=ip.x + 12 + r_w + 4 + btn_edit_w + 4, y=cur_y, w=btn_del_w, h=22, text='x')
            r_btn.action = lambda t=r_target: select(t)
            edit_btn.action = lambda n=r_name, tn=tgt_name: start_edit_link(n, tn)
            u_btn.action = lambda n=r_name: unlink_relation(n)
            r_btn.relation_key = r_name
            r_btn.relations['target'] = entity
            edit_btn.relation_key = r_name
            edit_btn.relations['target'] = entity
            cur_y += 24
    for r_btn, u_btn in state.relation_rows[num_rel_rows:]:
        put(r_btn, visible=False)
        put(u_btn, visible=False)
    for edit_btn in state.relation_edit_buttons[num_rel_rows:]:
        put(edit_btn, visible=False)
    if num_rel_rows > 0:
        cur_y += 4

    # 5. Metadata label
    put(state.metadata, x=ip.x + 12, y=cur_y, w=max(0, ip.w - 24), h=18,
        text=f'{len(children)} children | {len(relations)} relations')
    cur_y += 22

    # 6. Systems section
    if systems:
        put(state.system_label, visible=True, x=ip.x + 12, y=cur_y, w=90, h=18)
        cur_y += 20
        max_sys = min(len(systems), 6)
        while len(state.system_rows) < max_sys:
            idx = len(state.system_rows)
            btn = state.ui.button(state.inspector, f'System{idx}', '', lambda: None)
            state.system_rows.append(btn)
        btn_w = max(60, (ip.w - 24 - 12) // 3)
        for index, button in enumerate(state.system_rows):
            shown = index < max_sys
            put(button, visible=shown)
            if shown:
                name, instance = systems[index]
                col = index % 3
                row_idx = index // 3
                put(button, x=ip.x + 12 + col * (btn_w + 6),
                    y=cur_y + row_idx * 26,
                    w=btn_w, h=24, text=name + (' !' if instance.errors else ''))
                if button.components.get('system_key') != (entity.id, name):
                    button.system_key = (entity.id, name)
                    button.action = lambda e=entity, n=name: open_system(e, n)
        cur_y += num_sys_rows * 26 + 4
    else:
        put(state.system_label, visible=False)
        for button in state.system_rows:
            put(button, visible=False)

    # 7. Children quick navigation
    if children:
        max_children = min(len(children), 9)
        while len(state.child_rows) < max_children:
            idx = len(state.child_rows)
            btn = state.ui.button(state.inspector, f'Child{idx}', '', lambda: None)
            state.child_rows.append(btn)
        btn_w = max(60, (ip.w - 24 - 12) // 3)
        for index, button in enumerate(state.child_rows):
            shown = index < max_children
            put(button, visible=shown)
            if shown:
                child = children[index]
                c_name = str(child.components.get('name', str(child.id)[:8]))
                col = index % 3
                row_idx = index // 3
                put(button, x=ip.x + 12 + col * (btn_w + 6),
                    y=cur_y + row_idx * 24,
                    w=btn_w, h=22, text=c_name)
                if button.components.get('child_id') != child.id:
                    button.child_id = child.id
                    button.action = lambda c=child: select(c)
    else:
        for button in state.child_rows:
            put(button, visible=False)

    for owner in state.runtime.entities:
        for name, instance in owner.systems.items():
            if instance.errors:
                error = instance.errors[-1]
                message(f'{error.source}: {error.message}')

def commit_component(field):
    target, key = (field.relations['target'], field.component_key)
    target.components[key] = parse_value(field.buffer.text)
    message(f'Updated {key}')
    inspector_sync()

def add_component():
    name = state.add_name.buffer.text.strip()
    if not name:
        raise ValueError('Enter a component name')
    selected().components[name] = parse_value(state.add_value.buffer.text)
    state.add_name.buffer = TextBuffer()
    state.add_value.buffer = TextBuffer()
    message(f'Added {name}')
    inspector_sync()

def commit_tags():
    tags = {tag.strip() for tag in state.tags_field.buffer.text.split(',') if tag.strip()}
    for tag in set(selected().tags) - tags:
        selected().tags.discard(tag)
    for tag in tags:
        selected().tags.add(tag)
    message('Tags updated')
    inspector_sync()

def resolve_name(text):
    text = text.strip()
    if not text:
        raise ValueError('Enter an entity name or UUID')
    try:
        return state.runtime.resolve(text)
    except (ValueError, KeyError):
        exact = [e for e in state.runtime.entities if e.components.get('name') == text]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise ValueError(f"Ambiguous entity name '{text}'. Use UUID instead.")

        lower_matches = [e for e in state.runtime.entities if str(e.components.get('name', '')).lower() == text.lower()]
        if len(lower_matches) == 1:
            return lower_matches[0]
        if len(lower_matches) > 1:
            raise ValueError(f"Ambiguous entity name '{text}'. Use UUID instead.")

        uuid_matches = [e for e in state.runtime.entities if str(e.id).lower().startswith(text.lower())]
        if len(uuid_matches) == 1:
            return uuid_matches[0]
        if len(uuid_matches) > 1:
            raise ValueError(f"Ambiguous UUID prefix '{text}'. Use full UUID.")

        tag_matches = [e for e in state.runtime.entities if text in e.tags]
        if len(tag_matches) == 1:
            return tag_matches[0]
        if len(tag_matches) > 1:
            raise ValueError(f"Multiple entities share tag '{text}'. Use UUID or unique name.")

        raise ValueError(f"No entity found matching '{text}'")

def commit_parent():
    text = state.parent_field.buffer.text.strip()
    selected().parent = resolve_name(text) if text else None
    message('Parent updated')
    hierarchy_sync()
    inspector_sync()

def commit_relation():
    raw = state.relation_field.buffer.text.strip()
    if not raw:
        raise ValueError('Enter relation=target or target name')
    editing_rel = state.relation_field.components.pop("editing_relation", None)
    if '=' in raw:
        name, _, text = raw.partition('=')
        name = name.strip()
        text = text.strip()
        if not name:
            raise ValueError('Use relation=entity name or UUID')
        if text:
            target = resolve_name(text)
            if editing_rel and editing_rel != name:
                selected().relations.pop(editing_rel, None)
            selected().relations[name] = target
            tgt_name = str(target.components.get('name', str(target.id)[:8]))
            message(f"Linked '{name}' -> '{tgt_name}'")
        else:
            rel_to_remove = editing_rel or name
            selected().relations.pop(rel_to_remove, None)
            message(f"Unlinked relation '{rel_to_remove}'")
    else:
        target = resolve_name(raw)
        tgt_name = str(target.components.get('name', str(target.id)[:8]))
        name = editing_rel or tgt_name.lower().replace(" ", "_")
        selected().relations[name] = target
        message(f"Linked '{name}' -> '{tgt_name}'")
    state.relation_field.buffer = TextBuffer()
    inspector_sync()

def start_edit_link(name, tgt_name=None):
    ent = selected()
    if tgt_name is None:
        tgt = ent.relations.get(name)
        tgt_name = str(tgt.components.get('name', str(tgt.id)[:8])) if tgt else ''
    state.relation_field.buffer = TextBuffer(f"{name}={tgt_name}")
    state.relation_field.buffer.anchor = 0
    state.relation_field.buffer.cursor = len(state.relation_field.buffer.text)
    state.relation_field.components["editing_relation"] = name
    state.ui.focus(state.relation_field)
    message(f"Editing link '{name}'. Press Enter or click + to save.")

def quick_link_to(target):
    source = selected()
    if source is target:
        message("Cannot link entity to itself")
        return
    tgt_name = str(target.components.get('name', str(target.id)[:8]))
    base_name = tgt_name.lower().replace(" ", "_")
    name = base_name
    count = 1
    while name in source.relations and source.relations[name] is not target:
        count += 1
        name = f"{base_name}_{count}"
    source.relations[name] = target
    message(f"Linked '{name}' -> '{tgt_name}'")
    inspector_sync()


def commit_name():
    name = state.name_field.buffer.text.strip()
    ent = selected()
    if name:
        ent.components['name'] = name
        message(f"Renamed entity to '{name}'")
    else:
        ent.components.pop('name', None)
        message("Cleared entity name")
    hierarchy_sync()
    inspector_sync()


def inspector_add_child():
    parent = selected()
    c_name = f"Child_{len(parent.children) + 1}"
    child = state.runtime.create(parent=parent, name=c_name)
    select(child)
    message(f"Added child '{c_name}'")
    hierarchy_sync()
    inspector_sync()


def inspector_duplicate_entity():
    ent = selected()
    if ent is state.app or ent is state.game or any(ent is r for r in (state.header, state.hierarchy, state.inspector, state.code_panel, state.status, state.viewport)):
        message("Cannot duplicate engine or editor root")
        return
    parent = ent.parent or state.game
    orig_name = str(ent.components.get('name', 'Entity'))
    new_name = orig_name + "_copy"
    comps = dict(ent.components)
    comps['name'] = new_name
    dup = state.runtime.create(parent=parent, tags=list(ent.tags), **comps)
    select(dup)
    message(f"Duplicated '{orig_name}' as '{new_name}'")
    hierarchy_sync()
    inspector_sync()


def inspector_delete_entity():
    ent = selected()
    if ent is state.app or ent is state.game or any(ent is r for r in (state.header, state.hierarchy, state.inspector, state.code_panel, state.status, state.viewport)):
        message("Cannot delete engine or editor root")
        return
    parent = ent.parent or state.game
    ent_name = str(ent.components.get('name', str(ent.id)[:8]))
    ent.destroy()
    select(parent)
    message(f"Deleted entity '{ent_name}'")
    hierarchy_sync()
    inspector_sync()


def delete_component(key):
    ent = selected()
    if key in ent.components:
        del ent.components[key]
        if state.ui.focused and getattr(state.ui.focused, "component_key", None) == key:
            del state.app.relations['focus']
        message(f"Deleted component '{key}'")
        inspector_sync()


def unlink_relation(name):
    ent = selected()
    if name in ent.relations:
        del ent.relations[name]
        if state.relation_field.components.get("editing_relation") == name:
            state.relation_field.components.pop("editing_relation", None)
            state.relation_field.buffer = TextBuffer()
        message(f"Unlinked relation '{name}'")
        inspector_sync()


def quick_add_pos():
    ent = selected()
    ent.components.setdefault("x", 0.0)
    ent.components.setdefault("y", 0.0)
    message("Added Pos (x, y)")
    inspector_sync()


def quick_add_size():
    ent = selected()
    ent.components.setdefault("w", 32.0)
    ent.components.setdefault("h", 32.0)
    message("Added Size (w, h)")
    inspector_sync()


def quick_add_vel():
    ent = selected()
    ent.components.setdefault("vx", 0.0)
    ent.components.setdefault("vy", 0.0)
    message("Added Vel (vx, vy)")
    inspector_sync()


def quick_add_color():
    ent = selected()
    ent.components.setdefault("color", (200, 200, 200))
    message("Added Color")
    inspector_sync()


def quick_add_speed():
    ent = selected()
    ent.components.setdefault("speed", 100.0)
    message("Added Speed")
    inspector_sync()


def open_add_component_menu():
    ent = selected()
    actions = [
        dict(label="+ Transform / Pos (x, y)", run=lambda e: (select(ent), quick_add_pos())),
        dict(label="+ Size (w, h)", run=lambda e: (select(ent), quick_add_size())),
        dict(label="+ Velocity (vx, vy)", run=lambda e: (select(ent), quick_add_vel())),
        dict(label="+ Color (r, g, b)", run=lambda e: (select(ent), quick_add_color())),
        dict(label="+ Speed", run=lambda e: (select(ent), quick_add_speed())),
        None,
        dict(label="Custom Component...", run=lambda e: context_add_component(ent)),
    ]
    open_menu(state.ui, ent, state.add_comp_menu_button.x, state.add_comp_menu_button.y + state.add_comp_menu_button.h + 2, actions=actions)


def hierarchy_scroll_drag(thumb, event):
    visible_count = getattr(state.hierarchy, "visible_count", 0)
    capacity = max(1, int((state.hierarchy.h - 34) // 22))
    max_scroll = max(0, visible_count - capacity)
    if max_scroll <= 0:
        return True
    track = state.hierarchy_scroll_track
    travel = max(1, track.h - thumb.h)
    rel_y = event[2] - track.y - thumb.h / 2
    ratio = max(0.0, min(1.0, rel_y / travel))
    state.hierarchy.scroll = int(round(ratio * max_scroll))
    return True


def hierarchy_track_click(track, event):
    capacity = max(1, int((state.hierarchy.h - 34) // 22))
    thumb = state.hierarchy_scroll_thumb
    if not thumb.visible:
        return True
    visible_count = getattr(state.hierarchy, "visible_count", 0)
    max_scroll = max(0, visible_count - capacity)
    if event[2] < thumb.y:
        state.hierarchy.scroll = max(0, state.hierarchy.scroll - capacity)
    elif event[2] > thumb.y + thumb.h:
        state.hierarchy.scroll = min(max_scroll, state.hierarchy.scroll + capacity)
    return True


def inspector_scroll_drag(thumb, event):
    item_count = getattr(state.inspector, "item_count", 0)
    capacity = getattr(state.inspector, "capacity", 1)
    max_scroll = max(0, item_count - capacity)
    if max_scroll <= 0:
        return True
    track = state.inspector_scroll_track
    travel = max(1, track.h - thumb.h)
    rel_y = event[2] - track.y - thumb.h / 2
    ratio = max(0.0, min(1.0, rel_y / travel))
    state.inspector.scroll = int(round(ratio * max_scroll))
    return True


def inspector_track_click(track, event):
    capacity = getattr(state.inspector, "capacity", 1)
    thumb = state.inspector_scroll_thumb
    if not thumb.visible:
        return True
    item_count = getattr(state.inspector, "item_count", 0)
    max_scroll = max(0, item_count - capacity)
    if event[2] < thumb.y:
        state.inspector.scroll = max(0, state.inspector.scroll - capacity)
    elif event[2] > thumb.y + thumb.h:
        state.inspector.scroll = min(max_scroll, state.inspector.scroll + capacity)
    return True

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
    message('New source: choose a filename, edit, then Save / reload')

def open_path():
    path = source_path()
    text = path.read_text(encoding='utf-8')
    if not confirm_discard('open'):
        return
    state.code.buffer = TextBuffer(text)
    state._saved_source = (state.path_field.buffer.text, text)
    message(f'Opened {path.name}')

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


def hierarchy_click(row, event):
    target = row.relations["target"]
    if event[1] < row.x + row.indent + 24:
        expanded = set(state.hierarchy.expanded)
        expanded.symmetric_difference_update({target.id})
        state.hierarchy.expanded = expanded
    select(target)


def component_click(control, event):
    if event[3] == 4:
        open_panel(target=control.relations["target"], component=control.component_key)
        return True
    return False


def scroll_list(control, event):
    control.scroll = max(0, control.scroll-int(event[4])*3)


def viewport_click(control, event):
    control.drag_pos = None
    wx, wy = screen_to_world(state.camera, control, event[1], event[2])
    hits = set(space.query(wx, wy))
    target = next((child for child in reversed(state.game.children) if child in hits), None)
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
                            (state.quick_pos_btn, quick_add_pos),
                            (state.quick_size_btn, quick_add_size),
                            (state.quick_vel_btn, quick_add_vel),
                            (state.quick_color_btn, quick_add_color)):
        control.action = action
    for control, action in ((state.path_field, open_path), (state.tags_field, commit_tags),
                            (state.parent_field, commit_parent), (state.relation_field, commit_relation),
                            (state.name_field, commit_name)):
        control.on_commit = action
    state.hierarchy_scroll_track.on_click = hierarchy_track_click
    state.hierarchy_scroll_thumb.on_drag = hierarchy_scroll_drag
    state.inspector_scroll_track.on_click = inspector_track_click
    state.inspector_scroll_thumb.on_drag = inspector_scroll_drag
    for row in state.hierarchy_rows:
        row.on_click = hierarchy_click
    for _, field in state.component_rows:
        field.on_commit = lambda field=field: commit_component(field)
        field.on_click = component_click
    for button in state.system_rows:
        button.components.pop("system_key", None)


def start():
    if state is None:
        initialize()
    bind_actions()
    if "ui" not in entity.systems:
        state.ui.install(definition=assets.system(project / "ui.py"))


def update(dt):
    layout()
    hierarchy_sync()
    inspector_sync()
    panels_sync()
    row, column = state.code.buffer.position
    diag = state.code.components.get("diagnostic")
    run_status = "paused" if state.game.components.get("paused") else "running"
    if diag:
        put(state.code_info, text=f"SyntaxError Ln {diag['line']}, Col {diag['column']}: {diag['message']}", ink=(248, 81, 73, 255))
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


def context_target(control, event):
    if 'component_key' in control.components and 'target' in control.relations:
        return dict(entity=control.relations['target'], component=control.component_key)
    if 'relation_key' in control.components and 'target' in control.relations:
        return dict(entity=control.relations['target'], relation=control.relation_key)
    if control is state.viewport:
        wx, wy = screen_to_world(state.camera, control, event[1], event[2])
        hits = set(space.query(wx, wy))
        return next((child for child in reversed(state.game.children) if child in hits), state.game)
    for candidate in (control,) + control.ancestors:
        if 'target' in candidate.relations:
            return candidate.relations['target']
    if control is state.inspector or state.inspector in control.ancestors:
        return selected()
    return control


def context_actions(target):
    if isinstance(target, dict) and 'component' in target:
        ent = target['entity']
        comp = target['component']
        return [
            dict(label='Inspect component', run=lambda t: open_panel(target=ent, component=comp)),
            dict(label=f"Delete '{comp}'", run=lambda t: delete_component(comp)),
            None,
            dict(label="Add component...", run=lambda t: context_add_component(ent)),
        ]
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
        dict(label='+ Add Pos (x, y)', run=lambda e: (select(e), quick_add_pos())),
        dict(label='+ Add Size (w, h)', run=lambda e: (select(e), quick_add_size())),
        dict(label='+ Add Velocity (vx, vy)', run=lambda e: (select(e), quick_add_vel())),
        dict(label='+ Add Color', run=lambda e: (select(e), quick_add_color())),
        dict(label='+ Add Speed', run=lambda e: (select(e), quick_add_speed())),
        dict(label='+ Custom Component...', run=context_add_component),
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
