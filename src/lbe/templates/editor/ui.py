"""Generic entity-control input and rendering system."""


def update(dt):
    entity.items.require_value("ui").process()


def draw():
    entity.items.require_value("ui").draw()
