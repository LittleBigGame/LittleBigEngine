"""Inspector panel entity system."""

import ast
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from lbe.ui import bind_callbacks, put, contains, parse_box, PANEL, FIELD, INK, MUTED
from lbe.text import TextBuffer
from lbe.menus import open_menu
from lbe.project import template_path


state = entity.inherit("application_state")
selected = lambda: state.selected()
inspected = lambda: state.inspected() if hasattr(state, "inspected") else state.selected()
select = lambda target: state.select(target)
inspect_entity = lambda target: state.inspect_entity(target) if hasattr(state, "inspect_entity") else state.select(target)
message = lambda text: state.message(text)
open_system = lambda *args, **kwargs: state.open_system(*args, **kwargs)
open_panel = lambda *args, **kwargs: state.open_panel(*args, **kwargs)
save_editor_project = lambda: state.save_editor_project()
hierarchy_sync = lambda: state.hierarchy_sync()
new_source = lambda: state.new_source() if hasattr(state, "new_source") else None


def format_float_clean(f):
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
    try:
        return clean_repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def parse_value(text):
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        raise ValueError("Use a Python literal; put text in quotes") from None

def inspector_sync():
    ip = state.inspector
    if not ip.components.get("visible", True):
        put(state.name_label, visible=False)
        put(state.name_field, visible=False)
        put(state.selection_label, visible=False)
        put(state.identity_label, visible=False)
        put(state.add_child_button, visible=False)
        put(state.duplicate_button, visible=False)
        put(state.delete_button, visible=False)
        for chip in state.quick_preset_chips:
            put(chip, visible=False)
        put(state.quick_add_chip_btn, visible=False)
        put(state.divider_identity, visible=False)
        put(state.components_title, visible=False)
        put(state.add_comp_menu_button, visible=False)
        for lbl, fld in state.component_rows:
            put(lbl, visible=False)
            put(fld, visible=False)
        for btn in state.component_delete_buttons:
            put(btn, visible=False)
        put(state.inspector_scroll_track, visible=False)
        put(state.inspector_scroll_thumb, visible=False)
        put(state.add_name, visible=False)
        put(state.add_value, visible=False)
        put(state.add_button, visible=False)
        put(state.divider_components, visible=False)
        put(state.system_label, visible=False)
        put(state.add_system_button, visible=False)
        put(state.no_systems_label, visible=False)
        for b in state.system_rows:
            put(b, visible=False)
        for b in state.system_edit_buttons:
            put(b, visible=False)
        for b in state.system_detach_buttons:
            put(b, visible=False)
        put(state.divider_systems, visible=False)
        put(state.links_header, visible=False)
        put(state.tags_label, visible=False)
        put(state.tags_field, visible=False)
        put(state.parent_label, visible=False)
        put(state.parent_field, visible=False)
        put(state.relations_label, visible=False)
        put(state.relation_field, visible=False)
        put(state.link_add_button, visible=False)
        put(state.metadata, visible=False)
        for r_btn, u_btn in state.relation_rows:
            put(r_btn, visible=False)
            put(u_btn, visible=False)
        for edit_btn in state.relation_edit_buttons:
            put(edit_btn, visible=False)
        for button in state.child_rows:
            put(button, visible=False)
        return

    entity = inspected()
    items = tuple(entity.components.items())
    systems = tuple(entity.systems.items())
    children = tuple(entity.children)
    relations = tuple(entity.relations.items())
    i_pad = parse_box(ip.components.get("padding", (8, 12, 8, 12)))
    max_bottom = ip.y + ip.h - 6

    # Header: Name field
    ent_name = str(entity.components.get('name', ''))
    show_header = (ip.y + 54 <= max_bottom)
    put(state.name_label, visible=show_header, x=ip.x + 12, y=ip.y + 32, w=38, h=22, text='Name')
    put(state.name_field, visible=show_header, x=ip.x + 54, y=ip.y + 30, w=max(30, ip.w - 66), h=24)
    state.ui.set_text(state.name_field, ent_name)
    put(state.selection_label, visible=False, text=ent_name or str(entity.id))

    # Row 2: Identity label
    ent_display = ent_name or "Entity"
    show_id = (ip.y + 74 <= max_bottom)
    put(state.identity_label, visible=show_id, x=ip.x + 12, y=ip.y + 56, w=max(30, ip.w - 24), h=18,
        text=f'🔷 Entity: {ent_display}')

    # Hide removed action buttons and chip bar
    put(state.add_child_button, visible=False)
    put(state.duplicate_button, visible=False)
    put(state.delete_button, visible=False)
    for chip in state.quick_preset_chips:
        put(chip, visible=False)
    put(state.quick_add_chip_btn, visible=False)

    # Divider 1: between Identity and Components
    put(state.divider_identity, visible=(ip.y + 79 <= max_bottom), x=ip.x + 12, y=ip.y + 78, w=max(0, ip.w - 24), h=1)

    cur_y = ip.y + 86

    # SECTION 1: COMPONENTS (Collapsible)
    comp_collapsed = "components" in state.collapsed_sections
    show_comp_title = (cur_y + 22 <= max_bottom)
    put(state.components_title, visible=show_comp_title, x=ip.x + 12, y=cur_y, w=max(80, ip.w - 24 - 80), h=22,
        text=f"{'▶' if comp_collapsed else '▼'} COMPONENTS ({len(items)})")
    comp_btn_w = 70
    put(state.add_comp_menu_button, visible=show_comp_title, x=ip.x + ip.w - 12 - comp_btn_w, y=cur_y, w=comp_btn_w, h=22, text='+ Add')
    cur_y += 26

    sys_collapsed = "systems" in state.collapsed_sections
    links_collapsed = "links" in state.collapsed_sections

    num_sys_rows = min(len(systems), 6) if (systems and not sys_collapsed) else 0
    sys_content_h = (18 if not systems else num_sys_rows * 26 + 4) if not sys_collapsed else 0
    sys_section_h = 26 + sys_content_h + (6 if not sys_collapsed else 0)

    num_rel_rows = min(len(relations), 3) if (relations and not links_collapsed) else 0
    rel_rows_h = (num_rel_rows * 24 + 4) if (relations and not links_collapsed) else 0
    num_child_rows = min(3, (len(children) + 2) // 3) if (children and not links_collapsed) else 0
    child_h = (num_child_rows * 24 + 4) if (children and not links_collapsed) else 0
    links_content_h = (30 * 3 + rel_rows_h + 22 + child_h + 8) if not links_collapsed else 0
    links_section_h = 26 + links_content_h

    bottom_h = sys_section_h + links_section_h + 8

    if comp_collapsed:
        for lbl, fld in state.component_rows:
            put(lbl, visible=False)
            put(fld, visible=False)
        for btn in state.component_delete_buttons:
            put(btn, visible=False)
        put(state.inspector_scroll_track, visible=False)
        put(state.inspector_scroll_thumb, visible=False)
        put(state.add_name, visible=False)
        put(state.add_value, visible=False)
        put(state.add_button, visible=False)
        put(state.divider_components, visible=False)
    else:
        comp_start_y = cur_y
        avail_comp_h = max(25, ip.h - (comp_start_y - ip.y) - bottom_h)
        capacity = max(1, int(avail_comp_h // 25))
        max_scroll = max(0, len(items) - capacity)
        state.inspector.item_count = len(items)
        state.inspector.capacity = capacity
        put(state.inspector, scroll=max(0, min(state.inspector.scroll, max_scroll)))

        while len(state.component_rows) < capacity:
            n = len(state.component_rows)
            label = state.ui.field(state.inspector, f'ComponentLabel{n}', '', color=PANEL, ink=MUTED)
            field = state.ui.field(state.inspector, f'ComponentField{n}', '')
            state.component_rows.append((label, field))

        has_comp_scroll = len(items) > capacity and capacity > 0
        sb_w = 10 if has_comp_scroll else 0

        for btn in state.component_delete_buttons:
            put(btn, visible=False)

        for index, (label, field) in enumerate(state.component_rows):
            source = index + state.inspector.scroll
            shown = index < capacity and source < len(items)
            put(label, visible=shown)
            put(field, visible=shown)
            if not shown:
                continue
            key, value = items[source]
            from lbe.assets import AssetRef, ASSET_ICONS
            is_asset = isinstance(value, AssetRef)
            is_entity = hasattr(value, "components") and hasattr(value, "id")
            editable = type(value) in (int, float, bool, str, tuple, list, dict, type(None)) and not is_asset and not is_entity
            y = comp_start_y + index * 25
            lbl_w = min(110, max(50, (ip.w - 24 - 8) // 3))
            field_w = max(40, ip.w - 12 - lbl_w - 6 - sb_w - 12)
            put(label, x=ip.x + 12, y=y + 1, w=lbl_w, h=23)
            if is_asset:
                icon = ASSET_ICONS.get(value.type, "📦")
                display_val = f" {icon} {value.type.capitalize()}: {(state.runtime.assets.registry.get(value.id) or {}).get('name', value.name or 'Asset')} "
                put(field, x=ip.x + 12 + lbl_w + 6, y=y, w=field_w, h=23, readonly=True,
                    color=(35, 55, 75), normal_color=(35, 55, 75), hover_color=(50, 80, 110),
                    ink=(220, 240, 255))
            elif is_entity:
                ename = value.components.get("name") or "Entity"
                display_val = f" 🔷 Entity: {ename} "
                put(field, x=ip.x + 12 + lbl_w + 6, y=y, w=field_w, h=23, readonly=True,
                    color=(35, 55, 75), normal_color=(35, 55, 75), hover_color=(50, 80, 110),
                    ink=(220, 240, 255))
            else:
                put(field, x=ip.x + 12 + lbl_w + 6, y=y, w=field_w, h=23, readonly=not editable,
                    color=FIELD, normal_color=FIELD, ink=INK)
            if field.components.get('component_key') != key or field.relations.get('target') is not entity:
                if state.ui.focused in (field, label):
                    del state.app.relations['focus']
            field.component_key = key
            field.relations['target'] = entity
            label.component_key = key
            label.relations['target'] = entity
            field.on_commit = lambda f=field: commit_component(f)
            field.on_click = component_click
            label.on_commit = lambda lbl=label: commit_component_key(lbl)
            label.on_click = component_click
            state.ui.set_text(label, key)
            state.ui.set_text(field, display_val if (is_asset or is_entity) else safe_repr(value))

        if has_comp_scroll:
            track_x = ip.x + ip.w - 10
            track_y = comp_start_y
            track_w = 6
            track_h = capacity * 25
            put(state.inspector_scroll_track, visible=True, x=track_x, y=track_y, w=track_w, h=track_h)
            thumb_h = max(16, int(track_h * (capacity / len(items))))
            travel = max(1, track_h - thumb_h)
            thumb_y = track_y + int(travel * (state.inspector.scroll / max_scroll)) if max_scroll > 0 else track_y
            put(state.inspector_scroll_thumb, visible=True, x=track_x, y=thumb_y, w=track_w, h=thumb_h)
        else:
            put(state.inspector_scroll_track, visible=False)
            put(state.inspector_scroll_thumb, visible=False)

        cur_y = comp_start_y + capacity * 25 + 4

        # Hide bottom add component row
        put(state.add_name, visible=False)
        put(state.add_value, visible=False)
        put(state.add_button, visible=False)

        # Divider 2: between Components and Systems
        put(state.divider_components, visible=(cur_y + 1 <= max_bottom), x=ip.x + 12, y=cur_y, w=max(0, ip.w - 24), h=1)
        cur_y += 6

    # SECTION 2: SYSTEMS (Collapsible)
    show_sys_title = (cur_y + 22 <= max_bottom)
    put(state.system_label, visible=show_sys_title, x=ip.x + 12, y=cur_y, w=max(80, ip.w - 24 - 80), h=22,
        text=f"{'▶' if sys_collapsed else '▼'} SYSTEMS ({len(systems)})")
    sys_btn_w = len('+ Attach') * state.ui.pitch + 16
    put(state.add_system_button, visible=show_sys_title, x=ip.x + ip.w - 12 - sys_btn_w, y=cur_y, w=sys_btn_w, h=22, text='+ Attach')
    cur_y += 26

    if sys_collapsed:
        put(state.no_systems_label, visible=False)
        for b in state.system_rows:
            put(b, visible=False)
        for b in state.system_edit_buttons:
            put(b, visible=False)
        for b in state.system_detach_buttons:
            put(b, visible=False)
        put(state.divider_systems, visible=False)
    else:
        if not systems:
            show_no_sys = (cur_y + 20 <= max_bottom)
            put(state.no_systems_label, visible=show_no_sys, x=ip.x + 12, y=cur_y, w=max(30, ip.w - 24), h=20, text='No systems attached')
            cur_y += 22
            for b in state.system_rows:
                put(b, visible=False)
            for b in state.system_edit_buttons:
                put(b, visible=False)
            for b in state.system_detach_buttons:
                put(b, visible=False)
        else:
            put(state.no_systems_label, visible=False)
            max_sys = min(len(systems), 6)
            while len(state.system_rows) < max_sys:
                idx = len(state.system_rows)
                s_btn = state.ui.button(state.inspector, f'System{idx}', '', lambda: None)
                e_btn = state.ui.button(state.inspector, f'SystemEdit{idx}', 'Edit', lambda: None)
                d_btn = state.ui.button(state.inspector, f'SystemDel{idx}', 'x', lambda: None, color=(60, 30, 35))
                state.system_rows.append(s_btn)
                state.system_edit_buttons.append(e_btn)
                state.system_detach_buttons.append(d_btn)

            while len(state.system_edit_buttons) < len(state.system_rows):
                idx = len(state.system_edit_buttons)
                e_btn = state.ui.button(state.inspector, f'SystemEdit{idx}', 'Edit', lambda: None)
                d_btn = state.ui.button(state.inspector, f'SystemDel{idx}', 'x', lambda: None, color=(60, 30, 35))
                state.system_edit_buttons.append(e_btn)
                state.system_detach_buttons.append(d_btn)

            btn_edit_w = 52
            s_w = max(40, ip.w - 24 - btn_edit_w - 6)

            for index in range(len(state.system_rows)):
                s_btn = state.system_rows[index]
                e_btn = state.system_edit_buttons[index]
                d_btn = state.system_detach_buttons[index]
                put(d_btn, visible=False)
                shown = (index < max_sys) and (cur_y + 24 <= max_bottom)
                put(s_btn, visible=shown)
                put(e_btn, visible=shown)
                if shown:
                    name, instance = systems[index]
                    s_title = name + (' !' if instance.errors else '')
                    s_ink = (255, 120, 120) if instance.errors else INK
                    put(s_btn, x=ip.x + 12, y=cur_y, w=s_w, h=24, text=s_title, ink=s_ink)
                    put(e_btn, x=ip.x + 12 + s_w + 4, y=cur_y, w=btn_edit_w, h=24, text='Edit')
                    s_btn.system_key = (entity.id, name)
                    s_btn.action = lambda e=entity, n=name: open_system(e, n)
                    e_btn.action = lambda e=entity, n=name: open_system(e, n)
                    cur_y += 26
            cur_y += 4

        # Divider 3: between Systems and Links
        put(state.divider_systems, visible=(cur_y + 1 <= max_bottom), x=ip.x + 12, y=cur_y, w=max(0, ip.w - 24), h=1)
        cur_y += 6

    # SECTION 3: LINKS & HIERARCHY (Collapsible)
    show_links_title = (cur_y + 22 <= max_bottom)
    put(state.links_header, visible=show_links_title, x=ip.x + 12, y=cur_y, w=max(100, ip.w - 24), h=22,
        text=f"{'▶' if links_collapsed else '▼'} LINKS & HIERARCHY")
    cur_y += 26

    if links_collapsed or not show_links_title:
        put(state.tags_label, visible=False)
        put(state.tags_field, visible=False)
        put(state.parent_label, visible=False)
        put(state.parent_field, visible=False)
        put(state.relations_label, visible=False)
        put(state.relation_field, visible=False)
        put(state.link_add_button, visible=False)
        put(state.metadata, visible=False)
        for r_btn, u_btn in state.relation_rows:
            put(r_btn, visible=False)
            put(u_btn, visible=False)
        for edit_btn in state.relation_edit_buttons:
            put(edit_btn, visible=False)
        for button in state.child_rows:
            put(button, visible=False)
    else:
        # Tags row
        show_tags = (cur_y + 26 <= max_bottom)
        put(state.tags_label, visible=show_tags, x=ip.x + 12, y=cur_y + 4, w=60, h=22)
        put(state.tags_field, visible=show_tags, x=ip.x + 76, y=cur_y, w=max(30, ip.w - 88), h=26)
        if show_tags:
            state.ui.set_text(state.tags_field, ', '.join(entity.tags))
            cur_y += 30

        # Parent row
        show_parent = (cur_y + 26 <= max_bottom)
        put(state.parent_label, visible=show_parent, x=ip.x + 12, y=cur_y + 4, w=60, h=22)
        put(state.parent_field, visible=show_parent, x=ip.x + 76, y=cur_y, w=max(30, ip.w - 88), h=26)
        if show_parent:
            state.ui.set_text(state.parent_field, str(entity.parent.components.get('name', entity.parent.id)) if entity.parent else '')
            cur_y += 30

        # Link row
        show_link_row = (cur_y + 26 <= max_bottom)
        put(state.relations_label, visible=show_link_row, x=ip.x + 12, y=cur_y + 4, w=60, h=22)
        put(state.relation_field, visible=show_link_row, x=ip.x + 76, y=cur_y, w=max(30, ip.w - 88 - 36), h=26)
        put(state.link_add_button, visible=show_link_row, x=ip.x + ip.w - 42, y=cur_y, w=30, h=26, text='+')
        if show_link_row:
            cur_y += 30

        # Existing relations list
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
            shown = (index < num_rel_rows) and (cur_y + 22 <= max_bottom)
            put(r_btn, visible=shown)
            put(u_btn, visible=False)
            edit_btn = state.relation_edit_buttons[index]
            put(edit_btn, visible=shown)
            if shown:
                r_name, r_target = relations[index]
                tgt_name = str(r_target.components.get('name', str(r_target.id)[:8]))
                btn_edit_w = 40
                r_w = max(40, ip.w - 24 - btn_edit_w - 6)
                put(r_btn, x=ip.x + 12, y=cur_y, w=r_w, h=22, text=f"{r_name} -> {tgt_name}")
                put(edit_btn, x=ip.x + 12 + r_w + 4, y=cur_y, w=btn_edit_w, h=22, text='Edit')
                r_btn.action = lambda t=r_target: select(t)
                edit_btn.action = lambda n=r_name, tn=tgt_name: start_edit_link(n, tn)
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

        # Metadata
        show_meta = (cur_y + 18 <= max_bottom)
        put(state.metadata, visible=show_meta, x=ip.x + 12, y=cur_y, w=max(0, ip.w - 24), h=18,
            text=f'{len(children)} children | {len(relations)} relations')
        if show_meta:
            cur_y += 22

        # Children chips
        if children and cur_y + 22 <= max_bottom:
            max_children = min(len(children), 9)
            while len(state.child_rows) < max_children:
                idx = len(state.child_rows)
                btn = state.ui.button(state.inspector, f'Child{idx}', '', lambda: None)
                state.child_rows.append(btn)
            btn_w = max(60, (ip.w - 24 - 12) // 3)
            for index, button in enumerate(state.child_rows):
                row_idx = index // 3
                shown = (index < max_children) and (cur_y + (row_idx + 1) * 24 <= max_bottom)
                put(button, visible=shown)
                if shown:
                    child = children[index]
                    c_name = str(child.components.get('name', str(child.id)[:8]))
                    col = index % 3
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
    if field.buffer.text == safe_repr(target.components[key]):
        return
    target.components[key] = parse_value(field.buffer.text)
    message(f'Updated {key}')
    inspector_sync()

def save_component_changes(target, before):
    try:
        save_editor_project()
    except Exception:
        target.components.clear()
        target.components.update(before)
        raise


def add_component():
    ent = inspected()
    before = dict(ent.components)
    renaming_key = state.add_name.components.pop("renaming_key", None)
    saving_preset = state.add_name.components.pop("saving_preset", False)
    name = state.add_name.buffer.text.strip()
    if not name:
        raise ValueError('Enter a component name')
    val_text = state.add_value.buffer.text.strip() or '0'
    val = parse_value(val_text)

    if saving_preset:
        pin_to_quick_bar(name, val)
        state.add_name.buffer = TextBuffer()
        state.add_value.buffer = TextBuffer()
        return

    if renaming_key:
        if renaming_key != name and name in ent.components:
            raise ValueError(f"Component '{name}' already exists")
        if renaming_key != name:
            ent.components.pop(renaming_key, None)
        ent.components[name] = val
        message(f"Renamed component '{renaming_key}' -> '{name}'")
    else:
        ent.components[name] = val
        message(f"Added component '{name}'")
    state.add_name.buffer = TextBuffer()
    state.add_value.buffer = TextBuffer()
    save_component_changes(ent, before)
    inspector_sync()

def commit_tags():
    ent = inspected()
    renaming_tag = state.tags_field.components.pop("renaming_tag", None)
    tags = {tag.strip() for tag in state.tags_field.buffer.text.split(',') if tag.strip()}
    for tag in set(ent.tags) - tags:
        ent.tags.discard(tag)
    for tag in tags:
        ent.tags.add(tag)
    save_editor_project()
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
    inspected().parent = resolve_name(text) if text else None
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
                inspected().relations.pop(editing_rel, None)
            inspected().relations[name] = target
            tgt_name = str(target.components.get('name', str(target.id)[:8]))
            message(f"Linked '{name}' -> '{tgt_name}'")
        else:
            rel_to_remove = editing_rel or name
            inspected().relations.pop(rel_to_remove, None)
            message(f"Unlinked relation '{rel_to_remove}'")
    else:
        target = resolve_name(raw)
        tgt_name = str(target.components.get('name', str(target.id)[:8]))
        name = editing_rel or tgt_name.lower().replace(" ", "_")
        inspected().relations[name] = target
        message(f"Linked '{name}' -> '{tgt_name}'")
    state.relation_field.buffer = TextBuffer()
    inspector_sync()

def start_edit_link(name, tgt_name=None):
    ent = inspected()
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
    source = inspected()
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
    ent = inspected()
    if name:
        ent.components['name'] = name
        message(f"Renamed entity to '{name}'")
    else:
        ent.components.pop('name', None)
        message("Cleared entity name")
    hierarchy_sync()
    inspector_sync()


def inspector_add_child():
    parent = inspected()
    c_name = f"Child_{len(parent.children) + 1}"
    child = state.runtime.create(parent=parent, name=c_name)
    inspect_entity(child)
    message(f"Added child '{c_name}'")
    hierarchy_sync()
    inspector_sync()


def inspector_duplicate_entity():
    ent = inspected()
    if ent is state.app or ent is state.game or any(ent is r for r in (state.header, state.hierarchy, state.inspector, state.code_panel, state.status, state.viewport)):
        message("Cannot duplicate engine or editor root")
        return
    parent = ent.parent or state.game
    orig_name = str(ent.components.get('name', 'Entity'))
    new_name = orig_name + "_copy"
    comps = deepcopy(dict(ent.components))
    comps['name'] = new_name
    dup = state.runtime.create(parent=parent, tags=list(ent.tags), components=comps)
    inspect_entity(dup)
    message(f"Duplicated '{orig_name}' as '{new_name}'")
    hierarchy_sync()
    inspector_sync()


def inspector_delete_entity():
    ent = inspected()
    if ent is state.app or ent is state.game or any(ent is r for r in (state.header, state.hierarchy, state.inspector, state.code_panel, state.status, state.viewport)):
        message("Cannot delete engine or editor root")
        return
    parent = ent.parent or state.game
    ent_name = str(ent.components.get('name', str(ent.id)[:8]))
    ent.destroy()
    inspect_entity(parent)
    message(f"Deleted entity '{ent_name}'")
    hierarchy_sync()
    inspector_sync()


def delete_component(key):
    ent = inspected()
    if key in ent.components:
        del ent.components[key]
        if state.ui.focused and getattr(state.ui.focused, "component_key", None) == key:
            del state.app.relations['focus']
        message(f"Deleted component '{key}'")
        inspector_sync()


def unlink_relation(name):
    ent = inspected()
    if name in ent.relations:
        del ent.relations[name]
        if state.relation_field.components.get("editing_relation") == name:
            state.relation_field.components.pop("editing_relation", None)
            state.relation_field.buffer = TextBuffer()
        message(f"Unlinked relation '{name}'")
        inspector_sync()


def focus_component_value(key):
    for lbl, fld in state.component_rows:
        if fld.visible and getattr(fld, 'component_key', None) == key:
            state.ui.focus(fld)
            fld.buffer.anchor = 0
            fld.buffer.cursor = len(fld.buffer.text)
            break


def quick_add_pos():
    ent = inspected()
    ent.components.setdefault("x", 0.0)
    ent.components.setdefault("y", 0.0)
    message("Added Pos (x, y)")
    save_editor_project()
    inspector_sync()
    focus_component_value("x")


def quick_add_size():
    ent = inspected()
    ent.components.setdefault("w", 32.0)
    ent.components.setdefault("h", 32.0)
    message("Added Size (w, h)")
    save_editor_project()
    inspector_sync()
    focus_component_value("w")


def quick_add_vel():
    ent = inspected()
    ent.components.setdefault("vx", 0.0)
    ent.components.setdefault("vy", 0.0)
    message("Added Vel (vx, vy)")
    save_editor_project()
    inspector_sync()
    focus_component_value("vx")


def quick_add_color():
    ent = inspected()
    ent.components.setdefault("color", (200, 200, 200))
    message("Added Color")
    save_editor_project()
    inspector_sync()
    focus_component_value("color")


def quick_add_speed():
    ent = inspected()
    ent.components.setdefault("speed", 100.0)
    message("Added Speed")
    save_editor_project()
    inspector_sync()
    focus_component_value("speed")


def add_custom_component():
    ent = inspected()
    base = "custom_component"
    key = base
    i = 1
    while key in ent.components:
        key = f"{base}_{i}"
        i += 1
    ent.components[key] = 0
    save_editor_project()
    inspector_sync()
    start_rename_component(ent, key)


def context_add_component(target):
    select(target)
    add_custom_component()


def commit_component_key(lbl):
    target = lbl.relations.get('target', inspected())
    old_key = lbl.components.pop("renaming_key", getattr(lbl, "component_key", None))
    new_key = lbl.buffer.text.strip()
    if not new_key:
        state.ui.set_text(lbl, old_key or "")
        return
    if old_key and new_key != old_key and target and target.alive:
        if new_key in target.components:
            raise ValueError(f"Component '{new_key}' already exists")
        before = dict(target.components)
        val = target.components.pop(old_key)
        target.components[new_key] = val
        message(f"Renamed component '{old_key}' -> '{new_key}'")
        save_component_changes(target, before)
        inspector_sync()
        focus_component_value(new_key)


def open_add_component_menu(x=None, y=None, target=None):
    ent = target or inspected()
    btn = getattr(state, "add_comp_menu_button", None)
    if x is None or y is None:
        mouse = getattr(state.ui, "mouse_pos", None)
        if mouse and (btn is None or not contains(btn, *mouse)):
            x, y = mouse
        elif btn is not None:
            x, y = btn.x, btn.y + btn.h + 2
        else:
            x, y = 100, 100
    actions = [
        dict(label="+ Transform / Pos (x, y)", run=lambda e: (select(ent), quick_add_pos())),
        dict(label="+ Size (w, h)", run=lambda e: (select(ent), quick_add_size())),
        dict(label="+ Velocity (vx, vy)", run=lambda e: (select(ent), quick_add_vel())),
        dict(label="+ Color (r, g, b)", run=lambda e: (select(ent), quick_add_color())),
        dict(label="+ Speed", run=lambda e: (select(ent), quick_add_speed())),
        None,
        dict(label="+ Custom Component...", run=lambda e: (select(ent), add_custom_component())),
    ]
    open_menu(state.ui, ent, x, y, actions=actions)


def change_component_type(ent, comp, target_type):
    val = ent.components.get(comp)
    new_val = None
    try:
        if target_type == "float":
            if isinstance(val, (int, float, str)):
                new_val = float(val)
            else:
                new_val = 0.0
        elif target_type == "int":
            if isinstance(val, (int, float, str)):
                new_val = int(float(val))
            else:
                new_val = 0
        elif target_type == "str":
            new_val = str(val) if val is not None else ""
        elif target_type == "bool":
            new_val = bool(val)
        elif target_type == "tuple":
            if isinstance(val, (tuple, list)):
                new_val = tuple(val)
            elif val is not None:
                new_val = (val,)
            else:
                new_val = (0.0, 0.0)
        elif target_type == "list":
            if isinstance(val, (tuple, list)):
                new_val = list(val)
            elif val is not None:
                new_val = [val]
            else:
                new_val = [0.0, 0.0]
        elif target_type == "dict":
            new_val = dict(val)
        elif target_type == "AssetRef":
            from lbe.assets import AssetRef
            reg = getattr(state.runtime.assets, "registry", None)
            ref = None
            if reg:
                ref = reg.get_ref(val)
            if ref is None:
                raise ValueError("Select a registered asset reference")
            new_val = ref
        elif target_type == "NoneType":
            new_val = None
        else:
            new_val = val
    except (TypeError, ValueError) as error:
        raise ValueError(f"Cannot convert '{comp}' to {target_type}: {error}") from None

    before = dict(ent.components)
    ent.components[comp] = new_val
    message(f"Changed '{comp}' type to {target_type}")
    save_component_changes(ent, before)
    inspector_sync()
    focus_component_value(comp)


def open_change_type_menu(ent, comp):
    current_val = ent.components.get(comp)
    current_type = type(current_val).__name__
    types = [
        ("float", "float (e.g. 0.0)"),
        ("int", "int (e.g. 0)"),
        ("str", "str (text)"),
        ("bool", "bool (True/False)"),
        ("AssetRef", "Asset (project file reference)"),
        ("tuple", "tuple (e.g. (1, 2))"),
        ("list", "list (e.g. [1, 2])"),
        ("dict", "dict (e.g. {})"),
        ("NoneType", "None"),
    ]
    actions = []
    for t_id, label in types:
        is_current = (current_type == t_id)
        indicator = "> " if is_current else "   "
        actions.append(dict(
            label=f"{indicator}{label}",
            run=lambda _, t=t_id: change_component_type(ent, comp, t)
        ))
    mouse = getattr(state.ui, "mouse_pos", None)
    if mouse:
        x, y = mouse
    else:
        x, y = state.inspector.x + 20, state.inspector.y + 40
    open_menu(state.ui, ent, x, y, actions=actions)


def open_attach_system_menu():
    ent = inspected()
    candidates = []
    # Project directory
    if state.project and state.project.exists():
        for p in sorted(state.project.glob("*.py")):
            if p.name in ("ui.py", "app.py", "hierarchy.py", "inspector.py", "text_area.py", "code_editor.py"):
                continue
            candidates.append(p)
    # Also check template directory
    try:
        from lbe.project import template_path
        tpl = template_path("editor")
        if tpl.exists():
            for p in sorted(tpl.glob("*.py")):
                if p.name in ("ui.py", "app.py", "hierarchy.py", "inspector.py", "text_area.py", "code_editor.py"):
                    continue
                if not any(c.name == p.name for c in candidates):
                    candidates.append(p)
    except Exception:
        pass

    actions = []
    for p in candidates:
        name = p.stem
        already = name in ent.systems
        if not already:
            actions.append(dict(label=f"+ {name} ({p.name})", run=lambda e, path=p: attach_system_to_entity(ent, path)))
        else:
            actions.append(dict(label=f"{name} (attached)", run=None))

    if actions:
        actions.append(None)
    actions.append(dict(label="+ New System Script...", run=lambda e: prompt_new_system(ent)))

    open_menu(state.ui, ent, state.add_system_button.x, state.add_system_button.y + state.add_system_button.h + 2, actions=actions)


def prompt_new_system(ent):
    new_source()
    state.code.relations['owner'] = ent
    message(f"New system for {ent.components.get('name', ent.id)}: choose filename, edit, then Attach")


def attach_system_to_entity(ent, path):
    try:
        definition = state.runtime.assets.system(path)
        stem = path.stem
        if stem in ent.systems:
            instance = ent.systems.reload(stem, definition)
        else:
            instance = ent.systems.attach(stem, definition)
        save_editor_project()
        inspector_sync()
        if instance.errors:
            message(f"Attached {stem} with errors: {instance.errors[-1].message}")
        else:
            message(f"Attached {stem} to {ent.components.get('name', ent.id)}")
    except Exception as err:
        message(f"Failed to attach {path.stem}: {err}")


def detach_system_from_entity(ent, name):
    if ent is state.app and name in ('app', 'ui'):
        message('The active editor cannot detach itself')
        return
    try:
        del ent.systems[name]
        if state.code.relations.get('owner') is ent and state.code.components.get('system_name') == name:
            del state.code.relations['owner']
            state.code.components.pop('system_name', None)
        save_editor_project()
        inspector_sync()
        message(f"Detached system '{name}' from {ent.components.get('name', ent.id)}")
    except Exception as err:
        message(f"Failed to detach {name}: {err}")


def toggle_section(name):
    if name in state.collapsed_sections:
        state.collapsed_sections.remove(name)
    else:
        state.collapsed_sections.add(name)
    inspector_sync()


def open_add_chip_menu():
    ent = inspected()
    actions = [
        dict(label="+ Add custom component to entity...", run=lambda _: context_add_component(ent)),
        dict(label="+ Create new quick preset...", run=lambda _: prompt_add_preset()),
    ]
    unpinned = [k for k in ent.components if not any(p[0] == k for p in state.quick_component_presets)]
    if unpinned:
        actions.append(None)
        for k in unpinned:
            actions.append(dict(label=f"Pin '{k}' to quick-bar", run=lambda _, comp=k: pin_to_quick_bar(comp, ent.components.get(comp))))
    open_menu(state.ui, ent, state.quick_add_chip_btn.x, state.quick_add_chip_btn.y + state.quick_add_chip_btn.h + 2, actions=actions)


def prompt_add_preset():
    state.add_name.buffer = TextBuffer("custom")
    state.add_value.buffer = TextBuffer("1.0")
    state.add_name.components["saving_preset"] = True
    state.ui.focus(state.add_name)
    message("Creating quick preset: type component name and default value, then press Enter")


def pin_to_quick_bar(name, default_val):
    if not any(p[0] == name for p in state.quick_component_presets):
        state.quick_component_presets.append((name, {name: default_val}))
        message(f"Pinned '{name}' to quick-bar")
        inspector_sync()


def apply_quick_preset(name):
    ent = inspected()
    for p_name, p_data in state.quick_component_presets:
        if p_name == name:
            for k, v in p_data.items():
                ent.components.setdefault(k, v)
            message(f"Added {name} ({', '.join(p_data.keys())})")
            inspector_sync()
            return


def remove_quick_preset(name):
    state.quick_component_presets = [p for p in state.quick_component_presets if p[0] != name]
    message(f"Removed '{name}' from quick-bar")
    inspector_sync()


def start_rename_component(ent, old_key):
    for lbl, fld in state.component_rows:
        if lbl.visible and getattr(lbl, 'component_key', None) == old_key:
            state.ui.focus(lbl)
            lbl.buffer.anchor = 0
            lbl.buffer.cursor = len(lbl.buffer.text)
            lbl.components["renaming_key"] = old_key
            message(f"Renaming component '{old_key}': type new name and press Enter")
            return
    state.add_name.buffer = TextBuffer(old_key)
    state.add_value.buffer = TextBuffer(safe_repr(ent.components.get(old_key)))
    state.add_name.components["renaming_key"] = old_key
    state.ui.focus(state.add_name)
    message(f"Renaming component '{old_key}': type new name and press Enter")


def start_rename_tag(ent, old_tag):
    state.tags_field.components["renaming_tag"] = old_tag
    state.ui.focus(state.tags_field)
    message(f"Renaming tag '{old_tag}': edit in Tags box and press Enter")


def remove_tag(ent, tag):
    ent.tags.discard(tag)
    save_editor_project()
    inspector_sync()
    message(f"Removed tag '{tag}'")


def start_add_tag(ent):
    state.ui.focus(state.tags_field)
    message("Type tag name and press Enter to save")






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



def component_click(control, event):
    if len(event) > 3 and event[3] in (2, 4):
        return False
    target = control.relations.get("target")
    key = getattr(control, "component_key", None)
    if target and key:
        from lbe.assets import AssetRef
        val = target.components.get(key)
        if isinstance(val, AssetRef):
            open_asset_picker_menu(target, key)
            return True
    return False


def open_asset_picker_menu(ent, comp):
    current_val = ent.components.get(comp)
    reg = getattr(state.runtime.assets, "registry", None)
    from lbe.assets import ASSET_ICONS, AssetRef
    actions = []
    if reg:
        for uid, entry in sorted(reg.entries(), key=lambda x: (x[1]["type"], x[1]["name"].lower())):
            icon = ASSET_ICONS.get(entry["type"], "📦")
            is_active = (isinstance(current_val, AssetRef) and current_val.id == uid)
            pref = "> " if is_active else "   "
            actions.append(dict(
                label=f"{pref}{icon} {entry['name']}",
                run=lambda _, u=uid, e=entry: assign_asset_ref(ent, comp, u, e)
            ))
    if actions:
        actions.append(None)
    if hasattr(current_val, "id") and hasattr(state, "locate_in_file_explorer"):
        actions.append(dict(label="Locate in File Explorer", run=lambda _: state.locate_in_file_explorer(current_val.id)))
    actions.append(dict(label="Clear reference", run=lambda _: clear_asset_ref(ent, comp)))
    mouse = getattr(state.ui, "mouse_pos", None)
    x, y = mouse if mouse else (state.inspector.x + 20, state.inspector.y + 40)
    open_menu(state.ui, ent, x, y, actions=actions)


def assign_asset_ref(ent, comp, uid, entry):
    from lbe.assets import AssetRef
    ent.components[comp] = AssetRef(id=uid, type=entry["type"], name=entry["name"])
    save_editor_project()
    inspector_sync()
    message(f"Set '{comp}' to {entry['name']}")


def clear_asset_ref(ent, comp):
    ent.components[comp] = None
    save_editor_project()
    inspector_sync()
    message(f"Cleared '{comp}'")

def start():
    global _release
    _release = bind_callbacks(system, state, {
        "inspector_sync": inspector_sync,
        "format_float_clean": format_float_clean,
        "clean_repr": clean_repr,
        "safe_repr": safe_repr,
        "parse_value": parse_value,
        "commit_component": commit_component,
        "add_component": add_component,
        "commit_tags": commit_tags,
        "resolve_name": resolve_name,
        "commit_parent": commit_parent,
        "commit_relation": commit_relation,
        "start_edit_link": start_edit_link,
        "quick_link_to": quick_link_to,
        "commit_name": commit_name,
        "inspector_add_child": inspector_add_child,
        "inspector_duplicate_entity": inspector_duplicate_entity,
        "inspector_delete_entity": inspector_delete_entity,
        "delete_component": delete_component,
        "unlink_relation": unlink_relation,
        "focus_component_value": focus_component_value,
        "quick_add_pos": quick_add_pos,
        "quick_add_size": quick_add_size,
        "quick_add_vel": quick_add_vel,
        "quick_add_color": quick_add_color,
        "quick_add_speed": quick_add_speed,
        "add_custom_component": add_custom_component,
        "context_add_component": context_add_component,
        "commit_component_key": commit_component_key,
        "open_add_component_menu": open_add_component_menu,
        "open_attach_system_menu": open_attach_system_menu,
        "prompt_new_system": prompt_new_system,
        "attach_system_to_entity": attach_system_to_entity,
        "detach_system_from_entity": detach_system_from_entity,
        "toggle_section": toggle_section,
        "open_add_chip_menu": open_add_chip_menu,
        "prompt_add_preset": prompt_add_preset,
        "pin_to_quick_bar": pin_to_quick_bar,
        "apply_quick_preset": apply_quick_preset,
        "remove_quick_preset": remove_quick_preset,
        "start_rename_component": start_rename_component,
        "start_rename_tag": start_rename_tag,
        "remove_tag": remove_tag,
        "start_add_tag": start_add_tag,
        "change_component_type": change_component_type,
        "open_change_type_menu": open_change_type_menu,
        "inspector_scroll_drag": inspector_scroll_drag,
        "inspector_track_click": inspector_track_click,
        "component_click": component_click,
    })


def update(dt):
    inspector_sync()


def stop():
    release = globals().get("_release")
    if release:
        release()
