from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from lbe.scene import build_demo


class RecordingGraphics:
    def __init__(self):
        self.rectangles = []

    @contextmanager
    def view(self, camera, viewport):
        yield

    def rect(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))

    def text(self, *args, **kwargs):
        pass


class SceneTests(unittest.TestCase):
    def test_render_is_an_ordinary_inspectable_system(self):
        window = SimpleNamespace(width=900, height=600)
        graphics = RecordingGraphics()
        runtime = build_demo(window, graphics, None)
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
