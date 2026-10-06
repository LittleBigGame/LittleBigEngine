"""Saved, portable profiling workloads must exercise real collision/data paths."""
import importlib.util
import json
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

    def test_kernel_without_sprite_api_draws_round_balls_and_exchanges_packets(self):
        recorded = RecordingGraphics()
        graphics = SimpleNamespace(rect=recorded.rect, text=recorded.text, view=recorded.view)
        runtime = load_project(self.window, graphics, Input(), self.directory)
        self.addCleanup(runtime.close)
        game = runtime.services['game']
        for _ in range(30):
            runtime.step(1 / 60)
        profile.healthy(runtime)
        self.assertGreater(game.messages, 0)
        self.assertTrue(any(b.payload['generation'] > 0 for b in game.children))
        for ball in game.children:
            recorded.rectangles.clear()
            ball.run(game.drawing_script)
            self.assertEqual(len(recorded.rectangles), 16)
            for args, kw in recorded.rectangles:
                x, y, w, h = args
                self.assertGreaterEqual(x, ball.x)
                self.assertGreaterEqual(y, ball.y)
                self.assertLessEqual(x + w, ball.x + ball.w + 1e-10)
                self.assertLessEqual(y + h, ball.y + ball.h + 1e-10)
                self.assertEqual(kw['key'][0], ball.id)
            widths = [args[2] for args, _ in recorded.rectangles]
            self.assertLess(widths[0], widths[7])
            self.assertAlmostEqual(widths[0], widths[-1])

    def test_build_refuses_existing_scene_and_archive_has_relative_projects(self):
        with self.assertRaises(FileExistsError):
            build.build_scene(self.directory, 16)
        (self.directory / 'profiles').mkdir()
        (self.directory / 'profiles/raw.txt').write_text('profiling output', encoding='utf-8')
        archive = build.zip_bundle(self.directory, self.directory.parent / 'scenes.zip', include_profiles=False)
        import zipfile
        with zipfile.ZipFile(archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertIn('project.json', bundle.namelist())
            self.assertIn('textures/ball.png', bundle.namelist())
            self.assertNotIn('profiles/raw.txt', bundle.namelist())
            self.assertFalse(any(Path(name).is_absolute() or '..' in Path(name).parts for name in bundle.namelist()))

    def test_distributed_zip_has_exact_saved_inputs_and_current_portable_sources(self):
        import zipfile
        example = Path(__file__).resolve().parents[1] / 'examples/bouncy_box'
        with zipfile.ZipFile(example / 'LBETestScenes.zip') as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertFalse(any(name.startswith('profiles/') for name in bundle.namelist()))
            self.assertEqual(bundle.read('profile_scenes.py'), (example / 'profile_scenes.py').read_bytes())
            for count in (128, 512, 2048, 4096):
                prefix = f'BouncyBox_{count:05d}.lbe/'
                data = json.loads(bundle.read(prefix + 'project.json'))
                self.assertEqual(len(data['entities']), count + 3)
                self.assertEqual(json.loads(bundle.read(prefix + 'scene.json'))['balls'], count)
                assets = data['assets']
                texture = next(uid for uid, value in assets.items() if value['path'] == 'textures/ball.png')
                balls = [e for e in data['entities'] if 'ball' in e['tags']]
                self.assertEqual(len(balls), count)
                self.assertTrue(all(ball['components']['sprite']['id'] == texture for ball in balls))
                for path in (example / 'template').rglob('*.py'):
                    relative = path.relative_to(example / 'template').as_posix()
                    self.assertEqual(bundle.read(prefix + relative), path.read_bytes())
                for entity in data['entities']:
                    for kind in ('systems', 'scripts'):
                        for declaration in entity.get(kind, {}).values():
                            if 'active_source' in declaration:
                                self.assertEqual(declaration['active_source'],
                                                 bundle.read(prefix + declaration['path']).decode('utf-8'))
                self.assertTrue(all(not Path(value['path']).is_absolute() and '..' not in Path(value['path']).parts
                                    for value in assets.values()))


@unittest.skipUnless(importlib.util.find_spec('pyglet'), 'optional desktop dependency')
class NativeBouncyBoxTests(unittest.TestCase):
    def test_saved_scene_paints_ball_centers_with_both_graphics_apis(self):
        import pyglet
        from pyglet import gl
        from lbe.desktop import Graphics
        from lbe.space import world_to_screen
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = build.build_scene(Path(temporary.name) / 'scene.lbe', 16)
        window = pyglet.window.Window(320, 240, visible=False)
        self.addCleanup(window.close)
        window.switch_to()
        graphics = Graphics(window)
        self.addCleanup(graphics.close)
        for textured in (True, False):
            with self.subTest(textured=textured):
                adapter = graphics if textured else SimpleNamespace(
                    rect=graphics.rect, text=graphics.text, view=graphics.view)
                runtime = load_project(window, adapter, Input(), directory)
                try:
                    window.clear()
                    graphics.begin()
                    runtime.step(0)
                    graphics.finish()
                    gl.glFinish()
                    profile.healthy(runtime)
                    game = runtime.services['game']
                    viewport, camera = game.relations['viewport'], game.relations['camera']
                    image = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
                    pixels = image.get_bytes('RGBA', image.width * 4)
                    for ball in game.children:
                        x, y = world_to_screen(camera, viewport,
                                               ball.x + ball.radius, ball.y + ball.radius)
                        px = int(x * image.width / window.width)
                        py = image.height - 1 - int(y * image.height / window.height)
                        index = (py * image.width + px) * 4
                        rgb = tuple(pixels[index:index + 3])
                        self.assertGreater(sum(rgb), 120, (ball.id, rgb))
                    self.assertEqual(len(graphics._textures), 1 if textured else 0)
                finally:
                    runtime.close()
                    graphics.close()
