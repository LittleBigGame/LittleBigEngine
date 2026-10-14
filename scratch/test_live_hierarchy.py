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
dpg.create_viewport(title="Test", width=400, height=600)
theme = create_editor_theme()
dpg.bind_theme(theme)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

# Find GameGUI entity to select it
for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        session.select_entity(rid)
        break

with dpg.window(label="Hierarchy Window", width=380, height=580, no_title_bar=True, pos=(0, 0)):
    panel = HierarchyPanel(session, tag="window_hierarchy", use_vector_cards=True)
    panel.build()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

# Test clicking on a card using simulated callback
app_id = None
for rid in kernel.resources:
    if session.get_entity_name(rid) == "Application":
        app_id = rid
        break

print("Testing card click...")
row_dl = f"window_hierarchy_card_{app_id}_dl" # let's check registered user_data
# We'll test after updating hierarchy_panel.py!
dpg.destroy_context()
print("Context created and destroyed successfully.")
