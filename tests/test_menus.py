import tempfile
import unittest
from types import SimpleNamespace
from lbe import Runtime
from lbe.desktop import Input
from lbe.ui import UI
from lbe.menus import open_menu
from lbe.project import load_project, template_path
from test_scene import RecordingGraphics


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.root = self.runtime.create()
        self.ui = UI(self.root, SimpleNamespace(width=900, height=700), RecordingGraphics(), Input())
        self.addCleanup(self.runtime.close)

    def test_custom_target_keyboard_disabled_and_no_text_leak(self):
        target = {'count': 0}
        field = self.ui.field(self.root, 'Field', 'original')
        self.ui.focus(field)
        menu = open_menu(self.ui, target, 899, 699, [
            dict(label='Disabled', enabled=False, run=lambda t: self.fail()),
            None, dict(label='Increment', run=lambda t: t.update(count=t['count']+1))])
        self.assertLessEqual(menu.x+menu.w, 900)
        self.assertLessEqual(menu.y+menu.h, 700)
        self.ui.dispatch(('text', 'leak'))
        self.assertEqual(field.buffer.text, 'original')
        self.ui.dispatch(('key', 'DOWN', False, False))
        self.ui.dispatch(('key', 'ENTER', False, False))
        self.assertEqual(target['count'], 1)
        self.assertNotIn('context_menu', self.root.relations)
        self.assertIs(self.ui.focused, field)

    def test_provider_discovery_right_click_and_outside_capture(self):
        calls = []
        button = self.ui.button(self.root, 'Button', 'Button', lambda: calls.append('button'), x=0,y=0,w=100,h=30)
        button.context_actions = lambda target: [dict(label='Custom',run=lambda t: calls.append(t))]
        self.ui.dispatch(('click', 10, 10, 4, 0))
        menu = self.root.relations['context_menu']
        self.assertIs(menu.context_target, button)
        self.assertEqual(calls, [])
        self.ui.dispatch(('click', 800, 600, 1, 0))
        self.assertEqual(calls, [])
        self.assertFalse(menu.alive)

    def test_mouse_action_and_dead_target(self):
        calls = []
        target = self.runtime.create()
        menu = open_menu(self.ui, target, 30, 40, [dict(label='Run', run=calls.append)])
        item = menu.children[0]
        self.ui.dispatch(('click', item.x+2, item.y+2, 1, 0))
        self.assertEqual(calls, [target])
        open_menu(self.ui, target, 30, 40, [dict(label='Run', run=calls.append)])
        self.runtime.destroy(target)
        self.ui.dispatch(('key', 'ENTER', False, False))
        self.assertEqual(calls, [target])
        self.assertNotIn('context_menu', self.root.relations)

    def test_long_menu_keyboard_reveals_last_action(self):
        self.ui.window.height = 100
        menu = open_menu(self.ui, object(), 0, 0, [dict(label=str(i), run=lambda t: None) for i in range(20)])
        self.ui.dispatch(('key', 'UP', False, False))
        self.assertTrue(menu.children[-1].visible)
        self.ui.dispatch(('key', 'ESCAPE', False, False))
        self.assertFalse(menu.alive)

    def test_editor_hierarchy_and_viewport(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = load_project(self.ui.window, RecordingGraphics(), Input(), directory, template=template_path('editor'))
            self.addCleanup(runtime.close)
            runtime.step(0)
            root = runtime.entities[0]
            state = root.application_state
            ui = state.ui
            row = next(r for r in state.hierarchy_rows if r.visible)
            ui.dispatch(('click', row.x+40, row.y+10, 4, 0))
            self.assertIs(root.relations['context_menu'].context_target, row.relations['target'])
            ui.dispatch(('key', 'ESCAPE', False, False))
            viewport = state.viewport
            ui.dispatch(('click', viewport.x+viewport.w-5, viewport.y+viewport.h-5, 4, 0))
            self.assertIs(root.relations['context_menu'].context_target, state.game)
            self.assertTrue(all(not s.errors for e in runtime.entities for s in e.systems.values()))

    def test_menu_motion_scroll_and_empty_actions(self):
        # Empty actions return None
        self.assertIsNone(open_menu(self.ui, object(), 10, 10, []))

        # Motion highlights item
        menu = open_menu(self.ui, object(), 10, 10, [
            dict(label="First", run=lambda t: None),
            dict(label="Second", run=lambda t: None),
        ])
        item1 = menu.children[1]
        self.ui.dispatch(("motion", item1.x + 5, item1.y + 5))
        self.assertEqual(menu.active, 1)

        # Scroll moves offset
        self.ui.dispatch(("scroll", menu.x + 5, menu.y + 5, 0, -1))

        # Disabled item click does not run
        ran = []
        menu2 = open_menu(self.ui, object(), 10, 10, [
            dict(label="Disabled", enabled=False, run=ran.append)
        ])
        dis_item = menu2.children[0]
        self.ui.dispatch(("click", dis_item.x + 5, dis_item.y + 5, 1, 0))
        self.assertEqual(ran, [])

