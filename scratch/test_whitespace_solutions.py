import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.theme import create_editor_theme

dpg.create_context()
dpg.create_viewport(title="Whitespace Solutions Comparison", width=1280, height=650)

# Theme with standard indent
theme_std = create_editor_theme()

# Theme with compact indent (14px)
with dpg.theme() as theme_compact:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 14.0)
        dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 2.0)

with dpg.window(label="Whitespace Solutions Comparison", width=1250, height=600):
    with dpg.group(horizontal=True):
        
        # Option A: Current (Default Indent ~21px, Empty Leaf Gap)
        with dpg.child_window(width=290, height=560):
            dpg.add_text("Option A: Current Baseline")
            dpg.add_text("(Default Indent, Empty Leaf Gap)", color=(130, 135, 145))
            dpg.add_separator()
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                        dpg.add_tree_node(label="Excalibur", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_ToNodes)

        # Option B: Compact Indent (14px) - Much tighter lines, no wasted gap
        with dpg.child_window(width=290, height=560):
            dpg.bind_item_theme(dpg.last_item(), theme_compact)
            dpg.add_text("Option B: Compact Indent (14px)")
            dpg.add_text("(Tight IDE-style nesting like VS Code)", color=(130, 135, 145))
            dpg.add_separator()
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                        dpg.add_tree_node(label="Excalibur", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="GoblinHP", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_ToNodes)

        # Option C: Subtle Bullet / Anchor on Leaves (bullet=True)
        with dpg.child_window(width=290, height=560):
            dpg.add_text("Option C: Subtle Bullet Anchor")
            dpg.add_text("(Leaves have bullet=True, no brackets)", color=(130, 135, 145))
            dpg.add_separator()
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
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

        # Option D: Clean Type Glyphs (e.g. Godot / Unity style)
        with dpg.child_window(width=290, height=560):
            dpg.add_text("Option D: Clean Type Glyphs")
            dpg.add_text("(Sleek ASCII type indicators: #, @, +)", color=(130, 135, 145))
            dpg.add_separator()
            with dpg.tree_node(label="Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="T  PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                        dpg.add_tree_node(label="*  Excalibur", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="=  GoblinHP", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label=">  Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="#  Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_ToNodes)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/whitespace_solutions.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

# Copy to artifacts directory
artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
artifact_dir.mkdir(parents=True, exist_ok=True)
dest_path = artifact_dir / "whitespace_solutions.png"
shutil.copy2(out_scratch, dest_path)

print(f"Comparison saved to {dest_path}")
