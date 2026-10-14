import sys
sys.path.insert(0, ".")
from pathlib import Path
import tempfile
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.hierarchy_panel import HierarchyPanel
from editor.theme import create_editor_theme
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="Editor Hierarchy Test", width=600, height=800)

theme = create_editor_theme()
dpg.bind_theme(theme)

with tempfile.TemporaryDirectory() as tmpdir:
    kernel = Kernel(Path(tmpdir))
    populate_demo_world_if_empty(kernel)
    session = EditorSession(kernel)

    panel = HierarchyPanel(session, tag="test_hierarchy")
    panel.build()

    dpg.setup_dearpygui()
    dpg.show_viewport()

    for _ in range(5):
        dpg.render_dearpygui_frame()

    dpg.output_frame_buffer(file="f:/ModEngine/scratch/real_hierarchy_before.png")
    for _ in range(5):
        dpg.render_dearpygui_frame()

    dpg.destroy_context()
    print("Saved real_hierarchy_before.png")
