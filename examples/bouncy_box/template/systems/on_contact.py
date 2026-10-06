"""Collision message receiver: UUID routing, bounded nested data, thermal/material feedback."""
import colorsys
import math
components = ('temperature', 'contacts', 'checksum', 'payload')


def run(entity, packet):
    other = resolve(packet['other']) if packet['other'] is not None else None
    if other is not None:
        entity.relations['last_contact'] = other
    impulse = packet['impulse']
    entity.temperature = min(120.0, max(0.0, entity.temperature
        + (packet['temperature'] - entity.temperature) * 0.08 + impulse * impulse * 0.002))
    entity.contacts += 1
    entity.checksum = ((entity.checksum * 1664525 + 1013904223)
                       ^ packet['checksum'] ^ packet['tick']) & 0xffffffff
    with entity.components.edit('payload') as payload:
        payload['generation'] += 1
        payload['signal'] = math.tanh(payload['signal'] * 0.6 + packet['signal'] * 0.35 + impulse * 0.01)
        payload['trace'] = (payload['trace'] + [packet['other']])[-8:]
    # Neighbour data and impact temperature feed the next physics/render steps.
    neighbor = entity.relations.get('neighbor')
    signal = entity.payload['signal'] + (neighbor.payload['signal'] * 0.05 if neighbor else 0)
    entity.restitution = max(0.96, entity.parent.restitution - entity.temperature * 0.00005)
    rgb = colorsys.hsv_to_rgb((entity.checksum % 360) / 360.0, 0.45 + signal * 0.2, 0.95)
    entity.tint = tuple(int(c * 255) for c in rgb) + (255,)
    if entity.temperature > 55:
        entity.tags.add('hot')
    else:
        entity.tags.discard('hot')
