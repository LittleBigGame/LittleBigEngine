"""Repeated visible input, save/reopen, rendering and observer invariants."""

from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest

from lbe.desktop import Input
from lbe.project import load_project, template_path
from test_scene import RecordingGraphics


class EditorSessionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.window = SimpleNamespace(width=1440, height=900,
                                      set_clipboard_text=lambda text: None,
                                      get_clipboard_text=lambda: '')
        self.open()

    def open(self):
        self.graphics = RecordingGraphics()
        self.input = Input()
        self.runtime = load_project(self.window, self.graphics, self.input,
                                    self.directory, template=template_path('editor'))
        self.addCleanup(self.runtime.close)
        self.editor = self.runtime.entities[0].application_state
        self.send()

    def healthy(self):
        self.assertFalse(self.runtime.events.errors, list(self.runtime.events.errors))
        self.assertFalse(self.runtime.changes.errors, list(self.runtime.changes.errors))
        self.assertNotIn('ui_error', self.editor.app.components)
        for entity in self.runtime.entities:
            for instance in (*entity.systems.values(), *entity.scripts.values()):
                self.assertTrue(instance.running, (instance.name, list(instance.errors)))
                self.assertFalse(instance.errors, (instance.name, list(instance.errors)))
            if entity.parent is not None:
                self.assertIn(entity, entity.parent.children)
            for target in entity.relations.values():
                self.assertTrue(target.alive)

    def send(self, *events):
        self.input.pending.extend(events)
        self.graphics.rectangles.clear()
        self.graphics.texts.clear()
        self.runtime.step(1 / 60)
        self.healthy()

    def click(self, control, count=1):
        self.assertTrue(self.editor.ui.visible(control), control)
        x, y = control.x + control.w / 2, control.y + control.h / 2
        self.send(('click', x, y, 1, 0, count), ('release', x, y, 1, 0))

    def key(self, name, ctrl=False, shift=False):
        self.send(('key', name, ctrl, shift), ('key_up', name, ctrl, shift))

    def menu_item(self, text):
        menu = self.editor.app.relations['context_menu']
        return next(c for c in menu.children if text in c.components.get('text', ''))

    def test_seeded_edit_undo_menu_resize_and_restart_sequences(self):
        rng = random.Random(271828)
        identities = tuple(e.id for e in self.editor.game.children)
        for cycle in range(40):
            with self.subTest(cycle=cycle):
                target = self.runtime.resolve(rng.choice(identities))
                row = next(r for r in self.editor.hierarchy_rows
                           if r.visible and r.relations.get('target') is target)
                self.click(row, count=2)
                fields = [f for _, f in self.editor.component_rows
                          if f.visible and f.component_key == 'x']
                for _ in range(10):
                    if fields:
                        break
                    track = self.editor.inspector_scroll_track
                    self.assertTrue(self.editor.ui.visible(track))
                    x, y = track.x + track.w / 2, track.y + track.h - 1
                    self.send(('click', x, y, 1, 0), ('release', x, y, 1, 0))
                    fields = [f for _, f in self.editor.component_rows
                              if f.visible and f.component_key == 'x']
                self.assertTrue(fields, (cycle, target.components.get('name'),
                                         self.editor.app.relations.get('selection'),
                                         [(f.components.get('component_key'), f.visible)
                                          for _, f in self.editor.component_rows],
                                         self.editor.inspector.w, self.editor.inspector.h))
                field = fields[0]
                before = target.x
                value = rng.randint(-10, 10)
                self.click(field)
                self.key('A', ctrl=True)
                self.send(('text', str(value)))
                self.key('ENTER')
                self.assertEqual(target.x, value)
                self.key('Z', ctrl=True)
                self.assertEqual(target.x, before)
                self.key('Z', ctrl=True, shift=True)
                self.assertEqual(target.x, value)
                self.key('ESCAPE')
                self.click(self.editor.menu_view_btn)
                self.key('ESCAPE')
                self.key('F3')
                self.key('F3')
                self.window.width, self.window.height = rng.choice([(1440, 900), (1100, 740), (1600, 1000)])
                self.send()
                self.click(self.editor.menu_file_btn)
                self.click(self.menu_item('Save Project'))
                if cycle % 8 == 7:
                    expected = {identity: self.runtime.resolve(identity).x for identity in identities}
                    self.runtime.close()
                    self.open()
                    self.assertEqual({identity: self.runtime.resolve(identity).x for identity in identities}, expected)
        self.assertLess(len(self.runtime.entities), 600)

    def test_invalid_unscripted_geometry_does_not_stop_rendering_and_recovers(self):
        parent = self.runtime.create(parent=self.editor.game, name='Parent', x=1, y=1)
        child = self.runtime.create(parent=parent, name='Fallback', x=1, y=1,
                                    w=1, h=1, color=(100, 150, 200))
        parent.x = 'invalid parent coordinate'
        self.send()
        renderer = self.editor.game.systems['render']
        self.assertTrue(renderer.running)
        self.assertNotIn(child, self.runtime.services['space'].query(0, 0, 10, 10))
        self.click(self.editor.viewport)
        parent.x = 1
        self.send()
        self.assertIn(child, self.runtime.services['space'].query(0, 0, 10, 10))
        self.assertTrue(any(kw.get('key') == (child.id.hex, 'fallback_draw')
                            for _, kw in self.graphics.rectangles))
