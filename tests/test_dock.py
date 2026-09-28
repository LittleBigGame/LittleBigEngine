"""Tests for the editor DockTree layout engine."""

import unittest
from lbe.dock import DockTree, SplitNode, TabGroupNode


class TestDockTree(unittest.TestCase):
    def test_default_layout_partitions_screen(self):
        tree = DockTree()
        screen_w, screen_h = 1200, 800
        rects = tree.compute_layout(0, 44, screen_w, screen_h - 44 - 20)

        # Expected 4 active panels
        self.assertIn("hierarchy", rects)
        self.assertIn("inspector", rects)
        self.assertIn("viewport", rects)
        self.assertIn("code_panel", rects)

        # Content rects must have positive dimensions
        for name, (x, y, w, h) in rects.items():
            self.assertGreater(w, 0, f"Panel {name} width was not positive")
            self.assertGreater(h, 0, f"Panel {name} height was not positive")
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 44)
            self.assertLessEqual(x + w, screen_w)
            self.assertLessEqual(y + h, screen_h - 20)

    def test_tab_groups_have_tab_rects(self):
        tree = DockTree()
        tree.compute_layout(0, 0, 1000, 600)
        group = tree.find_tab_group_with_panel("hierarchy")
        self.assertIsNotNone(group)
        self.assertEqual(group.panels, ["hierarchy", "files"])
        self.assertEqual(len(group.tab_rects), 2)
        p0, r0 = group.tab_rects[0]
        p1, r1 = group.tab_rects[1]
        self.assertEqual(p0, "hierarchy")
        self.assertEqual(p1, "files")
        self.assertGreater(r0[2], 0)
        self.assertGreater(r1[2], 0)

    def test_switching_active_tab(self):
        tree = DockTree()
        group = tree.find_tab_group_with_panel("hierarchy")
        self.assertEqual(group.active_panel, "hierarchy")

        group.active = 1
        self.assertEqual(group.active_panel, "files")

        rects = tree.compute_layout(0, 0, 1000, 600)
        self.assertNotIn("hierarchy", rects)
        self.assertIn("files", rects)

    def test_dock_as_tab_center(self):
        tree = DockTree()
        # Move inspector into hierarchy+files tab group
        success = tree.dock_panel("inspector", "hierarchy", "center")
        self.assertTrue(success)

        group = tree.find_tab_group_with_panel("hierarchy")
        self.assertIn("inspector", group.panels)
        self.assertEqual(group.active_panel, "inspector")

        # Tree was pruned of the old inspector split
        rects = tree.compute_layout(0, 0, 1000, 600)
        self.assertIn("inspector", rects)
        self.assertIn("viewport", rects)
        self.assertIn("code_panel", rects)

    def test_dock_split_left_right_top_bottom(self):
        tree = DockTree()
        # Dock code_panel to the right of inspector
        success = tree.dock_panel("code_panel", "inspector", "right")
        self.assertTrue(success)

        rects = tree.compute_layout(0, 0, 1200, 800)
        self.assertIn("code_panel", rects)
        self.assertIn("inspector", rects)

        # Code panel and inspector must now share the bottom left space side by side
        insp_r = rects["inspector"]
        code_r = rects["code_panel"]
        self.assertLessEqual(insp_r[0] + insp_r[2], code_r[0] + 10)  # inspector is to the left of code_panel

    def test_splitters_list(self):
        tree = DockTree()
        tree.compute_layout(0, 0, 1000, 600)
        splitters = tree.all_splitters()
        # Default layout has 3 splitters: main (horizontal), left (vertical), right (vertical)
        self.assertEqual(len(splitters), 3)
        for node, (sx, sy, sw, sh), orient in splitters:
            self.assertGreater(sw, 0)
            self.assertGreater(sh, 0)
            self.assertIn(orient, ("horizontal", "vertical"))

    def test_serialization_round_trip(self):
        tree = DockTree()
        tree.dock_panel("files", "viewport", "bottom")
        d = tree.to_dict()

        restored = DockTree.from_dict(d)
        rects1 = tree.compute_layout(0, 0, 1000, 600)
        rects2 = restored.compute_layout(0, 0, 1000, 600)
        self.assertEqual(rects1, rects2)

    def test_drop_zones_and_preview(self):
        target = (100, 100, 400, 300)
        zones = DockTree.get_dock_drop_zones(target)
        self.assertIn("left", zones)
        self.assertIn("right", zones)
        self.assertIn("top", zones)
        self.assertIn("bottom", zones)
        self.assertIn("center", zones)

        prev_left = DockTree.get_dock_preview_rect(target, "left")
        self.assertEqual(prev_left, (100, 100, 200, 300))

        prev_center = DockTree.get_dock_preview_rect(target, "center")
        self.assertEqual(prev_center, target)


if __name__ == "__main__":
    unittest.main()
