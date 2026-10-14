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
dpg.create_viewport(title="Test Aligned Hierarchy", width=400, height=650)

theme = create_editor_theme()
dpg.bind_theme(theme)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

# Find GameGUI to select it for comparison
gamegui_id = None
for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        gamegui_id = rid
        break
if gamegui_id is not None:
    session.select_entity(gamegui_id)

collapsed_entities = set()

def get_visible_tree_rows(session, collapsed_set):
    """Flatten visible hierarchy into ordered list with ancestor continuity tracking."""
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
                # Next continues: this depth continues if child is not last
                next_continues = list(parent_continues) + [not child_is_last]
                walk(child_id, depth + 1, child_is_last, next_continues)

    for i, root_id in enumerate(roots):
        walk(root_id, depth=0, is_last=(i == len(roots) - 1), parent_continues=[])

    return rows

rows = get_visible_tree_rows(session, collapsed_entities)

ROW_H = 22
X0 = 10.0
ARROW_W = 8.0
GAP = 6.0
INDENT = ARROW_W + GAP  # 14.0px
LINE_COLOR = (80, 85, 100, 255)
LINE_THICK = 1.0

total_h = max(400, len(rows) * ROW_H + 20)

with dpg.window(label="Hierarchy", width=360, height=600, no_title_bar=True, no_move=True, no_resize=True, pos=(0, 0)):
    # Header bar
    with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(init_width_or_weight=0.7)
        dpg.add_table_column(init_width_or_weight=0.3)
        with dpg.table_row():
            dpg.add_text("Hierarchy", color=(235, 240, 250, 255))
            dpg.add_button(label=">", width=22)

    dpg.add_input_text(hint="Search hierarchy...", width=-1)
    with dpg.group(horizontal=True):
        dpg.add_button(label="All", width=50)
        dpg.add_button(label="Game World", width=85)
        dpg.add_button(label="UI & Tools", width=85)
    dpg.add_separator()

    # Hierarchy container
    with dpg.child_window(width=-1, height=-1, border=True):
        dl = dpg.add_drawlist(width=340, height=total_h)

        for i, r in enumerate(rows):
            y_top = i * ROW_H
            y_mid = y_top + ROW_H / 2.0
            y_bot = y_top + ROW_H
            d = r["depth"]
            eid = r["entity_id"]
            is_selected = (session.selected_entity_id == eid)

            x_icon = X0 + d * INDENT
            x_text = x_icon + INDENT
            x_center = x_icon + ARROW_W / 2.0

            # 1. Background selection / hover highlight
            if is_selected:
                dpg.draw_rectangle(
                    (4.0, y_top + 1.0),
                    (330.0, y_bot - 1.0),
                    color=(0, 120, 255, 255),
                    fill=(0, 80, 160, 140),
                    rounding=3.0,
                    thickness=1.5,
                    parent=dl,
                )

            # 2. Ancestor vertical pass-through lines
            for k in range(d - 1):
                if k < len(r["ancestor_continues"]) and r["ancestor_continues"][k]:
                    x_anc = X0 + k * INDENT + ARROW_W / 2.0
                    dpg.draw_line(
                        (x_anc, y_top),
                        (x_anc, y_bot),
                        color=LINE_COLOR,
                        thickness=LINE_THICK,
                        parent=dl,
                    )

            # 3. Connection to immediate parent
            if d > 0:
                x_parent = X0 + (d - 1) * INDENT + ARROW_W / 2.0
                # Vertical line down from top of this row to middle
                dpg.draw_line(
                    (x_parent, y_top),
                    (x_parent, y_mid),
                    color=LINE_COLOR,
                    thickness=LINE_THICK,
                    parent=dl,
                )
                # Horizontal tick to child icon
                dpg.draw_line(
                    (x_parent, y_mid),
                    (x_icon - 1.0, y_mid),
                    color=LINE_COLOR,
                    thickness=LINE_THICK,
                    parent=dl,
                )
                # If not last child, vertical line continues down to bottom of row
                if not r["is_last"]:
                    dpg.draw_line(
                        (x_parent, y_mid),
                        (x_parent, y_bot),
                        color=LINE_COLOR,
                        thickness=LINE_THICK,
                        parent=dl,
                    )

            # 4. Icon: Triangle for parent, Circle for leaf
            if not r["is_leaf"]:
                # Parent node: Triangle
                tri_y = y_mid - 4.0
                tri_c = (220, 225, 235, 255) if is_selected else (190, 195, 205, 255)
                if r["is_expanded"]:
                    # ▼ Downward pointing triangle
                    p1 = (x_icon, tri_y + 2.0)
                    p2 = (x_icon + ARROW_W, tri_y + 2.0)
                    p3 = (x_icon + ARROW_W / 2.0, tri_y + 2.0 + ARROW_W * 0.7)
                    dpg.draw_triangle(p1, p2, p3, color=tri_c, fill=tri_c, parent=dl)
                else:
                    # ▶ Rightward pointing triangle
                    p1 = (x_icon + 1.5, tri_y)
                    p2 = (x_icon + 1.5, tri_y + ARROW_W)
                    p3 = (x_icon + 1.5 + ARROW_W * 0.7, tri_y + ARROW_W / 2.0)
                    dpg.draw_triangle(p1, p2, p3, color=tri_c, fill=tri_c, parent=dl)
            else:
                # Leaf node: Circle!
                cx = x_icon + ARROW_W / 2.0
                cy = y_mid
                if not is_selected:
                    # Hollow circle
                    dpg.draw_circle(
                        (cx, cy),
                        radius=3.5,
                        color=(150, 155, 165, 255),
                        thickness=1.4,
                        parent=dl,
                    )
                else:
                    # Selected circle: Outer blue ring + filled white core
                    dpg.draw_circle(
                        (cx, cy),
                        radius=4.0,
                        color=(0, 120, 255, 255),
                        thickness=1.5,
                        parent=dl,
                    )
                    dpg.draw_circle(
                        (cx, cy),
                        radius=2.0,
                        color=(255, 255, 255, 255),
                        fill=(255, 255, 255, 255),
                        parent=dl,
                    )

            # 5. Label text
            txt_color = (255, 255, 255, 255) if is_selected else (220, 225, 235, 255)
            dpg.draw_text(
                (x_text, y_mid - 7.0),
                r["name"],
                color=txt_color,
                size=13.0,
                parent=dl,
            )

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/test_aligned_hierarchy.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
dest_path = artifact_dir / "test_aligned_hierarchy.png"
shutil.copy2(out_scratch, dest_path)
print(f"Rendered to {dest_path}")
