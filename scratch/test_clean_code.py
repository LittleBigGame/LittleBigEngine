import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.theme import create_editor_theme
from editor.vector_glyphs import draw_chevron_down, draw_chevron_right, draw_radio_dot
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="Test Clean Tree Rendering", width=380, height=600)

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

# Constants
ROW_HEIGHT = 22.0
ROW_Y_MID = ROW_HEIGHT / 2.0
TREE_X0 = 8.0
ARROW_WIDTH = 8.0
ARROW_GAP = 6.0
TREE_INDENT = ARROW_WIDTH + ARROW_GAP  # 14.0px
PIPE_LINE_COLOR = (55, 60, 72, 255)    # Subtle, darker pipe color
PIPE_LINE_THICKNESS = 1.0

with dpg.theme() as content_theme:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

with dpg.window(label="Hierarchy Window", width=350, height=540, no_title_bar=True, no_move=True, no_resize=True, pos=(0, 0)):
    dpg.add_text("Hierarchy")
    dpg.add_input_text(hint="Search hierarchy...", width=-1)
    with dpg.group(horizontal=True):
        dpg.add_button(label="All", width=50)
        dpg.add_button(label="Game World", width=85)
        dpg.add_button(label="UI & Tools", width=85)
    dpg.add_separator()

    with dpg.child_window(width=-1, height=-1, border=True) as cw:
        dpg.bind_item_theme(cw, content_theme)

        def render_node(entity_id, depth=0, is_last=False, ancestor_continues=()):
            name = session.get_entity_name(entity_id)
            children = session.get_children(entity_id)
            child_count = len(children)
            is_leaf = (child_count == 0)
            is_selected = (session.selected_entity_id == entity_id)

            x_icon = TREE_X0 + depth * TREE_INDENT
            x_center = x_icon + ARROW_WIDTH / 2.0
            x_text = x_icon + TREE_INDENT

            with dpg.group(horizontal=True, label=name):
                dl = dpg.add_drawlist(width=340, height=int(ROW_HEIGHT))

                # 1. Background selection highlight
                if is_selected:
                    dpg.draw_rectangle(
                        (4.0, 1.0),
                        (330.0, ROW_HEIGHT - 1.0),
                        color=(0, 120, 255, 255),
                        fill=(0, 80, 160, 140),
                        rounding=3.0,
                        thickness=1.5,
                        parent=dl,
                    )

                # 2. Ancestor vertical pass-through lines
                for k, continues in enumerate(ancestor_continues[:depth - 1]):
                    if continues:
                        x_anc = TREE_X0 + k * TREE_INDENT + ARROW_WIDTH / 2.0
                        dpg.draw_line(
                            (x_anc, 0.0),
                            (x_anc, ROW_HEIGHT),
                            color=PIPE_LINE_COLOR,
                            thickness=PIPE_LINE_THICKNESS,
                            parent=dl,
                        )

                # 3. Connection to immediate parent (passes behind arrow/circle center)
                if depth > 0:
                    x_parent = TREE_X0 + (depth - 1) * TREE_INDENT + ARROW_WIDTH / 2.0
                    dpg.draw_line(
                        (x_parent, 0.0),
                        (x_parent, ROW_Y_MID),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )
                    # Horizontal tick directly connects to arrow/circle center behind glyph
                    dpg.draw_line(
                        (x_parent, ROW_Y_MID),
                        (x_center, ROW_Y_MID),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )
                    if not is_last:
                        dpg.draw_line(
                            (x_parent, ROW_Y_MID),
                            (x_parent, ROW_HEIGHT),
                            color=PIPE_LINE_COLOR,
                            thickness=PIPE_LINE_THICKNESS,
                            parent=dl,
                        )

                # 4. Icon
                if not is_leaf:
                    tri_y = ROW_Y_MID - 4.0
                    color = (230, 235, 245, 255) if is_selected else (190, 195, 205, 255)
                    draw_chevron_down(dl, (x_icon, tri_y), color=color, size=ARROW_WIDTH)
                else:
                    draw_radio_dot(
                        dl,
                        center=(x_center, ROW_Y_MID),
                        selected=is_selected,
                        color=(0, 120, 255, 255),
                        radius=3.5,
                    )

                # 5. Label
                txt_color = (255, 255, 255, 255) if is_selected else (220, 225, 235, 255)
                dpg.draw_text(
                    (x_text, ROW_Y_MID - 7.0),
                    name,
                    color=txt_color,
                    size=13.0,
                    parent=dl,
                )

            # Children
            for i, child_id in enumerate(children):
                c_is_last = (i == child_count - 1)
                next_anc = ancestor_continues + (not c_is_last,)
                render_node(child_id, depth=depth + 1, is_last=c_is_last, ancestor_continues=next_anc)

        for root in session.get_root_entities():
            render_node(root)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/test_clean_code.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
dest_path = artifact_dir / "test_clean_code.png"
shutil.copy2(out_scratch, dest_path)
print(f"Rendered to {dest_path}")
