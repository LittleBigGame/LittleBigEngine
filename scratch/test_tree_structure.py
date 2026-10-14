import sys
sys.path.insert(0, ".")
from pathlib import Path
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.theme import create_editor_theme
from editor.vector_glyphs import draw_radio_dot, draw_chevron_down, draw_chevron_right
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="Tree Rendering Test", width=800, height=700)

theme = create_editor_theme()
dpg.bind_theme(theme)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

# Let's inspect the demo world entity hierarchy
print("Root entities:", [session.get_entity_name(r) for r in session.get_root_entities()])
for r in session.get_root_entities():
    print("  Root:", session.get_entity_name(r))
    for c in session.get_children(r):
        print("    Child:", session.get_entity_name(c))
        for gc in session.get_children(c):
            print("      Grandchild:", session.get_entity_name(gc))

dpg.destroy_context()
