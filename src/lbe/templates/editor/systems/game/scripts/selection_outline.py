"""Draw the selection outline for one entity."""
components = ("x", "y", "w", "h")

def run(entity, root, zoom):
    selected = entity
    x, y = 0.0, 0.0
    curr = selected
    while curr is not None and curr is not root:
        x += curr.components.get("x", 0.0)
        y += curr.components.get("y", 0.0)
        curr = curr.parent
    w = selected.w
    h = selected.h
    t = max(0.01, 2.0 / zoom)
    graphics.rect(x - t, y - t, w + 2 * t, t, color=(69, 182, 199), key=(selected.id, "sel_bot"), layer=2)
    graphics.rect(x - t, y + h, w + 2 * t, t, color=(69, 182, 199), key=(selected.id, "sel_top"), layer=2)
    graphics.rect(x - t, y, t, h, color=(69, 182, 199), key=(selected.id, "sel_left"), layer=2)
    graphics.rect(x + w, y, t, h, color=(69, 182, 199), key=(selected.id, "sel_right"), layer=2)
