"""Draw compatible children through their camera and viewport with culling and spatial debug."""


def draw():
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        camera = entity.relations.get("camera")
        viewport = entity.relations.get("viewport")
        zoom = getattr(camera, "zoom", 48.0) if camera else 48.0
        cam_x = camera.items.get_value("x", 0.0) if camera else 0.0
        cam_y = camera.items.get_value("y", 0.0) if camera else 0.0

        # Frustum culling bounds
        if camera and viewport and zoom > 0:
            half_w = (viewport.w / (2.0 * zoom))
            half_h = (viewport.h / (2.0 * zoom))
            view_min_x, view_max_x = cam_x - half_w, cam_x + half_w
            view_min_y, view_max_y = cam_y - half_h, cam_y + half_h
        else:
            view_min_x = view_min_y = -1e9
            view_max_x = view_max_y = 1e9

        # Space partition debug overlay (F3)
        show_debug = entity.items.get_value("show_spatial_debug")
        if not show_debug and hasattr(entity, "parent") and entity.parent:
            show_debug = entity.parent.items.get_value("show_spatial_debug")
        if show_debug and "space" in globals():
            cell_size = getattr(space, "cell_size", 16.0)
            cells = space.cells() if hasattr(space, "cells") else getattr(space, "_cells", {})
            t = max(0.01, 1.5 / zoom)
            for (cx, cy), members in cells.items():
                active_count = len([m for m in members if getattr(m, "alive", True)])
                if active_count == 0:
                    continue
                cell_x = cx * cell_size
                cell_y = cy * cell_size
                if (cell_x + cell_size < view_min_x or cell_x > view_max_x or
                    cell_y + cell_size < view_min_y or cell_y > view_max_y):
                    continue

                if active_count == 1:
                    fill_color = (46, 204, 113)
                    border_color = (39, 174, 96)
                else:
                    factor = max(0.25, 1.0 - (active_count - 2) * 0.12)
                    r = int(max(60, min(240, 240 * factor)))
                    g = int(max(10, min(50, 50 * factor)))
                    b = int(max(10, min(50, 50 * factor)))
                    fill_color = (r, g, b)
                    border_color = (max(30, r - 30), max(5, g - 10), max(5, b - 10))

                key_b = f"sc_{cx}_{cy}"
                graphics.rect(cell_x, cell_y, cell_size, t, color=border_color, key=(key_b, "b"), layer=0)
                graphics.rect(cell_x, cell_y + cell_size - t, cell_size, t, color=border_color, key=(key_b, "t"), layer=0)
                graphics.rect(cell_x, cell_y, t, cell_size, color=border_color, key=(key_b, "l"), layer=0)
                graphics.rect(cell_x + cell_size - t, cell_y, t, cell_size, color=border_color, key=(key_b, "r"), layer=0)
                graphics.rect(cell_x + t, cell_y + t, cell_size - 2 * t, cell_size - 2 * t, color=fill_color, key=(key_b, "f"), layer=0)

        # Draw child entities (with viewport culling)
        def draw_tree(node, px=0.0, py=0.0):
            x = px + node.items.get_value("x", 0.0)
            y = py + node.items.get_value("y", 0.0)
            color = node.items.get_value("color")
            if color is not None:
                w = node.items.get_value("w", 1.0)
                h = node.items.get_value("h", 1.0)
                if (max(x, x + w) >= view_min_x and min(x, x + w) <= view_max_x and
                    max(y, y + h) >= view_min_y and min(y, y + h) <= view_max_y):
                    graphics.rect(x, y, w, h,
                                  color=color, key=node.id, layer=node.items.get_value("layer", 1))
            for child in node.children:
                draw_tree(child, x, y)

        for child in entity.children:
            draw_tree(child)
