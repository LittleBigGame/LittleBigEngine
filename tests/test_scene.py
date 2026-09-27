from contextlib import contextmanager
from types import SimpleNamespace
import unittest

import tempfile
from lbe.project import load_project, template_path


class RecordingGraphics:
    def __init__(self):
        self.rectangles = []
        self.texts = []

    @contextmanager
    def view(self, camera, viewport):
        yield

    def rect(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))

    def text(self, *args, **kwargs):
        self.texts.append((args, kwargs))

    def char_width(self, size=10):
        return 8.0

    def line_height(self, size=10):
        return 20


class SceneTests(unittest.TestCase):
    def test_render_is_an_ordinary_inspectable_system(self):
        window = SimpleNamespace(width=900, height=600)
        graphics = RecordingGraphics()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runtime = load_project(window, graphics, None, directory.name, template=template_path("demo"))
        runtime.step(0)
        self.assertEqual(len(graphics.rectangles), 2)
        game = next(e for e in runtime.entities if e.components.get("name") == "Game")
        instance = game.systems["render"]
        self.assertEqual(tuple(instance.errors), ())
        self.assertIn("def draw", instance.definition.source)
        self.assertEqual(len(game.children), 2)
        game.children[0].x = 10
        self.assertIn(game.children[0], runtime.services["space"].query(10, 0))
        window.width = 1000
        runtime.step(0)
        self.assertEqual(game.relations["viewport"].w, 1000)
        runtime.close()

    def test_render_draws_child_entities_recursively(self):
        window = SimpleNamespace(width=900, height=600)
        graphics = RecordingGraphics()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runtime = load_project(window, graphics, None, directory.name, template=template_path("demo"))
        runtime.step(0)
        game = next(e for e in runtime.entities if e.components.get("name") == "Game")
        self.assertEqual(len(graphics.rectangles), 2)
        # Create a child entity under one of the game's direct children
        child = runtime.create(parent=game.children[0], name="ChildEntity", x=5.0, y=5.0, w=1.0, h=1.0, color=(255, 0, 0))
        graphics.rectangles.clear()
        runtime.step(0)
        # Verify child entity was drawn by render system transformed by parent
        keys = [kw.get("key") for _, kw in graphics.rectangles]
        self.assertIn(child.id, keys)
        self.assertEqual(len(graphics.rectangles), 3)
        child_rect = next(args for args, kw in graphics.rectangles if kw.get("key") == child.id)
        parent = game.children[0]
        self.assertEqual(child_rect[0], parent.x + 5.0)
        self.assertEqual(child_rect[1], parent.y + 5.0)
        runtime.close()
