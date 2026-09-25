import unittest

from lbe import Runtime


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()

    def test_arbitrary_components_and_reserved_names(self):
        entity = self.runtime.create(x=1, custom={"a": [1]}, components={"id": "data"})
        identity = entity.id
        self.assertEqual(entity.x, 1)
        entity.x = 4
        self.assertEqual(entity.components["x"], 4)
        self.assertEqual(entity.components["id"], "data")
        with self.assertRaises(AttributeError):
            entity.id = "replacement"
        self.assertEqual(entity.id, identity)
        del entity.x
        with self.assertRaises(AttributeError):
            _ = entity.x
        self.assertIs(self.runtime.resolve(str(identity)), entity)

    def test_component_edit_commits_and_rolls_back(self):
        entity = self.runtime.create(settings={"items": [1]})
        observed = []
        self.runtime.changes.subscribe(observed.append)
        with entity.components.edit("settings") as value:
            value["items"].append(2)
        self.assertEqual(entity.settings, {"items": [1, 2]})
        self.assertEqual(len(observed), 1)
        with self.assertRaises(ValueError):
            with entity.components.edit("settings") as value:
                value.clear()
                raise ValueError("cancel")
        self.assertEqual(entity.settings, {"items": [1, 2]})
        self.assertEqual(len(observed), 1)
        entity.settings["items"].append(3)
        entity.components.touch("settings")
        self.assertEqual(observed[-1].kind, "component.mutate")

    def test_invalid_create_does_not_leave_partial_entity(self):
        with self.assertRaises(ValueError):
            self.runtime.create(tags=["valid", 123])
        self.assertEqual(self.runtime.entities, ())
        self.assertEqual(len(self.runtime.changes.history), 0)

    def test_hierarchy_helpers_and_inheritance(self):
        app = self.runtime.create(tags=["root"], gravity=9.8)
        game = self.runtime.create(parent=app)
        level = self.runtime.create(parent=game, tags=["root"])
        player = self.runtime.create(parent=level, gravity=0)
        gun = self.runtime.create(parent=player)
        self.assertIs(gun.root, level)
        self.assertIs(level.root, level)
        self.assertEqual(gun.ancestors, (player, level, game, app))
        self.assertEqual(gun.depth, 4)
        self.assertEqual(app.descendants, (game, level, player, gun))
        self.assertEqual(gun.inherit("gravity"), 0)
        self.assertIs(gun.closest("gravity"), player)
        self.assertIs(app.find("gravity"), player)
        with self.assertRaises(KeyError):
            gun.inherit("missing")
        self.assertEqual(gun.inherit("missing", 10), 10)

    def test_reparenting_and_cycle_rejection(self):
        a, b = self.runtime.create(), self.runtime.create()
        child = self.runtime.create(parent=a)
        grandchild = self.runtime.create(parent=child)
        child.parent = b
        self.assertEqual(a.children, ())
        self.assertEqual(b.children, (child,))
        with self.assertRaises(ValueError):
            b.parent = grandchild
        self.assertIsNone(b.parent)
        with self.assertRaises(ValueError):
            child.parent = Runtime().create()
        self.assertIs(child.parent, b)

    def test_queries_follow_runtime_data_and_hierarchy(self):
        parent = self.runtime.create()
        other = self.runtime.create()
        a = self.runtime.create(parent=parent, x=0)
        b = self.runtime.create(parent=a, x=1, vx=1)
        query = parent.query("x", "vx")
        self.assertEqual(tuple(query), ())
        a.vx = 2
        self.assertEqual(tuple(query), (a,))
        self.assertEqual(tuple(parent.query("x", recursive=True)), (a, b))
        a.tags.add("moving")
        self.assertEqual(tuple(parent.query(tags="moving")), (a,))
        a.parent = other
        self.assertEqual(tuple(query), ())
        self.assertEqual(tuple(self.runtime.query("vx")), (a, b))
        del a.vx
        self.assertEqual(tuple(self.runtime.query("vx")), (b,))

    def test_child_order_and_siblings(self):
        parent = self.runtime.create()
        a = self.runtime.create(parent=parent)
        b = self.runtime.create(parent=parent)
        parent.move_child(b, 0)
        self.assertEqual(parent.children, (b, a))
        self.assertEqual(a.siblings, (b,))
        with self.assertRaises(IndexError):
            parent.move_child(a, 2)
        self.assertEqual(parent.children, (b, a))

    def test_destroy_subtree_cleans_incoming_relations(self):
        parent = self.runtime.create()
        child = self.runtime.create(parent=parent)
        survivor = self.runtime.create()
        survivor.relations["target"] = child
        parent.destroy()
        self.assertEqual(self.runtime.entities, (survivor,))
        self.assertEqual(dict(survivor.relations), {})
        self.assertFalse(child.alive)
        with self.assertRaises(ReferenceError):
            child.x = 1
        with self.assertRaises(KeyError):
            self.runtime.resolve(child.id)
        with self.assertRaises(ValueError):
            survivor.relations["outside"] = Runtime().create()

    def test_changes_and_listener_failure_do_not_break_mutation(self):
        entity = self.runtime.create()
        seen = []
        def broken(change):
            raise ValueError("listener failed")
        self.runtime.changes.subscribe(broken)
        unsubscribe = self.runtime.changes.subscribe(seen.append)
        entity.tags.add("a")
        entity.tags.add("a")
        entity.tags.discard("a")
        entity.x = 1
        del entity.x
        unsubscribe()
        unsubscribe()
        entity.x = 2
        self.assertEqual([c.kind for c in seen], ["tag.add", "tag.remove", "component.set", "component.remove"])
        self.assertEqual(len(self.runtime.changes.errors), 5)

    def test_nonfinite_or_negative_time_is_rejected(self):
        for value in (-1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                self.runtime.step(value)
