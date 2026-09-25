import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from lbe import Runtime
from lbe.desktop import Input
from lbe.project import load_project, template_path
from lbe.ui import UI, stack
from test_scene import RecordingGraphics


class UITests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(width=900, height=700)
        self.graphics = RecordingGraphics()
        self.input = Input()

    def test_unrelated_application_runs_without_editor_services(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_project(self.window, self.graphics, self.input, directory,
                                   template=template_path("counter"))
            root = runtime.entities[0]
            runtime.step(0)
            button = next(e for e in root.descendants if e.components.get("name") == "Increment")
            self.input.pending.append(("click", button.x+10, button.y+10, 1, 0))
            runtime.step(0)
            self.assertEqual(root.count, 1)
            self.assertNotIn("editor", runtime.services)
            self.assertNotIn("application_state", root.components)
            self.assertFalse(any(e.components.get("name") in ("Game", "InspectorPanel", "CodeEditorPanel")
                                 for e in runtime.entities))
            notes = next(e for e in root.descendants if "multiline" in e.tags)
            self.input.pending.extend([("click", notes.x+60, notes.y+10, 1, 0),
                                       ("key", "A", True, False), ("text", "Independent app\nSecond line")])
            runtime.step(0)
            self.assertEqual(notes.buffer.text, "Independent app\nSecond line")
            self.assertTrue(any(e.components.get("part") == "cursor" for e in notes.children))
            self.assertTrue(all(not instance.errors for e in runtime.entities for instance in e.systems.values()))
            runtime.close()

    def test_ui_ownership_is_scoped_to_its_entity(self):
        runtime = Runtime()
        first, second = runtime.create(), runtime.create()
        ui = UI(first, self.window, self.graphics, self.input)
        other = UI(second, self.window, self.graphics, Input())
        first.count = second.count = 0
        a = ui.button(first, "A", "A", lambda: setattr(first, "count", first.count+1), x=0, y=0, w=40, h=30)
        other.button(second, "B", "B", lambda: setattr(second, "count", second.count+1), x=0, y=0, w=40, h=30)
        ui.install()
        other.install()
        self.input.pending.append(("click", 10, 10, 1, 0))
        runtime.step(0)
        self.assertEqual((first.count, second.count), (1, 0))
        self.assertEqual(tuple(ui.controls()), (a,))

    def test_hidden_parent_blocks_control_input(self):
        runtime = Runtime()
        root = runtime.create(count=0)
        ui = UI(root, self.window, self.graphics, self.input)
        panel = ui.create(root, "Panel", "panel", x=0, y=0, w=100, h=100, visible=False)
        ui.button(panel, "Button", "Click", lambda: setattr(root, "count", 1), x=0, y=0, w=50, h=30)
        ui.install()
        self.input.pending.append(("click", 10, 10, 1, 0))
        runtime.step(0)
        self.assertEqual(root.count, 0)

    def test_stack_layout_works_with_plain_entities(self):
        runtime = Runtime()
        parent = runtime.create(x=10, y=20)
        a = runtime.create(parent=parent, w=30, h=40)
        b = runtime.create(parent=parent, w=50, h=60)
        stack(parent, (a, b), padding=5, gap=3)
        self.assertEqual((a.x, a.y, b.x, b.y), (15, 25, 15, 68))

    def test_existing_project_is_not_populated_with_template_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"app.py"
            path.write_text("entity.answer = 42", encoding="utf-8")
            runtime = load_project(self.window, self.graphics, self.input, directory,
                                   template=template_path("editor"))
            self.assertEqual(runtime.entities[0].answer, 42)
            self.assertEqual({p.name for p in Path(directory).iterdir()}, {"app.py"})
            runtime.close()
