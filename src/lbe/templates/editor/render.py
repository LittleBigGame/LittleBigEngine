"""Draw compatible children through their camera and viewport with culling and spatial debug."""

from lbe.space import world_bounds

invalid_targets = set()
invalid_textures = set()


def draw():
    viewport = entity.relations['viewport']
    if not viewport.components.get('visible', True) or viewport.w <= 0 or viewport.h <= 0:
        return
    with graphics.view(entity.relations["camera"], entity.relations["viewport"]):
        camera = entity.relations.get("camera")
        viewport = entity.relations.get("viewport")
        zoom = getattr(camera, "zoom", 32.0) if camera else 32.0
        cam_x = camera.components.get("x", 0.0) if camera else 0.0
        cam_y = camera.components.get("y", 0.0) if camera else 0.0

        # Compute visible world bounds for viewport frustum culling
        if camera and viewport and zoom > 0:
            half_w = (viewport.w / (2.0 * zoom))
            half_h = (viewport.h / (2.0 * zoom))
            view_min_x, view_max_x = cam_x - half_w, cam_x + half_w
            view_min_y, view_max_y = cam_y - half_h, cam_y + half_h
        else:
            view_min_x = view_min_y = -1e9
            view_max_x = view_max_y = 1e9

        # Space partition debug overlay (toggled via F3)
        show_debug = entity.components.get("show_spatial_debug")
        if not show_debug and hasattr(entity, "parent") and entity.parent:
            show_debug = entity.parent.components.get("show_spatial_debug")
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
                # Cull debug cells outside visible viewport
                if (cell_x + cell_size < view_min_x or cell_x > view_max_x or
                    cell_y + cell_size < view_min_y or cell_y > view_max_y):
                    continue

                if active_count == 1:
                    # Green if one thing is in that cell
                    fill_color = (46, 204, 113)
                    border_color = (39, 174, 96)
                else:
                    # Red if multiple things; gets darker as density increases
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

        # The system orchestrates; each target script call is backend-isolated.
        drawn_ids = set()
        for target in query('x', 'y', 'w', 'h', 'sprite', recursive=True):
            try:
                box = world_bounds(target)
                if box is None:
                    raise ValueError('Invalid texture geometry')
                x, y, right, top = box
                if right < view_min_x or x > view_max_x or top < view_min_y or y > view_max_y:
                    drawn_ids.add(target.id)
                    continue
                graphics.sprite(assets.resolve(target.sprite), x, y, right - x, top - y,
                                color=target.components.get('tint', (255, 255, 255, 255)),
                                rotation=target.components.get('rotation', 0),
                                key=target.id, layer=target.components.get('layer', 1))
                drawn_ids.add(target.id)
                invalid_textures.discard(target.id)
            except (OSError, KeyError, TypeError, ValueError) as error:
                if target.id not in invalid_textures:
                    events.emit('texture.error', target, str(error))
                    invalid_textures.add(target.id)
        drawing = assets.get("f084e424-d2d9-5fd1-8624-63580396274c")
        if drawing:
            for target in query(drawing, *drawing.components, recursive=True):
                if target.id in drawn_ids:
                    continue
                target.run(drawing)
                drawn_ids.add(target.id)

        for target in query("x", "y", "color", recursive=True):
            if target.id in drawn_ids:
                continue
            try:
                box = world_bounds(target)
                if box is None:
                    raise ValueError('Geometry requires finite numeric x, y, w and h')
                tx, ty, right, bottom = box
                tw = abs(target.components.get('w', 1.5))
                th = abs(target.components.get('h', 1.5))
                right, bottom = tx + tw, ty + th
                if right < view_min_x or tx > view_max_x or bottom < view_min_y or ty > view_max_y:
                    continue
                clr = target.components.get("color")
                if not isinstance(clr, (list, tuple)) or len(clr) < 3 or any(type(c) is not int or not 0 <= c <= 255 for c in clr[:3]):
                    raise ValueError('Color requires RGB integers from 0 to 255')
                graphics.rect(tx, ty, tw, th, color=clr[:3], key=(target.id.hex, "fallback_draw"), layer=1)
                invalid_targets.discard(target.id)
            except (TypeError, ValueError) as error:
                if target.id not in invalid_targets:
                    events.emit('render.error', target, str(error))
                    invalid_targets.add(target.id)
        invalid_targets.intersection_update(e.id for e in runtime.entities)
        invalid_textures.intersection_update(e.id for e in runtime.entities)

        selected = entity.relations.get("selection")
        outline = assets.get("dbc0d180-5a28-56a1-bc9c-85d63174e431")
        if selected is not None and selected.alive and outline and outline in selected.scripts:
            selected.run(outline, entity, zoom)
