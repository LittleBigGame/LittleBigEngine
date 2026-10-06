"""Portable UUID textures, imports, native sprite ownership and viewport clipping."""

import importlib.util
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4
import zlib

from lbe import Assets, Runtime, TextureAsset
from lbe.assets import AssetRegistry
from lbe.desktop import Graphics, Input
from lbe.project import load_project, template_path, serialize_value
from lbe.project_files import ProjectFiles
from test_scene import RecordingGraphics


def png_bytes(width=2, height=2, color=(255, 0, 0, 255)):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes(color) * width) * height)) + chunk(b'IEND', b''))


class TextureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / 'ball.png'
        self.path.write_bytes(png_bytes())
        self.registry = AssetRegistry(self.directory)
        self.uid = self.registry.register(self.path)
        self.assets = Assets(self.registry)

    def test_uuid_resolution_is_lazy_serializable_and_tracks_renames(self):
        texture = self.assets.resolve(str(self.uid))
        self.assertIsInstance(texture, TextureAsset)
        self.assertEqual(texture.path, self.path)
        self.assertEqual(serialize_value(texture)['id'], str(self.uid))
        new_path = self.directory / 'renamed.png'
        self.path.rename(new_path)
        self.registry.rename(self.uid, new_path)
        self.assertEqual(texture.path, new_path)
        self.assertEqual(self.assets.resolve(self.registry.get_ref(self.uid)).id, self.uid)
        new_path.unlink()
        with self.assertRaises(FileNotFoundError):
            _ = texture.path
        new_path.write_bytes(png_bytes())
        self.assertEqual(texture.path, new_path)

    def test_import_preserves_original_and_has_reversible_uuid(self):
        runtime = Runtime()
        self.addCleanup(runtime.close)
        runtime.assets.registry = self.registry
        files = ProjectFiles(runtime, self.directory)
        ref = files.import_file(self.path, 'textures/import.png', save=lambda: None)
        imported = self.directory / 'textures/import.png'
        self.assertEqual(imported.read_bytes(), self.path.read_bytes())
        self.assertNotEqual(ref.id, self.uid)
        files.undo(save=lambda: None)
        self.assertFalse(imported.exists())
        self.assertTrue(self.path.exists())
        files.undo(save=lambda: None, redo=True)
        self.assertEqual(self.registry.get_id(imported), ref.id)
        self.assertEqual(runtime.assets.resolve(ref).path, imported)

    def test_import_save_failure_recovers_project_registry_and_copy(self):
        runtime = Runtime()
        self.addCleanup(runtime.close)
        runtime.assets.registry = self.registry
        files = ProjectFiles(runtime, self.directory)
        original = self.directory / 'project.json'
        original.write_text('{"version": 1}', encoding='utf-8')
        before = self.registry.to_dict()
        def fail():
            original.write_text('{}', encoding='utf-8')
            raise OSError('save failed')
        with self.assertRaisesRegex(OSError, 'save failed'):
            files.import_file(self.path, 'textures/import.png', save=fail)
        self.assertFalse((self.directory / 'textures/import.png').exists())
        self.assertEqual(self.registry.to_dict(), before)
        self.assertEqual(__import__('json').loads(original.read_text()), {'version': 1})
        with self.assertRaises(FileExistsError):
            files.import_file(self.path, self.path, save=lambda: None)
        self.assertEqual(self.path.read_bytes(), png_bytes())

    def test_native_drop_import_pill_assignment_and_project_reopen(self):
        project = self.directory / 'project'
        graphics, input_state = RecordingGraphics(), Input()
        window = SimpleNamespace(width=1440, height=900, set_clipboard_text=lambda _: None)
        runtime = load_project(window, graphics, input_state, project, template=template_path('editor'))
        self.addCleanup(runtime.close)
        runtime.step(0)
        editor = runtime.entities[0].application_state
        input_state.pending.append(('file_drop', (str(self.path),)))
        runtime.step(0)
        uid = runtime.assets.registry.get_id('textures/ball.png')
        self.assertIsNotNone(uid)
        input_state.pending.extend([
            ('click', editor.code.x + 60, editor.code.y + 60, 1, 0),
            ('key', 'A', True, False), ('key', 'BACKSPACE', False, False)])
        runtime.step(0)
        data = dict(id=str(uid), name='ball.png', path='textures/ball.png', type='image')
        editor.app.components['asset_drag'] = data
        input_state.pending.append(('release', editor.code.x + 60, editor.code.y + 60, 1, 0))
        runtime.step(0)
        self.assertIn(f'asset("{uid}")', editor.code.buffer.text)
        runtime.step(0)
        pills = [c for c in editor.ui.controls() if 'asset_pill' in c.tags]
        self.assertTrue(any(c.visible and c.asset_id == str(uid) for c in pills),
                        (editor.code.buffer.text[:180], editor.code.buffer.scroll,
                         [(c.components.get('asset_id'), c.visible) for c in pills]))
        target = editor.game.children[0]
        runtime.entities[0].systems['app'].namespace['apply_asset_to_entity'](target, data)
        runtime.step(0)
        self.assertTrue(any(kw.get('key') == target.id for _, kw in graphics.sprites))
        runtime.close()
        reopened = load_project(window, RecordingGraphics(), Input(), project, template=template_path('editor'))
        self.addCleanup(reopened.close)
        restored = reopened.resolve(target.id)
        self.assertEqual(restored.sprite.id, uid)
        self.assertEqual(reopened.assets.resolve(restored.sprite).path, project / 'textures/ball.png')


@unittest.skipUnless(importlib.util.find_spec('pyglet'), 'optional desktop dependency')
class NativeTextureTests(unittest.TestCase):
    def setUp(self):
        import pyglet
        self.window = pyglet.window.Window(64, 64, visible=False)
        self.addCleanup(self.window.close)
        self.window.switch_to()
        self.graphics = Graphics(self.window)
        self.addCleanup(self.graphics.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'ball.png'
        self.path.write_bytes(png_bytes())
        registry = AssetRegistry(directory.name)
        self.ref = Assets(registry).resolve(registry.register(self.path))

    def test_sprites_share_texture_pool_refresh_edits_and_release_gpu_ownership(self):
        graphics = self.graphics
        graphics.begin()
        for key in range(2):
            graphics.sprite(self.ref, key * 10, 0, 8, 8, key=key)
        graphics.finish()
        self.assertEqual(len(graphics._pool), 2)
        self.assertEqual(len(graphics._textures), 1)
        sprite = graphics._pool[('sprite', 0, 1)]
        image = sprite.image
        self.path.write_bytes(png_bytes(3, 3, (0, 255, 0, 255)))
        graphics.begin()
        graphics.sprite(self.ref, 0, 0, 8, 8, key=0)
        graphics.finish()
        self.assertIs(graphics._pool[('sprite', 0, 1)], sprite)
        self.assertIsNot(sprite.image, image)
        self.assertEqual(sprite.image.width, 3)
        graphics.begin()
        graphics.finish()
        self.assertEqual(graphics._pool, {})
        self.assertEqual(graphics._textures, {})

    def test_corrupt_image_fails_without_poisoning_repaired_texture(self):
        self.path.write_bytes(b'broken image')
        self.graphics.begin()
        with self.assertRaisesRegex(ValueError, 'Cannot load texture'):
            self.graphics.sprite(self.ref, 0, 0)
        self.graphics.finish()
        self.path.write_bytes(png_bytes())
        self.graphics.begin()
        self.graphics.sprite(self.ref, 0, 0, key='fixed')
        self.graphics.finish()
        self.assertEqual(len(self.graphics._pool), 1)

    def test_world_sprites_are_clipped_to_viewport_and_restore_gl_state(self):
        import pyglet
        from pyglet import gl
        gl.glClearColor(0, 0, 0, 1)
        self.window.clear()
        viewport = SimpleNamespace(x=16, y=16, w=16, h=16)
        camera = SimpleNamespace(x=0, y=0, zoom=1)
        self.graphics.begin()
        with self.graphics.view(camera, viewport):
            self.graphics.sprite(self.ref, -24, -24, 48, 48, key='clip')
        self.graphics.finish()
        data = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
        pixels = data.get_bytes('RGBA', data.width * 4)
        def pixel(x, y):
            index = (y * data.width + x) * 4
            return tuple(pixels[index:index + 3])
        self.assertEqual(pixel(5, 5), (0, 0, 0))
        self.assertEqual(pixel(24, 40), (255, 0, 0))
        self.assertFalse(gl.glIsEnabled(gl.GL_SCISSOR_TEST))


if __name__ == '__main__':
    unittest.main()
