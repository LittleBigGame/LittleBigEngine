import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Jump Out Tests", width=1280, height=600)

def make_test_theme(indent, rounding=0.0):
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, float(indent))
            dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (90, 100, 120, 255))
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
            dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, float(rounding))
    return t

configs = [
    ("A. 14px, Round=0 (Sharp)", 14.0, 0.0),
    ("B. 16px, Round=0 (Sharp)", 16.0, 0.0),
    ("C. 16px, Round=1 (Subtle)", 16.0, 1.0),
    ("D. 18px, Round=0 (Sharp)", 18.0, 0.0),
    ("E. 18px, Round=1.5 (Clean)", 18.0, 1.5),
]

with dpg.window(label="Jump Out Tests", width=1250, height=550):
    with dpg.group(horizontal=True):
        for label, ind, rnd in configs:
            th = make_test_theme(ind, rnd)
            with dpg.child_window(width=235, height=510):
                dpg.bind_item_theme(dpg.last_item(), th)
                dpg.add_text(label)
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

out_scratch = "f:/ModEngine/scratch/jump_out_tests.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
artifact_dir.mkdir(parents=True, exist_ok=True)
dest_path = artifact_dir / "jump_out_tests.png"
shutil.copy2(out_scratch, dest_path)

print(f"Saved {dest_path}")
