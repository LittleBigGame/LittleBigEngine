import sys
sys.path.insert(0, ".")
from pathlib import Path
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.hierarchy_panel import HierarchyPanel
from editor.theme import create_editor_theme
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="LittleBigEngine Hierarchy", width=360, height=560)
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

with dpg.window(label="Hierarchy Window", width=350, height=540, no_title_bar=True, no_move=True, no_resize=True, pos=(0, 0)):
    panel = HierarchyPanel(session, tag="window_hierarchy", use_vector_cards=True)
    panel.build()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/test_tree_fixed_corners.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved", out_scratch)
