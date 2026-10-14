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

print("Initial collapsed entities:", panel._collapsed_entities)

# Find entities
entities_by_name = {}
for rid in kernel.resources:
    name = session.get_entity_name(rid)
    if name:
        entities_by_name[name] = rid

print("Selecting GameGUI...")
session.select_entity(entities_by_name["GameGUI"])
# In the buggy version, selecting GameGUI caused _collapsed_entities to add every parent entity!
print("After selecting GameGUI, collapsed entities:", panel._collapsed_entities)
# It should still be empty (all expanded by default)
assert len(panel._collapsed_entities) == 0, f"Expected 0 collapsed entities, got {panel._collapsed_entities}"

# Now select Button
print("Selecting Button...")
session.select_entity(entities_by_name["Button"])
print("After selecting Button, collapsed entities:", panel._collapsed_entities)
assert len(panel._collapsed_entities) == 0, f"Expected 0 collapsed entities, got {panel._collapsed_entities}"

# Now collapse Player specifically via toggle
print("Collapsing Player...")
panel._toggle_expanded(entities_by_name["Player"])
assert entities_by_name["Player"] in panel._collapsed_entities
print("Collapsed entities:", panel._collapsed_entities)

# Now select GoblinHP
print("Selecting GoblinHP...")
session.select_entity(entities_by_name["GoblinHP"])
# Player should STILL be collapsed, but other parents (Application, Game, Goblin) should NOT be collapsed!
assert entities_by_name["Player"] in panel._collapsed_entities
assert entities_by_name["Game"] not in panel._collapsed_entities
assert entities_by_name["Application"] not in panel._collapsed_entities

dpg.destroy_context()
print("SELECTION COLLAPSE TEST PASSED! Tree does NOT collapse on selection!")
