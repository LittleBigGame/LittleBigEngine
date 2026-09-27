"""Project File Explorer entity system for LittleBigEngine."""

import os
from pathlib import Path
from lbe.ui import put, contains, PANEL, FIELD, INK, MUTED, ACCENT
from lbe.assets import ASSET_ICONS, AssetRef
from lbe.menus import open_menu


class StateProxy:
    def __getattr__(self, name):
        s = entity.root.components.get("application_state")
        return getattr(s, name)

    def __setattr__(self, name, value):
        s = entity.root.components.get("application_state")
        setattr(s, name, value)


state = StateProxy()
selected = lambda: state.selected()
message = lambda text: state.message(text)


def build_file_tree(project_dir, expanded_folders):
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
                atype = "system" if ext == ".py" else ("image" if ext in (".png", ".jpg", ".jpeg", ".bmp") else ("audio" if ext in (".wav", ".ogg", ".mp3") else "data"))
                icon = ASSET_ICONS.get(atype, "📄")
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

    scan_dir(pdir, 0)
    return items


def file_explorer_sync():
    fe = getattr(state, "file_explorer", None)
    if fe is None or not fe.components.get("visible", True):
        return

    expanded = fe.components.setdefault("expanded", set())
    visible_items = build_file_tree(state.project, expanded)
    fe.components["visible_items"] = visible_items

    capacity = int((fe.h - 34) // 22)
    max_scroll = max(0, len(visible_items) - capacity)
    fe.scroll = max(0, min(fe.components.get("scroll", 0), max_scroll))

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

    for index, row in enumerate(rows):
        source = index + fe.scroll
        if index >= capacity or source >= len(visible_items):
            put(row, visible=False)
            continue

        item = visible_items[source]
        row.components["file_item"] = item

        indent = item["depth"] * 14
        arrow = ("▼ " if item["expanded"] else "▶ ") if item["is_dir"] else "  "
        label = f"{arrow}{item['icon']} {item['name']}"

        is_hovered = False
        if mouse_pos and state.ui.visible(row):
            rx, ry = row.x, row.y
            mx, my = mouse_pos
            if rx <= mx <= rx + row_w and ry <= my <= ry + 20:
                is_hovered = True

        bg_color = (35, 48, 65) if is_hovered else PANEL
        ink_color = (130, 200, 255) if item["type"] == "system" else ((255, 200, 100) if item["is_dir"] else INK)

        put(row, visible=True, x=fe.x + 8 + indent, y=fe.y + 30 + index * 22,
            w=max(40, row_w - indent), h=20, text=label,
            color=bg_color, normal_color=PANEL, hover_color=(35, 48, 65),
            ink=ink_color)

    # Scrollbar
    track = getattr(state, "file_scroll_track", None)
    thumb = getattr(state, "file_scroll_thumb", None)
    if track is not None and thumb is not None:
        if has_scroll:
            avail_h = fe.h - 38
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

    item = row.components.get("file_item")
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
    if item["type"] == "system":
        # Open in code editor
        state.open_specific_file(item["path"])
        message(f"Opened {item['name']}")
    else:
        message(f"{item['type'].capitalize()}: {item['name']}")

    return True


def file_row_drag(row, event):
    """Initiate drag of asset from File Explorer."""
    item = row.components.get("file_item")
    if not item or item["is_dir"]:
        return False

    reg = getattr(state.runtime.assets, "registry", None)
    asset_id = item.get("asset_id")
    if asset_id is None and reg:
        asset_id = reg.register(item["path"])
        item["asset_id"] = asset_id

    state.app.components["asset_drag"] = {
        "id": asset_id,
        "name": item["name"],
        "path": item["rel_path"],
        "type": item["type"],
        "icon": item["icon"],
    }
    return True


def file_scroll_drag(thumb, event):
    fe = state.file_explorer
    items = fe.components.get("visible_items", [])
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
    items = fe.components.get("visible_items", [])
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
    state.file_explorer_sync = file_explorer_sync
    state.file_scroll_drag = file_scroll_drag
    state.file_track_click = file_track_click
