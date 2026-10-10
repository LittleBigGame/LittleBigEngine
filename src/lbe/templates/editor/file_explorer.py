"""Project File Explorer entity system for LittleBigEngine."""

import os
from time import monotonic
from pathlib import Path
from lbe.ui import bind_callbacks, put, contains, PANEL, FIELD, INK, MUTED, ACCENT
from lbe.assets import ASSET_ICONS, AssetRef, asset_icon
from lbe.menus import open_menu


state = entity.inherit("application_state")
selected = lambda: state.selected()
message = lambda text: state.message(text)


def build_file_tree(project_dir, expanded_folders, view_root=None):
    """Build a flattened list of visible files and directories based on expanded state."""
    if not project_dir or not Path(project_dir).exists():
        return []

    pdir = Path(project_dir).resolve()
    items = []

    def scan_dir(cur_dir, depth):
        try:
            entries = sorted(cur_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            return

        for entry in entries:
            # Skip hidden files, __pycache__, and venvs
            if entry.name.startswith(".") or entry.name in ("__pycache__", "venv", ".venv"):
                continue

            rel_path = str(entry.relative_to(pdir)).replace("\\", "/")
            is_dir = entry.is_dir()
            is_expanded = rel_path in expanded_folders

            if is_dir:
                icon = "📂" if is_expanded else "📁"
                items.append({
                    "path": entry,
                    "rel_path": rel_path,
                    "name": entry.name,
                    "is_dir": True,
                    "depth": depth,
                    "expanded": is_expanded,
                    "icon": icon,
                    "type": "folder",
                })
                if is_expanded:
                    scan_dir(entry, depth + 1)
            else:
                ext = entry.suffix.lower()
                atype = state.runtime.assets.registry.infer_type(entry)
                icon = asset_icon(entry, atype)
                reg = getattr(state.runtime.assets, "registry", None)
                asset_id = reg.get_id(entry) if reg else None
                items.append({
                    "path": entry,
                    "rel_path": rel_path,
                    "name": entry.name,
                    "is_dir": False,
                    "depth": depth,
                    "expanded": False,
                    "icon": icon,
                    "type": atype,
                    "asset_id": asset_id,
                })

    root = Path(view_root).resolve() if view_root is not None else pdir
    relative = root.relative_to(pdir).as_posix()
    items.append(dict(path=root,rel_path=relative,name=root.name,is_dir=True,
                      depth=0,expanded=relative in expanded_folders,icon="📂",type="folder"))
    if relative in expanded_folders:
        scan_dir(root, 1)
    return items


def file_view_root():
    relative = entity.items.get_value("view_root", "systems/game")
    root = (state.project / relative).resolve()
    if not root.is_relative_to(state.project) or not root.is_dir():
        root = state.project
        entity.items.set_value("view_root", ".")
    return root


def set_file_root(path):
    path = Path(path).resolve()
    if not path.is_relative_to(state.project) or not path.is_dir():
        return
    entity.items.set_value("view_root", path.relative_to(state.project).as_posix())
    entity.items.set_value("selected_file", path.relative_to(state.project).as_posix())
    entity.items.ensure_value("expanded", set()).add(path.relative_to(state.project).as_posix())
    entity.items.set_value("scroll", 0)
    state.file_tree_key = None
    file_explorer_sync()


def reveal_file(path):
    path = Path(path).resolve()
    if not path.is_relative_to(state.project):
        return
    root = file_view_root()
    while not path.is_relative_to(root) and root != state.project:
        root = root.parent
    entity.items.set_value("view_root", root.relative_to(state.project).as_posix())
    expanded = entity.items.ensure_value("expanded", set())
    parent = path if path.is_dir() else path.parent
    while parent.is_relative_to(root):
        expanded.add(parent.relative_to(state.project).as_posix())
        if parent == root:
            break
        parent = parent.parent
    entity.items.set_value("selected_file", path.relative_to(state.project).as_posix())
    entity.items.set_value("scroll", 0)
    state.file_tree_key = None


def file_explorer_sync():
    fe = getattr(state, "file_explorer", None)
    if fe is None or not fe.items.get_value("visible", True):
        for row in getattr(state, "file_explorer_rows", []):
            put(row, visible=False)
        track = getattr(state, "file_scroll_track", None)
        thumb = getattr(state, "file_scroll_thumb", None)
        if track is not None:
            put(track, visible=False)
        if thumb is not None:
            put(thumb, visible=False)
        return

    expanded = fe.items.ensure_value("expanded", set())
    selection = fe.items.get_value('selected_file')
    if selection and fe.items.get_value('revealed_selection') != selection:
        fe.items.set_value('revealed_selection', selection)
        reveal_file(state.project / selection)
    root = file_view_root()
    expanded.add(root.relative_to(state.project).as_posix())
    key = (str(root), tuple(sorted(expanded)), state.runtime.assets.registry.revision, int(monotonic()))
    if getattr(state, "file_tree_key", None) != key:
        state.file_tree_items = build_file_tree(state.project, expanded, root)
        state.file_tree_key = key
    visible_items = state.file_tree_items
    fe.items.set_value("visible_items", visible_items)

    capacity = int(max(0, (fe.h - 34)) // 22)
    max_scroll = max(0, len(visible_items) - capacity)
    if selection and fe.items.get_value('scrolled_selection') != selection:
        fe.items.set_value('scrolled_selection', selection)
        index = next((i for i,item in enumerate(visible_items) if item['rel_path'] == selection),0)
        fe.scroll = max(0,index-capacity+1)

    fe.scroll = max(0, min(fe.items.get_value("scroll", 0), max_scroll))

    rows = getattr(state, "file_explorer_rows", None)
    if rows is None:
        rows = []
        state.file_explorer_rows = rows

    while len(rows) < capacity:
        row = state.ui.create(fe, f'FileRow{len(rows)}', 'button', text='', indent=0,
                              normal_color=PANEL, hover_color=(35, 45, 58))
        row.on_click = file_row_click
        row.on_drag = file_row_drag
        rows.append(row)

    has_scroll = len(visible_items) > capacity and capacity > 0
    row_w = fe.w - 20 if has_scroll else fe.w - 16
    mouse_pos = getattr(state.ui, "mouse_pos", None)
    max_bottom = fe.y + fe.h - 6

    for index, row in enumerate(rows):
        source = index + fe.scroll
        row_y = fe.y + 30 + index * 22
        if index >= capacity or source >= len(visible_items) or row_y + 20 > max_bottom:
            put(row, visible=False)
            continue

        item = visible_items[source]
        row.items.set_value("file_item", item)

        indent = item["depth"] * 14
        arrow = ("▼ " if item["expanded"] else "▶ ") if item["is_dir"] else "  "
        label = f"{arrow}{item['icon']} {item['name']}"

        is_hovered = False
        if mouse_pos and state.ui.visible(row):
            rx, ry = row.x, row.y
            mx, my = mouse_pos
            if rx <= mx <= rx + row_w and ry <= my <= ry + 20:
                is_hovered = True

        selected_file = fe.items.get_value("selected_file")
        is_selected = (selected_file == item["rel_path"])
        normal_col = (45, 95, 125) if is_selected else PANEL
        hover_col = (55, 105, 135) if is_selected else (35, 48, 65)
        bg_color = hover_col if is_hovered else normal_col
        ink_color = (255, 255, 255) if is_selected else ((130, 200, 255) if item["type"] in ("system","script") else ((255, 200, 100) if item["is_dir"] else INK))

        put(row, visible=True, x=fe.x + 8 + indent, y=row_y,
            w=max(40, row_w - indent), h=20, text=label,
            color=bg_color, normal_color=normal_col, hover_color=hover_col,
            ink=ink_color)

    # Scrollbar
    track = getattr(state, "file_scroll_track", None)
    thumb = getattr(state, "file_scroll_thumb", None)
    if track is not None and thumb is not None:
        if has_scroll and capacity > 0:
            avail_h = max(10, min(fe.h - 38, max_bottom - (fe.y + 32)))
            thumb_h = max(18, int(avail_h * capacity / max(1, len(visible_items))))
            thumb_y = fe.y + 32 + int((avail_h - thumb_h) * fe.scroll / max(1, max_scroll))
            put(track, visible=True, x=fe.x + fe.w - 12, y=fe.y + 32, w=8, h=avail_h)
            put(thumb, visible=True, x=fe.x + fe.w - 12, y=thumb_y, w=8, h=thumb_h)
        else:
            put(track, visible=False)
            put(thumb, visible=False)


def file_row_click(row, event):
    # Right-click handled by context menu
    if len(event) > 3 and event[3] in (2, 4):
        return False

    item = row.items.get_value("file_item")
    if not item:
        return True

    fe = state.file_explorer
    if item["is_dir"]:
        # Toggle folder expanded
        rel = item["rel_path"]
        if rel in fe.expanded:
            fe.expanded.remove(rel)
        else:
            fe.expanded.add(rel)
        file_explorer_sync()
        return True

    click_count = event[5] if len(event) >= 6 else 1
    fe.items.set_value("selected_file", item["rel_path"])
    if click_count >= 2:
        if item["type"] in ("system","script"):
            # Open in code editor
            state.open_specific_file(item["path"])
            message(f"Opened {item['name']}")
        else:
            message(f"{item['type'].capitalize()}: {item['name']}")
    else:
        message(f"Selected {item['name']}")

    file_explorer_sync()
    return True


def file_row_drag(row, event):
    """Initiate drag of asset from File Explorer."""
    if state.app.items.get_value("asset_drag") is not None:
        return True
    item = row.items.get_value("file_item")
    if not item or item["is_dir"]:
        return False

    reg = getattr(state.runtime.assets, "registry", None)
    asset_id = item.get("asset_id")
    if asset_id is None and reg:
        asset_id = reg.register(item["path"])
        item["asset_id"] = asset_id

    state.app.items.set_value("asset_drag", {
        "id": asset_id,
        "name": item["name"],
        "path": item["rel_path"],
        "type": item["type"],
        "icon": item["icon"],
    })
    return True


def file_scroll_drag(thumb, event):
    fe = state.file_explorer
    items = fe.items.get_value("visible_items", [])
    capacity = int((fe.h - 34) // 22)
    max_scroll = max(0, len(items) - capacity)
    if max_scroll <= 0:
        return True
    avail_h = fe.h - 38
    if len(event) > 6 and event[6] != 0:
        frac = event[6] / max(1, avail_h)
        fe.scroll = max(0, min(max_scroll, fe.scroll + int(frac * max_scroll)))
    elif len(event) > 2:
        frac = (event[2] - (fe.y + 32)) / max(1, avail_h)
        fe.scroll = max(0, min(max_scroll, int(frac * max_scroll)))
    file_explorer_sync()
    return True


def file_track_click(track, event):
    fe = state.file_explorer
    items = fe.items.get_value("visible_items", [])
    capacity = int((fe.h - 34) // 22)
    max_scroll = max(0, len(items) - capacity)
    if max_scroll <= 0 or len(event) < 3:
        return True
    avail_h = fe.h - 38
    frac = (event[2] - (fe.y + 32)) / max(1, avail_h)
    fe.scroll = max(0, min(max_scroll, int(frac * max_scroll)))
    file_explorer_sync()
    return True


def update(dt):
    file_explorer_sync()


def start():
    global _release
    _release = bind_callbacks(system, state, {
        "file_explorer_sync": file_explorer_sync,
        "set_file_root": set_file_root,
        "reveal_file": reveal_file,
        "file_scroll_drag": file_scroll_drag,
        "file_track_click": file_track_click,
    })


def stop():
    release = globals().get("_release")
    if release:
        release()
