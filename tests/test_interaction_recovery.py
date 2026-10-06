"""Interrupted input must never leave stale pointer ownership or drop payloads."""

from types import SimpleNamespace
import unittest

from lbe import Runtime
from lbe.desktop import Input
from lbe.ui import UI
from test_scene import RecordingGraphics


class InteractionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)
        self.root = self.runtime.create()
        self.input = Input()
        self.ui = UI(self.root, SimpleNamespace(width=900, height=700),
                     RecordingGraphics(), self.input)
        self.ui.install()
        self.handle = self.ui.splitter(self.root, 'Handle', axis='x', x=10, y=10, w=10, h=100)

    def capture(self):
        self.ui.dispatch(('click', 12, 12, 1, 0))
        self.root.relations['text_drag'] = self.handle
        for name in ('entity_drag', 'asset_drag', 'dock_drag'):
            self.root.components[name] = {'name': 'payload'}

    def assert_released(self):
        for name in ('text_drag', 'active_drag'):
            self.assertNotIn(name, self.root.relations)
        for name in ('entity_drag', 'asset_drag', 'dock_drag'):
            self.assertNotIn(name, self.root.components)

    def test_focus_loss_cancels_every_capture_and_held_key(self):
        self.capture()
        self.input.press('CTRL')
        self.input.ctrl = True
        self.input.pending.append(('cancel',))
        self.runtime.step(0)
        self.assert_released()
        self.assertEqual(self.input.held, set())
        self.assertFalse(self.input.ctrl)

    def test_escape_cancels_a_drag_without_running_drop_actions(self):
        self.capture()
        calls = []
        self.root.on_entity_drop = lambda *args: calls.append(args)
        self.ui.dispatch(('key', 'ESCAPE', False, False))
        self.ui.dispatch(('release', 12, 12, 1, 0))
        self.assert_released()
        self.assertEqual(calls, [])

    def test_failing_drop_still_releases_capture_and_payloads(self):
        self.capture()
        def failed_drop(*args):
            raise ValueError('drop rejected')
        self.root.on_entity_drop = failed_drop
        self.input.pending.append(('release', 12, 12, 1, 0))
        self.runtime.step(0)
        self.assert_released()
        self.assertIn('drop rejected', self.root.ui_error)
        calls = []
        button = self.ui.button(self.root, 'Action', 'Action', lambda: calls.append(True),
                                x=40, y=10, w=50, h=30)
        self.input.pending.append(('click', 45, 15, 1, 0))
        self.runtime.step(0)
        self.assertEqual(calls, [True])

    def test_failing_release_callback_cannot_retain_drop_payloads(self):
        self.capture()
        def failed_release(*args):
            raise ValueError('release rejected')
        self.handle.on_release = failed_release
        self.input.pending.append(('release', 12, 12, 1, 0))
        self.runtime.step(0)
        self.assert_released()
