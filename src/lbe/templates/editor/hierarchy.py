"""Hierarchy panel entity system."""

from lbe.ui import bind_callbacks, put, contains, PANEL, INK


state = entity.inherit("application_state")
selected = lambda: state.selected()
select = lambda target: state.select(target)
message = lambda text: state.message(text)

def view_root():
    root = entity.items.target("view_root")
    if root is None or not root.alive:
        root = state.game if state.game.alive else state.app
        entity.items.connect("view_root", root)
    return root


def set_hierarchy_root(target):
    if target is None or not target.alive:
        return
    entity.items.connect("view_root", target)
    state.hierarchy.scroll = 0
    state.hierarchy.expanded.add(target.id)
    state.select(target)
    hierarchy_sync()


def reveal_hierarchy(target):
    root = view_root()
    while root is not target and root not in target.ancestors and root.parent is not None:
        root = root.parent
    # Separate top-level trees have no shared entity ancestor.
    if root is not target and root not in target.ancestors:
        root = target.root
    entity.items.connect("view_root", root)
    for ancestor in target.ancestors:
        state.hierarchy.expanded.add(ancestor.id)
    return root


def hierarchy_sync():
    if not getattr(state, "hierarchy", None) or not state.hierarchy.items.get_value("visible", True):
        for row in getattr(state, "hierarchy_rows", []):
            put(row, visible=False)
        if hasattr(state, "hierarchy_scroll_track"):
            put(state.hierarchy_scroll_track, visible=False)
        if hasattr(state, "hierarchy_scroll_thumb"):
            put(state.hierarchy_scroll_thumb, visible=False)
        return

    visible = []
    root = reveal_hierarchy(selected())
    traversal_stack = [(root, 0)]
    expanded = state.hierarchy.expanded
    while traversal_stack and len(visible) < 10000:
        entity, depth = traversal_stack.pop()
        visible.append((entity, depth))
        if entity.id in expanded:
            traversal_stack.extend(((child, depth + 1) for child in reversed(entity.children)))
    capacity = int(max(0, (state.hierarchy.h - 34)) // 22)
    state.hierarchy.visible_count = len(visible)
    max_scroll = max(0, len(visible) - capacity)
    target = selected()
    if state.hierarchy.items.get_value('revealed_selection') != target.id:
        state.hierarchy.items.set_value('revealed_selection', target.id)
        index = next((i for i,(e,_) in enumerate(visible) if e is target), 0)
        state.hierarchy.scroll = max(0,index-capacity+1)

    put(state.hierarchy, scroll=max(0, min(state.hierarchy.scroll, max_scroll)))
    while len(state.hierarchy_rows) < capacity:
        row = state.ui.create(state.hierarchy, f'HierarchyRow{len(state.hierarchy_rows)}', 'button', text='', indent=0,
                              normal_color=PANEL, hover_color=(35, 45, 58))
        row.on_click = state.hierarchy_click
        row.on_drag = state.hierarchy_row_drag
        state.hierarchy_rows.append(row)
    has_scroll = len(visible) > capacity and capacity > 0
    row_w = state.hierarchy.w - 20 if has_scroll else state.hierarchy.w - 16
    mouse_pos = getattr(state.ui, "mouse_pos", None)
    max_bottom = state.hierarchy.y + state.hierarchy.h - 6
    for index, row in enumerate(state.hierarchy_rows):
        source = index + state.hierarchy.scroll
        row_y = state.hierarchy.y + 32 + index * 22
        if index >= capacity or source >= len(visible) or row_y + 22 > max_bottom:
            put(row, visible=False)
            continue
        target, depth = visible[source]
        if row.items.target('target') is not target:
            row.items.connect('target', target)
        name = str(target.items.get_value('name', str(target.id)[:8]))
        marker = '-' if target.id in expanded else '+'
        is_selected = target is selected()
        indicator = '> ' if is_selected else '  '
        text = '  ' * min(depth, 8) + (marker if target.children else ' ') + ' ' + indicator + name
        normal_col = (45, 95, 125) if is_selected else PANEL
        hover_col = (55, 105, 135) if is_selected else (35, 45, 58)
        is_hovered = bool(mouse_pos and contains(row, *mouse_pos))
        put(row, visible=True, x=state.hierarchy.x + 8, y=row_y,
            w=row_w, h=22, text=text, indent=min(depth, 8) * 16,
            normal_color=normal_col, hover_color=hover_col,
            color=hover_col if is_hovered else normal_col,
            ink=(255, 255, 255, 255) if is_selected else INK)
    if has_scroll and capacity > 0:
        track_x = state.hierarchy.x + state.hierarchy.w - 10
        track_y = state.hierarchy.y + 32
        track_w = 6
        track_h = max(10, min(capacity * 22, max_bottom - track_y))
        put(state.hierarchy_scroll_track, visible=True, x=track_x, y=track_y, w=track_w, h=track_h)
        thumb_h = max(16, int(track_h * (capacity / len(visible))))
        travel = max(1, track_h - thumb_h)
        thumb_y = track_y + int(travel * (state.hierarchy.scroll / max_scroll)) if max_scroll > 0 else track_y
        put(state.hierarchy_scroll_thumb, visible=True, x=track_x, y=thumb_y, w=track_w, h=thumb_h)
    else:
        put(state.hierarchy_scroll_track, visible=False)
        put(state.hierarchy_scroll_thumb, visible=False)



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




def hierarchy_click(row, event):
    target = row.items.target("target")
    if target is None:
        return
    if event[1] < row.x + row.indent + 24:
        expanded = set(state.hierarchy.expanded)
        expanded.symmetric_difference_update({target.id})
        state.hierarchy.expanded = expanded
    click_count = event[5] if len(event) >= 6 else 1
    # Right-click selects target for context menu
    if len(event) > 3 and event[3] in (2, 4):
        select(target)
        return
    if click_count >= 2:
        select(target)
    else:
        state.app.items.connect('selection', target)
        state.game.items.connect('selection', target)


def hierarchy_row_drag(row, event):
    if state.app.items.get_value("entity_drag") is not None or state.app.items.get_value("asset_drag") is not None:
        return True
    target = row.items.target("target")
    if target is None:
        return False
    ent_name = str(target.items.get_value("name", str(target.id)[:8]))
    state.app.items.set_value("entity_drag", {
        "id": str(target.id),
        "name": ent_name,
        "type": "entity",
        "entity": target,
    })
    return True


def start():
    global _release
    _release = bind_callbacks(system, state, {
        "hierarchy_sync": hierarchy_sync,
        "set_hierarchy_root": set_hierarchy_root,
        "reveal_hierarchy": reveal_hierarchy,
        "hierarchy_click": hierarchy_click,
        "hierarchy_row_drag": hierarchy_row_drag,
        "hierarchy_scroll_drag": hierarchy_scroll_drag,
        "hierarchy_track_click": hierarchy_track_click,
    })
    if hasattr(state, "hierarchy_scroll_thumb"):
        state.hierarchy_scroll_thumb.on_drag = state.hierarchy_scroll_drag
    if hasattr(state, "hierarchy_scroll_track"):
        state.hierarchy_scroll_track.on_click = state.hierarchy_track_click
    for row in getattr(state, "hierarchy_rows", ()):
        row.on_click = state.hierarchy_click
        row.on_drag = state.hierarchy_row_drag


def update(dt):
    hierarchy_sync()


def stop():
    release = globals().get("_release")
    if release:
        release()
