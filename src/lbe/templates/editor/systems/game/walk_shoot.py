"""Editable sample: WASD/arrows move; Space shoots in the last direction."""
from math import hypot

cooldown = 0.0


def update(dt):
    global cooldown
    cooldown = max(0.0, cooldown - dt)
    for player in query("x", "y", "speed", tags=("player",), recursive=True):
        dx = int(input.is_key_down("D") or input.is_key_down("RIGHT")) - int(input.is_key_down("A") or input.is_key_down("LEFT"))
        dy = int(input.is_key_down("W") or input.is_key_down("UP")) - int(input.is_key_down("S") or input.is_key_down("DOWN"))
        length = hypot(dx, dy)
        if length:
            dx, dy = dx / length, dy / length
            player.x += dx * player.speed * dt
            player.y += dy * player.speed * dt
            player.aim_x, player.aim_y = dx, dy
        if input.is_key_down("SPACE") and cooldown == 0.0:
            bullet = create(parent=entity, tags=("bullet",), name="Bullet",
                            x=player.x + player.w / 2, y=player.y + player.h / 2,
                            w=0.2, h=0.2, color=(255, 215, 100),
                            vx=player.aim_x * 14, vy=player.aim_y * 14, life=1.2)
            drawing = assets.get("f084e424-d2d9-5fd1-8624-63580396274c")
            if drawing:
                bullet.items.attach_script(drawing)
            cooldown = 0.18
    for bullet in query("x", "y", "vx", "vy", "life", tags=("bullet",), recursive=True):
        bullet.x += bullet.vx * dt
        bullet.y += bullet.vy * dt
        bullet.life -= dt
        if bullet.life <= 0:
            bullet.destroy()
