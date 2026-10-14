import sys
sys.path.insert(0, ".")
from pathlib import Path
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.app import EditorApp
from main import populate_demo_world_if_empty

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)

app = EditorApp(kernel=kernel, title="LittleBigEngine Test App")
app.setup_ui()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

# Test what happens when _on_vector_card_clicked is called
panel = app.hierarchy_panel
print("Hierarchy panel tag:", panel.tag)
print("Content tag exists:", dpg.does_item_exist(panel.content_tag))
print("Children of content_tag:", dpg.get_item_children(panel.content_tag, 1))

app.destroy()
print("App teardown successful")
