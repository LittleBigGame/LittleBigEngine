"""Generic entity-control input and rendering system."""


def update(dt):
    entity.components["ui"].process()


def draw():
    entity.components["ui"].draw()
