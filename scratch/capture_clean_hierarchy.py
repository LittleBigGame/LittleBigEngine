import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
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

kernel = Kernel(Path("./Example World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

# Find GameGUI entity to select it like in user screenshot
gamegui_id = None
for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        gamegui_id = rid
        break

if gamegui_id is not None:
    session.select_entity(gamegui_id)

with dpg.window(label="Hierarchy Window", width=350, height=540, no_title_bar=True, no_move=True, no_resize=True, pos=(0, 0)):
    panel = HierarchyPanel(session, tag="window_hierarchy", use_vector_cards=True)
    panel.build()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/hierarchy_clean_pipes.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

# Copy to artifacts directory
artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
artifact_dir.mkdir(parents=True, exist_ok=True)
dest_path = artifact_dir / "hierarchy_clean_pipes.png"
shutil.copy2(out_scratch, dest_path)

print(f"Successfully generated and copied to {dest_path}")
