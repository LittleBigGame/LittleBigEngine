import unittest
from uuid import uuid4
from lbe import Component, Runtime, InheritedComponent, Relation, Parent, SystemDefinition, register_item_type
from lbe.project import activate_entities, deserialize_entities, resolve_references, serialize_entities, validate_project_data


class ItemStorageTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.other = Runtime()
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.other.close)

    def test_roundtrip_preserves_every_item_identity_and_patch(self):
        source = self.runtime.create(x=2, tags=["blueprint"])
        child = self.runtime.create(parent=source)
        child.items.connect("source", source)
        child.items.inherit_value("x", source.items.component("x"), [{"op": "add", "value": 3}])
        child.items.attach_system("idle", SystemDefinition("def update(dt): pass"))
        data = serialize_entities([child, source])
        restored = deserialize_entities(data, self.other)
        for e in (source, child):
            self.assertEqual(set(e.items), set(restored[e.id].items))
        c = restored[child.id]
        self.assertEqual(c.x, 5)
        self.assertIsInstance(c.items.component("x"), InheritedComponent)
        restored[source.id].x = 10
        self.assertEqual(c.x, 13)

    def test_legacy_projections_are_rejected_not_ignored(self):
        e = self.runtime.create(x=2)
        data = serialize_entities([e])
        self.assertEqual(set(data[0]), {'id', 'items'})
        data[0]["components"] = {"x": 999}
        with self.assertRaises(ValueError):
            deserialize_entities(data, self.other)
        self.assertFalse(self.other.entities)

    def test_legacy_formats_are_rejected_without_conversion(self):
        document = {"version": 2, "entities": [{"id": str(uuid4()), "components": {"x": 1}, "tags": ["player"]}]}
        with self.assertRaises(ValueError):
            validate_project_data(document)
        self.assertEqual(document['version'], 2)
        self.assertFalse(self.other.entities)

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

    def test_unresolved_links_are_actual_items_and_can_be_renamed_recovered_or_removed(self):
        owner_id, target_id, relation_id, parent_id = (uuid4() for _ in range(4))
        data = [{'id': str(owner_id), 'items': {
            str(relation_id): {'type': 'Relation', 'name': 'friend', 'target': str(target_id)},
            str(parent_id): {'type': 'Parent', 'name': 'parent', 'target': str(target_id), 'position': 0},
        }}]
        owner = deserialize_entities(data, self.other)[owner_id]
        self.assertIsInstance(owner.items[relation_id], Relation)
        self.assertIsInstance(owner.items[parent_id], Parent)
        self.assertEqual(serialize_entities([owner]), data)
        owner.items.rename(relation_id, 'peer')
        target = self.other.create(identity=target_id)
        resolve_references(owner, self.other)
        self.assertIs(owner.items.require_target('peer'), target)
        self.assertEqual(target.children, (owner,))
        target.destroy()
        self.assertFalse(owner.alive)

        owner = deserialize_entities(data, self.runtime)[owner_id]
        owner.items.remove(relation_id)
        owner.items.remove(parent_id)
        self.assertFalse(owner.items)

    def test_missing_source_recovery_keeps_script_name_asset_item_handle_and_order(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from lbe.scripts import ScriptInstance
        with TemporaryDirectory() as folder:
            uid, asset_id, item_id, value_id = (uuid4() for _ in range(4))
            document = [{'id': str(uid), 'items': {
                str(item_id): {'type': 'Script', 'name': 'action', 'definition': {'path': 'action.py', 'asset_id': str(asset_id)}},
                str(value_id): {'type': 'Component', 'name': 'x', 'value': 1},
            }}]
            owner = deserialize_entities(document, self.other, project_dir=folder)[uid]
            script = owner.items[item_id]
            handle = self.other.linker.handle(item_id)
            self.assertIsInstance(script, ScriptInstance)
            self.assertFalse(script.running)
            self.assertEqual(tuple(owner.items), (item_id, value_id))
            self.assertEqual(serialize_entities([owner], project_dir=folder), document)
            Path(folder, 'action.py').write_text('def run(): return 9', encoding='utf-8')
            activate_entities([owner], self.other, project_dir=folder)
            self.assertIs(self.other.linker.resolve_handle(handle), script)
            self.assertEqual(owner.items.run_script(asset_id), 9)
            self.assertEqual(script.name, 'action')
            self.assertEqual(script.definition.asset_id, asset_id)

    def test_application_typed_data_can_register_a_codec_without_core_changes(self):
        from dataclasses import dataclass, field
        from unittest.mock import patch
        from lbe.item_storage import ITEM_TYPES

        @dataclass(frozen=True)
        class Transform(Component):
            pass

        @dataclass(frozen=True)
        class Inventory:
            name: str
            contents: tuple
            id: object = field(default_factory=uuid4)

        with patch.dict(ITEM_TYPES):
            register_item_type(Transform)
            register_item_type(Inventory)
            records = (Transform('pose', {'x': 2}), Inventory('bag', ('key', 'apple')))
            owner = self.runtime.create(items=records)
            document = serialize_entities([owner])
            restored = deserialize_entities(document, self.other)[owner.id]
            self.assertEqual(tuple(restored.items.values()), records)
            self.assertEqual(restored.all(Transform), (records[0],))
            self.assertEqual(restored.all(Inventory), (records[1],))
            self.assertEqual(serialize_entities([restored]), document)
