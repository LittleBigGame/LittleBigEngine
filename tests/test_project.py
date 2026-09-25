import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID, uuid4

from lbe.core import Entity, Runtime
from lbe.project import (
    CURRENT_VERSION,
    serialize_value,
    deserialize_value,
    serialize_entity,
    serialize_entities,
    deserialize_entities,
    migrate_project_data,
    save_project,
    load_project_data,
)


class ProjectPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close)

    def test_supported_primitive_and_collection_types_roundtrip(self):
        eid = uuid4()
        e = self.runtime.create(identity=eid)

        test_cases = [
            ("int", 42),
            ("negative_int", -100),
            ("float", 3.14159),
            ("str", "hello world"),
            ("bool_true", True),
            ("bool_false", False),
            ("none", None),
            ("uuid", eid),
            ("tuple", (1, "two", 3.0, (True, False))),
            ("set", {"apple", "banana", "cherry"}),
            ("list", [1, 2, [3, 4]]),
            ("dict", {"k1": 10, "k2": "val", "nested": {"a": [1, 2]}}),
            ("entity_ref", e),
        ]

        for name, value in test_cases:
            serialized = serialize_value(value)
            deserialized = deserialize_value(serialized, runtime=self.runtime)
            if isinstance(value, Entity):
                self.assertIs(deserialized, value, f"Failed on {name}")
            else:
                self.assertEqual(deserialized, value, f"Failed on {name}")
                self.assertIs(type(deserialized), type(value), f"Type mismatch on {name}")

    def test_unsupported_arbitrary_python_objects_explicitly_rejected(self):
        class ArbitraryObject:
            pass

        unsupported_values = [
            lambda x: x,
            ArbitraryObject(),
            float("inf"),
            float("nan"),
            {123: "non-string key"},
        ]

        for value in unsupported_values:
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    serialize_value(value)

    def test_unsupported_component_on_entity_raises_type_error(self):
        entity = self.runtime.create()
        entity.components["callback"] = lambda: None
        with self.assertRaises(TypeError) as ctx:
            serialize_entity(entity)
        self.assertIn("cannot be serialized", str(ctx.exception))

    def test_entity_serialization_preserves_uuid_hierarchy_tags_components_relations(self):
        parent_id = uuid4()
        child_id = uuid4()
        parent = self.runtime.create(identity=parent_id, tags=["root", "game"], name="GameRoot", level=1)
        child = self.runtime.create(identity=child_id, parent=parent, tags=["actor"], name="Player", hp=100)
        parent.relations["player"] = child
        child.relations["target"] = parent

        serialized = serialize_entities([parent, child])
        self.assertEqual(len(serialized), 2)

        # Deserialize in a new runtime
        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        restored = deserialize_entities(serialized, runtime2)

        self.assertIn(parent_id, restored)
        self.assertIn(child_id, restored)

        r_parent = restored[parent_id]
        r_child = restored[child_id]

        self.assertEqual(r_parent.id, parent_id)
        self.assertEqual(r_child.id, child_id)
        self.assertEqual(set(r_parent.tags), {"root", "game"})
        self.assertEqual(set(r_child.tags), {"actor"})
        self.assertEqual(r_parent.name, "GameRoot")
        self.assertEqual(r_parent.level, 1)
        self.assertEqual(r_child.name, "Player")
        self.assertEqual(r_child.hp, 100)

        # Hierarchy
        self.assertIs(r_child.parent, r_parent)
        self.assertEqual(r_parent.children, (r_child,))

        # Relations (reference integrity)
        self.assertIs(r_parent.relations["player"], r_child)
        self.assertIs(r_child.relations["target"], r_parent)

    def test_system_attachments_serialized_and_reconstructed_safely(self):
        project_dir = Path(self.directory.name)
        script_path = project_dir / "movement.py"
        script_path.write_text("def update(dt):\n    entity.x += dt\n", encoding="utf-8")

        entity = self.runtime.create(x=0.0)
        definition = self.runtime.assets.system(script_path)
        entity.systems.attach("movement", definition)

        serialized = serialize_entities([entity], project_dir=project_dir)
        self.assertIn("movement", serialized[0]["systems"])
        self.assertEqual(serialized[0]["systems"]["movement"]["path"], "movement.py")

        # Restore into runtime2
        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        restored = deserialize_entities(serialized, runtime2, project_dir=project_dir)
        r_entity = restored[entity.id]

        self.assertIn("movement", r_entity.systems)
        self.assertTrue(r_entity.systems["movement"].running)
        runtime2.step(1.0)
        self.assertEqual(r_entity.x, 1.0)

    def test_missing_script_reconstructs_safely_without_crashing(self):
        project_dir = Path(self.directory.name)
        data = [{
            "id": str(uuid4()),
            "parent": None,
            "tags": [],
            "components": {},
            "relations": {},
            "systems": {"nonexistent": {"path": "missing_script.py"}},
        }]

        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        restored = deserialize_entities(data, runtime2, project_dir=project_dir)
        self.assertEqual(len(restored), 1)

    def test_atomic_save_and_load_project(self):
        project_dir = Path(self.directory.name)
        entity = self.runtime.create(name="TestEntity", score=500)
        layout = {"left_column_w": 400, "camera": {"zoom": 64.0}}

        file_path = save_project(project_dir, entities=[entity], layout=layout)
        self.assertTrue(file_path.exists())

        loaded_data = load_project_data(project_dir)
        self.assertIsNotNone(loaded_data)
        self.assertEqual(loaded_data["version"], CURRENT_VERSION)
        self.assertEqual(len(loaded_data["entities"]), 1)
        self.assertEqual(loaded_data["entities"][0]["components"]["name"], "TestEntity")
        self.assertEqual(loaded_data["layout"]["left_column_w"], 400)
        self.assertEqual(loaded_data["layout"]["camera"]["zoom"], 64.0)

    def test_migration_pipeline_v0_to_v1(self):
        # v0 format without version, with list components and comma-separated tags string
        v0_data = {
            "entities": [
                {
                    "id": str(uuid4()),
                    "tags": "root, game",
                    "components": [
                        {"name": "x", "value": 10},
                        {"name": "name", "value": "LegacyGame"},
                    ],
                }
            ],
            # layout missing
        }

        migrated = migrate_project_data(v0_data)
        self.assertEqual(migrated["version"], 1)
        self.assertIn("layout", migrated)
        e = migrated["entities"][0]
        self.assertEqual(e["tags"], ["root", "game"])
        self.assertEqual(e["components"], {"x": 10, "name": "LegacyGame"})

    def test_migration_rejects_newer_version(self):
        future_data = {
            "version": 999,
            "entities": [],
        }
        with self.assertRaises(ValueError) as ctx:
            migrate_project_data(future_data)
        self.assertIn("newer than supported version", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
