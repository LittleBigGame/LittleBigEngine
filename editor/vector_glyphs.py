"""Vector drawing primitives for LittleBigEngine Dear PyGui Editor.

Provides pixel-perfect vector geometry for chevrons, radio indicators,
window chrome icons, dashed bounding boxes, and tree connector lines.
Zero unicode font glyph dependencies.
"""

from __future__ import annotations
from typing import Any

import dearpygui.dearpygui as dpg


def draw_chevron_down(
    drawlist: int | str,
    pmin: tuple[float, float],
    color: tuple[int, int, int, int] = (200, 200, 200, 255),
    size: float = 8.0,
) -> None:
    """Draw a clean vector triangle pointing downwards (expanded folder)."""
    x, y = pmin
    p1 = (x, y + 2.0)
    p2 = (x + size, y + 2.0)
    p3 = (x + size / 2.0, y + 2.0 + size * 0.75)
    dpg.draw_triangle(p1, p2, p3, color=color, fill=color, parent=drawlist)


def draw_chevron_right(
    drawlist: int | str,
    pmin: tuple[float, float],
    color: tuple[int, int, int, int] = (200, 200, 200, 255),
    size: float = 8.0,
) -> None:
    """Draw a clean vector triangle pointing to the right (collapsed folder)."""
    x, y = pmin
    p1 = (x + 2.0, y)
    p2 = (x + 2.0, y + size)
    p3 = (x + 2.0 + size * 0.75, y + size / 2.0)
    dpg.draw_triangle(p1, p2, p3, color=color, fill=color, parent=drawlist)


def draw_radio_dot(
    drawlist: int | str,
    center: tuple[float, float],
    selected: bool,
    color: tuple[int, int, int, int] = (0, 120, 255, 255),
    radius: float = 4.5,
) -> None:
    """Draw an antialiased vector radio indicator (hollow ring vs filled core)."""
    cx, cy = center
    if not selected:
        dpg.draw_circle(
            (cx, cy),
            radius=radius,
            color=(140, 140, 140, 255),
            thickness=1.5,
            parent=drawlist,
        )
    else:
        # Outer electric blue ring
        dpg.draw_circle(
            (cx, cy),
            radius=radius,
            color=color,
            thickness=1.5,
            parent=drawlist,
        )
        # Inner white solid core
        dpg.draw_circle(
            (cx, cy),
            radius=radius * 0.55,
            color=(255, 255, 255, 255),
            fill=(255, 255, 255, 255),
            parent=drawlist,
        )


def draw_window_chrome(
    drawlist: int | str,
    kind: str,
    pmin: tuple[float, float],
    size: float = 10.0,
    color: tuple[int, int, int, int] = (200, 200, 200, 255),
) -> None:
    """Draw vector window chrome controls: close (X), minimise (-), maximise ([]), or flyout arrow."""
    x, y = pmin
    if kind == "close":
        # Two crossing diagonal lines
        c = color if color != (200, 200, 200, 255) else (230, 50, 50, 255)
        dpg.draw_line((x, y), (x + size, y + size), color=c, thickness=1.5, parent=drawlist)
        dpg.draw_line((x + size, y), (x, y + size), color=c, thickness=1.5, parent=drawlist)
    elif kind in ("min", "minimise"):
        # Horizontal bar
        my = y + size / 2.0
        dpg.draw_line((x, my), (x + size, my), color=color, thickness=2.0, parent=drawlist)
    elif kind in ("max", "maximise"):
        # Square outline
        dpg.draw_rectangle(
            (x, y),
            (x + size, y + size),
            color=color,
            thickness=1.2,
            parent=drawlist,
        )
    elif kind == "flyout_arrow":
        # Small vector chevron arrow pointing outward
        draw_chevron_right(drawlist, (x, y), color=color, size=size)
    elif kind == "lock":
        draw_lock_icon(drawlist, (x, y), locked=True, color=color, size=size)
    elif kind == "unlock":
        draw_lock_icon(drawlist, (x, y), locked=False, color=color, size=size)


def draw_lock_icon(
    drawlist: int | str,
    pmin: tuple[float, float],
    locked: bool = True,
    color: tuple[int, int, int, int] = (200, 200, 200, 255),
    size: float = 10.0,
) -> None:
    """Draw a vector padlock: rectangular base with curved or open shackle loop."""
    x, y = pmin
    w = size
    h = size * 0.65
    base_y = y + size * 0.45
    dpg.draw_rectangle(
        (x + 1.0, base_y),
        (x + w - 1.0, base_y + h),
        color=color,
        fill=color,
        rounding=1.5,
        parent=drawlist,
    )
    shackle_w = w * 0.55
    sx = x + (w - shackle_w) / 2.0
    sy = y + 1.0
    if locked:
        dpg.draw_line((sx, base_y), (sx, sy + 2.0), color=color, thickness=1.5, parent=drawlist)
        dpg.draw_line((sx + shackle_w, base_y), (sx + shackle_w, sy + 2.0), color=color, thickness=1.5, parent=drawlist)
        dpg.draw_line((sx, sy + 2.0), (sx + shackle_w, sy + 2.0), color=color, thickness=1.5, parent=drawlist)
    else:
        dpg.draw_line((sx, base_y), (sx, sy), color=color, thickness=1.5, parent=drawlist)
        dpg.draw_line((sx, sy), (sx + shackle_w, sy), color=color, thickness=1.5, parent=drawlist)
        dpg.draw_line((sx + shackle_w, sy), (sx + shackle_w, sy + 3.0), color=color, thickness=1.5, parent=drawlist)


def draw_branch_lines(
    drawlist: int | str,
    start_p: tuple[float, float],
    end_p: tuple[float, float],
    color: tuple[int, int, int, int] = (70, 70, 70, 255),
    thickness: float = 1.0,
) -> None:
    """Draw L-shaped connector lines from parent node down and across to child node."""
    sx, sy = start_p
    ex, ey = end_p
    # Vertical line down to child's row
    dpg.draw_line((sx, sy), (sx, ey), color=color, thickness=thickness, parent=drawlist)
    # Horizontal tick to child
    dpg.draw_line((sx, ey), (ex, ey), color=color, thickness=thickness, parent=drawlist)


def draw_dashed_rect(
    drawlist: int | str,
    pmin: tuple[float, float],
    pmax: tuple[float, float],
    color: tuple[int, int, int, int] = (90, 90, 90, 255),
    dash_len: float = 4.0,
    gap_len: float = 3.0,
    thickness: float = 1.0,
) -> None:
    """Draw a dashed rectangular outline around a bounding box."""
    x1, y1 = pmin
    x2, y2 = pmax

    def draw_dashed_segment(ax: float, ay: float, bx: float, by: float) -> None:
        dx = bx - ax
        dy = by - ay
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= 0.0:
            return
        ux = dx / dist
        uy = dy / dist
        step = dash_len + gap_len
        curr = 0.0
        while curr < dist:
            seg_len = min(dash_len, dist - curr)
            dpg.draw_line(
                (ax + ux * curr, ay + uy * curr),
                (ax + ux * (curr + seg_len), ay + uy * (curr + seg_len)),
                color=color,
                thickness=thickness,
                parent=drawlist,
            )
            curr += step

    # Top, Right, Bottom, Left
    draw_dashed_segment(x1, y1, x2, y1)
    draw_dashed_segment(x2, y1, x2, y2)
    draw_dashed_segment(x2, y2, x1, y2)
    draw_dashed_segment(x1, y2, x1, y1)


def add_vector_button(
    parent: int | str,
    kind: str,
    callback: Any = None,
    tooltip: str | None = None,
    tag: str | None = None,
    width: int = 22,
    height: int = 22,
    color: tuple[int, int, int, int] = (200, 205, 215, 255),
) -> int | str:
    """Create an interactive clickable vector glyph button."""
    grp_tag = tag or f"vec_btn_{dpg.generate_uuid()}"
    with dpg.group(horizontal=True, parent=parent, tag=grp_tag) as grp:
        dl_tag = f"{grp_tag}_dl"
        dl = dpg.add_drawlist(width=width, height=height, tag=dl_tag)
        ox = (width - 10.0) / 2.0
        oy = (height - 10.0) / 2.0
        draw_window_chrome(dl, kind, (ox, oy), size=10.0, color=color)

        if tooltip:
            with dpg.tooltip(grp):
                dpg.add_text(tooltip)

        if callback is not None:
            reg = dpg.add_item_handler_registry()
            dpg.add_item_clicked_handler(button=0, callback=lambda s, a, u: callback(), parent=reg)
            dpg.bind_item_handler_registry(grp, reg)

    return grp_tag
