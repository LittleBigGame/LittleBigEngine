import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.theme import create_editor_theme
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="Compare Approaches", width=800, height=650)

theme = create_editor_theme()
dpg.bind_theme(theme)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

# Select GameGUI
for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        session.select_entity(rid)
        break

# Setup theme with ItemSpacing = (0, 0)
with dpg.theme() as zero_spacing_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

def get_visible_tree_rows(session, collapsed_set):
    roots = session.get_root_entities()
    rows = []
    def walk(entity_id, depth, is_last, parent_continues):
        name = session.get_entity_name(entity_id)
        children = session.get_children(entity_id)
        is_leaf = (len(children) == 0)
        is_expanded = (entity_id not in collapsed_set) and not is_leaf

        rows.append({
            "entity_id": entity_id,
            "name": name,
            "depth": depth,
            "is_leaf": is_leaf,
            "is_expanded": is_expanded,
            "is_last": is_last,
            "ancestor_continues": list(parent_continues),
            "children_count": len(children),
        })

        if is_expanded:
            for idx, child_id in enumerate(children):
                child_is_last = (idx == len(children) - 1)
                next_continues = list(parent_continues) + [not child_is_last]
                walk(child_id, depth + 1, child_is_last, next_continues)

    for i, root_id in enumerate(roots):
        walk(root_id, depth=0, is_last=(i == len(roots) - 1), parent_continues=[])
    return rows

rows = get_visible_tree_rows(session, set())

ROW_H = 22
X0 = 10.0
ARROW_W = 8.0
GAP = 6.0
INDENT = 14.0
LINE_COLOR = (80, 85, 100, 255)
LINE_THICK = 1.0

with dpg.window(label="Comparison Window", width=780, height=600):
    with dpg.group(horizontal=True):
        # 1. Single Unified Drawlist
        with dpg.child_window(width=370, height=560, border=True) as cw1:
            dpg.add_text("Approach 1: Single Unified Drawlist")
            dl1 = dpg.add_drawlist(width=350, height=len(rows) * ROW_H + 20)
            for i, r in enumerate(rows):
                y_top = i * ROW_H
                y_mid = y_top + ROW_H / 2.0
                y_bot = y_top + ROW_H
                d = r["depth"]
                eid = r["entity_id"]
                is_selected = (session.selected_entity_id == eid)
                x_icon = X0 + d * INDENT
                x_text = x_icon + INDENT

                if is_selected:
                    dpg.draw_rectangle((4.0, y_top + 1.0), (340.0, y_bot - 1.0),
                                       color=(0, 120, 255, 255), fill=(0, 80, 160, 140),
                                       rounding=3.0, thickness=1.5, parent=dl1)

                for k in range(d - 1):
                    if k < len(r["ancestor_continues"]) and r["ancestor_continues"][k]:
                        x_anc = X0 + k * INDENT + ARROW_W / 2.0
                        dpg.draw_line((x_anc, y_top), (x_anc, y_bot), color=LINE_COLOR, thickness=LINE_THICK, parent=dl1)

                if d > 0:
                    x_parent = X0 + (d - 1) * INDENT + ARROW_W / 2.0
                    dpg.draw_line((x_parent, y_top), (x_parent, y_mid), color=LINE_COLOR, thickness=LINE_THICK, parent=dl1)
                    # Line touches icon directly
                    dest_x = x_icon if not r["is_leaf"] else (x_icon + ARROW_W / 2.0 - 3.5)
                    dpg.draw_line((x_parent, y_mid), (dest_x, y_mid), color=LINE_COLOR, thickness=LINE_THICK, parent=dl1)
                    if not r["is_last"]:
                        dpg.draw_line((x_parent, y_mid), (x_parent, y_bot), color=LINE_COLOR, thickness=LINE_THICK, parent=dl1)

                if not r["is_leaf"]:
                    tri_y = y_mid - 4.0
                    tri_c = (220, 225, 235, 255) if is_selected else (190, 195, 205, 255)
                    if r["is_expanded"]:
                        p1 = (x_icon, tri_y + 2.0)
                        p2 = (x_icon + ARROW_W, tri_y + 2.0)
                        p3 = (x_icon + ARROW_W / 2.0, tri_y + 2.0 + ARROW_W * 0.7)
                        dpg.draw_triangle(p1, p2, p3, color=tri_c, fill=tri_c, parent=dl1)
                    else:
                        p1 = (x_icon + 1.5, tri_y)
                        p2 = (x_icon + 1.5, tri_y + ARROW_W)
                        p3 = (x_icon + 1.5 + ARROW_W * 0.7, tri_y + ARROW_W / 2.0)
                        dpg.draw_triangle(p1, p2, p3, color=tri_c, fill=tri_c, parent=dl1)
                else:
                    cx = x_icon + ARROW_W / 2.0
                    cy = y_mid
                    if not is_selected:
                        dpg.draw_circle((cx, cy), radius=3.5, color=(150, 155, 165, 255), thickness=1.4, parent=dl1)
                    else:
                        dpg.draw_circle((cx, cy), radius=4.0, color=(0, 120, 255, 255), thickness=1.5, parent=dl1)
                        dpg.draw_circle((cx, cy), radius=2.0, color=(255, 255, 255, 255), fill=(255, 255, 255, 255), parent=dl1)

                txt_color = (255, 255, 255, 255) if is_selected else (220, 225, 235, 255)
                dpg.draw_text((x_text, y_mid - 7.0), r["name"], color=txt_color, size=13.0, parent=dl1)

        # 2. Per-Row Item with Zero Spacing
        with dpg.child_window(width=370, height=560, border=True) as cw2:
            dpg.bind_item_theme(cw2, zero_spacing_theme)
            dpg.add_text("Approach 2: Per-Row Drawlist (Zero Spacing)")
            for i, r in enumerate(rows):
                eid = r["entity_id"]
                name = r["name"]
                d = r["depth"]
                is_selected = (session.selected_entity_id == eid)
                x_icon = X0 + d * INDENT
                x_text = x_icon + INDENT
                y_mid = ROW_H / 2.0

                with dpg.group(horizontal=True, label=name) as grp:
                    dl = dpg.add_drawlist(width=350, height=ROW_H)
                    if is_selected:
                        dpg.draw_rectangle((4.0, 1.0), (340.0, ROW_H - 1.0),
                                           color=(0, 120, 255, 255), fill=(0, 80, 160, 140),
                                           rounding=3.0, thickness=1.5, parent=dl)

                    for k in range(d - 1):
                        if k < len(r["ancestor_continues"]) and r["ancestor_continues"][k]:
                            x_anc = X0 + k * INDENT + ARROW_W / 2.0
                            dpg.draw_line((x_anc, 0), (x_anc, ROW_H), color=LINE_COLOR, thickness=LINE_THICK, parent=dl)

                    if d > 0:
                        x_parent = X0 + (d - 1) * INDENT + ARROW_W / 2.0
                        dpg.draw_line((x_parent, 0), (x_parent, y_mid), color=LINE_COLOR, thickness=LINE_THICK, parent=dl)
                        dest_x = x_icon if not r["is_leaf"] else (x_icon + ARROW_W / 2.0 - 3.5)
                        dpg.draw_line((x_parent, y_mid), (dest_x, y_mid), color=LINE_COLOR, thickness=LINE_THICK, parent=dl)
                        if not r["is_last"]:
                            dpg.draw_line((x_parent, y_mid), (x_parent, ROW_H), color=LINE_COLOR, thickness=LINE_THICK, parent=dl)

                    if not r["is_leaf"]:
                        tri_y = y_mid - 4.0
                        tri_c = (220, 225, 235, 255) if is_selected else (190, 195, 205, 255)
                        if r["is_expanded"]:
                            p1 = (x_icon, tri_y + 2.0)
                            p2 = (x_icon + ARROW_W, tri_y + 2.0)
                            p3 = (x_icon + ARROW_W / 2.0, tri_y + 2.0 + ARROW_W * 0.7)
                            dpg.draw_triangle(p1, p2, p3, color=tri_c, fill=tri_c, parent=dl)
                        else:
                            p1 = (x_icon + 1.5, tri_y)
                            p2 = (x_icon + 1.5, tri_y + ARROW_W)
                            p3 = (x_icon + 1.5 + ARROW_W * 0.7, tri_y + ARROW_W / 2.0)
                            dpg.draw_triangle(p1, p2, p3, color=tri_c, fill=tri_c, parent=dl)
                    else:
                        cx = x_icon + ARROW_W / 2.0
                        cy = y_mid
                        if not is_selected:
                            dpg.draw_circle((cx, cy), radius=3.5, color=(150, 155, 165, 255), thickness=1.4, parent=dl)
                        else:
                            dpg.draw_circle((cx, cy), radius=4.0, color=(0, 120, 255, 255), thickness=1.5, parent=dl)
                            dpg.draw_circle((cx, cy), radius=2.0, color=(255, 255, 255, 255), fill=(255, 255, 255, 255), parent=dl)

                    txt_color = (255, 255, 255, 255) if is_selected else (220, 225, 235, 255)
                    dpg.draw_text((x_text, y_mid - 7.0), name, color=txt_color, size=13.0, parent=dl)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/compare_approaches.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
dest_path = artifact_dir / "compare_approaches.png"
shutil.copy2(out_scratch, dest_path)
print(f"Saved comparison to {dest_path}")
