"""Optional pyglet platform adapter; no editor or gameplay rules live here."""

from contextlib import contextmanager
from dataclasses import dataclass, field
import sys

from .space import world_to_screen


@dataclass
class Input:
    pending: list = field(default_factory=list)
    x: float = 0
    y: float = 0

    def drain(self):
        pending, self.pending = self.pending, []
        return pending


class Graphics:
    def __init__(self, window):
        import pyglet

        self.window = window
        self.batch = pyglet.graphics.Batch()
        self._groups = {i: pyglet.graphics.Group(order=i) for i in range(8)}
        self._pool = {}
        self._used = set()
        self._counter = 0
        self._view = None

    def begin(self):
        self._used.clear()
        self._counter = 0

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
                                          color=color, batch=self.batch, group=self._groups[layer])
            self._pool[identity] = obj
        obj.x, obj.y = x, self.window.height - y - h
        obj.width, obj.height = max(0, w), max(0, h)
        obj.color = color

    def text(self, text, x, y, *, color=(215, 223, 233, 255), size=10, key=None, layer=3):
        import pyglet

        identity = self._identity("text", key, layer)
        obj = self._pool.get(identity)
        if obj is None:
            obj = pyglet.text.Label(str(text), font_name="Consolas", font_size=size,
                                    x=x, y=self.window.height - y, anchor_y="top",
                                    color=color, batch=self.batch, group=self._groups[layer])
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

    def close(self):
        for obj in self._pool.values():
            obj.delete()
        self._pool.clear()


def launch(build, *, headless=False, frames=None, screenshot=None):
    import pyglet

    if headless and sys.platform != "win32":
        pyglet.options["headless"] = True
    from pyglet.window import key

    window = pyglet.window.Window(1440, 900, caption="LittleBigEngine", resizable=True, vsync=True,
                                  visible=not headless)
    window.set_minimum_size(1000, 700)
    graphics = Graphics(window)
    input_state = Input()
    runtime = build(window, graphics, input_state)
    elapsed = 0.0
    rendered = 0
    closed = False
    failures = set()

    @window.event
    def on_draw():
        nonlocal elapsed, rendered
        window.clear()
        graphics.begin()
        runtime.step(min(elapsed, 0.1))
        for entity in runtime.entities:
            for instance in entity.systems.values():
                failures.update((error.source, error.message) for error in instance.errors)
        elapsed = 0.0
        graphics.finish()
        rendered += 1
        if frames is not None and rendered >= frames:
            if screenshot:
                pyglet.image.get_buffer_manager().get_color_buffer().save(str(screenshot))
            pyglet.app.exit()

    @window.event
    def on_mouse_press(x, y, button, modifiers):
        input_state.pending.append(("click", x, window.height - y, button, modifiers))

    @window.event
    def on_mouse_drag(x, y, dx, dy, buttons, modifiers):
        input_state.pending.append(("drag", x, window.height - y, buttons, modifiers))

    @window.event
    def on_mouse_motion(x, y, dx, dy):
        input_state.x, input_state.y = x, window.height - y

    @window.event
    def on_mouse_scroll(x, y, scroll_x, scroll_y):
        input_state.pending.append(("scroll", x, window.height - y, scroll_x, scroll_y))

    @window.event
    def on_text(text):
        if text not in ("\r", "\n", "\t"):
            input_state.pending.append(("text", text))

    @window.event
    def on_key_press(symbol, modifiers):
        if symbol in (key.LEFT, key.RIGHT, key.UP, key.DOWN, key.HOME, key.END,
                      key.PAGEUP, key.PAGEDOWN, key.BACKSPACE, key.DELETE):
            return pyglet.event.EVENT_HANDLED
        input_state.pending.append(("key", key.symbol_string(symbol),
                                    bool(modifiers & key.MOD_CTRL), bool(modifiers & key.MOD_SHIFT)))
        return pyglet.event.EVENT_HANDLED

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
            input_state.pending.append(("key", motions[motion], False, False))

    @window.event
    def on_text_motion_select(motion):
        if motion in motions:
            input_state.pending.append(("key", motions[motion], False, True))

    @window.event
    def on_close():
        nonlocal closed
        if not closed:
            closed = True
            runtime.close()
            graphics.close()
            pyglet.clock.unschedule(tick)

    def tick(dt):
        nonlocal elapsed
        elapsed += dt
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
