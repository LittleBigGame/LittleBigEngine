"""Two entities rendered by a project-owned script."""

game = create(parent=entity, name="Game", tags=["root"])
camera = create(parent=entity, name="Camera", x=0.0, y=0.0, zoom=48.0)
viewport = create(parent=entity, name="Viewport", x=0, y=0, w=window.width, h=window.height)
game.relations["camera"] = camera
game.relations["viewport"] = viewport
create(parent=game, name="Entity A", x=-3.0, y=-1.0, w=2.0, h=2.0, color=(75, 185, 210))
create(parent=game, name="Entity B", x=1.0, y=0.0, w=1.5, h=1.5, color=(232, 165, 80))
game.systems.attach("render", assets.system(project / "render.py"))


def update(dt):
    viewport.w, viewport.h = window.width, window.height


def draw():
    graphics.text("LittleBigEngine | two entities, one ordinary render system", 24, 20)
