import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

dpg.create_context()
dpg.create_viewport(title="Whitespace Solutions Comparison v2", width=1280, height=650)

# Theme with standard indent
with dpg.theme() as theme_std:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 2.0)

# Theme with compact indent (14px)
with dpg.theme() as theme_compact:
    with dpg.theme_component(dpg.mvAll):
        dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing, 14.0)
        dpg.add_theme_color(dpg.mvThemeCol_TreeLines, (80, 85, 100, 255))
        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesSize, 1.0)
        dpg.add_theme_style(dpg.mvStyleVar_TreeLinesRounding, 2.0)

with dpg.window(label="Whitespace Solutions Comparison", width=1250, height=600):
    with dpg.group(horizontal=True):
        
        # 1: Option A (Current Baseline)
        with dpg.child_window(width=290, height=560):
            dpg.bind_item_theme(dpg.last_item(), theme_std)
            dpg.add_text("1. Current Baseline")
            dpg.add_text("(Default Indent, Empty Gap)", color=(130, 135, 145))
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

        # 2: Option B (Compact Indent 14px only)
        with dpg.child_window(width=290, height=560):
            dpg.bind_item_theme(dpg.last_item(), theme_compact)
            dpg.add_text("2. Compact Indent (14px)")
            dpg.add_text("(Tight IDE nesting, no extra glyphs)", color=(130, 135, 145))
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

        # 3: Option C (Compact Indent 14px + Subtle Bullet on Leaves)
        with dpg.child_window(width=290, height=560):
            dpg.bind_item_theme(dpg.last_item(), theme_compact)
            dpg.add_text("3. Compact Indent + Bullet Anchor")
            dpg.add_text("(14px indent, tiny bullet on leaves)", color=(130, 135, 145))
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

        # 4: Option D (Compact Indent 14px + Entity Type Badges - Godot/Blender style)
        with dpg.child_window(width=290, height=560):
            dpg.bind_item_theme(dpg.last_item(), theme_compact)
            dpg.add_text("4. Compact + Entity Type Tags")
            dpg.add_text("(Godot-style clean type prefixes)", color=(130, 135, 145))
            dpg.add_separator()
            with dpg.tree_node(label="App  Application", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                with dpg.tree_node(label="Wrld Game", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    with dpg.tree_node(label="Act  Player", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Txt  PlayerNameTag", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                        dpg.add_tree_node(label="Item Excalibur", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="Act  Goblin", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="UI   GoblinHP", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                    with dpg.tree_node(label="UI   GameGUI", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                        dpg.add_tree_node(label="Btn  Button", leaf=True, lines=dpg.mvTreeLines_ToNodes)
                with dpg.tree_node(label="Tool Editor", lines=dpg.mvTreeLines_ToNodes, default_open=True):
                    dpg.add_tree_node(label="Pnl  Hierarchy Panel", leaf=True, lines=dpg.mvTreeLines_ToNodes)

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/whitespace_solutions_v2.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

# Copy to artifacts directory
artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
artifact_dir.mkdir(parents=True, exist_ok=True)
dest_path = artifact_dir / "whitespace_solutions_v2.png"
shutil.copy2(out_scratch, dest_path)

print(f"Comparison v2 saved to {dest_path}")
