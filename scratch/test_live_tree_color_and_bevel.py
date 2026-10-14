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
dpg.create_viewport(title="Compare Hierarchy Lines", width=750, height=560)
theme = create_editor_theme()
dpg.bind_theme(theme)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        session.select_entity(rid)
        break

# Window 1: Cubic Arc 1px (R=3.5, color=(80, 85, 100))
# Let's test with custom drawlist rendering
with dpg.window(label="Tree with 1px Crisp (80, 85, 100)", width=350, height=540, pos=(0, 0)):
    panel = HierarchyPanel(session, tag="window_hierarchy", use_vector_cards=True)
    panel.build()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out = "f:/ModEngine/scratch/test_tree_color_check.png"
dpg.output_frame_buffer(file=out)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved to", out)
