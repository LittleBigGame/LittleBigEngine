"""Actual pooled texture sprites, UUID script dispatch, walls and observable statistics."""
from lbe.space import world_bounds


def draw():
    if not entity.render_enabled:
        return
    viewport, camera = entity.relations['viewport'], entity.relations['camera']
    graphics.rect(0, 0, window.width, window.height, color=(8, 12, 20), key='background', layer=-2)
    with graphics.view(camera, viewport):
        for edge, (x, y, w, h) in enumerate(((0, 0, entity.box_w, 0.05),
                (0, entity.box_h - 0.05, entity.box_w, 0.05),
                (0, 0, 0.05, entity.box_h), (entity.box_w - 0.05, 0, 0.05, entity.box_h))):
            graphics.rect(x, y, w, h, color=(75, 120, 155), key=('wall', edge), layer=0)
        half_w, half_h = viewport.w / camera.zoom / 2, viewport.h / camera.zoom / 2
        for ball in query(entity.drawing_script, 'x', 'y', 'w', 'h', tags=['ball']):
            box = world_bounds(ball)
            if box is not None and box[2] >= camera.x - half_w and box[0] <= camera.x + half_w and box[3] >= camera.y - half_h and box[1] <= camera.y + half_h:
                ball.run(entity.drawing_script)
    graphics.text(f'{len(entity.children)} balls | contacts {entity.contacts} | walls {entity.wall_contacts} | messages {entity.messages}',
                  12, 8, key='stats', size=12)
    graphics.text(f'Energy {entity.kinetic_energy:.1f} | Space/F5 pause | S save | tick {entity.tick}',
                  12, 29, key='help', size=10)
