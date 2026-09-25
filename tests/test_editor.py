from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from lbe.desktop import Input
from lbe.project import load_project, template_path
from test_scene import RecordingGraphics


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.input = Input()
        self.graphics = RecordingGraphics()
        self.clipboard = ""
        self.window = SimpleNamespace(width=1440, height=900,
                                      set_clipboard_text=lambda text: setattr(self, "clipboard", text),
                                      get_clipboard_text=lambda: self.clipboard)
        self.runtime = load_project(self.window, self.graphics, self.input, self.directory.name, template=template_path("editor"))
        self.addCleanup(self.runtime.close)
        self.editor = self.runtime.entities[0].components["application_state"]
        self.runtime.step(0)
        self.assert_healthy()

    def assert_healthy(self):
        instance = self.editor.app.systems["app"]
        self.assertTrue(instance.running, list(instance.errors))
        self.assertEqual(list(instance.errors), [])

    def send(self, *events, dt=0):
        self.input.pending.extend(events)
        self.runtime.step(dt)
        self.assert_healthy()

    def click(self, entity):
        self.send(("click", entity.x+entity.w/2, entity.y+entity.h/2, 1, 0))

    def type(self, entity, text, commit=False):
        self.click(entity)
        self.send(("key", "A", True, False), ("text", text))
        if commit:
            self.send(("key", "ENTER", False, False))

    def select(self, target):
        row = next(row for row in self.editor.hierarchy_rows if row.visible and row.relations.get("target") is target)
        self.click(row)
        self.runtime.step(0)

    def test_live_component_editing_and_spatial_refresh(self):
        selected = self.editor.app.relations["selection"]
        x_field = next(field for _, field in self.editor.component_rows if field.visible and field.component_key == "x")
        self.type(x_field, "10.0", commit=True)
        self.assertEqual(selected.x, 10)
        self.assertIn(selected, self.runtime.services["space"].query(10, 0))
        color = next(field for _, field in self.editor.component_rows if field.visible and field.component_key == "color")
        self.type(color, "(255, 0, 128)", commit=True)
        self.assertEqual(selected.color, (255, 0, 128))
        self.assertIn((255, 0, 128), [kwargs["color"] for _, kwargs in self.graphics.rectangles if "color" in kwargs])

    def test_complete_system_authoring_path_through_input(self):
        moving, still = self.editor.game.children
        original = moving.x, moving.y
        stationary = still.x, still.y
        for name, value in (("vx", "2.0"), ("vy", "-1.0")):
            self.type(self.editor.add_name, name)
            self.type(self.editor.add_value, value)
            self.click(self.editor.add_button)
        self.assertEqual((moving.vx, moving.vy), (2, -1))
        self.click(self.editor.new_button)
        self.type(self.editor.path_field, "physics.py")
        self.type(self.editor.code, 'def update(dt):\n    for child in query("x", "y", "vx", "vy"):\n        child.x += child.vx * dt\n        child.y += child.vy * dt\n')
        self.click(self.editor.save_button)
        self.assertTrue((Path(self.directory.name)/"physics.py").exists())
        self.select(self.editor.game)
        self.click(self.editor.attach_button)
        self.runtime.step(0.5)
        self.assertEqual((moving.x, moving.y), (original[0]+1, original[1]-0.5))
        self.assertEqual((still.x, still.y), stationary)
        instance = self.editor.game.systems["physics"]
        self.assertTrue(instance.running)
        self.assertEqual(tuple(instance.errors), ())
        self.click(self.editor.system_panel_button)
        self.assertEqual(self.editor.extra_panels[-1].view_type, "system")
        self.assertIs(self.editor.extra_panels[-1].relations["target"], self.editor.game)

    def test_syntax_error_preserves_editor_and_previous_renderer(self):
        old = self.editor.game.systems["render"]
        self.type(self.editor.code, "def broken(")
        self.click(self.editor.save_button)
        self.assertIs(self.editor.game.systems["render"], old)
        self.assertTrue(old.running)
        self.assertIn("SyntaxError", self.editor.app.status)
        self.assert_healthy()

    def test_editor_source_is_visible_and_reload_keeps_spatial_index(self):
        self.select(self.editor.app)
        self.runtime.step(0)
        button = self.editor.system_rows[0]
        self.click(button)
        self.assertEqual(self.editor.path_field.buffer.text, "app.py")
        self.click(self.editor.save_button)
        self.runtime.step(0)
        self.assert_healthy()
        moving = self.editor.game.children[0]
        moving.x = 10
        self.assertIn(moving, self.runtime.services["space"].query(10, 0))

    def test_tags_relations_parent_and_generic_panel(self):
        moving = self.editor.app.relations["selection"]
        self.type(self.editor.tags_field, "visible, selected", commit=True)
        self.assertEqual(set(moving.tags), {"visible", "selected"})
        self.type(self.editor.relation_field, "friend=Entity B", commit=True)
        self.assertIs(moving.relations["friend"], self.editor.game.children[1])
        self.type(self.editor.parent_field, "Application", commit=True)
        self.assertIs(moving.parent, self.editor.app)
        self.click(self.editor.panel_button)
        panel = self.editor.extra_panels[-1]
        self.assertIs(panel.relations["target"], moving)
        self.assertIn(panel, self.editor.app.children)
        self.assertTrue(all("ui" in child.tags for child in panel.children))

    def test_clipboard_and_undo(self):
        self.type(self.editor.code, "hello")
        self.send(("key", "A", True, False), ("key", "C", True, False))
        self.assertEqual(self.clipboard, "hello")
        self.send(("text", "replacement"), ("key", "Z", True, False))
        self.assertEqual(self.editor.code.buffer.text, "hello")

    def test_unsupported_value_is_readonly(self):
        self.editor.app.relations["selection"].components.clear()
        self.editor.app.relations["selection"].opaque = object()
        self.runtime.step(0)
        field = next(field for _, field in self.editor.component_rows if field.visible)
        self.assertTrue(field.readonly)
        self.click(field)
        self.assertIsNot(self.editor.ui.focused, field)

    def test_source_cannot_escape_project_directory(self):
        self.type(self.editor.path_field, "../outside.py")
        self.click(self.editor.save_button)
        self.assertIn("inside the project", self.editor.app.status)

    def test_new_source_requires_repeat_before_discarding_edits(self):
        self.type(self.editor.code, "unsaved = 1")
        self.click(self.editor.new_button)
        self.assertEqual(self.editor.code.buffer.text, "unsaved = 1")
        self.assertIn("Unsaved", self.editor.app.status)
        self.click(self.editor.new_button)
        self.assertEqual(self.editor.code.buffer.text, "def update(dt):\n    pass\n")

    def test_component_panel_and_save_preserve_cursor(self):
        field = next(field for _, field in self.editor.component_rows if field.visible and field.component_key == "color")
        self.send(("click", field.x+10, field.y+10, 4, 0))
        self.assertEqual(self.editor.extra_panels[-1].view_type, "component")
        self.editor.extra_panels[-1].destroy()
        self.type(self.editor.code, "def draw():\n    pass\n")
        position = self.editor.code.buffer.cursor
        self.click(self.editor.save_button)
        self.assertEqual(self.editor.code.buffer.cursor, position)

    def test_game_runtime_error_keeps_editor_interactive(self):
        self.click(self.editor.new_button)
        self.type(self.editor.path_field, "broken.py")
        self.type(self.editor.code, "def update(dt): raise ValueError('script failed')")
        self.select(self.editor.game)
        self.click(self.editor.attach_button)
        self.runtime.step(1)
        self.assertFalse(self.editor.game.systems["broken"].running)
        self.assert_healthy()
        self.click(self.editor.panel_button)
        self.assertEqual(len(self.editor.extra_panels), 1)

    def test_project_source_reload_rebinds_actions_without_rebuilding_controls(self):
        from lbe import SystemDefinition
        root = self.editor.app
        old = root.systems["app"]
        source = old.definition.source.replace("New source:", "Revised source:")
        before = set(self.runtime.entities)
        replacement = root.systems.reload("app", SystemDefinition(source, old.definition.path))
        self.assertIsNot(replacement, old)
        self.assertEqual(set(self.runtime.entities), before)
        self.click(self.editor.new_button)
        self.assertIn("Revised source:", root.status)
        self.assertNotIn("editor", self.runtime.services)

    def test_source_editor_cursor_and_selection_alignment(self):
        code = self.editor.code
        pitch = code.components.get("pitch", 8.0)
        line_height = code.components.get("line_height", 20)
        self.click(code)
        self.send(("key", "A", True, False), ("text", "abcdefghijklmnopqrstuvwxyz\n1234567890"))

        # Click on character 15 of line 0 (before midpoint)
        click_x = code.x + 48 + 15 * pitch + pitch * 0.2
        click_y = code.y + 6 + line_height / 2
        self.send(("click", click_x, click_y, 1, 0))
        self.assertEqual(code.buffer.cursor, 15)

        # Click on character 15 of line 0 (after midpoint -> rounds to caret 16)
        self.send(("click", code.x + 48 + 15 * pitch + pitch * 0.8, click_y, 1, 0))
        self.assertEqual(code.buffer.cursor, 16)

        # Restore cursor to 15
        self.send(("click", click_x, click_y, 1, 0))
        self.assertEqual(code.buffer.cursor, 15)

        # Caret entity alignment
        caret = next(c for c in code.children if c.components.get("part") == "cursor")
        self.assertTrue(caret.visible)
        self.assertAlmostEqual(caret.x, code.x + 48 + 15 * pitch, delta=0.01)
        self.assertAlmostEqual(caret.y, code.y + 6, delta=0.01)

        # Select columns 5 to 12 on line 0
        code.buffer.anchor = 5
        code.buffer.cursor = 12
        code.components.touch("buffer")
        self.runtime.step(0)

        highlight = next(c for c in code.children if c.components.get("part") == "selection:0")
        self.assertTrue(highlight.visible)
        line = next(c for c in code.children if c.components.get("part") == "line:0")
        self.assertAlmostEqual(highlight.x, line.x + 5 * pitch, delta=0.01)
        self.assertAlmostEqual(highlight.w, (12 - 5) * pitch, delta=0.01)

        # Caret reveal and alignment on line 1
        code.buffer.cursor = code.buffer.anchor = len(code.buffer.text)
        code.components.touch("buffer")
        self.runtime.step(0)
        caret = next(c for c in code.children if c.components.get("part") == "cursor")
        row, col = code.buffer.position
        self.assertAlmostEqual(caret.x, code.x + 48 + (col - code.buffer.horizontal) * pitch, delta=0.01)
        self.assertAlmostEqual(caret.y, code.y + 6 + (row - code.buffer.scroll) * line_height, delta=0.01)

    def test_selection_visual_highlight_in_hierarchy_and_viewport(self):
        first, second = self.editor.game.children

        # Initially, first entity is selected
        self.select(first)
        self.runtime.step(0)

        # Check hierarchy row has clear visual highlight indicator
        row_first = next(r for r in self.editor.hierarchy_rows if r.visible and r.relations.get("target") is first)
        row_second = next(r for r in self.editor.hierarchy_rows if r.visible and r.relations.get("target") is second)
        self.assertIn("> ", row_first.text)
        self.assertNotIn("> ", row_second.text)
        self.assertEqual(row_first.color, (45, 95, 125))
        self.assertNotEqual(row_second.color, (45, 95, 125))

        # Check viewport draws highlight around first entity
        keys = [kwargs.get("key") for _, kwargs in self.graphics.rectangles]
        self.assertIn((first.id, "sel_bot"), keys)
        self.assertIn((first.id, "sel_top"), keys)
        self.assertNotIn((second.id, "sel_bot"), keys)

        # Switch selection to second entity
        self.select(second)
        self.graphics.rectangles.clear()
        self.runtime.step(0)

        self.assertNotIn("> ", row_first.text)
        self.assertIn("> ", row_second.text)
        self.assertNotEqual(row_first.color, (45, 95, 125))
        self.assertEqual(row_second.color, (45, 95, 125))

        keys = [kwargs.get("key") for _, kwargs in self.graphics.rectangles]
        self.assertNotIn((first.id, "sel_bot"), keys)
        self.assertIn((second.id, "sel_bot"), keys)

        # Select an entity without drawable spatial bounds (e.g. Game)
        self.select(self.editor.game)
        self.graphics.rectangles.clear()
        self.runtime.step(0)

        row_game = next(r for r in self.editor.hierarchy_rows if r.visible and r.relations.get("target") is self.editor.game)
        self.assertIn("> ", row_game.text)
        self.assertEqual(row_game.color, (45, 95, 125))
        # No selection borders drawn in viewport for Game
        keys = [kwargs.get("key") for _, kwargs in self.graphics.rectangles]
        self.assertFalse(any(isinstance(k, tuple) and len(k) == 2 and str(k[1]).startswith("sel_") for k in keys))

    def test_viewport_camera_mouse_navigation(self):
        vp = self.editor.viewport
        cam = self.editor.camera
        initial_cam_x, initial_cam_y = cam.x, cam.y
        initial_zoom = cam.zoom

        # Drag inside viewport with dx=48, dy=-24
        self.send(("drag", vp.x + 100, vp.y + 100, 1, 0, 48, -24))
        self.assertAlmostEqual(cam.x, initial_cam_x - 48 / initial_zoom, delta=0.01)
        self.assertAlmostEqual(cam.y, initial_cam_y - 24 / initial_zoom, delta=0.01)

        # Drag using incremental positions (without explicit dx/dy in event)
        self.editor.viewport.drag_pos = None
        cam_x_before = cam.x
        cam_y_before = cam.y
        self.send(("drag", vp.x + 200, vp.y + 200, 1, 0))
        self.send(("drag", vp.x + 248, vp.y + 224, 1, 0))
        self.assertAlmostEqual(cam.x, cam_x_before - 48 / initial_zoom, delta=0.01)
        self.assertAlmostEqual(cam.y, cam_y_before + 24 / initial_zoom, delta=0.01)

        # Scroll inside viewport zooms camera towards cursor
        cam_before_zoom = (cam.x, cam.y, cam.zoom)
        from lbe.space import screen_to_world
        cursor_world = screen_to_world(cam, vp, vp.x + 100, vp.y + 100)
        self.send(("scroll", vp.x + 100, vp.y + 100, 0, 1))
        self.assertGreater(cam.zoom, cam_before_zoom[2])
        cursor_world_after = screen_to_world(cam, vp, vp.x + 100, vp.y + 100)
        self.assertAlmostEqual(cursor_world[0], cursor_world_after[0], delta=0.01)
        self.assertAlmostEqual(cursor_world[1], cursor_world_after[1], delta=0.01)

        # Dragging outside viewport (e.g. in code editor) does not move camera
        cam_state = (cam.x, cam.y, cam.zoom)
        code = self.editor.code
        self.click(code)
        self.send(("drag", code.x + 60, code.y + 20, 1, 0, 50, 50))
        self.assertEqual((cam.x, cam.y, cam.zoom), cam_state)
