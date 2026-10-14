import sys
sys.path.insert(0, ".")
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Tree Lines Variations", width=1200, height=600)

from editor.theme import create_editor_theme
theme = create_editor_theme()
dpg.bind_theme(theme)

with dpg.window(label="Tree Lines Variations", width=1180, height=560):
    with dpg.group(horizontal=True):
        # Var 1: All mvTreeLines_None
        with dpg.child_window(width=280, height=520):
            dpg.add_text("1. mvTreeLines_None")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_None, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_None, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_None, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_None)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_None, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_None)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_None, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_None)

        # Var 2: last child has lines=mvTreeLines_None
        with dpg.child_window(width=280, height=520):
            dpg.add_text("2. Last child None")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_Full, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_Full)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_None, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_None)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_None, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_None)

        # Var 3: leaves have lines=mvTreeLines_None
        with dpg.child_window(width=280, height=520):
            dpg.add_text("3. Leaves None")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_Full, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_None)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_Full, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_None)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_Full, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_None)

        # Var 4: span_full_width=False
        with dpg.child_window(width=280, height=520):
            dpg.add_text("4. span_full_width=False")
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_Full, default_open=True, span_full_width=False):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_Full, default_open=True, span_full_width=False):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_Full, default_open=True, span_full_width=False):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_Full, span_full_width=False)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_Full, default_open=True, span_full_width=False):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_Full, span_full_width=False)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_Full, default_open=True, span_full_width=False):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_Full, span_full_width=False)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(5):
    dpg.render_dearpygui_frame()

out_path = "f:/ModEngine/scratch/variations.png"
dpg.output_frame_buffer(file=out_path)
for _ in range(5):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved variations:", out_path)
