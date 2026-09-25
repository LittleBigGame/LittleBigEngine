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
    state.zoom_label = state.ui.create(state.app, 'ViewportCaption', 'label', text='WORLD', ink=MUTED)
    state.selection_label = state.ui.create(state.inspector, 'Selection', 'label', text='')
    state.identity_label = state.ui.create(state.inspector, 'Identity', 'label', text='', ink=MUTED)
    state.add_name = state.ui.field(state.inspector, 'ComponentName', '', hint='component name')
    state.add_value = state.ui.field(state.inspector, 'ComponentValue', '', hint='value, e.g. 2.0')
    state.add_button = state.ui.button(state.inspector, 'AddComponent', '+', add_component)
    state.tags_field = state.ui.field(state.inspector, 'Tags', '', hint='tags, comma separated')
    state.tags_field.on_commit = commit_tags
    state.parent_field = state.ui.field(state.inspector, 'Parent', '', hint='parent name or UUID; blank detaches')
    state.parent_field.on_commit = commit_parent
    state.relation_field = state.ui.field(state.inspector, 'Relations', '', hint='relation=entity name (blank target removes)')
    state.relation_field.on_commit = commit_relation
    state.metadata = state.ui.create(state.inspector, 'Metadata', 'label', text='', ink=MUTED)
    state.system_label = state.ui.create(state.inspector, 'SystemsTitle', 'label', text='SYSTEMS', ink=MUTED)
    state.tags_label = state.ui.create(state.inspector, 'TagsLabel', 'label', text='Tags', ink=MUTED)
    state.parent_label = state.ui.create(state.inspector, 'ParentLabel', 'label', text='Parent', ink=MUTED)
    state.relations_label = state.ui.create(state.inspector, 'RelationsLabel', 'label', text='Link', ink=MUTED)
    state.code_info = state.ui.create(state.code_panel, 'SourceInfo', 'label', text='', ink=MUTED)
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
    for btn, width in ((state.panel_button, 174), (state.system_panel_button, 150),
                       (state.detach_button, 150), (state.save_project_button, 130)):
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

    # Right column (Viewport and Code editor panels)
    right_x = left_col_w + 8
    right_w = max(100, w - left_col_w - 24)
    split_y = state.code_panel.components.get("split_y", max(330, int(h * 0.45)))

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

    # Internal inspector layout:
    ip = state.inspector
    i_pad = parse_box(ip.components.get("padding", (8, 12, 8, 12)))
    put(state.selection_label, x=ip.x + i_pad[3], y=ip.y + 32, w=max(0, ip.w - i_pad[3] - i_pad[1]), h=20,
        text=selected().components.get('name', str(selected().id)))
    put(state.identity_label, x=ip.x + i_pad[3], y=ip.y + 54, w=max(0, ip.w - i_pad[3] - i_pad[1]), h=20,
        text=str(selected().id))
    bottom = ip.y + ip.h
    put(state.add_name, x=ip.x + 12, y=bottom - 206, w=120, h=26)
    put(state.add_value, x=ip.x + 138, y=bottom - 206, w=max(30, ip.w - 186), h=26)
    put(state.add_button, x=ip.x + ip.w - 42, y=bottom - 206, w=30, h=26)
    put(state.tags_field, x=ip.x + 76, y=bottom - 172, w=max(30, ip.w - 88), h=26)
    put(state.parent_field, x=ip.x + 76, y=bottom - 140, w=max(30, ip.w - 88), h=26)
    put(state.relation_field, x=ip.x + 76, y=bottom - 108, w=max(30, ip.w - 88), h=26)
    for label, field in ((state.tags_label, state.tags_field), (state.parent_label, state.parent_field),
                         (state.relations_label, state.relation_field)):
        put(label, x=ip.x + 12, y=field.y + 4, w=64, h=22)
    put(state.metadata, x=ip.x + 12, y=bottom - 78, w=max(0, ip.w - 24), h=18,
        text=f'{len(selected().children)} children | {len(selected().relations)} relations')
    put(state.system_label, x=ip.x + 12, y=bottom - 55, w=90, h=18)

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
    put(state.hierarchy, scroll=max(0, min(state.hierarchy.scroll, max(0, len(visible) - capacity))))
    while len(state.hierarchy_rows) < capacity:
        row = state.ui.create(state.hierarchy, f'HierarchyRow{len(state.hierarchy_rows)}', 'button', text='', indent=0)
        row.on_click = hierarchy_click
        state.hierarchy_rows.append(row)
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
            w=state.hierarchy.w - 16, h=22, text=text, indent=min(depth, 8) * 16,
            color=(45, 95, 125) if is_selected else PANEL,
            ink=(255, 255, 255, 255) if is_selected else INK)

def inspector_sync():
    entity = selected()
    items = tuple(entity.components.items())
    capacity = max(1, int((state.inspector.h - 292) // 28))
    put(state.inspector, scroll=max(0, min(state.inspector.scroll, max(0, len(items) - capacity))))
    while len(state.component_rows) < capacity:
        n = len(state.component_rows)
        label = state.ui.create(state.inspector, f'ComponentLabel{n}', 'label', text='', ink=MUTED)
        field = state.ui.field(state.inspector, f'ComponentField{n}', '')
        state.component_rows.append((label, field))
    for index, (label, field) in enumerate(state.component_rows):
        source = index + state.inspector.scroll
        shown = index < capacity and source < len(items)
        put(label, visible=shown)
        put(field, visible=shown)
        if not shown:
            continue
        key, value = items[source]
        editable = type(value) in (int, float, bool, str, tuple, list, dict, type(None))
        y = state.inspector.y + 82 + index * 28
        put(label, x=state.inspector.x + 12, y=y + 4, w=112, h=24, text=key)
        put(field, x=state.inspector.x + 126, y=y, w=state.inspector.w - 138, h=25, readonly=not editable)
        if field.components.get('component_key') != key or field.relations.get('target') is not entity:
            if state.ui.focused is field:
                del state.app.relations['focus']
            field.component_key = key
            field.relations['target'] = entity
            field.on_commit = lambda f=field: commit_component(f)
            field.on_click = component_click
        state.ui.set_text(field, safe_repr(value))
    state.ui.set_text(state.tags_field, ', '.join(entity.tags))
    state.ui.set_text(state.parent_field, str(entity.parent.components.get('name', entity.parent.id)) if entity.parent else '')
    systems = tuple(entity.systems.items())
    while len(state.system_rows) < len(systems):
        index = len(state.system_rows)
        button = state.ui.button(state.inspector, f'System{index}', '', lambda: None)
        state.system_rows.append(button)
    for index, button in enumerate(state.system_rows):
        put(button, visible=index < len(systems))
        if index < len(systems):
            name, instance = systems[index]
            put(button, x=state.inspector.x + 12 + (index % 3) * 108,
                y=state.inspector.y + state.inspector.h - 32 - (index // 3) * 26,
                w=102, h=24, text=name + (' !' if instance.errors else ''))
            if button.components.get('system_key') != (entity.id, name):
                button.system_key = (entity.id, name)
                button.action = lambda e=entity, n=name: open_system(e, n)
    children = tuple(entity.children)
    while len(state.child_rows) < len(children):
        index = len(state.child_rows)
        button = state.ui.button(state.inspector, f'Child{index}', '', lambda: None)
        state.child_rows.append(button)
    for index, button in enumerate(state.child_rows):
        shown = index < len(children)
        put(button, visible=shown)
        if shown:
            child = children[index]
            c_name = str(child.components.get('name', str(child.id)[:8]))
            put(button, x=state.inspector.x + 12 + (index % 3) * 108,
                y=state.inspector.y + state.inspector.h - 64 - (index // 3) * 24,
                w=102, h=22, text=c_name)
            if button.components.get('child_id') != child.id:
                button.child_id = child.id
                button.action = lambda c=child: select(c)
    for owner in state.runtime.entities:
        for name, instance in owner.systems.items():
            if instance.errors:
                error = instance.errors[-1]
                message(f'{error.source}: {error.message}')

def commit_component(field):
    target, key = (field.relations['target'], field.component_key)
    target.components[key] = parse_value(field.buffer.text)
    message(f'Updated {key}')

def add_component():
    name = state.add_name.buffer.text.strip()
    if not name:
        raise ValueError('Enter a component name')
    selected().components[name] = parse_value(state.add_value.buffer.text)
    state.add_name.buffer = TextBuffer()
    state.add_value.buffer = TextBuffer()
    message(f'Added {name}')

def commit_tags():
    tags = {tag.strip() for tag in state.tags_field.buffer.text.split(',') if tag.strip()}
    for tag in set(selected().tags) - tags:
        selected().tags.discard(tag)
    for tag in tags:
        selected().tags.add(tag)
    message('Tags updated')

def resolve_name(text):
    text = text.strip()
    try:
        return state.runtime.resolve(text)
    except (ValueError, KeyError):
        matches = [e for e in state.runtime.entities if e.components.get('name') == text]
        if len(matches) != 1:
            raise ValueError('Use a unique entity name or UUID') from None
        return matches[0]

def commit_parent():
    text = state.parent_field.buffer.text.strip()
    selected().parent = resolve_name(text) if text else None
    message('Parent updated')

def commit_relation():
    name, separator, text = state.relation_field.buffer.text.partition('=')
    if not separator or not name.strip():
        raise ValueError('Use relation=entity name or UUID')
    if text.strip():
        selected().relations[name.strip()] = resolve_name(text)
    else:
        selected().relations.pop(name.strip(), None)
    state.relation_field.buffer = TextBuffer()
    message('Relation updated')

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
    editor_roots = (state.background, state.camera, state.viewport,
                    state.header, state.hierarchy, state.inspector,
                    state.code_panel, state.status, state.zoom_label, *state.extra_panels)
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


def keyboard(event):
    if event[1] == "S" and event[2]:
        save()
        return True
    return False


def bind_actions():
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
                            (state.detach_button, detach_system), (state.add_button, add_component)):
        control.action = action
    for control, action in ((state.path_field, open_path), (state.tags_field, commit_tags),
                            (state.parent_field, commit_parent), (state.relation_field, commit_relation)):
        control.on_commit = action
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
    if diag:
        put(state.code_info, text=f"SyntaxError Ln {diag['line']}, Col {diag['column']}: {diag['message']}", ink=(248, 81, 73, 255))
    else:
        put(state.code_info, text=f"Ln {row+1}, Col {column+1} | Attach target: {selected().components.get('name', selected().id)} | Ctrl+S save", ink=MUTED)
