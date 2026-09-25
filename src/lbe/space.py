"""Derived spatial hash and continuous camera transforms."""

from math import floor, isfinite


def bounds(entity):
    try:
        x, y = entity.x, entity.y
        w = entity.components.get("w", 0)
        h = entity.components.get("h", 0)
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in (x, y, w, h)):
            return None
        return min(x, x + w), min(y, y + h), max(x, x + w), max(y, y + h)
    except (AttributeError, ReferenceError):
        return None


class SpatialIndex:
    """Spatial hash refreshed automatically from observable component changes.

    Oversized objects are kept separately rather than allocating unbounded cells.
    """

    def __init__(self, runtime, cell_size=16.0):
        if not isfinite(cell_size) or cell_size <= 0:
            raise ValueError("cell_size must be finite and positive")
        self.cell_size = cell_size
        self._bounds = {}
        self._membership = {}
        self._cells = {}
        self._large = set()
        self._unsubscribe = runtime.changes.subscribe(self._change)
        for entity in runtime.entities:
            self._refresh(entity)

    def _keys(self, box):
        left, bottom, right, top = (floor(v / self.cell_size) for v in box)
        if (right - left + 1) * (top - bottom + 1) > 4096:
            return None
        return {(x, y) for x in range(left, right + 1) for y in range(bottom, top + 1)}

    def _remove(self, entity):
        for key in self._membership.pop(entity, ()):
            bucket = self._cells[key]
            bucket.discard(entity)
            if not bucket:
                del self._cells[key]
        self._large.discard(entity)
        self._bounds.pop(entity, None)

    def _refresh(self, entity):
        self._remove(entity)
        box = bounds(entity)
        if box is None:
            return
        self._bounds[entity] = box
        keys = self._keys(box)
        if keys is None:
            self._large.add(entity)
        else:
            self._membership[entity] = keys
            for key in keys:
                self._cells.setdefault(key, set()).add(entity)

    def _change(self, change):
        if change.kind == "entity.destroy":
            self._remove(change.entity)
        elif change.kind == "entity.create" or (change.kind.startswith("component.") and change.key in {"x", "y", "w", "h"}):
            self._refresh(change.entity)

    def query(self, x, y, w=0, h=0):
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in (x, y, w, h)):
            raise ValueError("Spatial queries require finite coordinates")
        box = min(x, x + w), min(y, y + h), max(x, x + w), max(y, y + h)
        keys = self._keys(box)
        if keys is None:
            candidates = set(self._bounds)
        else:
            candidates = set(self._large)
            for key in keys:
                candidates.update(self._cells.get(key, ()))
        left, bottom, right, top = box
        return tuple(sorted((entity for entity in candidates
                             if self._bounds[entity][0] <= right
                             and self._bounds[entity][2] >= left
                             and self._bounds[entity][1] <= top
                             and self._bounds[entity][3] >= bottom), key=lambda e: e.id.int))

    def close(self):
        self._unsubscribe()
        self._bounds.clear()
        self._cells.clear()
        self._membership.clear()
        self._large.clear()


def world_to_screen(camera, viewport, x, y):
    zoom = camera.zoom
    if not isinstance(zoom, (int, float)) or not isfinite(zoom) or zoom <= 0:
        raise ValueError("Camera zoom must be finite and positive")
    return (viewport.x + viewport.w / 2 + (x - camera.x) * zoom,
            viewport.y + viewport.h / 2 - (y - camera.y) * zoom)


def screen_to_world(camera, viewport, x, y):
    origin_x, origin_y = world_to_screen(camera, viewport, 0, 0)
    return (x - origin_x) / camera.zoom, (origin_y - y) / camera.zoom
