"""Draw compatible children through their camera and viewport."""


def draw():
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        for child in query("x", "y", recursive=True):
            color = child.components.get("color")
            if color is None:
                continue
            w = child.components.get("w", 1.0)
            h = child.components.get("h", 1.0)
            layer = child.components.get("layer", 1)
            graphics.rect(child.x, child.y, w, h,
                          color=color, key=child.id, layer=layer)
        selected = entity.relations.get("selection")
        if selected is not None and selected.alive and "x" in selected.components and "y" in selected.components:
            x, y = selected.x, selected.y
            w = selected.components.get("w", 0.5)
            h = selected.components.get("h", 0.5)
            camera = entity.relations.get("camera")
            zoom = getattr(camera, "zoom", 32.0) if camera else 32.0
            t = max(0.01, 2.0 / zoom)
            graphics.rect(x - t, y - t, w + 2 * t, t, color=(69, 182, 199), key=(selected.id, "sel_bot"), layer=2)
            graphics.rect(x - t, y + h, w + 2 * t, t, color=(69, 182, 199), key=(selected.id, "sel_top"), layer=2)
            graphics.rect(x - t, y, t, h, color=(69, 182, 199), key=(selected.id, "sel_left"), layer=2)
            graphics.rect(x + w, y, t, h, color=(69, 182, 199), key=(selected.id, "sel_right"), layer=2)
