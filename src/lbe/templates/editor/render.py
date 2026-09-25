"""Draw compatible children through their camera and viewport."""


def draw():
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        for child in query("x", "y", "w", "h", "color"):
            graphics.rect(child.x, child.y, child.w, child.h,
                          color=child.color, key=child.id, layer=1)
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
