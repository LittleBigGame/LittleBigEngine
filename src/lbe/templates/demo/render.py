"""Draw compatible children through their camera and viewport."""


def draw():
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        for child in query("x", "y", recursive=True):
            color = child.components.get("color")
            if color is None:
                continue
            w = child.components.get("w", 1.0)
            h = child.components.get("h", 1.0)
            graphics.rect(child.x, child.y, w, h,
                          color=color, key=child.id, layer=child.components.get("layer", 1))
