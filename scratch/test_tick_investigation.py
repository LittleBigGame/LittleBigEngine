import sys
sys.path.insert(0, ".")
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Tick Investigation", width=1400, height=600)

from editor.theme import create_editor_theme

# Test variations:
# Var 1: IndentSpacing=14, FramePadding=(2, 4) vs (6, 4) vs (10, 4)
# Var 2: ItemInnerSpacing=(2, 4) vs (8, 4)
# Var 3: TreeLinesRounding=0 vs 2 vs 4
# Var 4: indent parameter on add_tree_node

with dpg.window(label="Investigation", width=1360, height=550):
    with dpg.group(horizontal=True):
        
        # Test 1: Baseline IndentSpacing 14, FramePadding (6, 4)
        with dpg.child_window(width=260, height=500):
            dpg.add_text("1. Baseline (FP=6, 4)")
            with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="PlayerNameTag", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Button", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)

        # Test 2: FramePadding=(2, 4)
        with dpg.child_window(width=260, height=500):
            with dpg.theme() as t2:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 14.0)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2, 4)
                    dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.bind_item_theme(dpg.last_item(), t2)
            dpg.add_text("2. FramePadding=(2, 4)")
            with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="PlayerNameTag", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Button", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)

        # Test 3: ItemInnerSpacing=(8, 4)
        with dpg.child_window(width=260, height=500):
            with dpg.theme() as t3:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 14.0)
                    dpg.add_theme_style(dpg.mvStyleVar_ItemInnerSpacing, 8, 4)
                    dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.bind_item_theme(dpg.last_item(), t3)
            dpg.add_text("3. ItemInnerSpacing=(8, 4)")
            with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="PlayerNameTag", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Button", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)

        # Test 4: TreeLinesRounding=0
        with dpg.child_window(width=260, height=500):
            with dpg.theme() as t4:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 14.0)
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 0.0)
                    dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.bind_item_theme(dpg.last_item(), t4)
            dpg.add_text("4. Rounding = 0.0")
            with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="PlayerNameTag", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Button", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)

        # Test 5: What if label has spaces or bullet?
        with dpg.child_window(width=260, height=500):
            with dpg.theme() as t5:
                with dpg.theme_component(dpg.mvAll):
                    dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 14.0)
                    dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
                    dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.bind_item_theme(dpg.last_item(), t5)
            dpg.add_text("5. Label with offset")
            with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="  PlayerNameTag", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="  Button", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/tick_investigation.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()
print("Saved tick_investigation.png")
