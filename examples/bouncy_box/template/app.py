"""Portable saved stress scene: no engine-private services or absolute paths."""
import json
import math
import random
from uuid import uuid5
from lbe.project import deserialize_entities, activate_entities, save_project, PersistentGraph
from lbe.space import world_bounds

config = json.loads((project / 'scene.json').read_text(encoding='utf-8'))
contact_id = assets.registry.get_id('systems/on_contact.py')
draw_id = assets.registry.get_id('systems/draw_ball.py')

if restoring:
    restored = deserialize_entities(project_data['entities'], runtime, default_parent=entity,
                                    project_dir=project, activate=False)
    game = next(e for e in restored.values() if e.components.get('name') == 'Bouncy Box')
    camera, viewport = game.relations['camera'], game.relations['viewport']
else:
    count = config['balls']
    columns = math.ceil(math.sqrt(count * 1.6))
    rows = math.ceil(count / columns)
    width, height = columns * 0.92 + 1, rows * 0.92 + 1
    game = create(parent=entity, name='Bouncy Box', tags=['root'],
                  box_w=width, box_h=height, gravity=config['gravity'],
                  timestep=config['timestep'], restitution=config['restitution'],
                  physics_enabled=True, render_enabled=True, contacts=0,
                  wall_contacts=0, messages=0, tick=0, dropped_time=0.0,
                  candidate_pairs=0, kinetic_energy=0.0,
                  contact_script=contact_id, drawing_script=draw_id)
    camera = create(parent=entity, name='Camera', x=width / 2, y=height / 2, zoom=1.0)
    viewport = create(parent=entity, name='Viewport', x=12, y=54,
                      w=window.width - 24, h=window.height - 66)
    game.relations['camera'], game.relations['viewport'] = camera, viewport
    rng = random.Random(config['seed'])
    texture = assets.registry.get_ref('textures/ball.png')
    contact, drawing = assets[contact_id], assets[draw_id]
    for index in range(count):
        radius = rng.uniform(0.28, 0.38)
        mass = math.pi * radius * radius * rng.uniform(0.8, 1.2)
        ball = create(parent=game, identity=uuid5(entity.id, f'ball:{index}'),
                      name=f'Ball {index:05d}', tags=['ball'], index=index,
                      x=0.5 + (index % columns) * 0.92, y=0.5 + (index // columns) * 0.92,
                      w=2 * radius, h=2 * radius, radius=radius, mass=mass,
                      vx=rng.uniform(-4, 4), vy=rng.uniform(-4, 4),
                      angular_velocity=rng.uniform(-4, 4), rotation=rng.uniform(0, 360),
                      restitution=config['restitution'], temperature=rng.uniform(10, 60),
                      contacts=0, checksum=rng.getrandbits(32), color=(220, 230, 255),
                      tint=(220, 230, 255, 255), sprite=texture,
                      payload={'generation': 0, 'signal': rng.random(), 'trace': []})
        ball.scripts.attach(contact)
        ball.scripts.attach(drawing)
    balls = game.children
    for index, ball in enumerate(balls):
        ball.relations['neighbor'] = balls[(index + 1) % len(balls)]

space.configure(scope=game, bounds_fn=world_bounds, cell_size=1.0)
runtime.services['game'] = game
if restoring:
    activate_entities(restored.values(), runtime, project_dir=project)
else:
    game.systems.attach('physics', assets.system(project / 'physics.py'))
    game.systems.attach('render', assets.system(project / 'render.py'))
graph = PersistentGraph(runtime, (e for e in runtime.entities if e is not entity), application=entity)
runtime.services['graph'] = graph


def save_scene():
    return save_project(project, entities=graph.entities, assets=assets.registry,
                        application_id=entity.id)


def update(dt):
    viewport.w, viewport.h = max(1, window.width - 24), max(1, window.height - 66)
    camera.zoom = min(viewport.w / game.box_w, viewport.h / game.box_h)
    for event in input.drain() if input is not None else ():
        if event[0] == 'key' and event[1] in ('SPACE', 'F5'):
            game.paused = not game.components.get('paused', False)
        elif event[0] == 'key' and event[1] == 'S':
            save_scene()


def stop():
    graph.close()
