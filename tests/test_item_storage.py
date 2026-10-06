import unittest
from uuid import uuid4
from lbe import Runtime, InheritedComponent, SystemDefinition
from lbe.project import deserialize_entities, serialize_entities, migrate_project_data


class ItemStorageTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.other = Runtime()
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.other.close)

    def test_roundtrip_preserves_every_item_identity_and_patch(self):
        source = self.runtime.create(x=2, tags=["blueprint"])
        child = self.runtime.create(parent=source)
        child.relations["source"] = source
        child.components.inherit("x", source.components.item("x"), [{"op": "add", "value": 3}])
        child.systems.attach("idle", SystemDefinition("def update(dt): pass"))
        data = serialize_entities([child, source])
        restored = deserialize_entities(data, self.other)
        for e in (source, child):
            self.assertEqual(set(e.items), set(restored[e.id].items))
        c = restored[child.id]
        self.assertEqual(c.x, 5)
        self.assertIsInstance(c.components.item("x"), InheritedComponent)
        restored[source.id].x = 10
        self.assertEqual(c.x, 13)

    def test_items_are_authoritative_not_redundant_legacy_projections(self):
        e = self.runtime.create(x=2)
        data = serialize_entities([e])
        data[0]["components"]["x"] = 999
        restored = deserialize_entities(data, self.other)
        self.assertEqual(restored[e.id].x, 2)

    def test_legacy_migration_is_deterministic(self):
        document = {"version": 2, "entities": [{"id": str(uuid4()), "components": {"x": 1}, "tags": ["player"]}]}
        first, second = migrate_project_data(document), migrate_project_data(document)
        self.assertEqual(first, second)
        self.assertEqual(first["version"], 3)
        entities = deserialize_entities(first["entities"], self.other)
        self.assertEqual(next(iter(entities.values())).x, 1)

    def test_duplicate_item_ids_fail_before_loading_any_entities(self):
        a, b = self.runtime.create(x=1), self.runtime.create(x=2)
        data = serialize_entities([a, b])
        uid = next(iter(data[0]["items"]))
        data[1]["items"] = {uid: next(iter(data[1]["items"].values()))}
        with self.assertRaises(ValueError):
            deserialize_entities(data, self.other)
        self.assertFalse(self.other.entities)

    def test_missing_composition_sources_are_retained_without_blank_objects(self):
        uid, source_id, item_id = uuid4(), uuid4(), uuid4()
        data = [{"id": str(uid), "items": {str(item_id): {"type": "InheritedComponent", "name": "x", "source": str(source_id), "patch": []}}}]
        e = deserialize_entities(data, self.other)[uid]
        with self.assertRaises(KeyError):
            _ = e.x
        self.assertEqual(len(self.other.entities), 1)
        saved = serialize_entities([e])
        self.assertEqual(saved[0]["items"][str(item_id)]["source"], str(source_id))

    def test_handles_are_scoped_to_runtime(self):
        a, b = self.runtime.create(), self.other.create()
        with self.assertRaises(ReferenceError):
            self.other.linker.resolve_handle(a.handle)
