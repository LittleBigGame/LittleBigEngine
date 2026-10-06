"""Saved, portable profiling workloads must exercise real collision/data paths."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from lbe.desktop import Input
from lbe.project import load_project
from test_scene import RecordingGraphics


def example_module(name):
    path = Path(__file__).resolve().parents[1] / 'examples/bouncy_box' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'bouncy_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = example_module('build')
profile = example_module('profile_scenes')


class BouncyBoxTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'scene'
        build.build_scene(self.directory, 16)
        self.window = SimpleNamespace(width=1440, height=900)
        self.runtime = self.load(self.directory)
        self.game = self.runtime.services['game']

    def load(self, directory):
        runtime = load_project(self.window, RecordingGraphics(), Input(), directory)
        self.addCleanup(runtime.close)
        return runtime

    def test_fixed_step_scene_exchanges_data_and_draws_shared_uuid_texture(self):
        ids = {b.id for b in self.game.children}
        before = {b.id: b.checksum for b in self.game.children}
        for _ in range(60):
            self.runtime.step(1 / 60)
        profile.healthy(self.runtime)
        self.assertEqual(self.game.tick, 120)
        self.assertGreater(self.game.messages, 0)
        self.assertGreater(self.game.contacts, 0)
        self.assertTrue(any(b.checksum != before[b.id] for b in self.game.children))
        self.assertTrue(any(b.payload['generation'] > 0 for b in self.game.children))
        self.assertTrue(any('last_contact' in b.relations for b in self.game.children))
        self.assertEqual({b.id for b in self.game.children}, ids)
        self.assertEqual(len(self.runtime.entities), 20)
        self.assertTrue(self.runtime.services['effects'].records())
        self.assertGreater(self.runtime.services['log'].sequence, 0)
        sprites = self.runtime.services['graphics'].sprites
        self.assertEqual(len({args[0].id for args, _ in sprites}), 1)
        self.assertEqual({kw['key'] for _, kw in sprites}, ids)

    def test_portable_saved_copy_replays_same_initial_state_and_uuid_routes(self):
        copied = self.directory.parent / 'copied-project'
        shutil.copytree(self.directory, copied)
        other = self.load(copied)
        for _ in range(25):
            self.runtime.step(1 / 60)
            other.step(1 / 60)
        profile.healthy(other)
        for ball in self.game.children:
            counterpart = other.resolve(ball.id)
            self.assertEqual((ball.x, ball.y, ball.vx, ball.vy, ball.checksum, ball.payload),
                             (counterpart.x, counterpart.y, counterpart.vx, counterpart.vy,
                              counterpart.checksum, counterpart.payload))
            self.assertTrue(other.assets.resolve(counterpart.sprite).path.is_relative_to(copied))

    def test_elastic_head_on_collision_preserves_momentum_and_routes_both_messages(self):
        first, second = self.game.children[:2]
        for ball, x, vx in ((first, 1.0, 1.0), (second, 1.6, -1.0)):
            ball.x, ball.y = x, 1.0
            ball.radius, ball.w, ball.h, ball.mass = 0.4, 0.8, 0.8, 1.0
            ball.vx, ball.vy, ball.angular_velocity = vx, 0.0, 0.0
            ball.restitution = 1.0
        self.assertTrue(self.game.systems['physics'].namespace['collide'](first, second))
        self.assertAlmostEqual(first.vx, -1.0)
        self.assertAlmostEqual(second.vx, 1.0)
        self.assertAlmostEqual(first.mass * first.vx + second.mass * second.vx, 0.0)
        self.assertAlmostEqual(0.5 * first.vx ** 2 + 0.5 * second.vx ** 2, 1.0)
        self.assertEqual(self.game.messages, 2)
        self.assertIs(first.relations['last_contact'], second)
        self.assertIs(second.relations['last_contact'], first)

    def test_frame_budget_bounds_catch_up_work(self):
        self.runtime.step(5)
        profile.healthy(self.runtime)
        self.assertEqual(self.game.tick, 8)
        self.assertGreater(self.game.dropped_time, 0)

    def test_build_refuses_existing_scene_and_archive_has_relative_projects(self):
        with self.assertRaises(FileExistsError):
            build.build_scene(self.directory, 16)
        archive = build.zip_bundle(self.directory, self.directory.parent / 'scenes.zip')
        import zipfile
        with zipfile.ZipFile(archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertIn('project.json', bundle.namelist())
            self.assertIn('textures/ball.png', bundle.namelist())
            self.assertFalse(any(Path(name).is_absolute() or '..' in Path(name).parts for name in bundle.namelist()))
