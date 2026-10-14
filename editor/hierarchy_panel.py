"""Hierarchy panel rendering entity tree as card rows with vector glyphs and 3-layer context menus."""

from __future__ import annotations

import math
from typing import Any
import dearpygui.dearpygui as dpg

from LBE.types import Error, RuntimeID
from .context_menu import open_context_menu
from .session import EditorSession
from .theme import get_card_theme, get_flyout_theme, get_tree_content_theme
from .vector_glyphs import draw_branch_lines, draw_chevron_down, draw_chevron_right, draw_radio_dot

# Layout metrics for letter-aligned vector card hierarchy
ROW_HEIGHT = 22.0
ROW_Y_MID = ROW_HEIGHT / 2.0
TREE_X0 = 8.0
ARROW_WIDTH = 8.0
ARROW_GAP = 6.0
TREE_INDENT = ARROW_WIDTH + ARROW_GAP  # 14.0px (locks child arrow to parent's first letter)
PIPE_LINE_COLOR = (80, 85, 100, 255)    # Matching theme TreeLines color
PIPE_LINE_THICKNESS = 1.0


class HierarchyPanel:
    """Dockable panel displaying the entity hierarchy tree as cards with auto-hiding chrome."""

    def __init__(
        self,
        session: EditorSession,
        tag: str = "window_hierarchy",
        use_vector_cards: bool = False,
    ) -> None:
        self.session = session
        self.tag = tag
        self.content_tag = f"{self.tag}_content"
        self.search_tag = f"{self.tag}_search"
        self.filter_tag = f"{self.tag}_filter"
        self.use_vector_cards = use_vector_cards
        self._subtree_filter: str = "All"
        self._filter_query: str = ""
        self._handler_registries: list[int | str] = []
        self._is_minimized: bool = False
        self._orig_height: int = 500
        self._collapsed_entities: set[RuntimeID] = set()
        self._node_tags: dict[RuntimeID, int | str] = {}

        self._unsubscribe_state = self.session.subscribe_state_changed(self.rebuild)
        self._unsubscribe_selection = self.session.subscribe_selection_changed(
            lambda _: self.rebuild()
        )

    @property
    def subtree_filter(self) -> str:
        return self._subtree_filter

    @subtree_filter.setter
    def subtree_filter(self, val: str) -> None:
        self._subtree_filter = val
        if dpg.does_item_exist(self.filter_tag):
            dpg.set_value(self.filter_tag, val)
        self.rebuild()

    def _find_panel_entity(self) -> RuntimeID | None:
        """Find the Hierarchy Panel entity in the session kernel."""
        for rid in self.session.kernel.resources:
            if not self.session.kernel.is_entity(rid):
                continue
            comps = self.session.get_components(rid)
            p_comp = comps.get("Panel") or comps.get("panel")
            if isinstance(p_comp, dict) and p_comp.get("panel_type") == "hierarchy":
                return rid
            if self.session.get_entity_name(rid) == "Hierarchy Panel":
                return rid
        return None

    def _get_panel_props(self) -> tuple[str, str, str, str]:
        """Read search placeholder and filter button labels (all, game, tools) from child entities."""
        hint = "Search hierarchy..."
        all_lbl = "All"
        game_lbl = "Game World"
        tools_lbl = "UI & Tools"

        panel_id = self._find_panel_entity()
        if panel_id is None:
            return hint, all_lbl, game_lbl, tools_lbl

        for child_id in self.session.get_children(panel_id):
            c_name = self.session.get_entity_name(child_id)
            c_comps = self.session.get_components(child_id)
            if c_name == "SearchInput" or "UITextInput" in c_comps or "uitextinput" in c_comps:
                tc = c_comps.get("UITextInput") or c_comps.get("uitextinput", {})
                if isinstance(tc, dict) and "hint" in tc and tc["hint"]:
                    hint = str(tc["hint"])
            elif c_name == "FilterBar" or "UIContainer" in c_comps or "uicontainer" in c_comps:
                for sub_id in self.session.get_children(child_id):
                    sub_name = self.session.get_entity_name(sub_id)
                    sub_comps = self.session.get_components(sub_id)
                    bc = sub_comps.get("UIButton") or sub_comps.get("uibutton", {})
                    lbl = str(bc.get("label", "")) if isinstance(bc, dict) and "label" in bc else ""
                    if sub_name == "AllFilter" and lbl:
                        all_lbl = lbl
                    elif sub_name == "GameFilter" and lbl:
                        game_lbl = lbl
                    elif sub_name == "ToolsFilter" and lbl:
                        tools_lbl = lbl

        return hint, all_lbl, game_lbl, tools_lbl

    def _toggle_expanded(self, entity_id: RuntimeID) -> None:
        if entity_id in self._collapsed_entities:
            self._collapsed_entities.remove(entity_id)
        else:
            self._collapsed_entities.add(entity_id)
        self.rebuild(preserve_open_states=False)

    def build(self) -> str:
        """Create the card-based hierarchy window structure."""
        with dpg.window(
            label="Hierarchy",
            tag=self.tag,
            width=320,
            height=500,
            pos=(10, 30),
        ):
            # Window Header
            dpg.add_text("Hierarchy", color=(235, 240, 250, 255))

            hint, all_lbl, game_lbl, tools_lbl = self._get_panel_props()

            # Clean search input
            dpg.add_input_text(
                hint=hint,
                tag=self.search_tag,
                width=-1,
                callback=self._on_search_changed,
            )

            # Filter bar reflecting child buttons
            with dpg.group(horizontal=True, tag=f"{self.tag}_filter_bar"):
                dpg.add_button(
                    label=all_lbl,
                    tag=f"{self.tag}_filter_all",
                    callback=lambda: setattr(self, "subtree_filter", "All"),
                    width=50,
                )
                dpg.add_button(
                    label=game_lbl,
                    tag=f"{self.tag}_filter_game",
                    callback=lambda: setattr(self, "subtree_filter", "Game World"),
                    width=85,
                )
                dpg.add_button(
                    label=tools_lbl,
                    tag=f"{self.tag}_filter_tools",
                    callback=lambda: setattr(self, "subtree_filter", "UI & Tools"),
                    width=85,
                )
            dpg.add_separator()

            # Main content area displaying the card tree
            with dpg.child_window(
                tag=self.content_tag,
                autosize_x=True,
                autosize_y=True,
                border=True,
            ):
                pass

            if self.use_vector_cards:
                dpg.bind_item_theme(self.content_tag, get_tree_content_theme())

        self._setup_background_right_click()
        self.rebuild()
        return self.tag

    def _setup_flyout_handlers(self) -> None:
        pass

    def create_ui_element(
        self, component_type: str, name: str | None = None
    ) -> RuntimeID | Error:
        """Create a UI entity under the currently selected entity (or root) and select it."""
        parent_id = self.session.selected_entity_id
        display_name = name or f"New_{component_type}"
        return self.session.create_ui_entity(
            name=display_name,
            component_type=component_type,
            parent_id=parent_id,
        )

    def _setup_background_right_click(self) -> None:
        """Allow right-clicking on empty background space in the panel."""
        with dpg.handler_registry() as reg:
            self._handler_registries.append(reg)
            dpg.add_mouse_click_handler(
                button=1,
                callback=self._on_background_right_click,
            )

    def _on_background_right_click(self) -> None:
        if dpg.does_item_exist(self.content_tag) and dpg.is_item_hovered(self.content_tag):
            open_context_menu(
                self.session,
                target_id=None,
                panel_type="hierarchy",
                panel_instance=self,
            )

    def _toggle_flyout(self, dock_tag: str) -> None:
        if dpg.does_item_exist(dock_tag):
            is_shown = dpg.is_item_shown(dock_tag)
            dpg.configure_item(dock_tag, show=not is_shown)

    def _toggle_minimize(self) -> None:
        self._is_minimized = not self._is_minimized
        if self._is_minimized:
            self._orig_height = dpg.get_item_height(self.tag) or 500
            dpg.set_item_height(self.tag, 60)
        else:
            dpg.set_item_height(self.tag, self._orig_height)

    def _toggle_maximize(self) -> None:
        curr_w = dpg.get_item_width(self.tag) or 320
        new_w = 600 if curr_w < 500 else 320
        dpg.set_item_width(self.tag, new_w)

    def rebuild(self, preserve_open_states: bool = True) -> None:
        """Re-render the card tree inside the content container."""
        if not dpg.does_item_exist(self.content_tag):
            return

        hint, all_lbl, game_lbl, tools_lbl = self._get_panel_props()
        if dpg.does_item_exist(self.search_tag):
            dpg.configure_item(self.search_tag, hint=hint)
        if dpg.does_item_exist(f"{self.tag}_filter_all"):
            dpg.configure_item(f"{self.tag}_filter_all", label=all_lbl)
            dpg.bind_item_theme(f"{self.tag}_filter_all", get_card_theme(selected=(self._subtree_filter == "All")))
        if dpg.does_item_exist(f"{self.tag}_filter_game"):
            dpg.configure_item(f"{self.tag}_filter_game", label=game_lbl)
            dpg.bind_item_theme(f"{self.tag}_filter_game", get_card_theme(selected=(self._subtree_filter == "Game World")))
        if dpg.does_item_exist(f"{self.tag}_filter_tools"):
            dpg.configure_item(f"{self.tag}_filter_tools", label=tools_lbl)
            dpg.bind_item_theme(f"{self.tag}_filter_tools", get_card_theme(selected=(self._subtree_filter == "UI & Tools")))

        for reg in self._handler_registries[2:]:
            if dpg.does_item_exist(reg):
                dpg.delete_item(reg)
        self._handler_registries = self._handler_registries[:2]

        if preserve_open_states and not self.use_vector_cards:
            for eid, tag in self._node_tags.items():
                if dpg.does_item_exist(tag):
                    try:
                        cfg = dpg.get_item_configuration(tag)
                        if not cfg.get("leaf", False):
                            if dpg.get_value(tag):
                                self._collapsed_entities.discard(eid)
                            else:
                                self._collapsed_entities.add(eid)
                    except Exception:
                        pass
        self._node_tags.clear()

        dpg.delete_item(self.content_tag, children_only=True)

        # 1. Check Root Scoping
        if self.session.view_root_id is not None and self.session.kernel.is_entity(self.session.view_root_id):
            root_ids = [self.session.view_root_id]
        elif self._subtree_filter == "Game World":
            root_ids = [
                rid for rid in self.session.get_root_entities()
                if not self._is_ui_entity(rid)
            ]
        elif self._subtree_filter == "UI & Tools":
            root_ids = [
                rid for rid in self.session.get_root_entities()
                if self._is_ui_entity(rid)
            ]
            for rid in sorted(self.session.kernel.resources.keys()):
                if not self.session.kernel.is_entity(rid) or rid in root_ids:
                    continue
                if self._is_ui_entity(rid):
                    parent = self.session.kernel.get_entity_parent(rid)
                    if parent is None or parent not in self.session.kernel.resources or not self._is_ui_entity(parent):
                        root_ids.append(rid)
        else:
            root_ids = self.session.get_root_entities()

        if not root_ids:
            dpg.add_text(
                "No entities loaded",
                parent=self.content_tag,
                color=(130, 135, 145),
            )
            return

        for i, entity_id in enumerate(root_ids):
            self._render_node(
                entity_id,
                parent_tag=self.content_tag,
                is_last=(i == len(root_ids) - 1),
            )

    def _is_ui_entity(self, entity_id: RuntimeID) -> bool:
        """Check if entity has any UI component or if any ancestor has UIContainer."""
        ui_types = {"uicontainer", "uibutton", "uislider", "uitextinput", "uitext", "uipanel", "panel"}
        comps = self.session.get_components(entity_id)
        if any(c.lower() in ui_types for c in comps):
            return True

        curr = self.session.kernel.get_entity_parent(entity_id)
        visited = {entity_id}
        while curr is not None and curr not in visited:
            visited.add(curr)
            parent_comps = self.session.get_components(curr)
            if any(c.lower() == "uicontainer" for c in parent_comps):
                return True
            curr = self.session.kernel.get_entity_parent(curr)

        return False

    def _render_node(
        self,
        entity_id: RuntimeID,
        parent_tag: str | int,
        depth: int = 0,
        is_last: bool = False,
    ) -> None:
        """Render a single entity card node and recursively render its children."""
        name = self.session.get_entity_name(entity_id)
        children = self.session.get_children(entity_id)

        if self._subtree_filter == "Game World":
            children = [c for c in children if not self._is_ui_entity(c)]

        child_count = len(children)
        is_selected = (self.session.selected_entity_id == entity_id)

        # Check search query filter
        if self._filter_query:
            q = self._filter_query.lower()
            matches_self = q in name.lower() or q in str(entity_id)
            descendant_match = self._has_matching_descendant(entity_id, q)
            if not matches_self and not descendant_match:
                return

        card_theme = get_card_theme(selected=is_selected)
        is_expanded = (entity_id not in self._collapsed_entities)

        if self.use_vector_cards:
            self._render_node_vector_cards(
                entity_id, parent_tag=parent_tag, depth=depth, is_last=is_last
            )
            return

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

    def _render_node_vector_cards(
        self,
        entity_id: RuntimeID,
        parent_tag: str | int,
        depth: int = 0,
        is_last: bool = False,
        ancestor_continues: tuple[bool, ...] = (),
    ) -> None:
        """Render a card row with letter-aligned vector chevrons, circles, and pipe lines."""
        name = self.session.get_entity_name(entity_id)
        children = self.session.get_children(entity_id)
        if self._subtree_filter == "Game World":
            children = [c for c in children if not self._is_ui_entity(c)]

        child_count = len(children)
        is_leaf = (child_count == 0)
        is_selected = (self.session.selected_entity_id == entity_id)
        is_expanded = (entity_id not in self._collapsed_entities) and not is_leaf

        x_icon = TREE_X0 + depth * TREE_INDENT
        x_center = x_icon + ARROW_WIDTH / 2.0
        x_text = x_icon + TREE_INDENT

        row_tag = f"{self.tag}_card_{entity_id}_{dpg.generate_uuid()}"
        self._node_tags[entity_id] = row_tag

        with dpg.group(horizontal=True, parent=parent_tag, tag=row_tag, label=name):
            dl = dpg.add_drawlist(width=340, height=int(ROW_HEIGHT), tag=f"{row_tag}_dl")

            # 1. Selection highlight box
            if is_selected:
                dpg.draw_rectangle(
                    (4.0, 1.0),
                    (330.0, ROW_HEIGHT - 1.0),
                    color=(0, 120, 255, 255),
                    fill=(0, 80, 160, 140),
                    rounding=3.0,
                    thickness=1.5,
                    parent=dl,
                )

            # 2. Ancestor vertical pass-through lines
            for k, continues in enumerate(ancestor_continues[:depth - 1]):
                if continues:
                    x_anc = TREE_X0 + k * TREE_INDENT + ARROW_WIDTH / 2.0
                    dpg.draw_line(
                        (x_anc, 0.0),
                        (x_anc, ROW_HEIGHT),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )

            # 3. Connection to immediate parent
            if depth > 0:
                x_parent = TREE_X0 + (depth - 1) * TREE_INDENT + ARROW_WIDTH / 2.0
                r_curve = 7.0
                k_arc = 0.552 * r_curve

                if is_last:
                    # Last child: vertical line down, crisp 1px circular arc, horizontal line to x_center
                    dpg.draw_line(
                        (x_parent, 0.0),
                        (x_parent, ROW_Y_MID - r_curve),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )
                    dpg.draw_bezier_cubic(
                        (x_parent, ROW_Y_MID - r_curve),
                        (x_parent, ROW_Y_MID - r_curve + k_arc),
                        (x_parent + r_curve - k_arc, ROW_Y_MID),
                        (x_parent + r_curve, ROW_Y_MID),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )
                    dpg.draw_line(
                        (x_parent + r_curve, ROW_Y_MID),
                        (x_center, ROW_Y_MID),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )
                else:
                    # Not last: vertical trunk continues straight down, clean perpendicular branch to x_center
                    dpg.draw_line(
                        (x_parent, 0.0),
                        (x_parent, ROW_HEIGHT),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )
                    dpg.draw_line(
                        (x_parent, ROW_Y_MID),
                        (x_center, ROW_Y_MID),
                        color=PIPE_LINE_COLOR,
                        thickness=PIPE_LINE_THICKNESS,
                        parent=dl,
                    )

            # 4. Outgoing connection to children (connects up behind the arrow)
            if child_count > 0 and is_expanded:
                dpg.draw_line(
                    (x_center, ROW_Y_MID),
                    (x_center, ROW_HEIGHT),
                    color=PIPE_LINE_COLOR,
                    thickness=PIPE_LINE_THICKNESS,
                    parent=dl,
                )

            # 5. Icon (Vector triangle for parents, vector circle for leaves)
            if not is_leaf:
                tri_y = ROW_Y_MID - 4.0
                color = (230, 235, 245, 255) if is_selected else (190, 195, 205, 255)
                if is_expanded:
                    draw_chevron_down(dl, (x_icon, tri_y), color=color, size=ARROW_WIDTH)
                else:
                    draw_chevron_right(dl, (x_icon, tri_y), color=color, size=ARROW_WIDTH)
            else:
                draw_radio_dot(
                    dl,
                    center=(x_center, ROW_Y_MID),
                    selected=is_selected,
                    color=(0, 120, 255, 255),
                    radius=3.5,
                )

            # 6. Label text
            txt_color = (255, 255, 255, 255) if is_selected else (220, 225, 235, 255)
            dpg.draw_text(
                (x_text, ROW_Y_MID - 7.0),
                name,
                color=txt_color,
                size=13.0,
                parent=dl,
            )

            # 7. Click & context menu handlers
            self._attach_vector_card_handlers(dl, entity_id, is_leaf, x_icon)

        # 8. Recursively render children if expanded
        if child_count > 0 and is_expanded:
            for i, child_id in enumerate(children):
                child_is_last = (i == child_count - 1)
                next_ancestors = ancestor_continues + (not child_is_last,)
                self._render_node_vector_cards(
                    child_id,
                    parent_tag=parent_tag,
                    depth=depth + 1,
                    is_last=child_is_last,
                    ancestor_continues=next_ancestors,
                )

    def _attach_vector_card_handlers(
        self,
        item_tag: int | str,
        entity_id: RuntimeID,
        is_leaf: bool,
        x_icon: float,
    ) -> None:
        """Attach left-click toggle/selection and right-click context menu handlers."""
        handler_reg = dpg.add_item_handler_registry()
        self._handler_registries.append(handler_reg)

        dpg.add_item_clicked_handler(
            button=0,
            callback=self._on_vector_card_clicked,
            user_data=(entity_id, is_leaf, x_icon, item_tag),
            parent=handler_reg,
        )
        dpg.add_item_clicked_handler(
            button=1,
            callback=lambda s, a, u: open_context_menu(
                self.session,
                target_id=u,
                panel_type="hierarchy",
                panel_instance=self,
            ),
            user_data=entity_id,
            parent=handler_reg,
        )
        dpg.bind_item_handler_registry(item_tag, handler_reg)

    def _on_vector_card_clicked(
        self,
        _sender: int | str,
        _app_data: Any,
        user_data: tuple[RuntimeID, bool, float, int | str],
    ) -> None:
        """Handle click on vector card: arrow toggles expansion, label selects entity."""
        entity_id, is_leaf, x_icon, dl_tag = user_data
        try:
            min_pos = dpg.get_item_rect_min(dl_tag)
            mx, _ = dpg.get_mouse_pos(local=False)
            local_x = mx - min_pos[0]
            if local_x <= x_icon + ARROW_WIDTH + 4.0 and not is_leaf:
                self._toggle_expanded(entity_id)
                return
        except Exception:
            pass
        self.session.select_entity(entity_id)

    def _on_node_toggled(self, entity_id: RuntimeID, is_open: bool) -> None:
        if is_open:
            self._collapsed_entities.discard(entity_id)
        else:
            self._collapsed_entities.add(entity_id)

    def _on_node_clicked(self, entity_id: RuntimeID, item_tag: int | str) -> None:
        if dpg.does_item_exist(item_tag):
            try:
                if dpg.is_item_toggled_open(item_tag):
                    return
            except Exception:
                pass
        self.session.select_entity(entity_id)

    def _attach_item_handlers(
        self,
        item_tag: int | str,
        entity_id: RuntimeID,
        include_left_click: bool = True,
        is_tree_node: bool = False,
    ) -> None:
        """Attach left-click (select) and right-click (3-layer context menu) handlers."""
        handler_reg = dpg.add_item_handler_registry()
        self._handler_registries.append(handler_reg)

        if is_tree_node:
            dpg.add_item_toggled_open_handler(
                callback=lambda s, a, u: self._on_node_toggled(u, a),
                user_data=entity_id,
                parent=handler_reg,
            )

        if include_left_click:
            # Left-click: Select entity and route to active inspector
            dpg.add_item_clicked_handler(
                button=0,
                callback=lambda s, a, u: self._on_node_clicked(u, s),
                user_data=entity_id,
                parent=handler_reg,
            )

        # Right-click: Open 3-layer context menu right at cursor
        dpg.add_item_clicked_handler(
            button=1,
            callback=lambda s, a, u: open_context_menu(
                self.session,
                target_id=u,
                panel_type="hierarchy",
                panel_instance=self,
            ),
            user_data=entity_id,
            parent=handler_reg,
        )

        dpg.bind_item_handler_registry(item_tag, handler_reg)

    def _has_matching_descendant(
        self,
        entity_id: RuntimeID,
        query: str,
        visited: set[RuntimeID] | None = None,
    ) -> bool:
        if visited is None:
            visited = set()
        if entity_id in visited:
            return False
        visited.add(entity_id)

        for cid in self.session.get_children(entity_id):
            if self._subtree_filter == "Game World" and self._is_ui_entity(cid):
                continue
            cname = self.session.get_entity_name(cid)
            if query in cname.lower() or query in str(cid):
                return True
            if self._has_matching_descendant(cid, query, visited=visited):
                return True
        return False

    def collapse_all(self) -> None:
        """Collapse all nodes in the hierarchy tree."""
        for rid in self.session.kernel.resources:
            if self.session.kernel.is_entity(rid):
                if len(self.session.get_children(rid)) > 0:
                    self._collapsed_entities.add(rid)
        self.rebuild(preserve_open_states=False)

    def expand_all(self) -> None:
        """Expand all nodes in the hierarchy tree."""
        self._collapsed_entities.clear()
        self.rebuild(preserve_open_states=False)

    def destroy(self) -> None:
        """Clean up session event subscriptions and handler registries."""
        if hasattr(self, "_unsubscribe_state") and callable(self._unsubscribe_state):
            try:
                self._unsubscribe_state()
            except Exception:
                pass
            self._unsubscribe_state = None
        if hasattr(self, "_unsubscribe_selection") and callable(self._unsubscribe_selection):
            try:
                self._unsubscribe_selection()
            except Exception:
                pass
            self._unsubscribe_selection = None
        for reg in self._handler_registries:
            if dpg.does_item_exist(reg):
                dpg.delete_item(reg)
        self._handler_registries.clear()

    def _on_search_changed(self, sender: str | int, app_data: str) -> None:
        self._filter_query = app_data.strip()
        self.rebuild()
