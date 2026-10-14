import sys
sys.path.insert(0, ".")
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Test Leaf Lines", width=900, height=600)

from editor.theme import create_editor_theme
theme = create_editor_theme()
dpg.bind_theme(theme)

with dpg.window(label="Tree Window", width=860, height=560):
    with dpg.group(horizontal=True):
        # Test A: All nodes have mvTreeLines_ToNodes, but leaf has mvTreeLines_None
        with dpg.child_window(width=400, height=520):
            dpg.add_text("Test A: ToNodes on parents, None on leaf")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_None)
                        dpg.add_tree_node(label="Excalibur", leaf=True, lines=dpg.mvTreeLines_None)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_None)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_None)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_None)

        # Test B: Last child has lines=mvTreeLines_ToNodes vs Full
        with dpg.child_window(width=400, height=520):
            dpg.add_text("Test B: Last parent node has lines=None")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    # What if GameGUI is the last child of Game, and has lines=ToNodes?
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_ToNodes)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.output_frame_buffer(file="f:/ModEngine/scratch/test_leaf_lines.png")
for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved test_leaf_lines.png")
