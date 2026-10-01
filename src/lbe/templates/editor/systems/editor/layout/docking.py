"""Dock layout and panel composition, attached as an ordinary editor system."""
from lbe.ui import bind_callbacks, put, parse_box, INK, MUTED, PANEL
from lbe.text import TextBuffer
from lbe.dock import DockTree, SplitNode, TabGroupNode

state=entity.inherit("application_state")

def hierarchy_sync(*args, **kwargs):
    return state.hierarchy_sync(*args, **kwargs)

def inspector_sync(*args, **kwargs):
    return state.inspector_sync(*args, **kwargs)

def message(*args, **kwargs):
    return state.message(*args, **kwargs)

def save_editor_project(*args, **kwargs):
    return state.save_editor_project(*args, **kwargs)

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
    if hasattr(state, "dock_tree"):
        split_main = state.dock_tree.find_node("split_main")
        if split_main and isinstance(split_main, SplitNode):
            ws_x = 8
            ws_w = max(100, w - 16)
            split_main.ratio = max(0.1, min(0.9, (new_w - ws_x) / ws_w))
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
    if hasattr(state, "dock_tree"):
        split_left = state.dock_tree.find_node("split_left")
        if split_left and isinstance(split_left, SplitNode):
            split_left.ratio = max(0.1, min(0.9, new_h / max(1, available_h)))
    layout()


def on_drag_code_splitter(control, event):
    top_y = state.header.y + state.header.h
    status_m = parse_box(state.status.components.get("margin", (0, 16, 5, 16)))
    status_h = state.status.components.get("h", 20)
    status_y = state.window.height - status_m[2] - status_h
    available_h = status_y - top_y
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
    if hasattr(state, "dock_tree"):
        split_right = state.dock_tree.find_node("split_right")
        if split_right and isinstance(split_right, SplitNode):
            split_right.ratio = max(0.1, min(0.9, (new_split - top_y) / max(1, available_h)))
    layout()


def contains_box(box, x, y):
    bx, by, bw, bh = box
    return bx <= x < bx + bw and by <= y < by + bh


def start_panel_dock_drag(panel_name, event):
    if len(event) < 3:
        return
    mx, my = event[1], event[2]
    state.app.components["dock_drag"] = {
        "panel": panel_name,
        "start_pos": (mx, my),
        "mouse_pos": (mx, my),
        "target_group": None,
        "target_rect": None,
        "drop_zones": None,
        "zone": None,
        "preview_rect": None,
    }


def on_dock_drag(dock_drag, event):
    if len(event) < 3 or not hasattr(state, "dock_tree"):
        return
    mx, my = event[1], event[2]
    dock_drag["mouse_pos"] = (mx, my)
    dragged = dock_drag.get("panel")

    best_group = None
    for group in state.dock_tree.all_tab_groups():
        if group.panels == [dragged]:
            continue
        gx, gy, gw, gh = group.rect
        if gx <= mx < gx + gw and gy <= my < gy + gh:
            best_group = group
            break

    if best_group is not None:
        target_rect = best_group.content_rect
        zones = DockTree.get_dock_drop_zones(target_rect)
        active_zone = None
        if contains_box(zones["center"], mx, my):
            active_zone = "center"
        elif contains_box(zones["left"], mx, my):
            active_zone = "left"
        elif contains_box(zones["right"], mx, my):
            active_zone = "right"
        elif contains_box(zones["top"], mx, my):
            active_zone = "top"
        elif contains_box(zones["bottom"], mx, my):
            active_zone = "bottom"
        else:
            tx, ty, tw, th = target_rect
            rel_x = (mx - tx) / max(1, tw)
            rel_y = (my - ty) / max(1, th)
            if 0.25 <= rel_x <= 0.75 and 0.25 <= rel_y <= 0.75:
                active_zone = "center"
            elif rel_x < 0.25:
                active_zone = "left"
            elif rel_x > 0.75:
                active_zone = "right"
            elif rel_y < 0.25:
                active_zone = "top"
            else:
                active_zone = "bottom"

        dock_drag["target_group"] = best_group
        dock_drag["target_rect"] = target_rect
        dock_drag["drop_zones"] = zones
        dock_drag["zone"] = active_zone
        dock_drag["preview_rect"] = DockTree.get_dock_preview_rect(target_rect, active_zone) if active_zone else None
    else:
        dock_drag["target_group"] = None
        dock_drag["target_rect"] = None
        dock_drag["drop_zones"] = None
        dock_drag["zone"] = None
        dock_drag["preview_rect"] = None


def on_dock_drop(dock_drag, event):
    dragged = dock_drag.get("panel")
    target_group = dock_drag.get("target_group")
    zone = dock_drag.get("zone")

    if dragged and target_group and zone and hasattr(state, "dock_tree"):
        success = state.dock_tree.dock_panel(dragged, target_group, zone)
        if success:
            display_name = dragged.replace("_", " ").title()
            message(f"Docked {display_name} ({zone})")
            save_editor_project()
    layout()
    sync_all_editor_panels()


def sync_all_editor_panels():
    fn_h = getattr(state, "hierarchy_sync", None)
    if fn_h and fn_h is not hierarchy_sync:
        fn_h()
    fn_f = getattr(state, "file_explorer_sync", None)
    if fn_f:
        fn_f()
    fn_i = getattr(state, "inspector_sync", None)
    if fn_i and fn_i is not inspector_sync:
        fn_i()


def close_panel(panel_name):
    if hasattr(state, "dock_tree"):
        state.dock_tree.remove_panel(panel_name)
    display_name = panel_name.replace("_", " ").title()
    message(f"Closed {display_name} (restore from View menu)")
    layout()
    sync_all_editor_panels()
    save_editor_project()


def toggle_panel_view(panel_name):
    if not hasattr(state, "dock_tree"):
        return
    group = state.dock_tree.find_tab_group_with_panel(panel_name)
    if group:
        close_panel(panel_name)
    else:
        state.dock_tree.restore_panel_default(panel_name)
        display_name = panel_name.replace("_", " ").title()
        message(f"Restored {display_name}")
        layout()
        sync_all_editor_panels()
        save_editor_project()


def reset_default_layout():
    state.dock_tree = DockTree()
    state.app.components["left_column_w"] = 370
    state.hierarchy.components["panel_h"] = 240
    state.code_panel.components["split_y"] = max(330, int(state.window.height * 0.45))
    message("Reset editor layout to default")
    layout()
    sync_all_editor_panels()
    save_editor_project()


def select_dock_tab(group, index, panel_name):
    group.active = index
    if panel_name == "hierarchy":
        state.active_left_tab = "hierarchy"
    elif panel_name == "files":
        state.active_left_tab = "files"
    layout()
    sync_all_editor_panels()


def layout():
    w, h = (state.window.width, state.window.height)
    put(state.app, x=0, y=0, w=w, h=h)
    put(state.background, x=0, y=0, w=w, h=h)

    # Header layout (docked top with padding)
    header_h = state.header.components.get("h", 44)
    put(state.header, x=0, y=0, w=w, h=header_h)
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

    # Top menu bar buttons layout
    if hasattr(state, "menu_file_btn"):
        put(state.menu_file_btn, x=64, y=8, w=48, h=28)
    if hasattr(state, "menu_edit_btn"):
        put(state.menu_edit_btn, x=116, y=8, w=48, h=28)
    if hasattr(state, "menu_view_btn"):
        put(state.menu_view_btn, x=168, y=8, w=54, h=28)

    # Status bar layout (docked bottom with margin)
    status_m = parse_box(state.status.components.get("margin", (0, 16, 5, 16)))
    status_h = state.status.components.get("h", 20)
    status_y = h - status_m[2] - status_h
    put(state.status, x=status_m[3], y=status_y, w=max(0, w - status_m[3] - status_m[1]), h=status_h, text=state.app.status)

    top_y = state.header.y + state.header.h
    ws_x = 8
    ws_y = top_y + 4
    ws_w = max(100, w - 16)
    ws_h = max(100, status_y - ws_y - 4)



    if hasattr(state, "dock_tree") and state.dock_tree.is_default():
        left_col_w = state.app.components.get("left_column_w", 370)
        panel_h = state.hierarchy.components.get("panel_h", 240)
        split_y = state.code_panel.components.get("split_y", max(330, int(h * 0.45)))
        group_hf = state.dock_tree.find_tab_group_with_panel("hierarchy")
        panel_rects = state.dock_tree.compute_default_layout(
            w=w,
            h=h,
            header_h=header_h,
            status_h=status_h,
            status_m_bottom=status_m[2],
            left_col_w=left_col_w,
            panel_h=panel_h,
            split_y=split_y,
        )
        split_main = state.dock_tree.find_node("split_main")
        split_left = state.dock_tree.find_node("split_left")
        split_right = state.dock_tree.find_node("split_right")
    else:
        split_main = state.dock_tree.find_node("split_main")
        split_left = state.dock_tree.find_node("split_left")
        split_right = state.dock_tree.find_node("split_right")
        panel_rects = state.dock_tree.compute_layout(ws_x, ws_y, ws_w, ws_h) if hasattr(state, "dock_tree") else {}

    # Legacy header tab buttons hidden — dynamic tab buttons on each group replace them
    put(state.tab_hierarchy, visible=False)
    put(state.tab_files, visible=False)

    # Panels layout
    if state.hierarchy.components.get("dock") == "float":
        put(state.hierarchy, visible=True)
    elif "hierarchy" in panel_rects:
        hx, hy, hw, hh = panel_rects["hierarchy"]
        put(state.hierarchy, visible=True, x=hx, y=hy, w=hw, h=hh)
    else:
        put(state.hierarchy, visible=False)

    if hasattr(state, "file_explorer"):
        if state.file_explorer.components.get("dock") == "float":
            put(state.file_explorer, visible=True)
        elif "files" in panel_rects:
            fx, fy, fw, fh = panel_rects["files"]
            put(state.file_explorer, visible=True, x=fx, y=fy, w=fw, h=fh)
        else:
            put(state.file_explorer, visible=False)

    if state.inspector.components.get("dock") == "float":
        pass
    elif "inspector" in panel_rects:
        ix, iy, iw, ih = panel_rects["inspector"]
        put(state.inspector, visible=True, x=ix, y=iy, w=iw, h=ih)
    else:
        put(state.inspector, visible=False)

    if state.viewport.components.get("dock") == "float":
        pass
    elif "viewport" in panel_rects:
        vx, vy, vw, vh = panel_rects["viewport"]
        group = state.dock_tree.find_tab_group_with_panel('viewport')
        px, py, pw, ph = group.rect
        content_y = max(vy, group.tab_bar_rect[1] + group.tab_bar_rect[3]) + 6
        content_bottom = py + ph - 26
        put(state.viewport_panel, visible=True, x=px, y=py, w=pw, h=ph)
        put(state.zoom_label, visible=True, x=px + 8, y=py + ph - 22, w=max(0, pw - 16), h=18,
            text=f'WORLD  /  {state.camera.zoom:.0f} px per metre  /  drag to pan  /  scroll to zoom')
        put(state.viewport, visible=True, x=px + 6, y=content_y, w=max(0, pw - 12), h=max(0, content_bottom-content_y))
    else:
        put(state.zoom_label, visible=False)
        put(state.viewport, visible=False)
        put(state.viewport_panel, visible=False)

    if state.code_panel.components.get("dock") == "float":
        pass
    elif "code_panel" in panel_rects:
        cx, cy, cw, ch = panel_rects["code_panel"]
        put(state.code_panel, visible=True, x=cx, y=cy, w=cw, h=ch)
        cp = state.code_panel
        c_pad = parse_box(cp.components.get("padding", (8, 12, 8, 12)))
        tb_y = cy + 32
        if state.ui.focused is not state.path_field and not state.path_field.components.get("readonly", True):
            state.path_field.components["readonly"] = True
            state.path_field.components["ink"] = (160, 180, 205)
            state.path_field.on_commit = None
            if state._saved_source:
                state.path_field.buffer = TextBuffer(state._saved_source[0])
        put(state.path_field, x=cx + c_pad[3], y=tb_y, w=max(130, cw - c_pad[3] - c_pad[1]), h=28)
        for button in (state.new_button, state.open_button, state.save_button, state.attach_button):
            put(button, visible=False)
        put(state.code, x=cx + c_pad[3], y=cy + 68, w=max(0, cw - c_pad[3] - c_pad[1]), h=max(0, ch - 100))
        put(state.code_info, x=cx + c_pad[3], y=cy + ch - 25, w=max(0, cw - c_pad[3] - c_pad[1]), h=20)
    else:
        put(state.code_panel, visible=False)

    # Panel close buttons (X)
    if hasattr(state, "close_hierarchy_btn"):
        if "hierarchy" in panel_rects and state.hierarchy.components.get("visible", True):
            hx, hy, hw, hh = panel_rects["hierarchy"]
            put(state.close_hierarchy_btn, visible=True, x=hx + hw - 24, y=hy + 4, w=18, h=18)
        else:
            put(state.close_hierarchy_btn, visible=False)

    if hasattr(state, "close_files_btn"):
        if "files" in panel_rects and state.file_explorer.components.get("visible", True):
            fx, fy, fw, fh = panel_rects["files"]
            put(state.close_files_btn, visible=True, x=fx + fw - 24, y=fy + 4, w=18, h=18)
        else:
            put(state.close_files_btn, visible=False)

    if hasattr(state, "close_inspector_btn"):
        if "inspector" in panel_rects and state.inspector.components.get("visible", True):
            ix, iy, iw, ih = panel_rects["inspector"]
            put(state.close_inspector_btn, visible=True, x=ix + iw - 24, y=iy + 4, w=18, h=18)
        else:
            put(state.close_inspector_btn, visible=False)

    if hasattr(state, "close_viewport_btn"):
        if "viewport" in panel_rects and state.viewport.components.get("visible", True):
            vx, vy, vw, vh = state.dock_tree.find_tab_group_with_panel('viewport').tab_bar_rect
            put(state.close_viewport_btn, visible=True, x=vx + vw - 24, y=vy + 4, w=18, h=18)
        else:
            put(state.close_viewport_btn, visible=False)

    if hasattr(state, "close_code_btn"):
        if "code_panel" in panel_rects and state.code_panel.components.get("visible", True):
            cx, cy, cw, ch = panel_rects["code_panel"]
            put(state.close_code_btn, visible=True, x=cx + cw - 24, y=cy + 4, w=18, h=18)
        else:
            put(state.close_code_btn, visible=False)

    # Dynamic Tab Buttons for all panel groups (title bars + tab selectors)
    panel_border = (38, 55, 75)
    for name,panel in (('hierarchy',state.hierarchy), ('files',state.file_explorer),
                       ('inspector',state.inspector), ('viewport',state.viewport_panel), ('code_panel',state.code_panel)):
        group = state.dock_tree.find_tab_group_with_panel(name)
        inset = max(0, group.tab_bar_rect[1]+group.tab_bar_rect[3]-panel.y) if group else 0
        put(panel, border_color=panel_border, border_width=2, border_inset=(inset,0,0,0), bevel=False)
    tab_btn_idx = 0
    if hasattr(state, "dock_tree") and hasattr(state, "dock_tab_buttons"):
        for group in state.dock_tree.all_tab_groups():
            if not group.tab_rects:
                continue
            for p_idx, (p_name, (tx, ty, tw, th)) in enumerate(group.tab_rects):
                if tab_btn_idx >= len(state.dock_tab_buttons):
                    btn = state.ui.button(state.app, f"DockTab_{tab_btn_idx}", "", lambda: None)
                    state.dock_tab_buttons.append(btn)
                btn = state.dock_tab_buttons[tab_btn_idx]
                tab_btn_idx += 1

                is_active = (p_idx == group.active)
                p_display = p_name.replace("_", " ").upper()
                if p_name == "code_panel":
                    p_display = "SYSTEM SOURCE"
                elif p_name == "files":
                    p_display = "PROJECT FILES"

                def _make_click(grp, idx, name):
                    return lambda: select_dock_tab(grp, idx, name)

                def _make_drag(name):
                    return lambda c, ev: start_panel_dock_drag(name, ev)

                act = _make_click(group, p_idx, p_name)
                btn.action = act
                btn.components["action"] = act
                btn.on_click = lambda c, ev, a=act: a()
                btn.on_drag = _make_drag(p_name)

                tab_ink = INK if is_active else MUTED
                tab_bg = panel_border if is_active else PANEL
                tab_hover = panel_border if is_active else (45, 60, 80)
                mouse = getattr(state.ui, 'mouse_pos', (-1, -1))
                hovered = tx <= mouse[0] < tx+tw and ty <= mouse[1] < ty+th
                put(btn, visible=True, x=tx, y=ty, w=tw, h=th, text=p_display,
                    normal_color=tab_bg, hover_color=tab_hover, ink=tab_ink, layer=4,
                    color=tab_hover if hovered else tab_bg, bevel=False, accent_color=None)

        for i in range(tab_btn_idx, len(state.dock_tab_buttons)):
            put(state.dock_tab_buttons[i], visible=False)

    # Splitters layout
    active_splitters = state.dock_tree.all_splitters() if hasattr(state, "dock_tree") else []
    active_node_ids = {node.id for (node, _, _) in active_splitters}

    if not split_left:
        for node, _, ori in active_splitters:
            if ori == "vertical" and node.id != getattr(split_right, "id", None):
                leaf_panels = []
                def _collect(n):
                    if isinstance(n, TabGroupNode): leaf_panels.extend(n.panels)
                    elif isinstance(n, SplitNode): _collect(n.first); _collect(n.second)
                _collect(node)
                if any(p in ("hierarchy", "files", "inspector") for p in leaf_panels) and not any(p in ("viewport", "code_panel") for p in leaf_panels):
                    split_left = node
                    break

    if not split_right:
        for node, _, ori in active_splitters:
            if ori == "vertical" and node is not split_left:
                leaf_panels = []
                def _collect(n):
                    if isinstance(n, TabGroupNode): leaf_panels.extend(n.panels)
                    elif isinstance(n, SplitNode): _collect(n.first); _collect(n.second)
                _collect(node)
                if any(p in ("viewport", "code_panel") for p in leaf_panels) and not any(p in ("hierarchy", "files", "inspector") for p in leaf_panels):
                    split_right = node
                    break

    claimed_ids = set()
    if split_main and split_main.id in active_node_ids and split_main.splitter_rect[2] > 0:
        sx, sy, sw, sh = split_main.splitter_rect
        put(state.col_splitter, visible=True, x=sx, y=sy, w=sw, h=sh)
        claimed_ids.add(split_main.id)
    else:
        put(state.col_splitter, visible=False)

    if split_left and split_left.id in active_node_ids and split_left.splitter_rect[3] > 0:
        sx, sy, sw, sh = split_left.splitter_rect
        put(state.hierarchy_splitter, visible=True, x=sx, y=sy, w=sw, h=sh)
        claimed_ids.add(split_left.id)
    else:
        put(state.hierarchy_splitter, visible=False)

    if split_right and split_right.id in active_node_ids and split_right.splitter_rect[3] > 0:
        sx, sy, sw, sh = split_right.splitter_rect
        put(state.code_splitter, visible=True, x=sx, y=sy, w=sw, h=sh)
        claimed_ids.add(split_right.id)
    else:
        put(state.code_splitter, visible=False)

    # Any additional dynamic splitters
    extra_idx = 0
    if hasattr(state, "extra_splitters"):
        for node, s_rect, orientation in active_splitters:
            if node.id in claimed_ids:
                continue
            if s_rect[2] <= 0 or s_rect[3] <= 0:
                continue
            if extra_idx >= len(state.extra_splitters):
                es = state.ui.splitter(state.app, f"ExtraSplitter_{extra_idx}", axis="x")
                state.extra_splitters.append(es)
            es = state.extra_splitters[extra_idx]
            extra_idx += 1

            axis = "x" if orientation == "horizontal" else "y"
            es.axis = axis

            def _make_drag(snode):
                def _on_drag(ctl, ev):
                    if len(ev) < 3:
                        return
                    nx, ny, nw, nh = snode.rect
                    if snode.orientation == "horizontal":
                        snode.ratio = max(0.05, min(0.95, (ev[1] - nx) / max(1, nw)))
                    else:
                        snode.ratio = max(0.05, min(0.95, (ev[2] - ny) / max(1, nh)))
                    layout()
                return _on_drag

            es.on_drag = _make_drag(node)
            put(es, visible=True, x=s_rect[0], y=s_rect[1], w=s_rect[2], h=s_rect[3])

        for i in range(extra_idx, len(state.extra_splitters)):
            put(state.extra_splitters[i], visible=False)


def start():
    global release
    release=bind_callbacks(system,state,{'close_panel':close_panel,'contains_box':contains_box,'layout':layout,'on_dock_drag':on_dock_drag,'on_dock_drop':on_dock_drop,'on_drag_code_splitter':on_drag_code_splitter,'on_drag_col_splitter':on_drag_col_splitter,'on_drag_hierarchy_splitter':on_drag_hierarchy_splitter,'reset_default_layout':reset_default_layout,'select_dock_tab':select_dock_tab,'start_panel_dock_drag':start_panel_dock_drag,'sync_all_editor_panels':sync_all_editor_panels,'toggle_panel_view':toggle_panel_view})

def stop():
    if "release" in globals(): release()
