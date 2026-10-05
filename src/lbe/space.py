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


def world_position(entity, root=None):
    """Template-level relative coordinates; Core hierarchy has no implicit transforms."""
    x = y = 0.0
    current = entity
    while current is not None and current is not root:
        if current is not entity and root is None and "root" in current.tags:
            break
        x += current.components.get("x", 0.0)
        y += current.components.get("y", 0.0)
        current = current.parent
    return x, y


def world_bounds(entity):
    box = bounds(entity)
    if box is None:
        return None
    x, y = world_position(entity)
    dx, dy = x - entity.x, y - entity.y
    return box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy


class SpatialIndex:
    """Spatial hash refreshed automatically from observable component changes.

    Oversized objects are kept separately rather than allocating unbounded cells.
    """

    def __init__(self, runtime, cell_size=1.0, *, scope=None, bounds_fn=bounds):
        if not isfinite(cell_size) or cell_size <= 0:
            raise ValueError("cell_size must be finite and positive")
        self.cell_size = cell_size
        self.runtime = runtime
        self.scope = scope
        self.bounds_fn = bounds_fn
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
        if self.scope is not None and entity is not self.scope and self.scope not in entity.ancestors:
            return
        box = self.bounds_fn(entity)
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
        elif change.kind in {"hierarchy.parent", "tag.add", "tag.remove"}:
            for entity in (change.entity,) + change.entity.descendants:
                self._refresh(entity)
        elif change.kind == "entity.create" or (change.kind.startswith("component.") and change.key in {"x", "y", "w", "h"}):
            self._refresh(change.entity)
            if self.bounds_fn is world_bounds and change.key in {"x", "y"}:
                for entity in change.entity.descendants:
                    self._refresh(entity)

    def configure(self, *, scope=None, bounds_fn=bounds, cell_size=None):
        """Change coordinate/membership policy without changing the public query operations."""
        self.scope, self.bounds_fn = scope, bounds_fn
        if cell_size is not None:
            if not isfinite(cell_size) or cell_size <= 0:
                raise ValueError("cell_size must be finite and positive")
            self.cell_size = cell_size
        self._bounds.clear()
        self._membership.clear()
        self._cells.clear()
        self._large.clear()
        for entity in self.runtime.entities:
            self._refresh(entity)

    def near(self, entity):
        """Get any entities in the same space partition(s) as entity, excluding entity itself."""
        if entity not in self._membership:
            self._refresh(entity)
        keys = self._membership.get(entity, ())
        nearby = set()
        for key in keys:
            nearby.update(self._cells.get(key, ()))
        nearby.update(self._large)
        nearby.discard(entity)
        return tuple(sorted((e for e in nearby if getattr(e, "alive", True)), key=lambda e: e.id.int))

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

    def cells(self):
        """Return a mapping of (cell_x, cell_y) -> set of alive entities in that cell."""
        result = {}
        for key, members in self._cells.items():
            alive = {e for e in members if getattr(e, "alive", True)}
            if alive:
                result[key] = alive
        return result

    def cell_bounds(self, key):
        """Return the (x, y, w, h) bounding box in world units for a given cell key."""
        cx, cy = key
        return cx * self.cell_size, cy * self.cell_size, self.cell_size, self.cell_size

    def collides(self, entity_a, entity_b):
        """Check if two entities have overlapping bounding boxes."""
        if entity_a is entity_b:
            return False
        box_a = self._bounds.get(entity_a)
        box_b = self._bounds.get(entity_b)
        if box_a is None or box_b is None:
            return False
        return (box_a[0] < box_b[2] and box_a[2] > box_b[0] and
                box_a[1] < box_b[3] and box_a[3] > box_b[1])

    def query_collisions(self, entity, tag=None):
        """Query all entities currently colliding with the given entity (AABB intersection).
        
        Uses the spatial hash to narrow candidates to only nearby entities before testing overlap.
        """
        box = self._bounds.get(entity)
        if box is None:
            return ()
        keys = self._keys(box)
        if keys is None:
            candidates = set(self._bounds)
        else:
            candidates = set(self._large)
            for key in keys:
                candidates.update(self._cells.get(key, ()))
        candidates.discard(entity)

        left, bottom, right, top = box
        hits = []
        for other in candidates:
            if not getattr(other, "alive", True):
                continue
            if tag is not None and tag not in getattr(other, "tags", ()):
                continue
            obox = self._bounds.get(other)
            if obox is None:
                continue
            if (obox[0] < right and obox[2] > left and
                obox[1] < top and obox[3] > bottom):
                hits.append(other)
        return tuple(sorted(hits, key=lambda e: e.id.int))

    def query_nearby(self, entity, radius=0.0):
        """Query entities near the given entity, expanded by an optional margin/radius."""
        box = self._bounds.get(entity)
        if box is None:
            return ()
        left, bottom, right, top = box
        return self.query(left - radius, bottom - radius, (right - left) + 2 * radius, (top - bottom) + 2 * radius)

    def query_radius(self, cx, cy, radius):
        """Query all entities whose bounding boxes overlap a circular region."""
        candidates = self.query(cx - radius, cy - radius, 2 * radius, 2 * radius)
        r_sq = radius * radius
        results = []
        for e in candidates:
            box = self._bounds.get(e)
            if box is None:
                continue
            # Distance from circle center to closest point on AABB
            closest_x = max(box[0], min(cx, box[2]))
            closest_y = max(box[1], min(cy, box[3]))
            dx = cx - closest_x
            dy = cy - closest_y
            if dx * dx + dy * dy <= r_sq:
                results.append(e)
        return tuple(results)

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
