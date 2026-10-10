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

def item_presentation(owner, item):
    """Describe the actual stored record, not a parallel inspector model."""
    from dataclasses import fields, is_dataclass
    from lbe import Component, InheritedComponent, Tag, Relation, Parent
    from lbe.scripts import ScriptInstance
    from lbe.systems import SystemInstance
    if isinstance(item, InheritedComponent):
        symbol, colour = "↳", (180, 145, 235)
    elif isinstance(item, Component):
        symbol, colour = "◆", (85, 190, 215)
    elif isinstance(item, Tag):
        return "#", (100, 205, 140), "Tag", "membership", False
    elif isinstance(item, (Parent, Relation)):
        target = state.runtime._entities.get(item.target)
        display = str(target.items.get_value("name", "Entity")) if target else "Missing Entity"
        return ("↑" if isinstance(item, Parent) else "↔"), (235, 190, 100), type(item).__name__, display, False
    elif isinstance(item, SystemInstance):
        script = isinstance(item, ScriptInstance)
        source = item.definition.path or "inline source"
        display = str(source).replace("\\", "/").rsplit("/", 1)[-1]
        if item.errors:
            display += " ! error"
        elif item.definition.source is None:
            display = "Unlinked: " + display
        return ("▶" if script else "λ"), ((185, 145, 230) if script else (235, 165, 90)), ("Script" if script else "System"), display, False
    else:
        data = ({f.name: getattr(item, f.name) for f in fields(item) if f.name not in ("id", "name")}
                if is_dataclass(item) else item)
        editable = is_dataclass(item) and isinstance(data, dict)
        return "◇", (170, 185, 205), type(item).__name__, safe_repr(data), editable
    try:
        value = owner.items.value(item.id)
    except (KeyError, TypeError, ValueError) as error:
        return symbol, (240, 115, 115), type(item).__name__, f"Unresolved: {error}", False
    from lbe.assets import AssetRef
    if isinstance(value, AssetRef):
        display = value.name or "Asset"
        icon = state.runtime.assets.registry.icon(value.id)
        return symbol, colour, f"{type(item).__name__} · Asset", icon + " " + display, False
    if hasattr(value, "items") and hasattr(value, "id"):
        return symbol, colour, f"{type(item).__name__} · Entity", str(value.items.get_value("name", "Entity")), False
    editable = type(value) in (int, float, bool, str, tuple, list, dict, type(None))
    return symbol, colour, f"{type(item).__name__} · {type(value).__name__}", safe_repr(value), editable


def commit_item_name(control):
    target = control.items.require_target("target")
    identity = control.items.require_value("item_id")
    previous = target[identity]
    name = control.buffer.text.strip()
    if name == previous.name:
        return
    target.items.rename(identity, name)
    try:
        save_editor_project()
    except Exception:
        target.items.rename(identity, previous.name)
        raise
    hierarchy_sync()
    inspector_sync()


def commit_item_data(control):
    from dataclasses import fields, replace
    from lbe import Component, InheritedComponent
    target = control.items.require_target("target")
    identity = control.items.require_value("item_id")
    before = target[identity]
    if control.buffer.text == item_presentation(target, before)[3]:
        return
    value = parse_value(control.buffer.text)
    if isinstance(before, InheritedComponent):
        after = replace(before, patch=({"op": "replace", "value": value},))
    elif isinstance(before, Component):
        after = replace(before, value=value)
    else:
        allowed = {f.name for f in fields(before)} - {"id", "name"}
        if not isinstance(value, dict) or set(value) != allowed:
            raise ValueError("Enter a dictionary containing the item's data fields; identity and name are edited separately")
        after = replace(before, **value)
    if after == before:
        return
    def apply(record):
        current = state.runtime.resolve(target.id)
        current.items.replace(identity, record)
        for _, field in state.component_rows:
            if field.items.target('target') is current and field.items.get_value('item_id') == identity:
                field.buffer = TextBuffer(item_presentation(current, record)[3])
                field.committed_text = field.buffer.text
        inspector_sync()
    apply(after)
    state.files.history.record(lambda: apply(before), lambda: apply(after), "change " + before.name)


def item_data_click(control, event):
    if len(event) > 3 and event[3] in (2, 4):
        return False
    from lbe import Parent, Relation, Component, InheritedComponent
    from lbe.systems import SystemInstance
    target = control.items.require_target("target")
    item = target[control.items.require_value("item_id")]
    if isinstance(item, SystemInstance):
        open_system(target, item.name)
        return True
    if isinstance(item, (Parent, Relation)):
        destination = state.runtime._entities.get(item.target)
        if destination is not None:
            inspect_entity(destination)
        else:
            message("Unresolved Entity reference; choose a target from the item menu")
        return True
    if isinstance(item, (Component, InheritedComponent)):
        return component_click(control, event)
    return False


def open_item_menu(owner, identity, control):
    from lbe import Parent, Relation
    from lbe.systems import SystemInstance
    item = owner[identity]
    actions = [dict(label=type(item).__name__ + ": " + item.name, run=None),
               dict(label="Copy item UUID", run=lambda _: state.window.set_clipboard_text(str(identity)))]
    if isinstance(item, SystemInstance):
        actions.append(dict(label="Edit source", run=lambda _: open_system(owner, item.name)))
    if isinstance(item, (Parent, Relation)):
        for target in state.runtime.entities:
            if target is owner:
                continue
            name = str(target.items.get_value("name", "Entity"))
            actions.append(dict(label="Target → " + name,
                run=lambda _, t=target: retarget_item(owner, identity, t)))
    protected = isinstance(item, SystemInstance) and (
        (owner is state.game and item.name == "render") or
        (owner is state.app and item.name in ("app", "ui")))
    if not protected:
        actions.append(dict(label="Remove item", run=lambda _: remove_item(owner, identity)))
    open_menu(state.ui, owner, control.x, control.y + control.h, actions=actions)


def retarget_item(owner, identity, target):
    from lbe import Parent
    item = owner[identity]
    if isinstance(item, Parent):
        owner.parent = target
    else:
        owner.items.connect(item.name, target)
    save_editor_project()
    hierarchy_sync()
    inspector_sync()


def remove_item(owner, identity):
    owner.items.remove(identity)
    save_editor_project()
    hierarchy_sync()
    inspector_sync()


def inspector_sync():
    ip = state.inspector
    # These former sections are not alternative projections of the data anymore.
    retired = ("add_child_button", "duplicate_button", "delete_button", "quick_add_chip_btn",
               "add_name", "add_value", "add_button", "divider_components", "system_label",
               "add_system_button", "no_systems_label", "divider_systems", "links_header",
               "tags_label", "tags_field", "parent_label", "parent_field", "relations_label",
               "relation_field", "link_add_button")
    for name in retired:
        put(getattr(state, name), visible=False)
    for group in (state.quick_preset_chips, state.component_delete_buttons, state.system_rows,
                  state.system_edit_buttons, state.system_detach_buttons, state.relation_edit_buttons,
                  state.child_rows):
        for control in group:
            put(control, visible=False)
    for pair in state.relation_rows:
        for control in pair:
            put(control, visible=False)
    if not hasattr(state, "item_type_buttons"):
        state.item_type_buttons = []
    visible = ip.items.get_value("visible", True)
    for control in (state.name_label, state.name_field, state.identity_label, state.divider_identity,
                    state.components_title, state.add_comp_menu_button, state.metadata):
        put(control, visible=visible)
    put(state.selection_label, visible=False)
    if not visible:
        for label, field in state.component_rows:
            put(label, visible=False)
            put(field, visible=False)
        for control in state.item_type_buttons:
            put(control, visible=False)
        put(state.inspector_scroll_track, visible=False)
        put(state.inspector_scroll_thumb, visible=False)
        return
    owner = inspected()
    records = tuple(owner.items.values())
    bottom = ip.y + ip.h - 6
    name = str(owner.items.get_value("name", "Entity"))
    put(state.name_label, x=ip.x+12, y=ip.y+32, w=38, h=22, text="Name")
    put(state.name_field, x=ip.x+54, y=ip.y+30, w=max(30, ip.w-66), h=24)
    state.ui.set_text(state.name_field, name)
    put(state.identity_label, x=ip.x+12, y=ip.y+56, w=max(30, ip.w-24), h=18, text="◆ Entity: "+name)
    state.identity_label.on_click = lambda *args: open_identity_menu(owner)
    put(state.divider_identity, x=ip.x+12, y=ip.y+78, w=max(0, ip.w-24), h=1)
    collapsed = "items" in state.collapsed_sections
    put(state.components_title, x=ip.x+12, y=ip.y+84, w=max(80, ip.w-110), h=22,
        text=f"{'▶' if collapsed else '▼'} ITEMS ({len(records)})")
    state.components_title.action = lambda: toggle_section("items")
    put(state.add_comp_menu_button, x=ip.x+ip.w-82, y=ip.y+84, w=70, h=22, text="+ Add")
    row_y = ip.y+112
    capacity = max(0, int((bottom-row_y-24)//44)) if not collapsed else 0
    max_scroll = max(0, len(records)-capacity)
    ip.items.update_values(item_count=len(records), capacity=capacity, scroll=max(0,min(ip.scroll,max_scroll)))
    while len(state.component_rows) < capacity:
        index = len(state.component_rows)
        label = state.ui.field(ip, f"ItemName{index}", "")
        field = state.ui.field(ip, f"ItemData{index}", "")
        state.component_rows.append((label, field))
    while len(state.item_type_buttons) < len(state.component_rows):
        index = len(state.item_type_buttons)
        state.item_type_buttons.append(state.ui.button(ip, f"ItemType{index}", "", lambda: None, color=PANEL))
    scrolling = capacity > 0 and len(records) > capacity
    for index, (label, field) in enumerate(state.component_rows):
        badge = state.item_type_buttons[index]
        source = index+ip.scroll
        shown = index < capacity and source < len(records)
        for control in (label, field, badge):
            put(control, visible=shown)
        if not shown:
            continue
        item = records[source]
        symbol, colour, kind, display, editable = item_presentation(owner, item)
        width = max(40, int((ip.w-36-(10 if scrolling else 0))*0.38))
        y = row_y+index*44
        for control in (label, field, badge):
            if control.items.get_value("item_id") != item.id or control.items.target("target") is not owner:
                if state.ui.focused is control:
                    state.app.items.disconnect("focus")
            control.items.update_values(item_id=item.id, component_key=None)
            control.items.connect("target", owner)
        from lbe import Component, InheritedComponent, Parent
        if isinstance(item, (Component, InheritedComponent)):
            label.items.set_value("component_key", item.name)
            field.items.update_values(component_key=item.name,
                provenance="inherited" if isinstance(item, InheritedComponent) else "local",
                source_id=item.source if isinstance(item, InheritedComponent) else None)
        tint = tuple(int(c*0.22) for c in colour)
        put(label, x=ip.x+12, y=y, w=width, h=23, readonly=isinstance(item, Parent),
            color=tint, normal_color=tint, hover_color=tuple(int(c*0.32) for c in colour), ink=colour)
        put(field, x=ip.x+18+width, y=y, w=max(30,ip.w-width-36-(10 if scrolling else 0)),
            h=23, readonly=not editable, color=FIELD, normal_color=FIELD, ink=INK)
        put(badge, x=ip.x+12, y=y+24, w=max(30,ip.w-36), h=17,
            text=symbol+" "+kind, ink=colour)
        label.on_commit = lambda c=label: commit_item_name(c)
        label.on_click = lambda c, ev: False
        field.on_commit = lambda c=field: commit_item_data(c)
        field.on_click = item_data_click
        badge.action = lambda o=owner, i=item.id, c=badge: open_item_menu(o,i,c)
        state.ui.set_text(label, item.name)
        state.ui.set_text(field, display)
    put(state.metadata, x=ip.x+12, y=bottom-18, w=max(0,ip.w-24), h=18,
        text=f"{len(records)} UUID items · {len(owner.children)} derived children")
    put(state.inspector_scroll_track, visible=scrolling)
    put(state.inspector_scroll_thumb, visible=scrolling)
    state.inspector_scroll_thumb.on_click = inspector_thumb_click
    if scrolling:
        height = capacity*44
        thumb_h = max(16,int(height*capacity/len(records)))
        put(state.inspector_scroll_track, x=ip.x+ip.w-10, y=row_y, w=6, h=height)
        put(state.inspector_scroll_thumb, x=ip.x+ip.w-10,
            y=row_y+int((height-thumb_h)*ip.scroll/max_scroll), w=6, h=thumb_h)

def commit_component(field):
    target, key = (field.items.require_target('target'), field.component_key)
    if field.buffer.text == safe_repr(target.items.require_value(key)):
        return
    from dataclasses import replace
    from lbe import InheritedComponent
    before = target.items.component(key)
    value = parse_value(field.buffer.text)
    after = (replace(before, patch=({"op": "replace", "value": value},))
             if isinstance(before, InheritedComponent) else replace(before, value=value))
    identity = target.id
    def apply(declaration):
        current = state.runtime.resolve(identity)
        if current is None or not current.alive:
            raise ValueError('Edited entity no longer exists')
        current.items.replace(declaration.id, declaration)
        for _, control in state.component_rows:
            if control.items.target('target') is current and control.items.get_value('component_key') == key:
                control.buffer = TextBuffer(safe_repr(current.items.require_value(key)))
                control.committed_text = control.buffer.text
        inspector_sync()
    apply(after)
    field.buffer = TextBuffer(safe_repr(target.items.require_value(key)))
    field.committed_text = field.buffer.text
    state.files.history.record(lambda:apply(before),lambda:apply(after),'change '+key)
    message(f'Updated {key}')
    inspector_sync()

def save_component_changes(target, before):
    try:
        save_editor_project()
    except Exception:
        from lbe import Component, InheritedComponent
        identities = {record.id for record in before}
        for record in tuple(target.items.values()):
            if isinstance(record, (Component, InheritedComponent)) and record.id not in identities:
                target.items.remove(record.id)
        for record in before:
            if record.id in target.items:
                target.items.rename(record.id, record.name)
                target.items.replace(record.id, record)
            else:
                target.items.add(record)
        raise


def component_snapshot(target):
    from lbe import Component, InheritedComponent
    return tuple(record for record in target.items.values()
                 if isinstance(record, (Component, InheritedComponent)))


def add_component():
    ent = inspected()
    before = component_snapshot(ent)
    renaming_key = state.add_name.items.remove_value("renaming_key", None)
    saving_preset = state.add_name.items.remove_value("saving_preset", False)
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
        if renaming_key != name and ent.items.has_value(name):
            raise ValueError(f"Component '{name}' already exists")
        if renaming_key != name:
            ent.items.rename(ent.items.component(renaming_key).id, name)
        ent.items.set_value(name, val)
        message(f"Renamed component '{renaming_key}' -> '{name}'")
    else:
        ent.items.set_value(name, val)
        message(f"Added component '{name}'")
    state.add_name.buffer = TextBuffer()
    state.add_value.buffer = TextBuffer()
    save_component_changes(ent, before)
    inspector_sync()

def commit_tags():
    ent = inspected()
    renaming_tag = state.tags_field.items.remove_value("renaming_tag", None)
    tags = {tag.strip() for tag in state.tags_field.buffer.text.split(',') if tag.strip()}
    previous = set(ent.items.tag_names())
    added = tags - previous
    if renaming_tag in previous and renaming_tag not in tags and len(added) == 1:
        from lbe import Tag
        ent.items.rename(ent.items.named(Tag, renaming_tag).id, next(iter(added)))
    for tag in set(ent.items.tag_names()) - tags:
        ent.items.remove_tag(tag)
    for tag in tags:
        ent.items.add_tag(tag)
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
        exact = [e for e in state.runtime.entities if e.items.get_value('name') == text]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise ValueError(f"Ambiguous entity name '{text}'. Use UUID instead.")

        lower_matches = [e for e in state.runtime.entities if str(e.items.get_value('name', '')).lower() == text.lower()]
        if len(lower_matches) == 1:
            return lower_matches[0]
        if len(lower_matches) > 1:
            raise ValueError(f"Ambiguous entity name '{text}'. Use UUID instead.")

        uuid_matches = [e for e in state.runtime.entities if str(e.id).lower().startswith(text.lower())]
        if len(uuid_matches) == 1:
            return uuid_matches[0]
        if len(uuid_matches) > 1:
            raise ValueError(f"Ambiguous UUID prefix '{text}'. Use full UUID.")

        tag_matches = [e for e in state.runtime.entities if e.items.has_tag(text)]
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
    editing_rel = state.relation_field.items.remove_value("editing_relation", None)
    if '=' in raw:
        name, _, text = raw.partition('=')
        name = name.strip()
        text = text.strip()
        if not name:
            raise ValueError('Use relation=entity name or UUID')
        if text:
            target = resolve_name(text)
            if editing_rel and editing_rel != name:
                inspected().items.disconnect(editing_rel, None)
            inspected().items.connect(name, target)
            tgt_name = str(target.items.get_value('name', str(target.id)[:8]))
            message(f"Linked '{name}' -> '{tgt_name}'")
        else:
            rel_to_remove = editing_rel or name
            inspected().items.disconnect(rel_to_remove, None)
            message(f"Unlinked relation '{rel_to_remove}'")
    else:
        target = resolve_name(raw)
        tgt_name = str(target.items.get_value('name', str(target.id)[:8]))
        name = editing_rel or tgt_name.lower().replace(" ", "_")
        inspected().items.connect(name, target)
        message(f"Linked '{name}' -> '{tgt_name}'")
    state.relation_field.buffer = TextBuffer()
    inspector_sync()

def start_edit_link(name, tgt_name=None):
    ent = inspected()
    if tgt_name is None:
        tgt = ent.items.target(name)
        tgt_name = str(tgt.items.get_value('name', str(tgt.id)[:8])) if tgt else ''
    state.relation_field.buffer = TextBuffer(f"{name}={tgt_name}")
    state.relation_field.buffer.anchor = 0
    state.relation_field.buffer.cursor = len(state.relation_field.buffer.text)
    state.relation_field.items.set_value("editing_relation", name)
    state.ui.focus(state.relation_field)
    message(f"Editing link '{name}'. Press Enter or click + to save.")

def quick_link_to(target):
    source = inspected()
    if source is target:
        message("Cannot link entity to itself")
        return
    tgt_name = str(target.items.get_value('name', str(target.id)[:8]))
    base_name = tgt_name.lower().replace(" ", "_")
    name = base_name
    count = 1
    while source.items.has_link(name) and source.items.require_target(name) is not target:
        count += 1
        name = f"{base_name}_{count}"
    source.items.connect(name, target)
    message(f"Linked '{name}' -> '{tgt_name}'")
    inspector_sync()


def commit_name():
    name = state.name_field.buffer.text.strip()
    ent = inspected()
    if name:
        ent.items.set_value('name', name)
        message(f"Renamed entity to '{name}'")
    else:
        ent.items.remove_value('name', None)
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
    orig_name = str(ent.items.get_value('name', 'Entity'))
    new_name = orig_name + "_copy"
    comps = deepcopy(dict(ent.items.value_dict()))
    comps['name'] = new_name
    from lbe import Component
    dup = state.runtime.create(parent=parent, tags=list(set(ent.items.tag_names())), items=tuple(Component(k, v) for k, v in comps.items()))
    from lbe import InheritedComponent
    for item in ent.all(InheritedComponent):
        dup.items.remove_value(item.name)
        dup.items.inherit_value(item.name, item.source, item.patch)
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
    ent_name = str(ent.items.get_value('name', str(ent.id)[:8]))
    ent.destroy()
    inspect_entity(parent)
    message(f"Deleted entity '{ent_name}'")
    hierarchy_sync()
    inspector_sync()


def delete_component(key):
    ent = inspected()
    if ent.items.has_value(key):
        ent.items.remove_value(key)
        if state.ui.focused and getattr(state.ui.focused, "component_key", None) == key:
            state.app.items.disconnect('focus')
        message(f"Deleted component '{key}'")
        inspector_sync()


def unlink_relation(name):
    ent = inspected()
    if ent.items.has_link(name):
        ent.items.disconnect(name)
        if state.relation_field.items.get_value("editing_relation") == name:
            state.relation_field.items.remove_value("editing_relation", None)
            state.relation_field.buffer = TextBuffer()
        message(f"Unlinked relation '{name}'")
        inspector_sync()


def focus_component_value(key):
    owner = inspected()
    identities = tuple(owner.items)
    if owner.items.has_value(key):
        index=identities.index(owner.items.component(key).id)
        capacity=max(1,state.inspector.items.get_value('capacity', 1))
        scroll=state.inspector.scroll
        if index < scroll or index >= scroll+capacity-1:
            neighbour=min(len(identities)-1,index+1)
            state.inspector.scroll=max(0,neighbour-capacity+1)
            inspector_sync()
    for lbl, fld in state.component_rows:
        if fld.visible and getattr(fld, 'component_key', None) == key:
            state.ui.focus(fld)
            fld.buffer.anchor = 0
            fld.buffer.cursor = len(fld.buffer.text)
            break


def quick_add_pos():
    ent = inspected()
    ent.items.ensure_value("x", 0.0)
    ent.items.ensure_value("y", 0.0)
    message("Added Pos (x, y)")
    save_editor_project()
    inspector_sync()
    focus_component_value("x")


def quick_add_size():
    ent = inspected()
    ent.items.ensure_value("w", 32.0)
    ent.items.ensure_value("h", 32.0)
    message("Added Size (w, h)")
    save_editor_project()
    inspector_sync()
    focus_component_value("w")


def quick_add_vel():
    ent = inspected()
    ent.items.ensure_value("vx", 0.0)
    ent.items.ensure_value("vy", 0.0)
    message("Added Vel (vx, vy)")
    save_editor_project()
    inspector_sync()
    focus_component_value("vx")


def quick_add_color():
    ent = inspected()
    ent.items.ensure_value("color", (200, 200, 200))
    message("Added Color")
    save_editor_project()
    inspector_sync()
    focus_component_value("color")


def quick_add_speed():
    ent = inspected()
    ent.items.ensure_value("speed", 100.0)
    message("Added Speed")
    save_editor_project()
    inspector_sync()
    focus_component_value("speed")


def add_custom_component():
    ent = inspected()
    base = "custom_component"
    key = base
    i = 1
    while ent.items.has_value(key):
        key = f"{base}_{i}"
        i += 1
    ent.items.set_value(key, 0)
    save_editor_project()
    inspector_sync()
    start_rename_component(ent, key)


def context_add_component(target):
    select(target)
    add_custom_component()


def commit_component_key(lbl):
    target = lbl.items.target('target', inspected())
    old_key = lbl.items.remove_value("renaming_key", getattr(lbl, "component_key", None))
    new_key = lbl.buffer.text.strip()
    if not new_key:
        state.ui.set_text(lbl, old_key or "")
        return
    if old_key and new_key != old_key and target and target.alive:
        if target.items.has_value(new_key):
            raise ValueError(f"Component '{new_key}' already exists")
        target.items.rename(target.items.component(old_key).id, new_key)
        message(f"Renamed component '{old_key}' -> '{new_key}'")
        try:
            save_editor_project()
        except Exception:
            target.items.rename(target.items.component(new_key).id, old_key)
            raise
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
        dict(label="+ Inherit component from copied reference", run=lambda _: inherit_copied_component(ent)),
        None,
        dict(label="# Tag", run=lambda _: add_tag_item(ent)),
        dict(label="↔ Relationship", run=lambda _: choose_item_target(ent, parent=False)),
        dict(label="↑ Parent", run=lambda _: choose_item_target(ent, parent=True)),
        dict(label="λ System / ▶ Script", run=lambda _: (inspect_entity(ent), open_attach_system_menu())),
        dict(label="+ Child entity", run=lambda _: (select(ent), inspector_add_child())),
    ]
    open_menu(state.ui, ent, x, y, actions=actions)


def add_tag_item(owner):
    name = "tag"
    suffix = 1
    while owner.items.has_tag(name):
        name = f"tag{suffix}"
        suffix += 1
    item = owner.items.add_tag(name)
    save_editor_project()
    focus_item(owner, item.id)


def choose_item_target(owner, parent=False):
    actions = []
    for target in state.runtime.entities:
        if target is owner:
            continue
        name = str(target.items.get_value("name", "Entity"))
        actions.append(dict(label=name, run=lambda _, t=target: add_link_item(owner, t, parent)))
    open_menu(state.ui, owner, state.inspector.x+20, state.inspector.y+110, actions=actions)


def add_link_item(owner, target, parent=False):
    if parent:
        owner.parent = target
        from lbe import Parent
        item = owner.all(Parent)[0]
    else:
        name = "link"
        suffix = 1
        while owner.items.has_link(name):
            name = f"link{suffix}"
            suffix += 1
        owner.items.connect(name, target)
        from lbe import Relation
        item = owner.items.named(Relation, name)
    save_editor_project()
    hierarchy_sync()
    focus_item(owner, item.id)


def focus_item(owner, identity):
    inspect_entity(owner)
    state.collapsed_sections.discard("items")
    identities = tuple(owner.items)
    index = identities.index(identity)
    state.inspector.scroll = index
    inspector_sync()
    for label, field in state.component_rows:
        if label.visible and label.items.get_value("item_id") == identity:
            state.ui.focus(label)
            label.buffer.anchor = 0
            label.buffer.cursor = len(label.buffer.text)
            break


def change_component_type(ent, comp, target_type):
    val = ent.items.get_value(comp)
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

    before = component_snapshot(ent)
    ent.items.set_value(comp, new_val)
    message(f"Changed '{comp}' type to {target_type}")
    save_component_changes(ent, before)
    inspector_sync()
    focus_component_value(comp)


def open_change_type_menu(ent, comp):
    current_val = ent.items.get_value(comp)
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
    # Recursively scan project directory and subdirectories (e.g. systems/game)
    if state.project and state.project.exists():
        for p in sorted(state.project.rglob("*.py")):
            if p.name in ("ui.py", "app.py", "hierarchy.py", "inspector.py", "text_area.py", "code_editor.py", "docking.py", "file_explorer.py", "system_log.py", "effects.py", "files.py"):
                continue
            rel_parts = p.relative_to(state.project).parts if p.is_relative_to(state.project) else ()
            if any(part in (".venv", "__pycache__", ".git") for part in rel_parts):
                continue
            candidates.append(p)
    # Also check template directory
    try:
        from lbe.project import template_path
        tpl = template_path("editor")
        if tpl.exists():
            for p in sorted(tpl.rglob("*.py")):
                if p.name in ("ui.py", "app.py", "hierarchy.py", "inspector.py", "text_area.py", "code_editor.py", "docking.py", "file_explorer.py", "system_log.py", "effects.py", "files.py"):
                    continue
                if not any(c.name == p.name for c in candidates):
                    candidates.append(p)
    except Exception:
        pass

    actions = []
    for p in candidates:
        name = p.stem
        already = ent.items.has_behaviour(name, kind='system') or ent.items.has_behaviour(name, kind='script')
        if not already:
            rel_label = str(p.relative_to(state.project)).replace("\\", "/") if p.is_relative_to(state.project) else p.name
            actions.append(dict(label=f"+ {name} ({rel_label})", run=lambda e, path=p: attach_system_to_entity(ent, path)))
        else:
            actions.append(dict(label=f"{name} (attached)", run=None))

    if actions:
        actions.append(None)
    actions.append(dict(label="+ New System Script...", run=lambda e: prompt_new_system(ent)))

    open_menu(state.ui, ent, state.add_system_button.x, state.add_system_button.y + state.add_system_button.h + 2, actions=actions)


def prompt_new_system(ent):
    target_dir = state.project / "systems" / "game" / "scripts"
    if not target_dir.exists():
        target_dir = state.project / "systems" / "game"
    target_dir.mkdir(parents=True, exist_ok=True)
    i = 1
    while (target_dir / f"script_{i}.py").exists():
        i += 1
    script_path = target_dir / f"script_{i}.py"
    initial_text = 'components = ("x", "y", "vx", "vy")\n\ndef run(dt):\n    self.x += getattr(self, "vx", 0.0) * dt\n    self.y += getattr(self, "vy", 0.0) * dt\n'
    script_path.write_text(initial_text, encoding="utf-8")
    
    attach_system_to_entity(ent, script_path)
    if hasattr(state, "open_specific_file"):
        state.open_specific_file(script_path)
    elif hasattr(state, "new_source_in_dir"):
        rel_name = str(script_path.relative_to(state.project)).replace("\\", "/")
        state.path_field.buffer = TextBuffer(rel_name)
        state.code.buffer = TextBuffer(initial_text)
        state._saved_source = (rel_name, initial_text)
        state.code.source_path = str(script_path)
        state.code.items.set_value("system_name", script_path.stem)
    state.code.items.connect('owner', ent)
    message(f"Created and attached {script_path.name} to {ent.items.get_value('name', ent.id)}")


def attach_system_to_entity(ent, path):
    try:
        definition = state.runtime.assets.system(path)
        stem = path.stem
        if ent.items.has_behaviour(stem, kind='system'):
            instance = ent.items.reload(ent.items.behaviour(stem, kind='system').id, definition)
        else:
            instance = ent.items.attach_system(stem, definition)
        save_editor_project()
        inspector_sync()
        if instance.errors:
            message(f"Attached {stem} with errors: {instance.errors[-1].message}")
        else:
            message(f"Attached {stem} to {ent.items.get_value('name', ent.id)}")
    except Exception as err:
        message(f"Failed to attach {path.stem}: {err}")


def detach_system_from_entity(ent, name):
    if ent is state.app and name in ('app', 'ui'):
        message('The active editor cannot detach itself')
        return
    if ent is state.game and name == 'render':
        message('Cannot detach core render system from Game')
        return
    try:
        collection = ent.items.behaviour_dict('system') if ent.items.has_behaviour(name, kind='system') else ent.items.behaviour_dict('script')
        ent.items.remove(collection[name].id)
        if state.code.items.target('owner') is ent and state.code.items.get_value('system_name') == name:
            state.code.items.disconnect('owner')
            state.code.items.remove_value('system_name', None)
        save_editor_project()
        inspector_sync()
        message(f"Detached system '{name}' from {ent.items.get_value('name', ent.id)}")
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
    unpinned = [k for k in ent.items.value_dict() if not any(p[0] == k for p in state.quick_component_presets)]
    if unpinned:
        actions.append(None)
        for k in unpinned:
            actions.append(dict(label=f"Pin '{k}' to quick-bar", run=lambda _, comp=k: pin_to_quick_bar(comp, ent.items.get_value(comp))))
    open_menu(state.ui, ent, state.quick_add_chip_btn.x, state.quick_add_chip_btn.y + state.quick_add_chip_btn.h + 2, actions=actions)


def prompt_add_preset():
    state.add_name.buffer = TextBuffer("custom")
    state.add_value.buffer = TextBuffer("1.0")
    state.add_name.items.set_value("saving_preset", True)
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
                ent.items.ensure_value(k, v)
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
            lbl.items.set_value("renaming_key", old_key)
            message(f"Renaming component '{old_key}': type new name and press Enter")
            return
    state.add_name.buffer = TextBuffer(old_key)
    state.add_value.buffer = TextBuffer(safe_repr(ent.items.get_value(old_key)))
    state.add_name.items.set_value("renaming_key", old_key)
    state.ui.focus(state.add_name)
    message(f"Renaming component '{old_key}': type new name and press Enter")


def start_rename_tag(ent, old_tag):
    state.tags_field.items.set_value("renaming_tag", old_tag)
    state.ui.focus(state.tags_field)
    message(f"Renaming tag '{old_tag}': edit in Tags box and press Enter")


def remove_tag(ent, tag):
    ent.items.remove_tag(tag)
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
    rel_y = event[2] - track.y - thumb.items.get_value("drag_offset", thumb.h / 2)
    ratio = max(0.0, min(1.0, rel_y / travel))
    state.inspector.scroll = int(round(ratio * max_scroll))
    return True


def inspector_thumb_click(thumb, event):
    thumb.items.set_value("drag_offset", event[2] - thumb.y)
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
    target = control.items.target("target")
    key = getattr(control, "component_key", None)
    if target and key:
        from lbe.assets import AssetRef
        val = target.items.get_value(key)
        if isinstance(val, AssetRef):
            open_asset_picker_menu(target, key)
            return True
    return False


def open_identity_menu(ent):
    x, y = state.identity_label.x, state.identity_label.y + state.identity_label.h
    handle = ent.handle
    actions = [
        dict(label=f"UUID: {ent.id}", run=None),
        dict(label=f"Runtime handle: {handle.slot}:{handle.generation} (temporary)", run=None),
        dict(label=f"Typed items: {len(ent.items)}", run=None),
        dict(label="Copy Entity reference", run=lambda _: state.window.set_clipboard_text(f"<|Entity:{ent.id}|>")),
        dict(label="Copy Entity UUID", run=lambda _: state.window.set_clipboard_text(str(ent.id))),
    ]
    for child in ent.children:
        name = str(child.items.get_value('name', 'Entity'))
        actions.append(dict(label='Child → ' + name, run=lambda _, c=child: inspect_entity(c)))
    for effect in effects.affecting(ent):
        try:
            owner = state.runtime.resolve(effect.owner)
        except KeyError:
            continue
        actions.append(dict(label='Affected by → ' + effect.system,
                            run=lambda _, o=owner, n=effect.system: open_system(o, n)))
    open_menu(state.ui, ent, x, y, actions=actions)


def inherit_copied_component(ent):
    from lbe.references import source_references
    from lbe import Component, InheritedComponent
    references = source_references(state.window.get_clipboard_text(), strict=True)
    if len(references) != 1 or references[0].kind != "Component":
        raise ValueError("Copy a Component reference from another entity's component menu first")
    source = runtime.linker.resolve(references[0].id, (Component, InheritedComponent))
    key = source.name
    suffix = 1
    while ent.items.has_value(key):
        key = f"{source.name}_inherited{suffix}"
        suffix += 1
    item = ent.items.inherit_value(key, source)
    try:
        save_editor_project()
    except Exception:
        ent.items.remove(item.id)
        raise
    inspector_sync()
    message(f"Inherited '{key}'; edits change the local patch, not its source")


def reset_component_patch(ent, key):
    original = ent.items.component(key)
    ent.items.patch_value(ent.items.component(key).id, ())
    try:
        save_editor_project()
    except Exception:
        ent.items.patch_value(ent.items.component(key).id, original.patch)
        raise
    inspector_sync()


def open_asset_picker_menu(ent, comp):
    current_val = ent.items.get_value(comp)
    reg = getattr(state.runtime.assets, "registry", None)
    from lbe.assets import ASSET_ICONS, AssetRef
    actions = []
    if reg:
        for uid, entry in sorted(reg.entries(), key=lambda x: (x[1]["type"], x[1]["name"].lower())):
            icon = reg.icon(uid)
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
    ent.items.set_value(comp, AssetRef(id=uid, type=entry["type"], name=entry["name"]))
    save_editor_project()
    inspector_sync()
    message(f"Set '{comp}' to {entry['name']}")


def clear_asset_ref(ent, comp):
    ent.items.set_value(comp, None)
    save_editor_project()
    inspector_sync()
    message(f"Cleared '{comp}'")

def start():
    global _release
    _release = bind_callbacks(system, state, {
        "focus_item": focus_item,
        "open_item_menu": open_item_menu,
        "inspector_sync": inspector_sync,
        "inherit_copied_component": inherit_copied_component,
        "reset_component_patch": reset_component_patch,
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
