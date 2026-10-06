"""Optional pyglet platform adapter; no editor or gameplay rules live here."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from math import isfinite
import sys

from .space import world_to_screen


@dataclass
class Input:
    pending: list = field(default_factory=list)
    x: float = 0
    y: float = 0
    ctrl: bool = False
    held: set[str] = field(default_factory=set)

    def is_key_down(self, name):
        return name.upper() in self.held

    def press(self, name):
        self.held.add(name.upper())

    def release(self, name):
        self.held.discard(name.upper())

    def drain(self):
        pending, self.pending = self.pending, []
        for event in pending:
            if event[0] == "key":
                self.press(event[1])
            elif event[0] == "key_up":
                self.release(event[1])
            elif event[0] == 'cancel':
                self.held.clear()
                self.ctrl = False
        return pending


class _LayerGroups(dict):
    def __missing__(self, layer):
        import pyglet

        group = pyglet.graphics.Group(order=int(layer))
        self[layer] = group
        return group


class Graphics:
    def __init__(self, window):
        import pyglet

        self.window = window
        self.batch = pyglet.graphics.Batch()
        self._groups = _LayerGroups()
        self._pool = {}
        self._used = set()
        self._counter = 0
        self._view = None
        self._textures = {}
        self._frame_images = {}
        self._texture_used = set()
        self._clip_groups = {}
        self._retired_textures = []

    def _group(self, layer):
        return self._groups[int(layer)]

    def begin(self):
        self._used.clear()
        self._counter = 0
        self._frame_images.clear()
        self._texture_used.clear()

    def _image(self, reference):
        import pyglet
        from .assets import TextureAsset
        token = (id(reference.registry), reference.id) if isinstance(reference, TextureAsset) else str(reference)
        if token in self._frame_images:
            result = self._frame_images[token]
            if isinstance(result, Exception):
                raise result
            return result
        try:
            path = reference.path if isinstance(reference, TextureAsset) else Path(reference).resolve()
            stat = path.stat()
            signature = stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns
            previous = self._textures.get(path)
            if previous is None or previous[0] != signature:
                image = pyglet.image.load(str(path)).get_texture()
                image.anchor_x, image.anchor_y = image.width / 2, image.height / 2
                self._textures[path] = signature, image
                if previous is not None:
                    # SpriteGroup hashes include texture.id. Keep old IDs alive
                    # until every sprite migrates and Batch prunes empty groups.
                    self._retired_textures.append(previous[1])
            image = self._textures[path][1]
            self._texture_used.add(path)
            self._frame_images[token] = image
            return image
        except Exception as error:
            failure = ValueError(f'Cannot load texture {reference}: {error}')
            self._frame_images[token] = failure
            raise failure from error

    def _sprite_group(self, layer):
        if self._view is None:
            return self._group(layer)
        import pyglet
        from pyglet import gl
        viewport = self._view[1]
        key = int(layer), id(viewport)
        if key not in self._clip_groups:
            window = self.window

            class ViewportGroup(pyglet.graphics.Group):
                def set_state(self):
                    self.enabled = gl.glIsEnabled(gl.GL_SCISSOR_TEST)
                    self.previous = (gl.GLint * 4)()
                    gl.glGetIntegerv(gl.GL_SCISSOR_BOX, self.previous)
                    # Logical window coordinates differ from framebuffer pixels on HiDPI.
                    fw, fh = window.get_framebuffer_size()
                    sx, sy = fw / window.width, fh / window.height
                    x = int(max(0, viewport.x) * sx)
                    y = int(max(0, window.height - viewport.y - viewport.h) * sy)
                    right = int(min(window.width, viewport.x + viewport.w) * sx)
                    top = int(min(window.height, window.height - viewport.y) * sy)
                    if self.enabled:
                        px, py, pw, ph = self.previous
                        x, y, right, top = max(x, px), max(y, py), min(right, px + pw), min(top, py + ph)
                    gl.glEnable(gl.GL_SCISSOR_TEST)
                    gl.glScissor(x, y, max(0, right - x), max(0, top - y))

                def unset_state(self):
                    gl.glScissor(*self.previous)
                    if not self.enabled:
                        gl.glDisable(gl.GL_SCISSOR_TEST)

                def __eq__(self, other):
                    return self is other

                def __hash__(self):
                    return id(self)

            self._clip_groups[key] = ViewportGroup(parent=self._group(layer))
        return self._clip_groups[key]

    def sprite(self, texture, x, y, w=None, h=None, *, color=(255, 255, 255, 255),
               rotation=0, key=None, layer=1):
        """Draw a UUID-resolved texture, sharing GPU images and pooled sprites.

        Coordinates match rect(); rotation is clockwise about the sprite center.
        Images refresh after edits/moves and are released when no longer drawn.
        """
        import pyglet
        image = self._image(texture)
        w, h = image.width if w is None else w, image.height if h is None else h
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in (x, y, w, h, rotation)) or w < 0 or h < 0:
            raise ValueError('Sprite geometry requires finite coordinates and nonnegative dimensions')
        if not isinstance(color, (tuple, list)) or len(color) not in (3, 4) or any(type(c) is not int or not 0 <= c <= 255 for c in color):
            raise ValueError('Sprite color requires RGB/RGBA integers from 0 to 255')
        if not w or not h:
            return
        if self._view is not None:
            camera, viewport = self._view
            x, y = world_to_screen(camera, viewport, x, y + h)
            w, h = w * camera.zoom, h * camera.zoom
        identity = self._identity('sprite', key, layer)
        obj = self._pool.get(identity)
        group = self._sprite_group(layer)
        if obj is None:
            obj = pyglet.sprite.Sprite(image, batch=self.batch, group=group, subpixel=True)
            self._pool[identity] = obj
        else:
            if obj.image is not image:
                obj.image = image
            if obj.group is not group:
                obj.group = group
        obj.update(x=x + w / 2, y=self.window.height - y - h / 2,
                   scale_x=w / image.width, scale_y=h / image.height, rotation=rotation)
        obj.color = color[:3]
        obj.opacity = color[3] if len(color) == 4 else 255

    def _identity(self, kind, key, layer):
        self._counter += 1
        identity = kind, key if key is not None else self._counter, layer
        self._used.add(identity)
        return identity

    @contextmanager
    def view(self, camera, viewport):
        previous = self._view
        self._view = camera, viewport
        try:
            yield
        finally:
            self._view = previous

    def rect(self, x, y, w, h, color=(255, 255, 255), *, key=None, layer=0):
        import pyglet

        if w < 0:
            x, w = x+w, -w
        if h < 0:
            y, h = y+h, -h
        if self._view:
            camera, viewport = self._view
            x, y = world_to_screen(camera, viewport, x, y + h)
            w, h = w * camera.zoom, h * camera.zoom
            right, bottom = min(x + w, viewport.x + viewport.w), min(y + h, viewport.y + viewport.h)
            x, y = max(x, viewport.x), max(y, viewport.y)
            w, h = max(0, right - x), max(0, bottom - y)
        identity = self._identity("rect", key, layer)
        obj = self._pool.get(identity)
        if obj is None:
            obj = pyglet.shapes.Rectangle(x, self.window.height - y - h, w, h,
                                          color=color, batch=self.batch, group=self._group(layer))
            self._pool[identity] = obj
        obj.x, obj.y = x, self.window.height - y - h
        obj.width, obj.height = max(0, w), max(0, h)
        obj.color = color

    def text(self, text, x, y, *, color=(215, 223, 233, 255), size=10, key=None, layer=3):
        import pyglet

        if self._view is not None:
            camera, viewport = self._view
            x, y = world_to_screen(camera, viewport, x, y)

        identity = self._identity("text", key, layer)
        obj = self._pool.get(identity)
        if obj is None:
            obj = pyglet.text.Label(str(text), font_name="Consolas", font_size=size,
                                    x=x, y=self.window.height - y, anchor_y="top",
                                    color=color, batch=self.batch, group=self._group(layer))
            self._pool[identity] = obj
        if obj.text != str(text):
            obj.text = str(text)
        obj.x, obj.y = x, self.window.height - y
        obj.color = color
        if obj.font_size != size:
            obj.font_size = size

    def char_width(self, size=10):
        if not hasattr(self, "_char_widths"):
            self._char_widths = {}
        if size not in self._char_widths:
            import pyglet
            sample = pyglet.text.Label("X" * 100, font_name="Consolas", font_size=size)
            self._char_widths[size] = sample.content_width / 100.0
        return self._char_widths[size]

    def line_height(self, size=10):
        if not hasattr(self, "_line_heights"):
            self._line_heights = {}
        if size not in self._line_heights:
            import pyglet
            sample = pyglet.text.Label("X", font_name="Consolas", font_size=size)
            self._line_heights[size] = sample.content_height
        return self._line_heights[size]

    def finish(self):
        for key in self._pool.keys() - self._used:
            self._pool.pop(key).delete()
        self.batch.draw()
        for path in self._textures.keys() - self._texture_used:
            self._textures.pop(path)[1].delete()
        for image in self._retired_textures:
            image.delete()
        self._retired_textures.clear()

    def close(self):
        import pyglet
        for obj in self._pool.values():
            obj.delete()
        self._pool.clear()
        self.batch = pyglet.graphics.Batch()
        for _, image in self._textures.values():
            image.delete()
        self._textures.clear()
        self._frame_images.clear()
        self._clip_groups.clear()
        for image in self._retired_textures:
            image.delete()
        self._retired_textures.clear()



def launch(build, *, headless=False, frames=None, screenshot=None):
    import pyglet

    if headless and sys.platform != "win32":
        pyglet.options["headless"] = True
    from pyglet.window import key

    window = pyglet.window.Window(1440, 900, caption="LittleBigEngine", resizable=True, vsync=True,
                                  visible=not headless)
    window.set_minimum_size(1000, 700)
    pressed_keys = set()
    is_active = True
    graphics = Graphics(window)
    input_state = Input()
    runtime = None
    pending_switch = None

    def _execute_switch(directory, template=None):
        nonlocal runtime
        if runtime is not None:
            space = runtime.services.get("space")
            if space is not None:
                space.close()
            runtime.close()
            runtime = None
        graphics.close()
        input_state.pending.clear()
        if directory is None:
            from .launcher import create_launcher_runtime
            runtime = create_launcher_runtime(window, graphics, input_state, switch_project)
            return
        from .project import load_project, template_path
        if template:
            if isinstance(template, str) and not Path(template).exists():
                tpl_p = template_path(template)
            else:
                tpl_p = Path(template).resolve()
        else:
            tpl_p = None
        try:
            runtime = load_project(window, graphics, input_state, directory, template=tpl_p)
            runtime.services["switch_project"] = switch_project
            if template and "game" in runtime.services and runtime.services["game"]:
                runtime.services["game"].components["paused"] = True
        except Exception as err:
            print(f"Error switching project to {directory}: {err}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            from .launcher import create_launcher_runtime
            runtime = create_launcher_runtime(window, graphics, input_state, switch_project)

    def switch_project(directory, template=None):
        nonlocal pending_switch
        pending_switch = (directory, template)

    if build is None:
        from .launcher import create_launcher_runtime
        runtime = create_launcher_runtime(window, graphics, input_state, switch_project)
    else:
        runtime = build(window, graphics, input_state)
        if runtime is not None and "switch_project" not in runtime.services:
            runtime.services["switch_project"] = switch_project

    elapsed = 0.0
    rendered = 0
    closed = False
    failures = set()
    last_ctrl = False

    def check_ctrl():
        if not is_active:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                return bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)
            except Exception:
                pass
        return bool({key.LCTRL, key.RCTRL} & pressed_keys)

    @window.event
    def on_activate():
        nonlocal is_active
        is_active = True

    @window.event
    def on_deactivate():
        nonlocal is_active
        is_active = False
        pressed_keys.clear()
        input_state.held.clear()
        input_state.ctrl = False
        input_state.pending.append(('cancel',))

    @window.event
    def on_draw():
        nonlocal elapsed, rendered, runtime, pending_switch
        if pending_switch is not None:
            target_dir, tpl = pending_switch
            pending_switch = None
            _execute_switch(target_dir, tpl)

        window.clear()
        graphics.begin()
        cur = runtime
        if cur is not None:
            cur.step(min(elapsed, 0.1))
            if cur is not None:
                for entity in cur.entities:
                    for instance in tuple(entity.systems.values()) + tuple(entity.scripts.values()):
                        if instance.errors:
                            failures.update((error.source, error.message) for error in instance.errors)
                            app_st = cur.services.get("application_state")
                            if app_st and hasattr(app_st, "app") and not instance.running:
                                last_err = instance.errors[-1]
                                app_st.app.status = f"Error in {instance.name}: {last_err.message} | Press Ctrl+L for System Log"
        elapsed = 0.0
        graphics.finish()
        rendered += 1
        if frames is not None and rendered >= frames:
            if screenshot:
                pyglet.image.get_buffer_manager().get_color_buffer().save(str(screenshot))
            pyglet.app.exit()

    @window.event
    def on_mouse_press(x, y, button, modifiers):
        ctrl = check_ctrl() or bool(modifiers & key.MOD_CTRL) or bool({key.LCTRL, key.RCTRL} & pressed_keys)
        shift = bool(modifiers & key.MOD_SHIFT) or bool({key.LSHIFT, key.RSHIFT} & pressed_keys)
        alt = bool(modifiers & key.MOD_ALT) or bool({key.LALT, key.RALT} & pressed_keys)
        mods = modifiers | (key.MOD_CTRL if ctrl else 0) | (key.MOD_SHIFT if shift else 0) | (key.MOD_ALT if alt else 0)
        input_state.ctrl = ctrl
        input_state.pending.append(("click", x, window.height - y, button, mods))

    @window.event
    def on_mouse_release(x, y, button, modifiers):
        ctrl = check_ctrl() or bool(modifiers & key.MOD_CTRL) or bool({key.LCTRL, key.RCTRL} & pressed_keys)
        shift = bool(modifiers & key.MOD_SHIFT) or bool({key.LSHIFT, key.RSHIFT} & pressed_keys)
        alt = bool(modifiers & key.MOD_ALT) or bool({key.LALT, key.RALT} & pressed_keys)
        mods = modifiers | (key.MOD_CTRL if ctrl else 0) | (key.MOD_SHIFT if shift else 0) | (key.MOD_ALT if alt else 0)
        input_state.ctrl = ctrl
        input_state.pending.append(("release", x, window.height - y, button, mods))

    @window.event
    def on_mouse_drag(x, y, dx, dy, buttons, modifiers):
        ctrl = check_ctrl() or bool(modifiers & key.MOD_CTRL) or bool({key.LCTRL, key.RCTRL} & pressed_keys)
        shift = bool(modifiers & key.MOD_SHIFT) or bool({key.LSHIFT, key.RSHIFT} & pressed_keys)
        alt = bool(modifiers & key.MOD_ALT) or bool({key.LALT, key.RALT} & pressed_keys)
        mods = modifiers | (key.MOD_CTRL if ctrl else 0) | (key.MOD_SHIFT if shift else 0) | (key.MOD_ALT if alt else 0)
        input_state.ctrl = ctrl
        input_state.pending.append(("drag", x, window.height - y, buttons, mods, dx, -dy))

    @window.event
    def on_mouse_motion(x, y, dx, dy):
        ctrl = check_ctrl()
        input_state.ctrl = ctrl
        shift = bool({key.LSHIFT, key.RSHIFT} & pressed_keys)
        alt = bool({key.LALT, key.RALT} & pressed_keys)
        mods = (key.MOD_CTRL if ctrl else 0) | (key.MOD_SHIFT if shift else 0) | (key.MOD_ALT if alt else 0)
        input_state.x, input_state.y = x, window.height - y
        input_state.pending.append(("motion", x, window.height - y, mods))

    @window.event
    def on_file_drop(x, y, paths):
        input_state.pending.append(('file_drop', tuple(paths)))

    @window.event
    def on_mouse_scroll(x, y, scroll_x, scroll_y):
        input_state.pending.append(("scroll", x, window.height - y, scroll_x, scroll_y))

    @window.event
    def on_text(text):
        if text not in ("\r", "\n", "\t"):
            input_state.pending.append(("text", text))

    @window.event
    def on_key_press(symbol, modifiers):
        pressed_keys.add(symbol)
        input_state.press(key.symbol_string(symbol))
        ctrl = check_ctrl() or bool(modifiers & key.MOD_CTRL) or symbol in (key.LCTRL, key.RCTRL)
        input_state.ctrl = ctrl
        shift = bool(modifiers & key.MOD_SHIFT) or bool({key.LSHIFT, key.RSHIFT} & pressed_keys)
        if symbol in (key.BACKSPACE, key.DELETE) and ctrl:
            input_state.pending.append(("key", key.symbol_string(symbol), True, shift))
            return pyglet.event.EVENT_HANDLED
        if symbol in (key.LEFT, key.RIGHT, key.UP, key.DOWN, key.HOME, key.END,
                      key.PAGEUP, key.PAGEDOWN, key.BACKSPACE, key.DELETE):
            return pyglet.event.EVENT_HANDLED
        input_state.pending.append(("key", key.symbol_string(symbol),
                                    ctrl, shift))
        return pyglet.event.EVENT_HANDLED

    @window.event
    def on_key_release(symbol, modifiers):
        pressed_keys.discard(symbol)
        input_state.release(key.symbol_string(symbol))
        ctrl = check_ctrl() or bool(modifiers & key.MOD_CTRL) or bool({key.LCTRL, key.RCTRL} & pressed_keys)
        input_state.ctrl = ctrl
        shift = bool(modifiers & key.MOD_SHIFT) or bool({key.LSHIFT, key.RSHIFT} & pressed_keys)
        input_state.pending.append(("key_up", key.symbol_string(symbol), ctrl, shift))


    motions = {
        key.MOTION_LEFT: "LEFT", key.MOTION_RIGHT: "RIGHT", key.MOTION_UP: "UP", key.MOTION_DOWN: "DOWN",
        key.MOTION_BEGINNING_OF_LINE: "HOME", key.MOTION_END_OF_LINE: "END",
        key.MOTION_BEGINNING_OF_FILE: "FILE_HOME", key.MOTION_END_OF_FILE: "FILE_END",
        key.MOTION_PREVIOUS_PAGE: "PAGEUP", key.MOTION_NEXT_PAGE: "PAGEDOWN",
        key.MOTION_PREVIOUS_WORD: "WORD_LEFT", key.MOTION_NEXT_WORD: "WORD_RIGHT",
        key.MOTION_BACKSPACE: "BACKSPACE", key.MOTION_DELETE: "DELETE",
    }

    @window.event
    def on_text_motion(motion):
        if motion in motions:
            ctrl = check_ctrl() or bool({key.LCTRL, key.RCTRL} & pressed_keys)
            input_state.pending.append(("key", motions[motion], ctrl, False))

    @window.event
    def on_text_motion_select(motion):
        if motion in motions:
            ctrl = check_ctrl() or bool({key.LCTRL, key.RCTRL} & pressed_keys)
            input_state.pending.append(("key", motions[motion], ctrl, True))

    @window.event
    def on_close():
        nonlocal closed
        if not closed:
            closed = True
            runtime.close()
            graphics.close()
            pyglet.clock.unschedule(tick)

    def tick(dt):
        nonlocal elapsed, last_ctrl
        elapsed += dt
        ctrl = check_ctrl()
        input_state.ctrl = ctrl
        if ctrl != last_ctrl:
            last_ctrl = ctrl
            input_state.pending.append(("key" if ctrl else "key_up", "LCTRL", ctrl, False))
        window.invalid = True

    pyglet.clock.schedule_interval(tick, 1 / 60)
    try:
        pyglet.app.run(interval=1 / 60)
    finally:
        space = runtime.services.get("space")
        if space is not None:
            space.close()
        if not closed:
            runtime.close()
            graphics.close()
            pyglet.clock.unschedule(tick)
        window.close()
    if frames is not None and failures:
        raise RuntimeError(f"Script diagnostics during smoke test: {sorted(failures)}")
    return runtime
