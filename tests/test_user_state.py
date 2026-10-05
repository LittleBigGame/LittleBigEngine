"""Tests for LittleBigEngine user state persistence and auto-opening last project."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lbe.user_state import (
    get_user_state,
    set_user_state,
    get_last_project,
    save_last_project,
    get_last_directory,
    STATE_FILE,
)
from lbe.project import load_project, template_path
from lbe.desktop import Input
import sys
sys.path.insert(0, str(Path(__file__).parent))
from test_scene import RecordingGraphics


class UserStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project_path = Path(self.directory.name).resolve()

        state_directory = self.project_path / 'preferences'
        for name, value in [('STATE_DIR', state_directory),
                            ('STATE_FILE', state_directory / 'state.json')]:
            binding = patch('lbe.user_state.' + name, value)
            binding.start()
            self.addCleanup(binding.stop)

    def test_save_and_get_last_project(self):
        proj_dir = self.project_path / "test_game.lbe"
        proj_dir.mkdir(parents=True, exist_ok=True)

        save_last_project(proj_dir)

        retrieved_proj = get_last_project()
        self.assertIsNotNone(retrieved_proj)
        self.assertEqual(retrieved_proj, proj_dir)

        retrieved_dir = get_last_directory()
        self.assertEqual(retrieved_dir, self.project_path)

    def test_load_project_automatically_updates_user_state(self):
        window = SimpleNamespace(width=1440, height=900)
        graphics = RecordingGraphics()
        input_state = Input()

        runtime = load_project(window, graphics, input_state, self.project_path, template=template_path("editor"))
        self.addCleanup(runtime.close)

        last_proj = get_last_project()
        self.assertEqual(last_proj, self.project_path)
