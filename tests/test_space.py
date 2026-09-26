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

