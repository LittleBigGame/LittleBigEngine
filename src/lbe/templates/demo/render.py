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
                graphics.rect(x, y, w, h,
                              color=color, key=node.id, layer=node.components.get("layer", 1))
            for child in node.children:
                draw_tree(child, x, y)

        for child in entity.children:
            draw_tree(child)
