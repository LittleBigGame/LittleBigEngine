"""Fixed-step circle impulses, angular friction, spatial broadphase and collision messages.

This is an intentionally observable Python workload, not a hidden/native physics
benchmark. Discrete collisions require small timesteps; it is not a CCD solver.
"""
import math
accumulator = 0.0
contact_id = entity.contact_script


def route(first_id, second_id, first_packet, second_packet):
    first = resolve(first_id)
    if first is not None:
        first.run(contact_id, first_packet)
    if second_id is not None:
        second = resolve(second_id)
        if second is not None:
            second.run(contact_id, second_packet)
    entity.messages += 1 if second_id is None else 2


def start():
    system.listen('physics.contact', route)


def packet(other, impulse):
    return dict(other=str(other.id) if other is not None else None,
                impulse=impulse, temperature=other.temperature if other else 25.0,
                checksum=other.checksum if other else 0x1234abcd,
                signal=other.payload['signal'] if other else 0.25, tick=entity.tick)


def walls(ball):
    impulse = 0.0
    if ball.x < 0:
        ball.x = 0.0
        if ball.vx < 0:
            impulse += abs(ball.vx) * ball.mass * (1 + ball.restitution)
            ball.vx *= -ball.restitution
    elif ball.x + ball.w > entity.box_w:
        ball.x = entity.box_w - ball.w
        if ball.vx > 0:
            impulse += abs(ball.vx) * ball.mass * (1 + ball.restitution)
            ball.vx *= -ball.restitution
    if ball.y < 0:
        ball.y = 0.0
        if ball.vy < 0:
            impulse += abs(ball.vy) * ball.mass * (1 + ball.restitution)
            ball.vy *= -ball.restitution
    elif ball.y + ball.h > entity.box_h:
        ball.y = entity.box_h - ball.h
        if ball.vy > 0:
            impulse += abs(ball.vy) * ball.mass * (1 + ball.restitution)
            ball.vy *= -ball.restitution
    if impulse:
        entity.wall_contacts += 1
        events.emit('physics.contact', ball.id, None, packet(None, impulse), None)


def collide(first, second):
    dx = second.x + second.radius - first.x - first.radius
    dy = second.y + second.radius - first.y - first.radius
    total = first.radius + second.radius
    distance_squared = dx * dx + dy * dy
    if distance_squared >= total * total:
        return False
    distance = math.sqrt(distance_squared)
    nx, ny = (dx / distance, dy / distance) if distance > 1e-10 else (1.0, 0.0)
    inv_a, inv_b = 1 / first.mass, 1 / second.mass
    correction = max(total - distance - 0.001, 0.0) * 0.7 / (inv_a + inv_b)
    first.x -= nx * correction * inv_a
    first.y -= ny * correction * inv_a
    second.x += nx * correction * inv_b
    second.y += ny * correction * inv_b
    rvx, rvy = second.vx - first.vx, second.vy - first.vy
    normal_speed = rvx * nx + rvy * ny
    if normal_speed >= 0:
        return False
    restitution = min(first.restitution, second.restitution)
    impulse = -(1 + restitution) * normal_speed / (inv_a + inv_b)
    tx, ty = -ny, nx
    inertia_a = 0.5 * first.mass * first.radius ** 2
    inertia_b = 0.5 * second.mass * second.radius ** 2
    tangential_speed = rvx * tx + rvy * ty - first.angular_velocity * first.radius - second.angular_velocity * second.radius
    friction = -(tangential_speed) / (inv_a + inv_b
                + first.radius ** 2 / inertia_a + second.radius ** 2 / inertia_b)
    mu = 0.015 + (first.temperature + second.temperature) * 0.00001
    friction = max(-mu * impulse, min(mu * impulse, friction))
    ix, iy = nx * impulse + tx * friction, ny * impulse + ty * friction
    first.vx -= ix * inv_a
    first.vy -= iy * inv_a
    second.vx += ix * inv_b
    second.vy += iy * inv_b
    first.angular_velocity -= first.radius * friction / inertia_a
    second.angular_velocity -= second.radius * friction / inertia_b
    # Snapshot both messages before either receiver changes its own values.
    first_packet, second_packet = packet(second, impulse), packet(first, impulse)
    entity.contacts += 1
    events.emit('physics.contact', first.id, second.id, first_packet, second_packet)
    return True


def substep(dt):
    balls = tuple(query('x', 'y', 'vx', 'vy', 'radius', tags=['ball']))
    entity.tick += 1
    for ball in balls:
        ball.vy += entity.gravity * dt
        ball.x += ball.vx * dt
        ball.y += ball.vy * dt
        ball.rotation = (ball.rotation + math.degrees(ball.angular_velocity * dt)) % 360
        walls(ball)
    for ball in balls:
        # Near uses the public observable spatial index, including AABB membership.
        for other in space.near(ball):
            if 'ball' in other.tags and other.index > ball.index:
                entity.candidate_pairs += 1
                collide(ball, other)
    # Positional correction can push a circle into a wall: restore the box invariant.
    for ball in balls:
        walls(ball)
    entity.kinetic_energy = sum(0.5 * b.mass * (b.vx * b.vx + b.vy * b.vy)
                               + 0.25 * b.mass * b.radius ** 2 * b.angular_velocity ** 2 for b in balls)


def update(dt):
    global accumulator
    if not entity.physics_enabled:
        return
    accumulator += min(dt, 0.1)
    steps = 0
    while accumulator + 1e-12 >= entity.timestep and steps < 8:
        substep(entity.timestep)
        accumulator -= entity.timestep
        steps += 1
    if accumulator >= entity.timestep:
        entity.dropped_time += accumulator
        accumulator = 0.0
