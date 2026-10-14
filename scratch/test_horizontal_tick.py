import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Indent Spacing Tick Comparison", width=1280, height=550)

def make_theme(indent_val):
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, float(indent_val))
            dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (100, 110, 130, 255))
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 2.0)
    return t

indents = [14.0, 18.0, 22.0, 26.0]
themes = [make_theme(i) for i in indents]

with dpg.window(label="Comparison", width=1250, height=500):
    with dpg.group(horizontal=True):
        for ind, th in zip(indents, themes):
            with dpg.child_window(width=290, height=460):
                dpg.bind_item_theme(dpg.last_item(), th)
                dpg.add_text(f"IndentSpacing = {ind}px")
                dpg.add_separator()
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                        dpg.add_tree_node(label="Excalibur", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, bullet=True, lines=dpg.mvTreeLines_ToNodes)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/tick_comparison.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
artifact_dir.mkdir(parents=True, exist_ok=True)
dest_path = artifact_dir / "tick_comparison.png"
shutil.copy2(out_scratch, dest_path)

print(f"Saved to {dest_path}")
