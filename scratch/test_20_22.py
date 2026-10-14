import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.hierarchy_panel import HierarchyPanel
from editor.theme import create_editor_theme, get_card_theme
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="20px vs 22px Test", width=800, height=600)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        session.select_entity(rid)
        break

def make_panel_window(indent_val, x_pos, tag_suffix):
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, float(indent_val))
            dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 2.0)
    
    with dpg.window(label=f"Indent {indent_val}px", width=360, height=540, pos=(x_pos, 0), no_title_bar=True):
        dpg.bind_item_theme(dpg.last_item(), th)
        p = HierarchyPanel(session, tag=f"window_hierarchy_{tag_suffix}")
        p.build()

make_panel_window(20.0, 0, "20")
make_panel_window(22.0, 380, "22")

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/tick_20_22.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
dest_path = artifact_dir / "tick_20_22.png"
shutil.copy2(out_scratch, dest_path)
print(f"Saved {dest_path}")
