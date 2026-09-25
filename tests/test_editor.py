from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from lbe.desktop import Input
from lbe.editor import build_editor
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
        self.runtime = build_editor(self.window, self.graphics, self.input, self.directory.name)
        self.addCleanup(self.runtime.close)
        self.editor = self.runtime.services["editor"]
        self.runtime.step(0)
        self.assert_healthy()

    def assert_healthy(self):
        instance = self.editor.app.systems["editor"]
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
        selected = self.editor.selected
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
        self.assertEqual(self.editor.path_field.buffer.text, "editor.py")
        self.click(self.editor.save_button)
        self.runtime.step(0)
        self.assert_healthy()
        moving = self.editor.game.children[0]
        moving.x = 10
        self.assertIn(moving, self.runtime.services["space"].query(10, 0))

    def test_tags_relations_parent_and_generic_panel(self):
        moving = self.editor.selected
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
        self.editor.selected.components.clear()
        self.editor.selected.opaque = object()
        self.runtime.step(0)
        field = next(field for _, field in self.editor.component_rows if field.visible)
        self.assertTrue(field.readonly)
        self.click(field)
        self.assertIsNot(self.editor.focused, field)

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
