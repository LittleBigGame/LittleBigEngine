"""Small scene assembled from ordinary entities and a render script."""

from pathlib import Path

from .core import Runtime
from .space import SpatialIndex
from .systems import SystemDefinition


def build_demo(window, graphics, input_state):
    runtime = Runtime()
    runtime.services.update(window=window, graphics=graphics, input=input_state)
    app = runtime.create(name="Application", tags=["root"])
    game = runtime.create(parent=app, name="Game", tags=["root"])
    camera = runtime.create(parent=app, name="Camera", x=0.0, y=0.0, zoom=48.0)
    viewport = runtime.create(parent=app, name="Viewport", x=0, y=0, w=window.width, h=window.height)
    game.relations["camera"] = camera
    game.relations["viewport"] = viewport
    runtime.create(parent=game, name="Entity A", x=-3.0, y=-1.0, w=2.0, h=2.0, color=(75, 185, 210))
    runtime.create(parent=game, name="Entity B", x=1.0, y=0.0, w=1.5, h=1.5, color=(232, 165, 80))
    runtime.services["space"] = SpatialIndex(runtime)
    game.systems.attach("render", runtime.assets.system(Path(__file__).parent / "scripts" / "render.py"))
    app.systems.attach("window", SystemDefinition('''
def update(dt):
    viewport = entity.find(tags="viewport")
    if viewport:
        viewport.w, viewport.h = window.width, window.height
def draw():
    graphics.text("LittleBigEngine | two entities, one ordinary render system", 24, 20)
def stop():
    space.close()
'''))
    viewport.tags.add("viewport")
    return runtime
