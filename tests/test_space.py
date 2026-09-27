import unittest

from lbe import Runtime
from lbe.space import SpatialIndex, screen_to_world, world_to_screen


class SpaceTests(unittest.TestCase):
    def test_mutations_remove_stale_bounds(self):
        runtime = Runtime()
        index = SpatialIndex(runtime, cell_size=1)
        entity = runtime.create(x=0, y=0, w=2, h=2)
        self.assertIn(entity, index.query(1, 1))
        entity.x = 10
        self.assertNotIn(entity, index.query(1, 1))
        self.assertIn(entity, index.query(11, 1))
        del entity.x
        self.assertNotIn(entity, index.query(11, 1))
        entity.x = 10
        entity.destroy()
        self.assertEqual(index.query(11, 1), ())
        index.close()

    def test_existing_points_negative_sizes_and_large_objects(self):
        runtime = Runtime()
        point = runtime.create(x=-2, y=-2)
        negative = runtime.create(x=0, y=0, w=-3, h=-3)
        huge = runtime.create(x=0, y=0, w=100000, h=100000)
        invalid = runtime.create(x=float("nan"), y=0)
        index = SpatialIndex(runtime, 1)
        self.assertEqual(set(index.query(-2, -2)), {point, negative})
        self.assertEqual(index.query(50000, 50000), (huge,))
        self.assertNotIn(invalid, index.query(0, 0))
        self.assertEqual(set(index.query(-3, -3, 100003, 100003)), {point, negative, huge})

    def test_camera_roundtrip(self):
        runtime = Runtime()
        camera = runtime.create(x=2.5, y=-3.5, zoom=32)
        viewport = runtime.create(x=100, y=50, w=600, h=400)
        self.assertEqual(world_to_screen(camera, viewport, 2.5, -3.5), (400, 250))
        screen = world_to_screen(camera, viewport, 7, 9)
        self.assertEqual(screen_to_world(camera, viewport, *screen), (7, 9))
        camera.zoom = 0
        with self.assertRaises(ValueError):
            screen_to_world(camera, viewport, 0, 0)

    def test_invalid_inputs_and_cell_sizes(self):
        runtime = Runtime()
        for bad_size in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                SpatialIndex(runtime, cell_size=bad_size)

        index = SpatialIndex(runtime, 16.0)
        for bad_coord in (float("nan"), float("inf"), "invalid", None):
            with self.assertRaises(ValueError):
                index.query(bad_coord, 0, 10, 10)
            with self.assertRaises(ValueError):
                index.query(0, bad_coord, 10, 10)
        index.close()

    def test_cells_and_cell_bounds(self):
        runtime = Runtime()
        index = SpatialIndex(runtime, cell_size=4.0)
        e1 = runtime.create(x=1.0, y=1.0, w=2.0, h=2.0)
        e2 = runtime.create(x=10.0, y=10.0, w=2.0, h=2.0)
        
        cells = index.cells()
        # e1 in cell (0, 0), e2 in cell (2, 2)
        self.assertIn((0, 0), cells)
        self.assertIn((2, 2), cells)
        self.assertEqual(cells[(0, 0)], {e1})
        self.assertEqual(cells[(2, 2)], {e2})
        
        bx, by, bw, bh = index.cell_bounds((0, 0))
        self.assertEqual((bx, by, bw, bh), (0.0, 0.0, 4.0, 4.0))
        
        e1.destroy()
        self.assertNotIn((0, 0), index.cells())
        index.close()

    def test_collides_and_query_collisions(self):
        runtime = Runtime()
        index = SpatialIndex(runtime, cell_size=4.0)
        e1 = runtime.create(name="Player", x=0.0, y=0.0, w=2.0, h=2.0, tags=["player"])
        e2 = runtime.create(name="Gem1", x=1.0, y=1.0, w=2.0, h=2.0, tags=["pickup"]) # Overlaps e1
        e3 = runtime.create(name="Gem2", x=10.0, y=10.0, w=2.0, h=2.0, tags=["pickup"]) # Far away
        e4 = runtime.create(name="Enemy", x=0.5, y=0.5, w=1.0, h=1.0, tags=["enemy"]) # Overlaps e1 and e2

        self.assertTrue(index.collides(e1, e2))
        self.assertTrue(index.collides(e1, e4))
        self.assertFalse(index.collides(e1, e3))
        self.assertFalse(index.collides(e1, e1)) # Does not collide with self

        # query_collisions on e1
        collisions = index.query_collisions(e1)
        self.assertEqual(set(collisions), {e2, e4})

        # query_collisions with tag filter
        pickup_collisions = index.query_collisions(e1, tag="pickup")
        self.assertEqual(set(pickup_collisions), {e2})

        enemy_collisions = index.query_collisions(e1, tag="enemy")
        self.assertEqual(set(enemy_collisions), {e4})

        index.close()

    def test_query_nearby_and_query_radius(self):
        runtime = Runtime()
        index = SpatialIndex(runtime, cell_size=4.0)
        center = runtime.create(x=0.0, y=0.0, w=1.0, h=1.0)
        near = runtime.create(x=2.0, y=0.0, w=1.0, h=1.0)
        far = runtime.create(x=20.0, y=20.0, w=1.0, h=1.0)

        nearby = set(index.query_nearby(center, radius=3.0))
        self.assertIn(center, nearby)
        self.assertIn(near, nearby)
        self.assertNotIn(far, nearby)

        radial = set(index.query_radius(0.0, 0.0, radius=3.5))
        self.assertIn(center, radial)
        self.assertIn(near, radial)
        self.assertNotIn(far, radial)

        index.close()

