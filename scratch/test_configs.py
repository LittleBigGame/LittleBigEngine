import sys
sys.path.insert(0, ".")
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Test Configurations", width=1200, height=700)

from editor.theme import create_editor_theme
theme = create_editor_theme()
dpg.bind_theme(theme)

with dpg.window(label="Tree Window", width=1160, height=660):
    with dpg.group(horizontal=True):
        # Config 1: What if GameGUI has no lines?
        with dpg.child_window(width=270, height=620):
            dpg.add_text("Config 1: GameGUI None")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_Full, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_Full)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_Full)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_None, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_None)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_Full)

        # Config 2: What if indent=0 on GameGUI?
        with dpg.child_window(width=270, height=620):
            dpg.add_text("Config 2: indent adjustments")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_Full, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_Full)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_Full)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_Full)

        # Config 3: What if we wrap children in an unindented group or spacing?
        with dpg.child_window(width=270, height=620):
            dpg.add_text("Config 3: unindented group")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_Full, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_Full)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_Full)
                    # GameGUI wrapped
                    with dpg.group():
                        with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_Full, default_open=True):
                            dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_Full)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_Full)

        # Config 4: What if root Application is NOT a tree_node or view root?
        with dpg.child_window(width=270, height=620):
            dpg.add_text("Config 4: no Application parent")
            with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True):
                with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_Full)
                with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_Full)
                with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_Full)
            with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_Full, default_open=True):
                dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_Full)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.output_frame_buffer(file="f:/ModEngine/scratch/configs.png")
for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved configs.png")
