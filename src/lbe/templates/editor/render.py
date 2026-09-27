"""Draw compatible children through their camera and viewport."""


def draw():
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        def draw_tree(node, px=0.0, py=0.0):
            x = px + node.components.get("x", 0.0)
            y = py + node.components.get("y", 0.0)
            color = node.components.get("color")
            if color is not None:
                w = node.components.get("w", 1.0)
                h = node.components.get("h", 1.0)
                layer = node.components.get("layer", 1)
                graphics.rect(x, y, w, h, color=color, key=node.id, layer=layer)
            for child in node.children:
                draw_tree(child, x, y)

        for child in entity.children:
            draw_tree(child)

        selected = entity.relations.get("selection")
        if selected is not None and selected.alive and "x" in selected.components and "y" in selected.components:
            x, y = 0.0, 0.0
            curr = selected
            while curr is not None and curr is not entity:
                x += curr.components.get("x", 0.0)
                y += curr.components.get("y", 0.0)
                curr = curr.parent
            w = selected.components.get("w", 0.5)
            h = selected.components.get("h", 0.5)
            camera = entity.relations.get("camera")
            zoom = getattr(camera, "zoom", 32.0) if camera else 32.0
            t = max(0.01, 2.0 / zoom)
            graphics.rect(x - t, y - t, w + 2 * t, t, color=(69, 182, 199), key=(selected.id, "sel_bot"), layer=2)
            graphics.rect(x - t, y + h, w + 2 * t, t, color=(69, 182, 199), key=(selected.id, "sel_top"), layer=2)
            graphics.rect(x - t, y, t, h, color=(69, 182, 199), key=(selected.id, "sel_left"), layer=2)
            graphics.rect(x + w, y, t, h, color=(69, 182, 199), key=(selected.id, "sel_right"), layer=2)
