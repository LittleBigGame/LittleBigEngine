"""A small independent application built with the same public UI primitives."""

from lbe.ui import UI, put, stack

ui = UI(entity, window, graphics, input)
entity.count = 0
panel = ui.create(entity, "CounterPanel", "panel", text="COUNTER", x=24, y=24, w=420, h=360)
label = ui.create(panel, "Value", "label", text="Count: 0", w=360, h=28)


def increment():
    entity.count += 1
    label.text = f"Count: {entity.count}"


button = ui.button(panel, "Increment", "Add one", increment, w=180, h=32)
notes = ui.multiline(panel, "Notes", "A reusable multiline text control.", w=380, h=180)


def start():
    ui.install()


def update(dt):
    put(panel, w=min(window.width-48, 620))
    stack(panel, (label, button, notes), padding=36, gap=12)
