"""Inspect observed system effects; selection is an ordinary UUID component."""
from uuid import UUID
from lbe.ui import bind_callbacks
from lbe.space import world_position

state = entity.inherit("application_state")
BLUE = (85, 155, 230)
GREEN = (90, 195, 125)


def highlight_system(identity):
    state.app.items.set_value("highlight_system_asset", UUID(str(identity)))
    state.message("System effects: queried blue, changed green")


def affected_entities():
    identity = state.app.items.get_value("highlight_system_asset")
    if identity is None:
        return {}
    colours = {}
    records = effects.for_asset(identity)
    for record in records:
        for target in record.queried:
            colours.setdefault(target, BLUE)
    for record in records:
        for target in record.changed:
            colours[target] = GREEN
    return colours


def outline(target, colour, world=False):
    values = target.items.value_dict()
    if not all(key in values for key in ("x", "y", "w", "h")):
        return
    x, y = world_position(target, state.game) if world else (target.x, target.y)
    w, h = target.w, target.h
    if w <= 0 or h <= 0:
        return
    t = 2 / max(0.01, state.camera.zoom) if world else 2
    for edge, box in enumerate(((x,y,w,t),(x,y+h-t,w,t),(x,y,t,h),(x+w-t,y,t,h))):
        graphics.rect(*box, color=colour, key=("system_effect", target.id, edge), layer=9)


def draw():
    colours = affected_entities()
    for target in runtime.entities:
        colour = colours.get(target.id)
        if colour is None:
            continue
        if state.game in target.ancestors:
            if not state.ui.visible(state.viewport):
                continue
            with graphics.view(state.camera, state.viewport):
                outline(target, colour, world=True)
        elif state.ui.visible(target):
            outline(target, colour)


def start():
    global release
    release = bind_callbacks(system, state, {"highlight_system":highlight_system, "affected_entities":affected_entities})


def stop():
    if "release" in globals():
        release()
