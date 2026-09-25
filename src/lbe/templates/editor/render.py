"""Draw compatible children through their camera and viewport."""


def draw():
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        for child in query("x", "y", "w", "h", "color"):
            graphics.rect(child.x, child.y, child.w, child.h,
                          color=child.color, key=child.id, layer=1)
