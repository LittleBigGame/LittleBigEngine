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

with dpg.window(label="Hierarchy Window", width=380, height=580, no_title_bar=True, pos=(0, 0)):
    panel = HierarchyPanel(session, tag="window_hierarchy", use_vector_cards=True)
    panel.build()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

print("Testing clicks...")
for rid in list(kernel.resources.keys()):
    if rid in panel._node_tags:
        row_tag = panel._node_tags[rid]
        dl_tag = f"{row_tag}_dl"
        # Call _on_vector_card_clicked with a simulated handler invocation
        # Leaf node click:
        panel._on_vector_card_clicked(0, None, (rid, True, 8.0, dl_tag))
        assert session.selected_entity_id == rid, f"Expected {rid} to be selected"

dpg.destroy_context()
print("SUCCESS: All card clicks executed without KeyError!")
