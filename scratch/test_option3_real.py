import sys
sys.path.insert(0, ".")
from pathlib import Path
import shutil
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.hierarchy_panel import HierarchyPanel
from editor.theme import create_editor_theme, get_card_theme
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="Option 3 Real Test", width=360, height=560)

theme = create_editor_theme()
dpg.bind_theme(theme)

kernel = Kernel(Path("./Test World"))
populate_demo_world_if_empty(kernel)
session = EditorSession(kernel)

# Select GameGUI to see highlighting
for rid in kernel.resources:
    if session.get_entity_name(rid) == "GameGUI":
        session.select_entity(rid)
        break

# Custom HierarchyPanel with bullet=True on leaf nodes
class Option3HierarchyPanel(HierarchyPanel):
    def _render_node(self, entity_id, parent_tag, depth=0, is_last=False):
        name = self.session.get_entity_name(entity_id)
        children = self.session.get_children(entity_id)
        if self._subtree_filter == "Game World":
            children = [c for c in children if not self._is_ui_entity(c)]
        child_count = len(children)
        is_selected = (self.session.selected_entity_id == entity_id)

        card_theme = get_card_theme(selected=is_selected)
        is_expanded = (entity_id not in self._collapsed_entities)

        if child_count > 0:
            node_tag = dpg.add_tree_node(
                label=name,
                parent=parent_tag,
                default_open=is_expanded,
                open_on_arrow=True,
                selectable=True,
                span_full_width=True,
                lines=dpg.mvTreeLines_ToNodes,
            )
            self._node_tags[entity_id] = node_tag
            dpg.bind_item_theme(node_tag, card_theme)
            self._attach_item_handlers(node_tag, entity_id, is_tree_node=True)

            for i, child_id in enumerate(children):
                self._render_node(
                    child_id,
                    parent_tag=node_tag,
                    depth=depth + 1,
                    is_last=(i == child_count - 1),
                )
        else:
            leaf_tag = dpg.add_tree_node(
                label=name,
                parent=parent_tag,
                leaf=True,
                bullet=True,
                selectable=True,
                span_full_width=True,
                lines=dpg.mvTreeLines_ToNodes,
            )
            self._node_tags[entity_id] = leaf_tag
            dpg.bind_item_theme(leaf_tag, card_theme)
            dpg.set_value(leaf_tag, is_selected)
            self._attach_item_handlers(leaf_tag, entity_id, is_tree_node=False)

with dpg.window(label="Hierarchy Window", width=350, height=540, no_title_bar=True, no_move=True, no_resize=True, pos=(0, 0)):
    panel = Option3HierarchyPanel(session, tag="window_hierarchy")
    panel.build()

dpg.setup_dearpygui()
dpg.show_viewport()

for _ in range(8):
    dpg.render_dearpygui_frame()

out_scratch = "f:/ModEngine/scratch/option3_real.png"
dpg.output_frame_buffer(file=out_scratch)
for _ in range(8):
    dpg.render_dearpygui_frame()

dpg.destroy_context()

artifact_dir = Path(r"C:\Users\Ico\.gemini\antigravity\brain\5a8234d1-0a55-4429-a69c-c4d8f77147c2")
dest_path = artifact_dir / "option3_real.png"
shutil.copy2(out_scratch, dest_path)
print("Saved option3_real.png")
