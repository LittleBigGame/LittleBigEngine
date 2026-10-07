import unittest
from uuid import uuid4

from lbe import Component, InheritedComponent, Parent, Relation, Runtime, SystemDefinition, SystemInstance, Tag


class ItemTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)

    def test_named_apis_share_one_store_and_stable_identities(self):
        e = self.runtime.create(tags=["player"], x=1)
        x = e.items.component("x")
        e.x = 2
        self.assertEqual(e.items.component("x").id, x.id)
        self.assertEqual(e[x.id].value, 2)
        self.assertEqual(len(e.items), 2)
        self.assertEqual(len(e.all(Tag)), 1)
        with self.assertRaises(TypeError):
            e.items[uuid4()] = x
        del e.x
        self.assertNotIn(x.id, e.items)
        with self.assertRaises(KeyError):
            self.runtime.linker.resolve(x.id)

    def test_hierarchy_and_relations_store_flat_uuids(self):
        p = self.runtime.create()
        c = self.runtime.create(parent=p)
        c.items.connect("target", p)
        self.assertEqual(c.all(Parent)[0].target, p.id)
        self.assertEqual(c.all(Relation)[0].target, p.id)
        self.assertIs(c.parent, p)
        self.assertIs(c.items.require_target("target"), p)
        c.parent = None
        self.assertFalse(c.all(Parent))
        self.assertFalse(p.children)

    def test_attachment_identity_survives_reload_and_move(self):
        e = self.runtime.create()
        definition = SystemDefinition("def update(dt): pass")
        a = e.systems.attach("a", definition)
        e.systems.attach("b", definition)
        handle = self.runtime.linker.handle(a.id)
        b = e.systems.reload("a", definition)
        self.assertEqual(a.id, b.id)
        self.assertIs(self.runtime.linker.resolve_handle(handle), b)
        e.systems.move("b", 0)
        self.assertEqual(list(e.systems), ["b", "a"])
        self.assertEqual(len(e.all(SystemInstance)), 2)
        e.systems.relocate("a", "<new>", new_name="renamed")
        self.assertIs(e[b.id], e.systems["renamed"])

    def test_composition_resolves_live_sources_without_mutating_them(self):
        source = self.runtime.create(stats={"hp": 10, "items": [1]})
        child = self.runtime.create()
        item = child.items.inherit_value("stats", source.items.component("stats"), (
            {"op": "add", "path": ["hp"], "value": 2},
            {"op": "add", "path": ["items"], "value": [2]},
        ))
        self.assertEqual(child.stats, {"hp": 12, "items": [1, 2]})
        self.assertEqual(source.stats, {"hp": 10, "items": [1]})
        source.stats = {"hp": 20, "items": [3]}
        self.assertEqual(child.stats, {"hp": 22, "items": [3, 2]})
        self.assertIn(item.id, self.runtime.linker.dependents(item.source))
        child.stats = {"hp": 99}
        self.assertIsInstance(child[item.id], InheritedComponent)
        self.assertEqual(child.stats, {"hp": 99})
        self.assertEqual(source.stats["hp"], 20)

    def test_handles_cannot_resurrect_destroyed_objects(self):
        e = self.runtime.create(x=1)
        handle = e.handle
        component_handle = self.runtime.linker.handle(e.items.component("x").id)
        e.destroy()
        self.runtime.create(x=2)
        for old in (handle, component_handle):
            with self.assertRaises(ReferenceError):
                self.runtime.linker.resolve_handle(old)

    def test_missing_and_cyclic_composition_is_explicit(self):
        e = self.runtime.create()
        with self.assertRaises(KeyError):
            e.items.inherit_value("x", uuid4())
        self.assertFalse(e.items)
        uid = uuid4()
        e.items._put(InheritedComponent("x", uid, id=uid))
        with self.assertRaises(ValueError):
            _ = e.x
