"""Docking layout engine for the editor.

Implements a binary split-tree with tab groups (DockTree) providing deterministic,
non-overlapping rectangular partitioning of the workspace.
"""

from typing import Dict, List, Optional, Tuple, Union, Any
import uuid


class TabGroupNode:
    """A leaf node in the dock tree containing one or more tabbed panels."""

    def __init__(self, panels: Optional[List[str]] = None, active: int = 0, node_id: Optional[str] = None):
        self.id = node_id or f"tab_{uuid.uuid4().hex[:8]}"
        self.panels: List[str] = list(panels) if panels else []
        self.active: int = max(0, min(active, len(self.panels) - 1)) if self.panels else 0
        self.rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.tab_bar_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.content_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.tab_rects: List[Tuple[str, Tuple[int, int, int, int]]] = []

    @property
    def active_panel(self) -> Optional[str]:
        if not self.panels or self.active < 0 or self.active >= len(self.panels):
            return None
        return self.panels[self.active]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "tab_group",
            "id": self.id,
            "panels": list(self.panels),
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TabGroupNode":
        return cls(
            panels=data.get("panels", []),
            active=data.get("active", 0),
            node_id=data.get("id"),
        )


class SplitNode:
    """A branch node in the dock tree splitting space between two children."""

    def __init__(
        self,
        orientation: str,  # 'horizontal' (left/right) or 'vertical' (top/bottom)
        first: Union["SplitNode", TabGroupNode],
        second: Union["SplitNode", TabGroupNode],
        ratio: float = 0.5,
        node_id: Optional[str] = None,
    ):
        if orientation not in ("horizontal", "vertical"):
            raise ValueError(f"Invalid orientation: {orientation}; must be 'horizontal' or 'vertical'")
        self.id = node_id or f"split_{uuid.uuid4().hex[:8]}"
        self.orientation = orientation
        self.ratio = max(0.05, min(0.95, float(ratio)))
        self.first = first
        self.second = second
        self.rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self.splitter_rect: Tuple[int, int, int, int] = (0, 0, 0, 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "split",
            "id": self.id,
            "orientation": self.orientation,
            "ratio": self.ratio,
            "first": self.first.to_dict(),
            "second": self.second.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SplitNode":
        first_data = data["first"]
        first_node = TabGroupNode.from_dict(first_data) if first_data.get("type") == "tab_group" else cls.from_dict(first_data)
        second_data = data["second"]
        second_node = TabGroupNode.from_dict(second_data) if second_data.get("type") == "tab_group" else cls.from_dict(second_data)
        return cls(
            orientation=data.get("orientation", "horizontal"),
            first=first_node,
            second=second_node,
            ratio=data.get("ratio", 0.5),
            node_id=data.get("id"),
        )


DockNode = Union[SplitNode, TabGroupNode]


class DockTree:
    """Binary partition tree of tabbed dock panels."""

    def __init__(self, root: Optional[DockNode] = None):
        self.root: DockNode = root if root is not None else self.default_root()

    @staticmethod
    def default_root() -> SplitNode:
        """Returns the canonical LittleBigEngine 4-panel default layout."""
        left_split = SplitNode(
            orientation="vertical",
            ratio=0.45,
            first=TabGroupNode(panels=["hierarchy", "files"], active=0, node_id="tab_hierarchy_files"),
            second=TabGroupNode(panels=["inspector"], active=0, node_id="tab_inspector"),
            node_id="split_left",
        )
        right_split = SplitNode(
            orientation="vertical",
            ratio=0.45,
            first=TabGroupNode(panels=["viewport"], active=0, node_id="tab_viewport"),
            second=TabGroupNode(panels=["code_panel"], active=0, node_id="tab_code"),
            node_id="split_right",
        )
        return SplitNode(
            orientation="horizontal",
            ratio=0.32,
            first=left_split,
            second=right_split,
            node_id="split_main",
        )

    def is_default(self) -> bool:
        if not isinstance(self.root, SplitNode):
            return False
        r = self.root
        if r.id != "split_main" or r.orientation != "horizontal":
            return False
        if not isinstance(r.first, SplitNode) or not isinstance(r.second, SplitNode):
            return False
        if r.first.id != "split_left" or r.second.id != "split_right":
            return False
        left = r.first
        right = r.second
        if not isinstance(left.first, TabGroupNode) or not isinstance(left.second, TabGroupNode):
            return False
        if not isinstance(right.first, TabGroupNode) or not isinstance(right.second, TabGroupNode):
            return False
        return (
            set(left.first.panels) == {"hierarchy", "files"}
            and left.second.panels == ["inspector"]
            and right.first.panels == ["viewport"]
            and right.second.panels == ["code_panel"]
        )

    def compute_default_layout(
        self,
        w: int,
        h: int,
        header_h: int = 44,
        status_h: int = 20,
        status_m_bottom: int = 5,
        left_col_w: int = 370,
        panel_h: int = 240,
        split_y: Optional[int] = None,
    ) -> Dict[str, Tuple[int, int, int, int]]:
        top_y = header_h
        status_y = h - status_m_bottom - status_h
        if split_y is None:
            split_y = max(330, int(h * 0.45))

        hw = max(50, left_col_w - 16)
        hh = panel_h
        top_panel_y = top_y + 8

        iy = top_panel_y + hh + 4 + 4
        ih = max(100, status_y - iy - 6 - 5)

        right_x = left_col_w + 8
        right_w = max(100, w - left_col_w - 24)

        # Store rects in the nodes so drag targeting works
        split_main = self.find_node("split_main")
        if split_main:
            split_main.rect = (0, top_y, w, status_y - top_y)
            split_main.splitter_rect = (left_col_w + 1, top_y, 6, max(0, status_y - top_y))

        split_left = self.find_node("split_left")
        if split_left:
            split_left.rect = (0, top_y, left_col_w, status_y - top_y)
            split_left.splitter_rect = (8, top_panel_y + hh + 1, hw, 6)

        split_right = self.find_node("split_right")
        if split_right:
            split_right.rect = (right_x, top_y, right_w, status_y - top_y)
            split_right.splitter_rect = (right_x, split_y - 8, right_w, 6)

        tg_hf = self.find_node("tab_hierarchy_files")
        if tg_hf:
            tg_hf.rect = (8, top_panel_y, hw, hh)
            tg_hf.content_rect = (8, top_panel_y, hw, hh)
            tg_hf.tab_bar_rect = (8, top_panel_y, hw, 26)
            avail_w = max(40, hw - 24)
            if len(tg_hf.panels) == 1:
                tg_hf.tab_rects = [(tg_hf.panels[0], (8, top_panel_y, avail_w, 26))]
            else:
                tw = max(40, min(140, (avail_w - (len(tg_hf.panels) - 1) * 2) // len(tg_hf.panels)))
                tab_x = 8
                tg_hf.tab_rects = []
                for p in tg_hf.panels:
                    tg_hf.tab_rects.append((p, (tab_x, top_panel_y, tw, 26)))
                    tab_x += tw + 2

        tg_insp = self.find_node("tab_inspector")
        if tg_insp:
            tg_insp.rect = (8, iy, hw, ih)
            tg_insp.content_rect = (8, iy, hw, ih)
            tg_insp.tab_bar_rect = (8, iy, hw, 26)
            avail_w = max(40, hw - 24)
            if len(tg_insp.panels) == 1:
                tg_insp.tab_rects = [(tg_insp.panels[0], (8, iy, avail_w, 26))]
            else:
                tw = max(40, min(140, (avail_w - (len(tg_insp.panels) - 1) * 2) // len(tg_insp.panels)))
                tab_x = 8
                tg_insp.tab_rects = []
                for p in tg_insp.panels:
                    tg_insp.tab_rects.append((p, (tab_x, iy, tw, 26)))
                    tab_x += tw + 2

        tg_vp = self.find_node("tab_viewport")
        if tg_vp:
            vp_h = max(50, split_y - top_y - 48)
            tg_vp.rect = (right_x, top_y + 12, right_w, vp_h + 24)
            tg_vp.content_rect = (right_x, top_y + 36, right_w, vp_h)
            tg_vp.tab_bar_rect = (right_x, top_y + 12, right_w, 24)
            avail_w = max(40, right_w - 24)
            if len(tg_vp.panels) == 1:
                tg_vp.tab_rects = [(tg_vp.panels[0], (right_x, top_y + 12, avail_w, 24))]
            else:
                tw = max(40, min(140, (avail_w - (len(tg_vp.panels) - 1) * 2) // len(tg_vp.panels)))
                tab_x = right_x
                tg_vp.tab_rects = []
                for p in tg_vp.panels:
                    tg_vp.tab_rects.append((p, (tab_x, top_y + 12, tw, 24)))
                    tab_x += tw + 2

        tg_code = self.find_node("tab_code")
        if tg_code:
            code_h = max(100, status_y - split_y - 11)
            tg_code.rect = (right_x, split_y, right_w, code_h)
            tg_code.content_rect = (right_x, split_y, right_w, code_h)
            tg_code.tab_bar_rect = (right_x, split_y, right_w, 26)
            avail_w = max(40, right_w - 24)
            if len(tg_code.panels) == 1:
                tg_code.tab_rects = [(tg_code.panels[0], (right_x, split_y, avail_w, 26))]
            else:
                tw = max(40, min(140, (avail_w - (len(tg_code.panels) - 1) * 2) // len(tg_code.panels)))
                tab_x = right_x
                tg_code.tab_rects = []
                for p in tg_code.panels:
                    tg_code.tab_rects.append((p, (tab_x, split_y, tw, 26)))
                    tab_x += tw + 2

        active_hf = tg_hf.active_panel if tg_hf else "hierarchy"
        return {
            active_hf: (8, top_panel_y, hw, hh),
            "inspector": (8, iy, hw, ih),
            "viewport": (right_x, top_y + 36, right_w, max(50, split_y - top_y - 48)),
            "code_panel": (right_x, split_y, right_w, max(100, status_y - split_y - 11)),
        }

    def compute_layout(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        splitter_thickness: int = 6,
        tab_bar_height: int = 26,
        min_panel_size: int = 60,
        gap: int = 2,
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """Compute all panel, tab bar, and splitter bounding boxes recursively.

        Returns a dictionary of active_panel_name -> (x, y, w, h) content rect.
        """
        panel_rects: Dict[str, Tuple[int, int, int, int]] = {}

        def _layout_node(node: DockNode, nx: int, ny: int, nw: int, nh: int):
            node.rect = (nx, ny, nw, nh)

            if isinstance(node, TabGroupNode):
                tb_h = tab_bar_height
                node.tab_bar_rect = (nx, ny, nw, tb_h)
                node.content_rect = (nx, ny, nw, nh)

                # Compute individual tab button rects
                node.tab_rects = []
                avail_w = max(40, nw - 24)
                if len(node.panels) == 1:
                    # Single panel: tab spans title bar width
                    node.tab_rects.append((node.panels[0], (nx, ny, avail_w, tb_h)))
                elif len(node.panels) > 1:
                    pad = 2
                    tw = max(40, min(140, (avail_w - (len(node.panels) - 1) * pad) // len(node.panels)))
                    tab_x = nx
                    for p in node.panels:
                        node.tab_rects.append((p, (tab_x, ny, tw, tb_h)))
                        tab_x += tw + pad

                # The active panel gets the content rect
                if node.active_panel:
                    panel_rects[node.active_panel] = node.content_rect

            elif isinstance(node, SplitNode):
                st = splitter_thickness
                sep = st + gap * 2
                if node.orientation == "horizontal":
                    # Left / Right split: vertical separator bar
                    available_w = max(0, nw - sep)
                    first_w = max(min_panel_size, min(available_w - min_panel_size, int(available_w * node.ratio)))
                    if available_w < min_panel_size * 2:
                        first_w = available_w // 2
                    second_w = max(0, available_w - first_w)

                    node.splitter_rect = (nx + first_w + gap, ny, st, nh)
                    _layout_node(node.first, nx, ny, first_w, nh)
                    _layout_node(node.second, nx + first_w + sep, ny, second_w, nh)

                else:
                    # Top / Bottom split: horizontal separator bar
                    available_h = max(0, nh - sep)
                    first_h = max(min_panel_size, min(available_h - min_panel_size, int(available_h * node.ratio)))
                    if available_h < min_panel_size * 2:
                        first_h = available_h // 2
                    second_h = max(0, available_h - first_h)

                    node.splitter_rect = (nx, ny + first_h + gap, nw, st)
                    _layout_node(node.first, nx, ny, nw, first_h)
                    _layout_node(node.second, nx, ny + first_h + sep, nw, second_h)

        _layout_node(self.root, x, y, w, h)
        return panel_rects

    def find_tab_group_with_panel(self, panel_name: str) -> Optional[TabGroupNode]:
        """Find the TabGroupNode containing the given panel."""
        def _search(node: DockNode) -> Optional[TabGroupNode]:
            if isinstance(node, TabGroupNode):
                if panel_name in node.panels:
                    return node
                return None
            elif isinstance(node, SplitNode):
                res = _search(node.first)
                if res:
                    return res
                return _search(node.second)
            return None

        return _search(self.root)

    def find_node(self, node_id: str) -> Optional[DockNode]:
        """Find a node by ID."""
        def _search(node: DockNode) -> Optional[DockNode]:
            if node.id == node_id:
                return node
            if isinstance(node, SplitNode):
                res = _search(node.first)
                if res:
                    return res
                return _search(node.second)
            return None

        return _search(self.root)

    def find_parent(self, target: DockNode) -> Tuple[Optional[SplitNode], Optional[int]]:
        """Find the parent SplitNode of a node. Returns (parent, child_index: 0 or 1)."""
        def _search(node: DockNode) -> Tuple[Optional[SplitNode], Optional[int]]:
            if isinstance(node, SplitNode):
                if node.first is target:
                    return (node, 0)
                if node.second is target:
                    return (node, 1)
                p, idx = _search(node.first)
                if p:
                    return (p, idx)
                return _search(node.second)
            return (None, None)

        return _search(self.root)

    def all_tab_groups(self) -> List[TabGroupNode]:
        """Return all leaf TabGroupNodes in traversal order."""
        result: List[TabGroupNode] = []
        def _walk(node: DockNode):
            if isinstance(node, TabGroupNode):
                result.append(node)
            elif isinstance(node, SplitNode):
                _walk(node.first)
                _walk(node.second)
        _walk(self.root)
        return result

    def all_splitters(self) -> List[Tuple[SplitNode, Tuple[int, int, int, int], str]]:
        """Return all active splitter rects and orientations: [(node, rect, orientation)]."""
        result: List[Tuple[SplitNode, Tuple[int, int, int, int], str]] = []
        def _walk(node: DockNode):
            if isinstance(node, SplitNode):
                result.append((node, node.splitter_rect, node.orientation))
                _walk(node.first)
                _walk(node.second)
        _walk(self.root)
        return result

    def remove_panel(self, panel_name: str) -> bool:
        """Remove a panel from its tab group. If the group becomes empty, prunes the tree."""
        group = self.find_tab_group_with_panel(panel_name)
        if not group:
            return False

        group.panels.remove(panel_name)
        if group.active >= len(group.panels):
            group.active = max(0, len(group.panels) - 1)

        # If group still has panels, keep it
        if group.panels:
            return True

        # Group is now empty: prune from parent
        parent, child_idx = self.find_parent(group)
        if parent is None:
            # Group is root and now empty
            return True

        sibling = parent.second if child_idx == 0 else parent.first
        grandparent, gp_idx = self.find_parent(parent)
        if grandparent is None:
            # Parent was root; sibling becomes new root
            self.root = sibling
        else:
            if gp_idx == 0:
                grandparent.first = sibling
            else:
                grandparent.second = sibling

        return True

    def dock_panel(
        self,
        panel_name: str,
        target_group: Union[TabGroupNode, str],
        position: str,
        split_id: Optional[str] = None,
    ) -> bool:
        """Dock a panel into a target group or split relative to it.

        position: 'center' (add as tab), 'left', 'right', 'top', 'bottom'.
        """
        if isinstance(target_group, str):
            tg = self.find_tab_group_with_panel(target_group)
            if not tg:
                tg = self.find_node(target_group)
            target_group = tg  # type: ignore

        if not isinstance(target_group, TabGroupNode):
            return False

        # If panel is already in tree, remove it first
        self.remove_panel(panel_name)

        if position == "center":
            # Add to target tab group
            if panel_name not in target_group.panels:
                target_group.panels.append(panel_name)
            target_group.active = target_group.panels.index(panel_name)
            return True

        # Splitting target group
        new_group = TabGroupNode(panels=[panel_name], active=0)

        if position in ("left", "right"):
            orientation = "horizontal"
            first = new_group if position == "left" else target_group
            second = target_group if position == "left" else new_group
        elif position in ("top", "bottom"):
            orientation = "vertical"
            first = new_group if position == "top" else target_group
            second = target_group if position == "top" else new_group
        else:
            raise ValueError(f"Unknown dock position: {position}")

        new_split = SplitNode(
            orientation=orientation,
            ratio=0.5,
            first=first,
            second=second,
            node_id=split_id or uuid.uuid4().hex[:8],
        )

        parent, child_idx = self.find_parent(target_group)
        if parent is None:
            # target_group was root
            self.root = new_split
        else:
            if child_idx == 0:
                parent.first = new_split
            else:
                parent.second = new_split

        return True

    def restore_panel_default(self, panel_name: str) -> bool:
        """Restore a closed/minimized panel to its default companion or quadrant."""
        if self.find_tab_group_with_panel(panel_name):
            return True  # Already open

        defaults = {
            "hierarchy": [("inspector", "top"), ("files", "center"), ("viewport", "left"), ("code_panel", "left")],
            "files": [("hierarchy", "center"), ("inspector", "top"), ("viewport", "left")],
            "inspector": [("hierarchy", "bottom"), ("files", "bottom"), ("code_panel", "left"), ("viewport", "left")],
            "viewport": [("code_panel", "top"), ("hierarchy", "right"), ("inspector", "right")],
            "code_panel": [("viewport", "bottom"), ("inspector", "right"), ("hierarchy", "right")],
        }

        for target_name, pos in defaults.get(panel_name, []):
            tg = self.find_tab_group_with_panel(target_name)
            if tg:
                split_id = None
                if {panel_name, target_name}.issubset({"hierarchy", "files", "inspector"}) and pos in ("top", "bottom"):
                    split_id = "split_left"
                elif {panel_name, target_name}.issubset({"viewport", "code_panel"}) and pos in ("top", "bottom"):
                    split_id = "split_right"
                elif pos in ("left", "right") and not self.find_node("split_main"):
                    split_id = "split_main"
                return self.dock_panel(panel_name, tg, pos, split_id=split_id)

        # Fallback: dock relative to first available group
        all_groups = self.all_tab_groups()
        if all_groups:
            return self.dock_panel(panel_name, all_groups[0], "bottom")

        # Root was empty
        self.root = TabGroupNode(panels=[panel_name], active=0)
        return True

    @staticmethod
    def get_dock_drop_zones(target_rect: Tuple[int, int, int, int]) -> Dict[str, Tuple[int, int, int, int]]:
        """Compute the 5 drop-target trigger hitboxes for a target panel rect.

        Returns { 'left': (x,y,w,h), 'right': ..., 'top': ..., 'bottom': ..., 'center': ... }
        """
        tx, ty, tw, th = target_rect
        inset_w = max(24, int(tw * 0.25))
        inset_h = max(24, int(th * 0.25))

        return {
            "left": (tx, ty, inset_w, th),
            "right": (tx + tw - inset_w, ty, inset_w, th),
            "top": (tx, ty, tw, inset_h),
            "bottom": (tx, ty + th - inset_h, tw, inset_h),
            "center": (tx + inset_w, ty + inset_h, max(0, tw - 2 * inset_w), max(0, th - 2 * inset_h)),
        }

    @staticmethod
    def get_dock_preview_rect(target_rect: Tuple[int, int, int, int], position: str) -> Tuple[int, int, int, int]:
        """Return the preview highlight rect for a given dock position."""
        tx, ty, tw, th = target_rect
        if position == "left":
            return (tx, ty, tw // 2, th)
        elif position == "right":
            return (tx + tw // 2, ty, tw - tw // 2, th)
        elif position == "top":
            return (tx, ty, tw, th // 2)
        elif position == "bottom":
            return (tx, ty + th // 2, tw, th - th // 2)
        elif position == "center":
            return (tx, ty, tw, th)
        return (tx, ty, tw, th)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "root": self.root.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DockTree":
        root_data = data.get("root", {})
        if root_data.get("type") == "split":
            root = SplitNode.from_dict(root_data)
        elif root_data.get("type") == "tab_group":
            root = TabGroupNode.from_dict(root_data)
        else:
            root = cls.default_root()
        return cls(root=root)
