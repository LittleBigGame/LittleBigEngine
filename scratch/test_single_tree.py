import sys
sys.path.insert(0, ".")
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Test Single Tree ToNodes", width=500, height=500)

from editor.theme import create_editor_theme
theme = create_editor_theme()
dpg.bind_theme(theme)

with dpg.window(label="Tree Window", width=460, height=460):
    with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
        dpg.add_tree_node(label="Player", leaf=True, lines=dpg.mvTreeLines_ToNodes)
        dpg.add_tree_node(label="Goblin", leaf=True, lines=dpg.mvTreeLines_ToNodes)
        with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
            dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
    with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
        dpg.add_tree_node(label="Hierarchy", leaf=True, lines=dpg.mvTreeLines_ToNodes)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.output_frame_buffer(file="f:/ModEngine/scratch/single_tonodes.png")
for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved single_tonodes.png")
