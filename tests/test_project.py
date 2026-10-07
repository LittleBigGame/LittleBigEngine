import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from lbe.core import Entity, Runtime
from lbe.desktop import Input
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
    load_project,
    template_path,
)

try:
    from test_scene import RecordingGraphics
except ImportError:
    from tests.test_scene import RecordingGraphics



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
        entity.items.set_value("callback", lambda: None)
        with self.assertRaises(TypeError) as ctx:
            serialize_entity(entity)
        self.assertIn("cannot be serialized", str(ctx.exception))

    def test_entity_serialization_preserves_uuid_hierarchy_tags_components_relations(self):
        parent_id = uuid4()
        child_id = uuid4()
        parent = self.runtime.create(identity=parent_id, tags=["root", "game"], name="GameRoot", level=1)
        child = self.runtime.create(identity=child_id, parent=parent, tags=["actor"], name="Player", hp=100)
        parent.items.connect("player", child)
        child.items.connect("target", parent)

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
        self.assertEqual(set(set(r_parent.items.tag_names())), {"root", "game"})
        self.assertEqual(set(set(r_child.items.tag_names())), {"actor"})
        self.assertEqual(r_parent.name, "GameRoot")
        self.assertEqual(r_parent.level, 1)
        self.assertEqual(r_child.name, "Player")
        self.assertEqual(r_child.hp, 100)

        # Hierarchy
        self.assertIs(r_child.parent, r_parent)
        self.assertEqual(r_parent.children, (r_child,))

        # Relations (reference integrity)
        self.assertIs(r_parent.items.require_target("player"), r_child)
        self.assertIs(r_child.items.require_target("target"), r_parent)

    def test_system_attachments_serialized_and_reconstructed_safely(self):
        project_dir = Path(self.directory.name)
        script_path = project_dir / "movement.py"
        script_path.write_text("def update(dt):\n    entity.x += dt\n", encoding="utf-8")

        entity = self.runtime.create(x=0.0)
        definition = self.runtime.assets.system(script_path)
        entity.items.attach_system("movement", definition)

        serialized = serialize_entities([entity], project_dir=project_dir)
        self.assertIn("movement", serialized[0]["systems"])
        self.assertEqual(serialized[0]["systems"]["movement"]["path"], "movement.py")

        # Restore into runtime2
        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        restored = deserialize_entities(serialized, runtime2, project_dir=project_dir)
        r_entity = restored[entity.id]

        self.assertIn("movement", r_entity.items.behaviour_dict('system'))
        self.assertTrue(r_entity.items.behaviour("movement", kind='system').running)
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
        self.assertEqual(migrated["version"], CURRENT_VERSION)
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

    def test_serialization_error_and_skip_modes(self):
        class Dummy:
            pass

        # on_unsupported='skip' returns None
        self.assertIsNone(serialize_value(Dummy(), on_unsupported="skip"))

        # on_unsupported unknown mode raises ValueError
        with self.assertRaises(ValueError):
            serialize_value(Dummy(), on_unsupported="invalid_mode")

        # Unknown type tag in deserialize_value raises ValueError
        with self.assertRaises(ValueError):
            deserialize_value({"__type__": "nonexistent_tag"})

        # Unsupported data structure in deserialize_value raises TypeError
        with self.assertRaises(TypeError):
            deserialize_value(Dummy())

    def test_application_entity_id_persists_across_save_and_load(self):
        project_dir = Path(self.directory.name)
        app_id = uuid4()
        save_project(project_dir, application_id=app_id)

        data = load_project_data(project_dir)
        self.assertEqual(data.get("application_id"), str(app_id))

        window = SimpleNamespace(width=800, height=600)
        graphics = RecordingGraphics()
        input_state = Input()
        runtime = load_project(window, graphics, input_state, project_dir, template=template_path("demo"))
        self.addCleanup(runtime.close)

        app_entity = runtime.resolve(app_id)
        self.assertEqual(app_entity.id, app_id)
        self.assertEqual(app_entity.items.get_value("name"), "Application")
        self.assertIn("root", set(app_entity.items.tag_names()))

    def test_system_script_resolves_application_entity_by_uuid_after_reload(self):
        project_dir = Path(self.directory.name)
        app_id = uuid4()

        script_path = project_dir / "app_resolver.py"
        script_path.write_text(f'app = resolve("{app_id}")\n', encoding="utf-8")

        runtime = Runtime()
        self.addCleanup(runtime.close)
        app_entity = runtime.create(identity=app_id, name="Application", tags=["root"])
        game_entity = runtime.create(name="Game", tags=["game"], parent=app_entity)
        sys_def = runtime.assets.system(script_path)
        game_entity.items.attach_system("app_resolver", sys_def)
        runtime.step(0)

        sys_inst = game_entity.items.behaviour("app_resolver", kind='system')
        self.assertTrue(sys_inst.running, list(sys_inst.errors))
        self.assertEqual(len(sys_inst.errors), 0)
        self.assertEqual(sys_inst.namespace["app"].id, app_id)

        # Save project with application_id
        save_project(project_dir, entities=[game_entity], application_id=app_id)

        # Reload project data and deserialize entities
        data = load_project_data(project_dir)
        self.assertEqual(data.get("application_id"), str(app_id))

        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        app2 = runtime2.create(identity=UUID(data["application_id"]), name="Application", tags=["root"])
        restored = deserialize_entities(data["entities"], runtime2, default_parent=app2, project_dir=project_dir)
        runtime2.step(0)

        game2 = next(e for e in restored.values() if e.items.get_value("name") == "Game")
        sys_inst2 = game2.items.behaviour("app_resolver", kind='system')
        self.assertTrue(sys_inst2.running, list(sys_inst2.errors))
        self.assertEqual(len(sys_inst2.errors), 0)
        self.assertEqual(sys_inst2.namespace["app"].id, app_id)
        self.assertIs(sys_inst2.namespace["app"], app2)

    def test_render_system_with_application_resolve_persists_across_reload(self):
        project_dir = Path(self.directory.name)
        window = SimpleNamespace(
            width=1440,
            height=900,
            set_clipboard_text=lambda text: None,
            get_clipboard_text=lambda: "",
        )
        graphics = RecordingGraphics()
        input_state = Input()

        runtime = load_project(window, graphics, input_state, project_dir, template=template_path("editor"))
        runtime.step(0)
        editor = runtime.entities[0].items.require_value("application_state")
        app_id = editor.app.id

        render_path = project_dir / "render.py"
        old_content = render_path.read_text(encoding="utf-8")
        render_path.write_text(f'app = resolve("{app_id}")\n' + old_content, encoding="utf-8")

        editor.app.items.behaviour("app", kind='system').namespace["save_editor_project"]()
        runtime.close()

        runtime2 = load_project(window, graphics, input_state, project_dir, template=template_path("editor"))
        self.addCleanup(runtime2.close)
        runtime2.step(0)
        editor2 = runtime2.entities[0].items.require_value("application_state")

        self.assertEqual(editor2.app.id, app_id)

        render_sys = editor2.game.items.behaviour("render", kind='system')
        self.assertTrue(render_sys.running, list(render_sys.errors))
        self.assertEqual(len(render_sys.errors), 0)
        self.assertEqual(render_sys.namespace["app"].id, app_id)

        editor2.open_specific_file(render_path)
        runtime2.step(0)
        pills = [e for e in runtime2.entities if e.items.has_tag("asset_pill")]
        app_pills = [p for p in pills if p.items.get_value("asset_id") == str(app_id)]
        self.assertTrue(len(app_pills) >= 1)
        self.assertIn("Application", app_pills[0].items.get_value("asset_name", ""))
        self.assertIn("Entity", app_pills[0].items.get_value("asset_name", ""))
        self.assertNotIn("Asset", app_pills[0].items.get_value("asset_name", ""))

    def test_system_script_rejects_display_name_as_identity(self):
        project_dir = Path(self.directory.name)
        script_path = project_dir / "name_resolve_sys.py"
        script_path.write_text(
            'app = resolve("Application")\n'
            'game = resolve("Game")\n',
            encoding="utf-8",
        )
        window = SimpleNamespace(width=800, height=600)
        graphics = RecordingGraphics()
        input_state = Input()
        runtime = load_project(window, graphics, input_state, project_dir, template=template_path("demo"))
        self.addCleanup(runtime.close)

        game = next(e for e in runtime.entities if e.items.get_value("name") == "Game")
        sys_def = runtime.assets.system(script_path)
        before = runtime.entities
        game.items.attach_system("name_resolve_sys", sys_def)
        runtime.step(0)

        sys_inst = game.items.behaviour("name_resolve_sys", kind='system')
        self.assertFalse(sys_inst.running)
        self.assertIn('Expected an entity UUID', sys_inst.errors[-1].message)
        self.assertEqual(runtime.entities, before)
        with self.assertRaises(KeyError):
            runtime.resolve('Game')
        self.assertIs(runtime.resolve(str(game.id)), game)

        with self.assertRaises(KeyError):
            runtime.resolve("NonExistentEntityName12345")

    def test_component_referencing_application_entity_persists(self):
        project_dir = Path(self.directory.name)
        app_id = uuid4()
        app_entity = self.runtime.create(identity=app_id, name="Application", tags=["root"])
        game_entity = self.runtime.create(name="Game", tags=["game"])
        player = self.runtime.create(name="Player", app_ref=app_entity, parent=game_entity)

        save_project(project_dir, entities=[game_entity, player], application_id=app_id)

        data = load_project_data(project_dir)
        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        app2 = runtime2.create(identity=UUID(data["application_id"]), name="Application", tags=["root"])
        restored = deserialize_entities(data["entities"], runtime2, default_parent=app2, project_dir=project_dir)

        player2 = next(e for e in restored.values() if e.items.get_value("name") == "Player")
        self.assertIs(player2.items.require_value("app_ref"), app2)
        self.assertEqual(player2.items.require_value("app_ref").id, app_id)

    def test_relation_referencing_application_entity_persists(self):
        project_dir = Path(self.directory.name)
        app_id = uuid4()
        app_entity = self.runtime.create(identity=app_id, name="Application", tags=["root"])
        game_entity = self.runtime.create(name="Game", tags=["game"])
        game_entity.items.connect("app_root", app_entity)

        save_project(project_dir, entities=[game_entity], application_id=app_id)

        data = load_project_data(project_dir)
        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        app2 = runtime2.create(identity=UUID(data["application_id"]), name="Application", tags=["root"])
        restored = deserialize_entities(data["entities"], runtime2, default_parent=app2, project_dir=project_dir)

        game2 = next(e for e in restored.values() if e.items.get_value("name") == "Game")
        self.assertIn("app_root", game2.items.link_dict())
        self.assertIs(game2.items.require_target("app_root"), app2)
        self.assertEqual(game2.items.require_target("app_root").id, app_id)

    def test_parent_hierarchy_under_application_entity_persists(self):
        project_dir = Path(self.directory.name)
        app_id = uuid4()
        app_entity = self.runtime.create(identity=app_id, name="Application", tags=["root"])
        game_entity = self.runtime.create(name="Game", tags=["game"], parent=app_entity)

        save_project(project_dir, entities=[game_entity], application_id=app_id)

        data = load_project_data(project_dir)
        runtime2 = Runtime()
        self.addCleanup(runtime2.close)
        app2 = runtime2.create(identity=UUID(data["application_id"]), name="Application", tags=["root"])
        restored = deserialize_entities(data["entities"], runtime2, default_parent=app2, project_dir=project_dir)

        game2 = next(e for e in restored.values() if e.items.get_value("name") == "Game")
        self.assertIs(game2.parent, app2)
        self.assertEqual(game2.parent.id, app_id)

    def test_load_project_deterministic_application_id_fallback(self):
        project_dir = Path(self.directory.name)
        window = SimpleNamespace(width=800, height=600)
        graphics = RecordingGraphics()
        input_state = Input()

        runtime1 = load_project(window, graphics, input_state, project_dir, template=template_path("demo"))
        app1_id = runtime1.entities[0].id
        runtime1.close()

        project_json = project_dir / "project.json"
        if project_json.exists():
            project_json.unlink()

        runtime2 = load_project(window, graphics, input_state, project_dir, template=template_path("demo"))
        app2_id = runtime2.entities[0].id
        runtime2.close()

        expected_id = uuid5(NAMESPACE_URL, f"lbe://{project_dir.resolve().as_posix()}/application")
        self.assertEqual(app1_id, expected_id)
        self.assertEqual(app2_id, expected_id)

    def test_load_project_recovers_app_id_from_layout_selection_legacy(self):
        project_dir = Path(self.directory.name)
        legacy_app_id = uuid4()
        data = {
            "version": 1,
            "entities": [
                {
                    "id": str(uuid4()),
                    "tags": ["game"],
                    "components": {"name": "Game"},
                    "relations": {},
                    "systems": {},
                }
            ],
            "layout": {
                "selection": str(legacy_app_id),
            },
        }
        (project_dir / "project.json").write_text(json.dumps(data), encoding="utf-8")
        (project_dir / "app.py").write_text("# dummy app\n", encoding="utf-8")

        window = SimpleNamespace(width=800, height=600)
        graphics = RecordingGraphics()
        input_state = Input()
        runtime = load_project(window, graphics, input_state, project_dir)
        self.addCleanup(runtime.close)

        app_entity = runtime.resolve(legacy_app_id)
        self.assertEqual(app_entity.id, legacy_app_id)
        self.assertEqual(app_entity.items.get_value("name"), "Application")

    def test_unresolved_entity_token_in_editor_displays_as_entity_not_asset(self):
        from lbe.ui import UI, TextBuffer
        fake_runtime = Runtime()
        self.addCleanup(fake_runtime.close)
        root = fake_runtime.create(name="Application", tags=["root"])
        window = SimpleNamespace(width=800, height=600)
        graphics = RecordingGraphics()
        input_state = Input()
        ui = UI(root, window, graphics, input_state)

        missing_id = uuid4()
        buf = TextBuffer(f'app = resolve("{missing_id}")\ntex = asset("{missing_id}")\n')
        control = fake_runtime.create(x=0, y=0, w=500, h=300, layer=0, buffer=buf, inline_references=True)
        control.items.add_tag("multiline")

        ui._sync_text(control)

        pills = [e for e in fake_runtime.entities if e.items.has_tag("asset_pill")]
        pill0 = next((p for p in pills if p.items.get_value("asset_row") == 0), None)
        self.assertIsNotNone(pill0)
        self.assertIn("Entity", pill0.items.get_value("asset_name", ""))
        self.assertNotIn("Asset", pill0.items.get_value("asset_name", ""))

        pill1 = next((p for p in pills if p.items.get_value("asset_row") == 1), None)
        self.assertIsNotNone(pill1)
        self.assertIn("Asset", pill1.items.get_value("asset_name", ""))


if __name__ == "__main__":
    unittest.main()
