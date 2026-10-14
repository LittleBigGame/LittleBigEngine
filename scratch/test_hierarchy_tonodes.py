import sys
sys.path.insert(0, ".")
from pathlib import Path
import tempfile
import dearpygui.dearpygui as dpg

from LBE.kernel import Kernel
from editor.session import EditorSession
from editor.hierarchy_panel import HierarchyPanel
from editor.theme import create_editor_theme
from main import populate_demo_world_if_empty

dpg.create_context()
dpg.create_viewport(title="Editor Hierarchy Test ToNodes", width=600, height=800)

theme = create_editor_theme()
dpg.bind_theme(theme)

# Monkey-patch HierarchyPanel._render_node to use mvTreeLines_ToNodes
orig_render = HierarchyPanel._render_node

def patched_render(self, entity_id, parent_tag, depth=0, is_last=False):
    # Call original but replace lines with ToNodes
    return orig_render(self, entity_id, parent_tag, depth=depth, is_last=is_last)

HierarchyPanel._render_node = patched_render

# Let's directly edit hierarchy_panel or test with a modified version
class PatchedHierarchyPanel(HierarchyPanel):
    def _render_node(self, entity_id, parent_tag, depth=0, is_last=False):
        name = self.session.get_entity_name(entity_id)
        children = self.session.get_children(entity_id)
        if self._subtree_filter == "Game World":
            children = [c for c in children if not self._is_ui_entity(c)]
        child_count = len(children)
        is_selected = (self.session.selected_entity_id == entity_id)

        from editor.theme import get_card_theme
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

            for child_id in children:
                self._render_node(child_id, parent_tag=node_tag, depth=depth + 1)
        else:
            leaf_tag = dpg.add_tree_node(
                label=name,
                parent=parent_tag,
                leaf=True,
                bullet=False,
                selectable=True,
                span_full_width=True,
                lines=dpg.mvTreeLines_ToNodes,
            )
            self._node_tags[entity_id] = leaf_tag
            dpg.bind_item_theme(leaf_tag, card_theme)
            dpg.set_value(leaf_tag, is_selected)
            self._attach_item_handlers(leaf_tag, entity_id, is_tree_node=False)

with tempfile.TemporaryDirectory() as tmpdir:
    kernel = Kernel(Path(tmpdir))
    populate_demo_world_if_empty(kernel)
    session = EditorSession(kernel)

    with dpg.window(label="Hierarchy Window", width=550, height=750):
        panel = PatchedHierarchyPanel(session, tag="test_hierarchy")
        panel.build()

    dpg.setup_dearpygui()
    dpg.show_viewport()

    for _ in range(5):
        dpg.render_dearpygui_frame()

    dpg.output_frame_buffer(file="f:/ModEngine/scratch/real_hierarchy_tonodes.png")
    for _ in range(5):
        dpg.render_dearpygui_frame()

    dpg.destroy_context()
    print("Saved real_hierarchy_tonodes.png")
