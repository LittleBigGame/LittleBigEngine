"""Interactive arcade game demonstrating space partitioning, collisions, and viewport culling."""

import math
import random
from lbe.space import world_bounds

game = create(parent=entity, name="Game", tags=["root"])
space.configure(scope=game, bounds_fn=world_bounds)
camera = create(parent=entity, name="Camera", x=0.0, y=0.0, zoom=48.0)
viewport = create(parent=entity, name="Viewport", x=0, y=0, w=window.width, h=window.height)
game.items.connect("camera", camera)
game.items.connect("viewport", viewport)

# Player entity (Entity A)
player = create(parent=game, name="Entity A", x=-3.0, y=-1.0, w=2.0, h=2.0,
                color=(75, 185, 210), tags=["player"])
player.items.ensure_value("vx", 0.0)
player.items.ensure_value("vy", 0.0)
player.items.ensure_value("score", 0)

# Target collectible entity (Entity B)
target = create(parent=game, name="Entity B", x=1.0, y=0.0, w=1.5, h=1.5,
                color=(232, 165, 80), tags=["pickup"])

game.items.attach_system("render", assets.system(project / "render.py"))


def on_key(event):
    if len(event) < 2:
        return False
    k = event[1]
    # F3 toggles spatial partition grid visualization
    if k == "F3":
        cur = game.items.get_value("show_spatial_debug", False)
        game.items.set_value("show_spatial_debug", not cur)
        return True
    return False


def spawn_spark(x, y):
    for _ in range(6):
        angle = random.uniform(0, 2 * math.pi)
        spd = random.uniform(2.0, 6.0)
        create(parent=game, name="Spark", x=x, y=y, w=0.3, h=0.3,
               vx=math.cos(angle) * spd, vy=math.sin(angle) * spd,
               color=(255, 220, 100), life=0.4, tags=["fx"])


def update(dt):
    viewport.w, viewport.h = window.width, window.height
    for event in input.drain() if input is not None else ():
        if event[0] == "key":
            on_key(event)
    if dt <= 0:
        return

    # 1. Player input & movement
    speed = 6.0
    vx = 0.0
    vy = 0.0
    if input is not None:
        if input.is_key_down("LEFT") or input.is_key_down("A"):
            vx -= speed
        if input.is_key_down("RIGHT") or input.is_key_down("D"):
            vx += speed
        if input.is_key_down("UP") or input.is_key_down("W"):
            vy += speed
        if input.is_key_down("DOWN") or input.is_key_down("S"):
            vy -= speed

    player.x += vx * dt
    player.y += vy * dt

    # Keep player within boundary
    player.x = max(-8.0, min(8.0 - player.w, player.x))
    player.y = max(-5.0, min(5.0 - player.h, player.y))

    # 2. Broadphase spatial collision detection using space partitioning
    hits = space.query_collisions(player)
    for other in hits:
        if other.items.has_tag("pickup"):
            player.items.set_value("score", player.items.get_value("score", 0) + 10)
            spawn_spark(other.x + other.w / 2, other.y + other.h / 2)
            # Relocate collectible to new position
            other.x = random.uniform(-6.0, 6.0)
            other.y = random.uniform(-4.0, 4.0)

    # 3. Update active particle sparks
    for child in tuple(game.children):
        if child.items.has_tag("fx"):
            child.items.set_value("life", child.items.get_value("life", 0.0) - dt)
            if child.items.require_value("life") <= 0:
                child.destroy()
            else:
                child.x += child.items.get_value("vx", 0.0) * dt
                child.y += child.items.get_value("vy", 0.0) * dt


def draw():
    score = player.items.get_value("score", 0)
    debug_on = game.items.get_value("show_spatial_debug", False)
    dbg_text = "[F3] Spatial Grid: ON" if debug_on else "[F3] Spatial Grid: OFF"
    graphics.text(f"LittleBigEngine | Score: {score} | [WASD/Arrows] Move | {dbg_text}", 24, 20)
